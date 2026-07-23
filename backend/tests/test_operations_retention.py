import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("argon2")
pytest.importorskip("pgvector")

from app.api.dependencies import get_database_session
from app.core.project_config import ProjectCatalog, ProjectId, RetentionConfig
from app.db.models.audit import AuditEvent
from app.db.models.auth import (
    LoginRateLimit,
    OperatorAccount,
    OperatorProjectMembership,
    OperatorSession,
    PasswordResetCredential,
)
from app.db.models.conversation import Conversation, Ticket, WhatsAppMessage
from app.db.models.enums import (
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    OperatorRole,
    OutboxStatus,
    TicketStatus,
)
from app.db.models.outbox import OutboxEntry
from app.db.session import create_database_engine
from app.main import create_app
from app.security.passwords import hash_password
from app.services.retention import apply_project_retention, apply_security_state_cleanup


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)

PROJECT_CONFIG_DIR = Path(__file__).parents[1] / "config" / "projects"
PASSWORD = "Synthetic-Operations-Password-2026"
ORIGIN = "http://localhost:8080"


@asynccontextmanager
async def operations_context() -> AsyncIterator[tuple[AsyncClient, AsyncClient, object]]:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()

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
            async with (
                AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as admin,
                AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as operator,
            ):
                yield admin, operator, connection
        await transaction.rollback()
    await engine.dispose()


async def create_account(connection, *, email: str, role: OperatorRole) -> OperatorAccount:
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
        database.add(
            OperatorProjectMembership(
                project_id="ONCODIR",
                operator_account_id=account.id,
                role=role,
                is_active=True,
            )
        )
        await database.commit()
        return account


async def login(client: AsyncClient, email: str) -> None:
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def short_retention_project():
    source = ProjectCatalog.load(PROJECT_CONFIG_DIR).get(ProjectId.ONCODIR)
    return source.model_copy(
        update={
            "retention": RetentionConfig(
                message_content_days=30,
                tickets_and_notes_days=365,
                audit_events_days=730,
                application_logs_days=90,
                backups_days=30,
                privacy_warning_inactivity_days=30,
                resolved_ticket_reopen_days=7,
            )
        }
    )


def test_retention_redacts_content_deletes_expired_records_and_preserves_delivery_intent() -> None:
    async def scenario() -> None:
        async with operations_context() as (_admin, _operator, connection):
            now = datetime.now(UTC)
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                recent_conversation = Conversation(
                    project_id="ONCODIR",
                    whatsapp_user_id="retention-recent",
                    last_inbound_at=now - timedelta(days=40),
                )
                database.add(recent_conversation)
                await database.flush()
                recent_message = WhatsAppMessage(
                    project_id="ONCODIR",
                    conversation_id=recent_conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender_type=MessageSenderType.BOT,
                    message_type=MessageType.TEXT,
                    text_content="Conținut sintetic de anonimizat",
                    delivery_status=DeliveryStatus.SENT,
                    created_at=now - timedelta(days=40),
                )
                database.add(recent_message)
                await database.flush()
                recent_outbox = OutboxEntry(
                    project_id="ONCODIR",
                    message_id=recent_message.id,
                    idempotency_key="retention-recent-outbox",
                    status=OutboxStatus.SENT,
                    payload={"kind": "text", "text": "Conținut sintetic de anonimizat"},
                )
                database.add(recent_outbox)

                expired_conversation = Conversation(
                    project_id="ONCODIR",
                    whatsapp_user_id="retention-expired",
                    last_inbound_at=now - timedelta(days=400),
                    created_at=now - timedelta(days=400),
                )
                database.add(expired_conversation)
                await database.flush()
                expired_ticket = Ticket(
                    project_id="ONCODIR",
                    conversation_id=expired_conversation.id,
                    reference="ONCODIR-RETENTION-EXPIRED",
                    status=TicketStatus.CLOSED,
                    last_activity_at=now - timedelta(days=400),
                )
                database.add(expired_ticket)
                await database.flush()
                expired_message = WhatsAppMessage(
                    project_id="ONCODIR",
                    conversation_id=expired_conversation.id,
                    ticket_id=expired_ticket.id,
                    direction=MessageDirection.INBOUND,
                    sender_type=MessageSenderType.USER,
                    message_type=MessageType.TEXT,
                    text_content="Conținut sintetic expirat",
                    delivery_status=DeliveryStatus.RECEIVED,
                    created_at=now - timedelta(days=400),
                )
                database.add(expired_message)

                pending_conversation = Conversation(
                    project_id="ONCODIR",
                    whatsapp_user_id="retention-pending",
                    last_inbound_at=now - timedelta(days=400),
                    created_at=now - timedelta(days=400),
                )
                database.add(pending_conversation)
                await database.flush()
                pending_message = WhatsAppMessage(
                    project_id="ONCODIR",
                    conversation_id=pending_conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    sender_type=MessageSenderType.BOT,
                    message_type=MessageType.TEXT,
                    text_content="Conținut necesar livrării în așteptare",
                    delivery_status=DeliveryStatus.QUEUED,
                    created_at=now - timedelta(days=400),
                )
                database.add(pending_message)
                await database.flush()
                pending_outbox = OutboxEntry(
                    project_id="ONCODIR",
                    message_id=pending_message.id,
                    idempotency_key="retention-pending-outbox",
                    status=OutboxStatus.PENDING,
                    payload={"kind": "text", "text": "Conținut necesar livrării în așteptare"},
                )
                database.add(pending_outbox)
                await database.flush()
                recent_message_id = recent_message.id
                recent_outbox_id = recent_outbox.id
                expired_ticket_id = expired_ticket.id
                expired_conversation_id = expired_conversation.id
                pending_message_id = pending_message.id
                pending_outbox_id = pending_outbox.id
                await database.commit()

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                result = await apply_project_retention(
                    database,
                    project=short_retention_project(),
                    now=now,
                    batch_size=1000,
                )
                await database.commit()
                assert result.messages_redacted == 3
                assert result.message_records_deleted == 1
                assert result.tickets_deleted == 1

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                recent = await database.get(WhatsAppMessage, recent_message_id)
                recent_entry = await database.get(OutboxEntry, recent_outbox_id)
                assert recent is not None and recent.content_redacted_at is not None
                assert recent.text_content is None
                assert recent_entry is not None and recent_entry.payload["redacted"] is True
                assert await database.get(Ticket, expired_ticket_id) is None
                assert await database.get(Conversation, expired_conversation_id) is None
                pending = await database.get(WhatsAppMessage, pending_message_id)
                pending_entry = await database.get(OutboxEntry, pending_outbox_id)
                assert pending is not None and pending.content_redacted_at is not None
                assert pending_entry is not None
                assert pending_entry.payload["text"] == "Conținut necesar livrării în așteptare"
                assert await database.scalar(
                    select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.project_id == "ONCODIR",
                        AuditEvent.action == "retention.project_applied",
                    )
                ) == 1

    asyncio.run(scenario())


