import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest.importorskip("argon2")
pytest.importorskip("pgvector")

from app.api.dependencies import get_database_session
from app.db.models.audit import AuditEvent
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.conversation import Conversation, OperatorNotification, Ticket, WhatsAppMessage
from app.db.models.enums import (
    DeliveryStatus,
    MessageType,
    OperatorRole,
    OutboxStatus,
    TemplateStatus,
    TicketStatus,
)
from app.db.models.outbox import OutboxEntry
from app.db.models.whatsapp import WhatsAppTemplate
from app.db.session import create_database_engine
from app.main import create_app
from app.integrations.whatsapp.mock import MockWhatsAppClient
from app.security.passwords import hash_password
from app.services.outbox_processor import OutboxProcessor
from app.services.ticket_workflow import escalate_inbound_text


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)

ORIGIN = "http://localhost:8080"
PASSWORD = "Synthetic-Ticket-Password-2026"


class FailingWhatsAppClient:
    async def send_text(self, _message):
        raise RuntimeError("synthetic provider failure")


@asynccontextmanager
async def ticket_test_context() -> AsyncIterator[tuple[AsyncClient, AsyncClient, object]]:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()

        async def override_database() -> AsyncIterator[AsyncSession]:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                try:
                    yield database
                except Exception:
                    await database.rollback()
                    raise

        app = create_app()
        app.dependency_overrides[get_database_session] = override_database
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with (
                AsyncClient(transport=transport, base_url="http://test") as first,
                AsyncClient(transport=transport, base_url="http://test") as second,
            ):
                yield first, second, connection
        await outer_transaction.rollback()
    await engine.dispose()


async def create_account(
    connection,
    *,
    email: str,
    role: OperatorRole = OperatorRole.OPERATOR,
    project_id: str = "ONCODIR",
) -> tuple[OperatorAccount, OperatorProjectMembership]:
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as database:
        account = OperatorAccount(
            email=email,
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
        )
        database.add(account)
        await database.flush()
        membership = OperatorProjectMembership(
            project_id=project_id,
            operator_account_id=account.id,
            role=role,
            is_active=True,
        )
        database.add(membership)
        await database.commit()
        return account, membership


async def login(client: AsyncClient, email: str) -> str:
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return client.cookies.get("screening_csrf")


