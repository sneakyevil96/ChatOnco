import asyncio
import os

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("pgvector")

from app.core.settings import get_settings
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.conversation import Conversation, Ticket, WhatsAppMessage
from app.db.models.enums import (
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    OperatorRole,
    TicketStatus,
)
from app.db.repositories.project_scoped import ProjectScopedRepository
from app.db.session import create_database_engine


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)


def test_same_whatsapp_user_is_isolated_per_project(database_session) -> None:
    database_session.add_all(
        [
            Conversation(project_id="ONCODIR", whatsapp_user_id="synthetic-shared-user"),
            Conversation(project_id="ONCOSCREEN", whatsapp_user_id="synthetic-shared-user"),
        ]
    )

    database_session.flush()


def test_cross_project_conversation_message_is_rejected(database_session) -> None:
    conversation = Conversation(
        project_id="ONCODIR",
        whatsapp_user_id="synthetic-message-owner",
    )
    database_session.add(conversation)
    database_session.flush()

    with pytest.raises(IntegrityError):
        with database_session.begin_nested():
            database_session.add(
                WhatsAppMessage(
                    project_id="ONCOSCREEN",
                    conversation_id=conversation.id,
                    direction=MessageDirection.INBOUND,
                    sender_type=MessageSenderType.USER,
                    message_type=MessageType.TEXT,
                    delivery_status=DeliveryStatus.RECEIVED,
                    text_content="Mesaj sintetic pentru verificarea izolării.",
                )
            )
            database_session.flush()


def test_only_one_active_ticket_is_allowed_per_conversation(database_session) -> None:
    conversation = Conversation(
        project_id="ONCODIR",
        whatsapp_user_id="synthetic-active-ticket-user",
    )
    database_session.add(conversation)
    database_session.flush()
    database_session.add(
        Ticket(
            project_id="ONCODIR",
            conversation_id=conversation.id,
            reference="ONCODIR-SYNTHETIC-1",
            status=TicketStatus.NEW,
        )
    )
    database_session.flush()
    with pytest.raises(IntegrityError):
        with database_session.begin_nested():
            database_session.add(
                Ticket(
                    project_id="ONCODIR",
                    conversation_id=conversation.id,
                    reference="ONCODIR-SYNTHETIC-2",
                    status=TicketStatus.CLAIMED,
                )
            )
            database_session.flush()


def test_multiple_inactive_tickets_are_allowed(database_session) -> None:
    conversation = Conversation(
        project_id="ONCOSCREEN",
        whatsapp_user_id="synthetic-resolved-ticket-user",
    )
    database_session.add(conversation)
    database_session.flush()
    database_session.add_all(
        [
            Ticket(
                project_id="ONCOSCREEN",
                conversation_id=conversation.id,
                reference="ONCOSCREEN-SYNTHETIC-1",
                status=TicketStatus.RESOLVED,
            ),
            Ticket(
                project_id="ONCOSCREEN",
                conversation_id=conversation.id,
                reference="ONCOSCREEN-SYNTHETIC-2",
                status=TicketStatus.CLOSED,
            ),
        ]
    )

    database_session.flush()


def test_cross_project_ticket_assignment_is_rejected(database_session) -> None:
    account = OperatorAccount(
        email="synthetic-operator@example.invalid",
        password_hash="synthetic-not-a-real-password-hash",
    )
    database_session.add(account)
    database_session.flush()
    membership = OperatorProjectMembership(
        project_id="ONCOSCREEN",
        operator_account_id=account.id,
        role=OperatorRole.OPERATOR,
    )
    conversation = Conversation(
        project_id="ONCODIR",
        whatsapp_user_id="synthetic-assignment-user",
    )
    database_session.add_all([membership, conversation])
    database_session.flush()
    with pytest.raises(IntegrityError):
        with database_session.begin_nested():
            database_session.add(
                Ticket(
                    project_id="ONCODIR",
                    conversation_id=conversation.id,
                    reference="ONCODIR-SYNTHETIC-ASSIGNMENT",
                    status=TicketStatus.CLAIMED,
                    assigned_membership_id=membership.id,
                )
            )
            database_session.flush()


def test_project_scoped_repository_never_lists_another_project() -> None:
    async def scenario() -> None:
        engine = create_database_engine(get_settings().database_url)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                session.add_all(
                    [
                        Conversation(
                            project_id="ONCODIR",
                            whatsapp_user_id="synthetic-repository-oncodir",
                        ),
                        Conversation(
                            project_id="ONCOSCREEN",
                            whatsapp_user_id="synthetic-repository-oncoscreen",
                        ),
                    ]
                )
                await session.flush()
                repository = ProjectScopedRepository(
                    session,
                    Conversation,
                    "ONCODIR",
                )

                conversations = await repository.list()

                assert conversations
                assert all(item.project_id == "ONCODIR" for item in conversations)
            finally:
                await session.close()
                await transaction.rollback()
        await engine.dispose()

    asyncio.run(scenario())