def test_operations_endpoints_are_administrator_only_and_content_free() -> None:
    async def scenario() -> None:
        async with operations_context() as (admin_client, operator_client, connection):
            administrator = await create_account(
                connection,
                email="phase7-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            operator = await create_account(
                connection,
                email="phase7-operator@example.invalid",
                role=OperatorRole.OPERATOR,
            )
            await login(admin_client, administrator.email)
            await login(operator_client, operator.email)
            admin_summary = await admin_client.get(
                "/api/v1/projects/ONCODIR/operations/summary"
            )
            operator_summary = await operator_client.get(
                "/api/v1/projects/ONCODIR/operations/summary"
            )
            audit = await admin_client.get(
                "/api/v1/projects/ONCODIR/operations/audit-events"
            )
            assert admin_summary.status_code == 200
            assert admin_summary.json()["retention"]["message_content_days"] == 90
            assert operator_summary.status_code == 403
            assert audit.status_code == 200
            serialized = audit.text.casefold()
            assert "text_content" not in serialized
            assert "phone_number" not in serialized

    asyncio.run(scenario())


def test_retention_dry_run_and_security_cleanup_are_safe_and_audited() -> None:
    async def scenario() -> None:
        async with operations_context() as (_admin, _operator, connection):
            now = datetime.now(UTC)
            account = await create_account(
                connection,
                email="phase7-cleanup@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            old = now - timedelta(days=40)
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                conversation = Conversation(
                    project_id="ONCODIR",
                    whatsapp_user_id="retention-dry-run",
                    last_inbound_at=old,
                )
                database.add(conversation)
                await database.flush()
                message = WhatsAppMessage(
                    project_id="ONCODIR",
                    conversation_id=conversation.id,
                    direction=MessageDirection.INBOUND,
                    sender_type=MessageSenderType.USER,
                    message_type=MessageType.TEXT,
                    text_content="Conținut sintetic păstrat de simulare",
                    delivery_status=DeliveryStatus.RECEIVED,
                    created_at=old,
                )
                database.add(message)
                session = OperatorSession(
                    operator_account_id=account.id,
                    token_hash="old-session-token-hash",
                    csrf_secret_hash="old-csrf-secret-hash",
                    idle_expires_at=old,
                    absolute_expires_at=old,
                    last_seen_at=old,
                    created_at=old,
                    updated_at=old,
                )
                reset = PasswordResetCredential(
                    operator_account_id=account.id,
                    token_hash="old-reset-token-hash",
                    expires_at=old,
                    created_at=old,
                    updated_at=old,
                )
                rate_limit = LoginRateLimit(
                    bucket_hash="old-rate-limit-bucket",
                    attempt_count=1,
                    window_started_at=old,
                    created_at=old,
                    updated_at=old,
                )
                old_global_audit = AuditEvent(
                    action="synthetic.old_global_event",
                    outcome="success",
                    created_at=now - timedelta(days=800),
                )
                database.add_all([session, reset, rate_limit, old_global_audit])
                await database.flush()
                message_id = message.id
                session_id = session.id
                reset_id = reset.id
                await database.commit()

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                preview = await apply_project_retention(
                    database,
                    project=short_retention_project(),
                    now=now,
                    dry_run=True,
                )
                assert preview.messages_redacted == 1
                await database.commit()

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                preserved = await database.get(WhatsAppMessage, message_id)
                assert preserved is not None
                assert preserved.text_content == "Conținut sintetic păstrat de simulare"
                assert preserved.content_redacted_at is None
                assert await database.scalar(
                    select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == "retention.project_applied",
                    )
                ) == 0

                cleanup = await apply_security_state_cleanup(
                    database,
                    global_audit_days=730,
                    cleanup_grace_days=30,
                    now=now,
                )
                await database.commit()
                assert cleanup.sessions_deleted == 1
                assert cleanup.reset_credentials_deleted == 1
                assert cleanup.rate_limit_buckets_deleted == 1
                assert cleanup.global_audit_events_deleted == 1

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                assert await database.get(OperatorSession, session_id) is None
                assert await database.get(PasswordResetCredential, reset_id) is None
                assert await database.get(
                    LoginRateLimit, "old-rate-limit-bucket"
                ) is None
                assert await database.scalar(
                    select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == "retention.security_state_applied",
                    )
                ) == 1

    asyncio.run(scenario())