def mutation_headers(token: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


async def seed_ticket(
    connection,
    *,
    whatsapp_user_id: str,
    text: str = "Întrebare sintetică necunoscută",
) -> Ticket:
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as database:
        result = await escalate_inbound_text(
            database,
            project_id="ONCODIR",
            whatsapp_user_id=whatsapp_user_id,
            phone_number_e164="+40700000123",
            text=text,
            meta_message_id=f"synthetic-{whatsapp_user_id}-{text}",
        )
        await database.commit()
        return result.ticket


def test_ticket_claim_is_atomic_and_operator_access_is_assignment_scoped() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (first, second, connection):
            first_account, _ = await create_account(
                connection,
                email="phase4-first@example.invalid",
            )
            second_account, _ = await create_account(
                connection,
                email="phase4-second@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-claim-user")
            first_csrf = await login(first, first_account.email)
            second_csrf = await login(second, second_account.email)

            queue = await first.get("/api/v1/projects/ONCODIR/tickets?queue=new")
            assert queue.status_code == 200
            assert queue.json()[0]["ticket_id"] == str(ticket.id)
            assert queue.json()[0]["masked_phone_number"].endswith("0123")
            assert "+40700000123" not in queue.text

            claimed = await first.post(
                f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/claim",
                headers=mutation_headers(first_csrf),
            )
            assert claimed.status_code == 200
            assert claimed.json()["status"] == "CLAIMED"

            conflicting_claim = await second.post(
                f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/claim",
                headers=mutation_headers(second_csrf),
            )
            assert conflicting_claim.status_code == 409
            assert (
                await second.get(f"/api/v1/projects/ONCODIR/tickets/{ticket.id}")
            ).status_code == 403

            released = await first.post(
                f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/release",
                headers=mutation_headers(first_csrf),
            )
            assert released.status_code == 200
            assert released.json()["status"] == "NEW"
            assert released.json()["assigned_membership_id"] is None

            claimed_by_second = await second.post(
                f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/claim",
                headers=mutation_headers(second_csrf),
            )
            assert claimed_by_second.status_code == 200
            assert (
                await first.post(
                    f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/close",
                    headers=mutation_headers(first_csrf),
                )
            ).status_code == 403
            assert (
                await first.get("/api/v1/projects/ONCOSCREEN/tickets?queue=new")
            ).status_code == 403

    asyncio.run(scenario())


def test_complete_ticket_lifecycle_queues_reply_and_reopens_on_user_message() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, admin_client, connection):
            operator, operator_membership = await create_account(
                connection,
                email="phase4-operator@example.invalid",
            )
            administrator, _ = await create_account(
                connection,
                email="phase4-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-lifecycle-user")
            operator_csrf = await login(operator_client, operator.email)
            admin_csrf = await login(admin_client, administrator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"

            assert (
                await operator_client.post(
                    f"{base}/claim",
                    headers=mutation_headers(operator_csrf),
                )
            ).status_code == 200
            reply = await operator_client.post(
                f"{base}/reply",
                json={"text": "Răspuns administrativ sintetic."},
                headers=mutation_headers(operator_csrf),
            )
            assert reply.status_code == 201
            assert reply.json()["delivery_status"] == "queued"
            note = await operator_client.post(
                f"{base}/notes",
                json={"content": "Notă internă sintetică."},
                headers=mutation_headers(operator_csrf),
            )
            assert note.status_code == 201
            waiting = await operator_client.post(
                f"{base}/waiting-user",
                headers=mutation_headers(operator_csrf),
            )
            assert waiting.json()["status"] == "WAITING_USER"

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                inbound = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-lifecycle-user",
                    text="Răspuns sintetic al utilizatorului.",
                    meta_message_id="phase4-user-reply",
                )
                await database.commit()
                assert inbound.ticket.id == ticket.id
                assert inbound.ticket.status == TicketStatus.CLAIMED

            detail = await operator_client.get(base)
            assert detail.status_code == 200
            assert detail.json()["customer_service_window_open"] is True
            assert len(detail.json()["messages"]) == 3
            assert detail.json()["internal_notes"][0]["content"] == "Notă internă sintetică."
            notifications = await operator_client.get(
                "/api/v1/projects/ONCODIR/tickets/notifications/unread"
            )
            assert notifications.status_code == 200
            assert notifications.json()[0]["notification_type"] == "user_replied"
            notification_id = notifications.json()[0]["notification_id"]
            assert (
                await operator_client.post(
                    f"/api/v1/projects/ONCODIR/tickets/notifications/{notification_id}/read",
                    headers=mutation_headers(operator_csrf),
                )
            ).status_code == 204
            assert (
                await operator_client.get(
                    "/api/v1/projects/ONCODIR/tickets/notifications/unread"
                )
            ).json() == []

            resolved = await operator_client.post(
                f"{base}/resolve",
                headers=mutation_headers(operator_csrf),
            )
            assert resolved.status_code == 200
            assert resolved.json()["status"] == "RESOLVED"

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                reopened = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-lifecycle-user",
                    text="Mesaj sintetic în perioada de redeschidere.",
                    meta_message_id="phase4-reopen-message",
                )
                await database.commit()
                assert reopened.reopened is True
                assert reopened.ticket.id == ticket.id
                assert reopened.ticket.status == TicketStatus.CLAIMED
                assert reopened.ticket.assigned_membership_id == operator_membership.id

            assert (
                await operator_client.post(
                    f"{base}/resolve",
                    headers=mutation_headers(operator_csrf),
                )
            ).status_code == 200
            closed = await admin_client.post(
                f"{base}/close",
                headers=mutation_headers(admin_csrf),
            )
            assert closed.status_code == 200
            assert closed.json()["status"] == "CLOSED"

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                after_close = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-lifecycle-user",
                    text="Întrebare sintetică nouă după închidere.",
                    meta_message_id="phase4-after-close",
                )
                await database.commit()
                assert after_close.ticket.id != ticket.id
                assert after_close.ticket.status == TicketStatus.NEW

                outbox = await database.scalar(
                    select(OutboxEntry).join(
                        WhatsAppMessage,
                        (WhatsAppMessage.project_id == OutboxEntry.project_id)
                        & (WhatsAppMessage.id == OutboxEntry.message_id),
                    ).where(WhatsAppMessage.ticket_id == ticket.id)
                )
                assert outbox is not None
                outbox_id = outbox.id
                outbound_message_id = outbox.message_id
                assert outbox.payload["text"] == "Răspuns administrativ sintetic."
                assert await database.scalar(
                    select(OperatorNotification).where(
                        OperatorNotification.ticket_id == ticket.id
                    )
                )
                assert await database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.project_id == "ONCODIR",
                        AuditEvent.target_id == str(ticket.id),
                        AuditEvent.action == "ticket.closed",
                    )
                )
                outbox.available_at = datetime(2000, 1, 1, tzinfo=UTC)
                await database.commit()

            processor = OutboxProcessor(
                async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ),
                MockWhatsAppClient(),
                worker_id="synthetic-phase4-worker",
                claim_seconds=60,
                maximum_attempts=5,
            )
            assert await processor.process_next() is True
            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                delivered_entry = await database.get(OutboxEntry, outbox_id)
                delivered_message = await database.get(WhatsAppMessage, outbound_message_id)
                assert delivered_entry is not None
                assert delivered_entry.status == OutboxStatus.SENT
                assert delivered_message is not None
                assert delivered_message.delivery_status == DeliveryStatus.SENT
                assert delivered_message.meta_message_id.startswith("mock-")

    asyncio.run(scenario())


