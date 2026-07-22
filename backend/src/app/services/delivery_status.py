from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import WhatsAppMessage
from app.db.models.enums import DeliveryStatus, MessageDirection
from app.db.models.whatsapp import WhatsAppWebhookEvent
from app.integrations.whatsapp.webhook import MetaDeliveryStatus


STATUS_ORDER = {
    DeliveryStatus.QUEUED: 0,
    DeliveryStatus.SENT: 1,
    DeliveryStatus.DELIVERED: 2,
    DeliveryStatus.READ: 3,
}


@dataclass(frozen=True, slots=True)
class DeliveryStatusResult:
    duplicate: bool
    matched: bool
    changed: bool


def apply_delivery_status(message: WhatsAppMessage, status: MetaDeliveryStatus) -> bool:
    target = DeliveryStatus(status.status)
    current = message.delivery_status
    if target == DeliveryStatus.FAILED:
        if current in {DeliveryStatus.DELIVERED, DeliveryStatus.READ}:
            return False
        message.delivery_status = target
        message.failed_at = status.timestamp
        message.error_code = status.error_code
        message.error_summary = status.error_summary
        message.provider_timestamp = status.timestamp
        return True
    if current == DeliveryStatus.FAILED:
        return False
    if STATUS_ORDER.get(target, -1) <= STATUS_ORDER.get(current, -1):
        return False
    message.delivery_status = target
    message.provider_timestamp = status.timestamp
    if target == DeliveryStatus.SENT:
        message.sent_at = status.timestamp
    elif target == DeliveryStatus.DELIVERED:
        message.delivered_at = status.timestamp
    elif target == DeliveryStatus.READ:
        message.read_at = status.timestamp
        if message.delivered_at is None:
            message.delivered_at = status.timestamp
    return True


async def record_delivery_status(
    database: AsyncSession,
    *,
    project_id: str,
    status: MetaDeliveryStatus,
) -> DeliveryStatusResult:
    event = await database.scalar(
        select(WhatsAppWebhookEvent)
        .where(
            WhatsAppWebhookEvent.project_id == project_id,
            WhatsAppWebhookEvent.event_key == status.event_key,
        )
        .with_for_update()
    )
    if event is not None and event.processed_at is not None:
        return DeliveryStatusResult(duplicate=True, matched=True, changed=False)
    if event is None:
        event = WhatsAppWebhookEvent(
            project_id=project_id,
            event_key=status.event_key,
            event_type="delivery_status",
            phone_number_id=status.phone_number_id,
            provider_message_id=status.message_id,
            provider_timestamp=status.timestamp,
            event_metadata={
                "status": status.status,
                "error_code": status.error_code,
                "error_summary": status.error_summary,
            },
        )
        database.add(event)
        await database.flush()
    message = await database.scalar(
        select(WhatsAppMessage)
        .where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.meta_message_id == status.message_id,
            WhatsAppMessage.direction == MessageDirection.OUTBOUND,
        )
        .with_for_update()
    )
    if message is None:
        return DeliveryStatusResult(duplicate=False, matched=False, changed=False)
    changed = apply_delivery_status(message, status)
    event.processed_at = datetime.now(UTC)
    return DeliveryStatusResult(duplicate=False, matched=True, changed=changed)


async def apply_pending_delivery_statuses(
    database: AsyncSession,
    *,
    project_id: str,
    provider_message_id: str,
    message: WhatsAppMessage,
) -> None:
    events = (
        await database.scalars(
            select(WhatsAppWebhookEvent)
            .where(
                WhatsAppWebhookEvent.project_id == project_id,
                WhatsAppWebhookEvent.provider_message_id == provider_message_id,
                WhatsAppWebhookEvent.event_type == "delivery_status",
                WhatsAppWebhookEvent.processed_at.is_(None),
            )
            .order_by(WhatsAppWebhookEvent.provider_timestamp, WhatsAppWebhookEvent.created_at)
            .with_for_update()
        )
    ).all()
    now = datetime.now(UTC)
    for event in events:
        metadata = event.event_metadata
        status = MetaDeliveryStatus(
            phone_number_id=event.phone_number_id,
            message_id=provider_message_id,
            status=str(metadata["status"]),
            timestamp=event.provider_timestamp or now,
            error_code=metadata.get("error_code"),
            error_summary=metadata.get("error_summary"),
        )
        apply_delivery_status(message, status)
        event.processed_at = now
