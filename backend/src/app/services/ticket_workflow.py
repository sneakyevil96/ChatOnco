from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import OperatorProjectMembership
from app.db.models.conversation import (
    Conversation,
    OperatorNotification,
    Ticket,
    WhatsAppMessage,
)
from app.db.models.enums import (
    ConversationState,
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    NotificationType,
    TicketStatus,
)
from app.services.audit import record_audit_event


ACTIVE_TICKET_STATUSES = (
    TicketStatus.NEW,
    TicketStatus.CLAIMED,
    TicketStatus.WAITING_USER,
)
INACTIVE_TICKET_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)


@dataclass(frozen=True, slots=True)
class InboundEscalationResult:
    conversation: Conversation
    ticket: Ticket
    message: WhatsAppMessage
    deduplicated: bool
    reopened: bool


def generate_ticket_reference(project_id: str, now: datetime) -> str:
    return f"{project_id}-{now:%Y%m%d}-{uuid4().hex[:8].upper()}"


def mask_phone_number(phone_number: str | None) -> str | None:
    if not phone_number:
        return None
    visible = min(4, max(2, len(phone_number) // 3))
    return f"{'•' * max(0, len(phone_number) - visible)}{phone_number[-visible:]}"


async def membership_is_active(
    database: AsyncSession,
    project_id: str,
    membership_id,
) -> bool:
    if membership_id is None:
        return False
    return bool(
        await database.scalar(
            select(OperatorProjectMembership.id).where(
                OperatorProjectMembership.project_id == project_id,
                OperatorProjectMembership.id == membership_id,
                OperatorProjectMembership.is_active.is_(True),
            )
        )
    )


def touch_ticket(ticket: Ticket, now: datetime) -> None:
    ticket.last_activity_at = now
    ticket.row_version += 1


async def escalate_inbound_text(
    database: AsyncSession,
    *,
    project_id: str,
    whatsapp_user_id: str,
    text: str,
    meta_message_id: str | None = None,
    phone_number_e164: str | None = None,
    received_at: datetime | None = None,
) -> InboundEscalationResult:
    """Persist an inbound text after the FAQ layer has decided to escalate it.

    This service is provider-independent and is exercised with synthetic data in
    Phase 4. A later Meta webhook adapter can call the same transaction boundary.
    """

    now = received_at or datetime.now(UTC)
    if meta_message_id:
        existing_message = await database.scalar(
            select(WhatsAppMessage).where(
                WhatsAppMessage.project_id == project_id,
                WhatsAppMessage.meta_message_id == meta_message_id,
            )
        )
        if existing_message is not None and existing_message.ticket_id is not None:
            existing_ticket = await database.scalar(
                select(Ticket).where(
                    Ticket.project_id == project_id,
                    Ticket.id == existing_message.ticket_id,
                )
            )
            existing_conversation = await database.scalar(
                select(Conversation).where(
                    Conversation.project_id == project_id,
                    Conversation.id == existing_message.conversation_id,
                )
            )
            if existing_ticket is not None and existing_conversation is not None:
                return InboundEscalationResult(
                    conversation=existing_conversation,
                    ticket=existing_ticket,
                    message=existing_message,
                    deduplicated=True,
                    reopened=False,
                )

    conversation = await database.scalar(
        select(Conversation)
        .where(
            Conversation.project_id == project_id,
            Conversation.whatsapp_user_id == whatsapp_user_id,
        )
        .with_for_update()
    )
    if conversation is None:
        conversation = Conversation(
            project_id=project_id,
            whatsapp_user_id=whatsapp_user_id,
            phone_number_e164=phone_number_e164,
            state=ConversationState.BOT,
        )
        database.add(conversation)
        await database.flush()
    elif phone_number_e164 and not conversation.phone_number_e164:
        conversation.phone_number_e164 = phone_number_e164

    active_ticket = await database.scalar(
        select(Ticket)
        .where(
            Ticket.project_id == project_id,
            Ticket.conversation_id == conversation.id,
            Ticket.status.in_(ACTIVE_TICKET_STATUSES),
        )
        .with_for_update()
    )
    ticket = active_ticket
    reopened = False

    if ticket is None:
        resolved_ticket = await database.scalar(
            select(Ticket)
            .where(
                Ticket.project_id == project_id,
                Ticket.conversation_id == conversation.id,
                Ticket.status == TicketStatus.RESOLVED,
                Ticket.reopen_until.is_not(None),
                Ticket.reopen_until >= now,
            )
            .order_by(Ticket.resolved_at.desc())
            .limit(1)
            .with_for_update()
        )
        if resolved_ticket is not None:
            ticket = resolved_ticket
            reopened = True
            if await membership_is_active(
                database,
                project_id,
                ticket.assigned_membership_id,
            ):
                ticket.status = TicketStatus.CLAIMED
                ticket.claimed_at = now
                conversation.state = ConversationState.HUMAN_ACTIVE
                database.add(
                    OperatorNotification(
                        project_id=project_id,
                        ticket_id=ticket.id,
                        recipient_membership_id=ticket.assigned_membership_id,
                        notification_type=NotificationType.TICKET_REOPENED,
                    )
                )
            else:
                ticket.status = TicketStatus.NEW
                ticket.assigned_membership_id = None
                ticket.claimed_at = None
                conversation.state = ConversationState.WAITING_HUMAN
            ticket.resolved_at = None
            ticket.reopen_until = None
            touch_ticket(ticket, now)
            await record_audit_event(
                database,
                project_id=project_id,
                action="ticket.automatically_reopened",
                outcome="success",
                target_type="ticket",
                target_id=str(ticket.id),
            )

    if ticket is None:
        ticket = Ticket(
            project_id=project_id,
            conversation_id=conversation.id,
            reference=generate_ticket_reference(project_id, now),
            status=TicketStatus.NEW,
            last_activity_at=now,
        )
        database.add(ticket)
        await database.flush()
        conversation.state = ConversationState.WAITING_HUMAN
        await record_audit_event(
            database,
            project_id=project_id,
            action="ticket.created_from_escalation",
            outcome="success",
            target_type="ticket",
            target_id=str(ticket.id),
        )
    elif active_ticket is not None:
        if ticket.status == TicketStatus.WAITING_USER:
            if await membership_is_active(
                database,
                project_id,
                ticket.assigned_membership_id,
            ):
                ticket.status = TicketStatus.CLAIMED
                ticket.claimed_at = now
                conversation.state = ConversationState.HUMAN_ACTIVE
                database.add(
                    OperatorNotification(
                        project_id=project_id,
                        ticket_id=ticket.id,
                        recipient_membership_id=ticket.assigned_membership_id,
                        notification_type=NotificationType.USER_REPLIED,
                    )
                )
            else:
                ticket.status = TicketStatus.NEW
                ticket.assigned_membership_id = None
                ticket.claimed_at = None
                conversation.state = ConversationState.WAITING_HUMAN
        elif ticket.status == TicketStatus.NEW:
            conversation.state = ConversationState.WAITING_HUMAN
        else:
            conversation.state = ConversationState.HUMAN_ACTIVE
        touch_ticket(ticket, now)

    message = WhatsAppMessage(
        project_id=project_id,
        conversation_id=conversation.id,
        ticket_id=ticket.id,
        meta_message_id=meta_message_id,
        direction=MessageDirection.INBOUND,
        sender_type=MessageSenderType.USER,
        message_type=MessageType.TEXT,
        text_content=text,
        delivery_status=DeliveryStatus.RECEIVED,
        provider_timestamp=now,
    )
    database.add(message)
    conversation.last_inbound_at = now
    await database.flush()
    return InboundEscalationResult(
        conversation=conversation,
        ticket=ticket,
        message=message,
        deduplicated=False,
        reopened=reopened,
    )