def test_user_reply_returns_to_new_queue_when_the_assignee_is_inactive() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, membership = await create_account(
                connection,
                email="phase4-inactive-assignee@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-inactive-user")
            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            assert (
                await operator_client.post(
                    f"{base}/waiting-user",
                    headers=mutation_headers(csrf),
                )
            ).status_code == 200

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                stored_membership = await database.get(OperatorProjectMembership, membership.id)
                assert stored_membership is not None
                stored_membership.is_active = False
                await database.commit()

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                result = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-inactive-user",
                    text="Mesaj după dezactivarea operatorului.",
                    meta_message_id="phase4-inactive-reply",
                )
                await database.commit()
                assert result.ticket.id == ticket.id
                assert result.ticket.status == TicketStatus.NEW
                assert result.ticket.assigned_membership_id is None

    asyncio.run(scenario())


def test_expired_reopen_period_creates_a_new_ticket_after_escalation() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, _membership = await create_account(
                connection,
                email="phase4-expired-reopen@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-expired-user")
            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            assert (
                await operator_client.post(f"{base}/resolve", headers=mutation_headers(csrf))
            ).status_code == 200

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                resolved = await database.get(Ticket, ticket.id)
                assert resolved is not None
                resolved.reopen_until = datetime.now(UTC) - timedelta(seconds=1)
                await database.commit()

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                result = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-expired-user",
                    text="Întrebare după expirarea perioadei de redeschidere.",
                    meta_message_id="phase4-expired-reopen-message",
                )
                await database.commit()
                assert result.reopened is False
                assert result.ticket.id != ticket.id
                assert result.ticket.status == TicketStatus.NEW

    asyncio.run(scenario())


