from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session
from app.core.project_config import ProjectCatalog
from app.db.models.enums import MessageType
from app.db.models.whatsapp import WhatsAppWebhookEvent
from app.integrations.whatsapp.secrets import MetaSecretCatalog
from app.integrations.whatsapp.webhook import (
    MetaWebhookPayloadError,
    parse_meta_webhook,
    verify_meta_signature,
)
from app.services.delivery_status import record_delivery_status
from app.services.inbound_orchestration import (
    handle_inbound_text,
    handle_inbound_unsupported,
)


router = APIRouter()


@router.get("")
async def verify_webhook(
    request: Request,
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    secrets: MetaSecretCatalog = request.app.state.whatsapp_secrets
    if hub_mode != "subscribe" or not secrets.accepts_verify_token(hub_verify_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    return PlainTextResponse(hub_challenge)


def _phone_number(sender_id: str) -> str | None:
    return f"+{sender_id}" if sender_id.isdigit() else None


@router.post("")
async def receive_webhook(
    request: Request,
    database: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    settings = request.app.state.settings
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > settings.whatsapp_webhook_max_bytes
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid content length") from exc
        if too_large:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large")
    raw_body = await request.body()
    if len(raw_body) > settings.whatsapp_webhook_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large")
    try:
        parsed = parse_meta_webhook(raw_body)
    except MetaWebhookPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc

    projects: ProjectCatalog = request.app.state.project_catalog
    resolved_projects = {}
    for phone_number_id in parsed.phone_number_ids:
        project = projects.by_phone_number_id(phone_number_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown receiving phone number")
        resolved_projects[phone_number_id] = project

    secrets: MetaSecretCatalog = request.app.state.whatsapp_secrets
    signature = request.headers.get("x-hub-signature-256")
    webhook_bindings = {
        project.whatsapp.webhook_binding for project in resolved_projects.values()
    }
    if not webhook_bindings or None in webhook_bindings:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook is not configured")
    try:
        signature_valid = all(
            verify_meta_signature(raw_body, signature, secrets.app_secret(binding))
            for binding in webhook_bindings
            if binding is not None
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook is not configured") from exc
    if not signature_valid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")

    now = datetime.now(UTC)
    for inbound in parsed.inbound_messages:
        project = resolved_projects[inbound.phone_number_id]
        project_id = project.project_id.value
        ledger = await database.scalar(
            select(WhatsAppWebhookEvent).where(
                WhatsAppWebhookEvent.project_id == project_id,
                WhatsAppWebhookEvent.event_key == inbound.event_key,
            )
        )
        if ledger is not None and ledger.processed_at is not None:
            continue
        if ledger is None:
            ledger = WhatsAppWebhookEvent(
                project_id=project_id,
                event_key=inbound.event_key,
                event_type="inbound_message",
                phone_number_id=inbound.phone_number_id,
                provider_message_id=inbound.message_id,
                provider_timestamp=inbound.timestamp,
                event_metadata={"message_type": inbound.kind},
            )
            database.add(ledger)
            await database.flush()

        if inbound.kind == "text" and inbound.text is not None:
            await handle_inbound_text(
                database,
                project=project,
                whatsapp_user_id=inbound.sender_id,
                phone_number_e164=_phone_number(inbound.sender_id),
                text=inbound.text,
                meta_message_id=inbound.message_id,
                received_at=inbound.timestamp,
            )
        elif (
            inbound.kind == "interactive"
            and inbound.interactive_action_id in project.whatsapp.interactive_actions
        ):
            mapped_text = project.whatsapp.interactive_actions[inbound.interactive_action_id]
            await handle_inbound_text(
                database,
                project=project,
                whatsapp_user_id=inbound.sender_id,
                phone_number_e164=_phone_number(inbound.sender_id),
                text=inbound.interactive_title or mapped_text,
                retrieval_text=mapped_text,
                meta_message_id=inbound.message_id,
                received_at=inbound.timestamp,
                message_type=MessageType.INTERACTIVE,
                attachment_metadata=inbound.attachment_metadata,
            )
        else:
            metadata = dict(inbound.attachment_metadata or {})
            metadata.setdefault("provider_type", inbound.kind)
            await handle_inbound_unsupported(
                database,
                project=project,
                whatsapp_user_id=inbound.sender_id,
                phone_number_e164=_phone_number(inbound.sender_id),
                meta_message_id=inbound.message_id,
                received_at=inbound.timestamp,
                attachment_metadata=metadata,
            )
        ledger.processed_at = now

    for delivery_status in parsed.delivery_statuses:
        project = resolved_projects[delivery_status.phone_number_id]
        await record_delivery_status(
            database,
            project_id=project.project_id.value,
            status=delivery_status,
        )
    await database.commit()
    return {"status": "accepted"}
