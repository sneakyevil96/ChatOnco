import asyncio
import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("pgvector")

from app.api.dependencies import get_database_session
from app.core.project_config import ProjectCatalog, ProjectId, WhatsAppConfig
from app.db.models.conversation import Conversation, Ticket, WhatsAppMessage
from app.db.models.enums import DeliveryStatus, MessageDirection, MessageType
from app.db.models.outbox import OutboxEntry
from app.db.models.whatsapp import WhatsAppWebhookEvent
from app.db.session import create_database_engine
from app.integrations.whatsapp.secrets import MetaBindingSecrets, MetaSecretCatalog
from app.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)

PROJECT_CONFIG_DIR = Path(__file__).parents[1] / "config" / "projects"
APP_SECRET = "synthetic-webhook-app-secret"
VERIFY_TOKEN = "synthetic-webhook-verify-token"


def enabled_catalog(*, interactive_actions: dict[str, str] | None = None) -> ProjectCatalog:
    source = ProjectCatalog.load(PROJECT_CONFIG_DIR)
    projects = {}
    for project_id, phone_id in (
        (ProjectId.ONCODIR, "synthetic-oncodir-phone"),
        (ProjectId.ONCOSCREEN, "synthetic-oncoscreen-phone"),
    ):
        projects[project_id] = source.get(project_id).model_copy(
            update={
                "whatsapp": WhatsAppConfig(
                    enabled=True,
                    phone_number_id=phone_id,
                    credential_binding=f"{project_id.value.lower()}-credentials",
                    webhook_binding="shared-synthetic-webhook",
                    interactive_actions=interactive_actions or {},
                    unsupported_warning_cooldown_minutes=10,
                )
            }
        )
    return ProjectCatalog(projects)


def secret_catalog() -> MetaSecretCatalog:
    return MetaSecretCatalog(
        {
            "shared-synthetic-webhook": MetaBindingSecrets(
                app_secret=APP_SECRET,
                verify_token=VERIFY_TOKEN,
            )
        }
    )


@asynccontextmanager
async def webhook_test_context() -> AsyncIterator[tuple[AsyncClient, object]]:
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
            app.state.project_catalog = enabled_catalog()
            app.state.whatsapp_secrets = secret_catalog()
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                yield client, connection
        await outer_transaction.rollback()
    await engine.dispose()


def payload(
    *,
    phone_number_id: str = "synthetic-oncodir-phone",
    messages: list[dict] | None = None,
    statuses: list[dict] | None = None,
) -> bytes:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "40000000000",
            "phone_number_id": phone_number_id,
        },
    }
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "synthetic-waba", "changes": [{"field": "messages", "value": value}]}],
        },
        separators=(",", ":"),
    ).encode()


def signed_headers(body: bytes) -> dict[str, str]:
    signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}",
    }


def text_message(message_id: str, timestamp: int = 1784678400) -> dict:
    return {
        "from": "40700000123",
        "id": message_id,
        "timestamp": str(timestamp),
        "type": "text",
        "text": {"body": "Întrebare sintetică fără răspuns"},
    }


def document_message(message_id: str, timestamp: int) -> dict:
    return {
        "from": "40700000456",
        "id": message_id,
        "timestamp": str(timestamp),
        "type": "document",
        "document": {
            "id": f"media-{message_id}",
            "mime_type": "application/pdf",
            "sha256": "synthetic-digest",
            "filename": "synthetic.pdf",
        },
    }


def test_webhook_verification_signature_dedup_and_first_interaction_warning() -> None:
    async def scenario() -> None:
        async with webhook_test_context() as (client, connection):
            verification = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": VERIFY_TOKEN,
                    "hub.challenge": "synthetic-challenge",
                },
            )
            assert verification.status_code == 200
            assert verification.text == "synthetic-challenge"

            body = payload(messages=[text_message("wamid.synthetic-inbound")])
            assert (await client.post("/webhooks/whatsapp", content=body)).status_code == 403
            first = await client.post(
                "/webhooks/whatsapp", content=body, headers=signed_headers(body)
            )
            duplicate = await client.post(
                "/webhooks/whatsapp", content=body, headers=signed_headers(body)
            )
            assert first.status_code == 200
            assert duplicate.status_code == 200

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                conversation = await database.scalar(
                    select(Conversation).where(
                        Conversation.project_id == "ONCODIR",
                        Conversation.whatsapp_user_id == "40700000123",
                    )
                )
                assert conversation is not None
                assert conversation.privacy_warning_sent_at is not None
                assert await database.scalar(
                    select(func.count()).select_from(Ticket).where(
                        Ticket.project_id == "ONCODIR",
                        Ticket.conversation_id == conversation.id,
                    )
                ) == 1
                assert await database.scalar(
                    select(func.count()).select_from(WhatsAppMessage).where(
                        WhatsAppMessage.project_id == "ONCODIR",
                        WhatsAppMessage.conversation_id == conversation.id,
                    )
                ) == 3
                assert await database.scalar(
                    select(func.count()).select_from(OutboxEntry).where(
                        OutboxEntry.project_id == "ONCODIR"
                    )
                ) == 2
                ledger = await database.scalar(
                    select(WhatsAppWebhookEvent).where(
                        WhatsAppWebhookEvent.event_key == "message:wamid.synthetic-inbound"
                    )
                )
                assert ledger is not None and ledger.processed_at is not None

    asyncio.run(scenario())