def test_outbox_retries_then_records_a_terminal_delivery_failure() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, _membership = await create_account(
                connection,
                email="phase4-failed-delivery@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-failed-delivery-user")
            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            reply = await operator_client.post(
                f"{base}/reply",
                json={"text": "Răspuns sintetic care va eșua."},
                headers=mutation_headers(csrf),
            )
            assert reply.status_code == 201
            message_id = reply.json()["message_id"]

            session_factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory.begin() as database:
                entry = await database.scalar(
                    select(OutboxEntry).where(OutboxEntry.message_id == message_id)
                )
                assert entry is not None
                entry.available_at = datetime(2000, 1, 1, tzinfo=UTC)
                entry_id = entry.id

            processor = OutboxProcessor(
                session_factory,
                FailingWhatsAppClient(),
                worker_id="synthetic-failing-worker",
                claim_seconds=60,
                maximum_attempts=2,
            )
            assert await processor.process_next() is True
            async with session_factory.begin() as database:
                entry = await database.get(OutboxEntry, entry_id)
                message = await database.get(WhatsAppMessage, message_id)
                assert entry is not None
                assert entry.status == OutboxStatus.PENDING
                assert entry.attempt_count == 1
                assert message is not None
                assert message.delivery_status == DeliveryStatus.QUEUED
                entry.available_at = datetime(2000, 1, 1, tzinfo=UTC)

            assert await processor.process_next() is True
            async with session_factory() as database:
                entry = await database.get(OutboxEntry, entry_id)
                message = await database.get(WhatsAppMessage, message_id)
                assert entry is not None
                assert entry.status == OutboxStatus.FAILED
                assert entry.attempt_count == 2
                assert entry.terminal_error_code == "RuntimeError"
                assert message is not None
                assert message.delivery_status == DeliveryStatus.FAILED
                assert message.error_summary == "synthetic provider failure"

    asyncio.run(scenario())


def test_freeform_reply_is_blocked_outside_the_whatsapp_service_window() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, _membership = await create_account(
                connection,
                email="phase4-window-closed@example.invalid",
            )
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                result = await escalate_inbound_text(
                    database,
                    project_id="ONCODIR",
                    whatsapp_user_id="phase4-window-closed-user",
                    phone_number_e164="+40700000999",
                    text="Mesaj sintetic mai vechi de 24 de ore.",
                    meta_message_id="phase4-window-closed-message",
                    received_at=datetime.now(UTC) - timedelta(hours=25),
                )
                await database.commit()
                ticket_id = result.ticket.id

            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket_id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            response = await operator_client.post(
                f"{base}/reply",
                json={"text": "Răspuns care necesită șablon."},
                headers=mutation_headers(csrf),
            )
            assert response.status_code == 409
            assert "șablon aprobat" in response.json()["detail"]

    asyncio.run(scenario())


def test_manual_reassignment_is_admin_only_and_audited() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, admin_client, connection):
            operator, operator_membership = await create_account(
                connection,
                email="phase4-reassign-operator@example.invalid",
            )
            administrator, _ = await create_account(
                connection,
                email="phase4-reassign-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase4-reassign-user")
            operator_csrf = await login(operator_client, operator.email)
            admin_csrf = await login(admin_client, administrator.email)
            endpoint = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}/reassign"

            denied = await operator_client.post(
                endpoint,
                json={"membership_id": str(operator_membership.id)},
                headers=mutation_headers(operator_csrf),
            )
            assert denied.status_code == 403
            assigned = await admin_client.post(
                endpoint,
                json={"membership_id": str(operator_membership.id)},
                headers=mutation_headers(admin_csrf),
            )
            assert assigned.status_code == 200
            assert assigned.json()["assigned_membership_id"] == str(operator_membership.id)

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                event = await database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "ticket.reassigned",
                        AuditEvent.target_id == str(ticket.id),
                    )
                )
                assert event is not None
                assert event.project_id == "ONCODIR"

    asyncio.run(scenario())


def test_worker_terminally_blocks_freeform_message_if_window_closes_after_queueing() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, _membership = await create_account(
                connection,
                email="phase6-worker-window@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase6-worker-window-user")
            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            reply = await operator_client.post(
                f"{base}/reply",
                json={"text": "Răspuns sintetic întârziat."},
                headers=mutation_headers(csrf),
            )
            assert reply.status_code == 201
            message_id = reply.json()["message_id"]
            session_factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory.begin() as database:
                conversation = await database.get(Conversation, ticket.conversation_id)
                entry = await database.scalar(
                    select(OutboxEntry).where(OutboxEntry.message_id == message_id)
                )
                assert conversation is not None and entry is not None
                conversation.last_inbound_at = datetime.now(UTC) - timedelta(hours=25)
                entry.available_at = datetime(2000, 1, 1, tzinfo=UTC)

            processor = OutboxProcessor(
                session_factory,
                MockWhatsAppClient(),
                worker_id="synthetic-window-worker",
                claim_seconds=60,
                maximum_attempts=5,
            )
            assert await processor.process_next() is True
            async with session_factory() as database:
                entry = await database.scalar(
                    select(OutboxEntry).where(OutboxEntry.message_id == message_id)
                )
                message = await database.get(WhatsAppMessage, message_id)
                assert entry is not None and message is not None
                assert entry.status == OutboxStatus.FAILED
                assert entry.attempt_count == 1
                assert entry.terminal_error_code == "customer_service_window_closed"
                assert message.delivery_status == DeliveryStatus.FAILED

    asyncio.run(scenario())


def test_approved_template_can_be_queued_and_sent_outside_service_window() -> None:
    async def scenario() -> None:
        async with ticket_test_context() as (operator_client, _unused, connection):
            operator, _membership = await create_account(
                connection,
                email="phase6-template@example.invalid",
            )
            ticket = await seed_ticket(connection, whatsapp_user_id="phase6-template-user")
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                conversation = await database.get(Conversation, ticket.conversation_id)
                assert conversation is not None
                conversation.last_inbound_at = datetime.now(UTC) - timedelta(hours=25)
                database.add(
                    WhatsAppTemplate(
                        project_id="ONCODIR",
                        template_name="synthetic_follow_up",
                        language_code="ro",
                        purpose="Test sintetic",
                        status=TemplateStatus.APPROVED,
                        approved_body_snapshot="Mesaj aprobat sintetic.",
                        variables_schema={"body_parameter_count": 0},
                    )
                )
                await database.commit()

            csrf = await login(operator_client, operator.email)
            base = f"/api/v1/projects/ONCODIR/tickets/{ticket.id}"
            assert (
                await operator_client.post(f"{base}/claim", headers=mutation_headers(csrf))
            ).status_code == 200
            templates = await operator_client.get("/api/v1/projects/ONCODIR/tickets/templates")
            assert templates.status_code == 200
            assert templates.json()[0]["template_name"] == "synthetic_follow_up"
            reply = await operator_client.post(
                f"{base}/reply-template",
                json={
                    "template_name": "synthetic_follow_up",
                    "language_code": "ro",
                    "body_parameters": [],
                },
                headers=mutation_headers(csrf),
            )
            assert reply.status_code == 201
            assert reply.json()["message_type"] == MessageType.TEMPLATE
            message_id = reply.json()["message_id"]
            session_factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory.begin() as database:
                entry = await database.scalar(
                    select(OutboxEntry).where(OutboxEntry.message_id == message_id)
                )
                assert entry is not None
                assert entry.payload["kind"] == "template"
                entry.available_at = datetime(2000, 1, 1, tzinfo=UTC)

            processor = OutboxProcessor(
                session_factory,
                MockWhatsAppClient(),
                worker_id="synthetic-template-worker",
                claim_seconds=60,
                maximum_attempts=5,
            )
            assert await processor.process_next() is True
            async with session_factory() as database:
                message = await database.get(WhatsAppMessage, message_id)
                assert message is not None
                assert message.delivery_status == DeliveryStatus.SENT

    asyncio.run(scenario())