def test_unsupported_attachment_sequence_creates_one_ticket_and_one_warning() -> None:
    async def scenario() -> None:
        async with webhook_test_context() as (client, connection):
            first_body = payload(messages=[document_message("wamid.synthetic-doc-1", 1784678400)])
            second_body = payload(messages=[document_message("wamid.synthetic-doc-2", 1784678460)])
            assert (
                await client.post(
                    "/webhooks/whatsapp", content=first_body, headers=signed_headers(first_body)
                )
            ).status_code == 200
            assert (
                await client.post(
                    "/webhooks/whatsapp", content=second_body, headers=signed_headers(second_body)
                )
            ).status_code == 200

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                conversation = await database.scalar(
                    select(Conversation).where(
                        Conversation.project_id == "ONCODIR",
                        Conversation.whatsapp_user_id == "40700000456",
                    )
                )
                assert conversation is not None
                inbound = (
                    await database.scalars(
                        select(WhatsAppMessage).where(
                            WhatsAppMessage.conversation_id == conversation.id,
                            WhatsAppMessage.direction == MessageDirection.INBOUND,
                        )
                    )
                ).all()
                outbound = (
                    await database.scalars(
                        select(WhatsAppMessage).where(
                            WhatsAppMessage.conversation_id == conversation.id,
                            WhatsAppMessage.direction == MessageDirection.OUTBOUND,
                        )
                    )
                ).all()
                assert len(inbound) == 2
                assert all(message.message_type == MessageType.UNSUPPORTED for message in inbound)
                assert all("media_id" in (message.attachment_metadata or {}) for message in inbound)
                assert len(outbound) == 1
                assert await database.scalar(
                    select(func.count()).select_from(Ticket).where(
                        Ticket.conversation_id == conversation.id
                    )
                ) == 1

    asyncio.run(scenario())


def test_delivery_statuses_are_monotonic_and_duplicate_safe() -> None:
    async def scenario() -> None:
        async with webhook_test_context() as (client, connection):
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                conversation = Conversation(
                    project_id="ONCODIR",
                    whatsapp_user_id="synthetic-status-user",
                )
                database.add(conversation)
                await database.flush()
                message = WhatsAppMessage(
                    project_id="ONCODIR",
                    conversation_id=conversation.id,
                    meta_message_id="wamid.synthetic-status",
                    direction=MessageDirection.OUTBOUND,
                    sender_type="bot",
                    message_type=MessageType.TEXT,
                    text_content="Mesaj sintetic",
                    delivery_status=DeliveryStatus.SENT,
                )
                database.add(message)
                await database.commit()
                message_id = message.id

            for status_value, timestamp in (("delivered", 1784678500), ("read", 1784678600), ("delivered", 1784678500)):
                body = payload(
                    statuses=[
                        {
                            "id": "wamid.synthetic-status",
                            "status": status_value,
                            "timestamp": str(timestamp),
                            "recipient_id": "synthetic-status-user",
                        }
                    ]
                )
                response = await client.post(
                    "/webhooks/whatsapp", content=body, headers=signed_headers(body)
                )
                assert response.status_code == 200

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                stored = await database.get(WhatsAppMessage, message_id)
                assert stored is not None
                assert stored.delivery_status == DeliveryStatus.READ
                assert stored.delivered_at is not None
                assert stored.read_at is not None
                assert await database.scalar(
                    select(func.count()).select_from(WhatsAppWebhookEvent).where(
                        WhatsAppWebhookEvent.provider_message_id == "wamid.synthetic-status"
                    )
                ) == 2

    asyncio.run(scenario())
