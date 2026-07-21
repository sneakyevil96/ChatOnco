from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_config import ProjectConfig
from app.db.models.conversation import Conversation, Ticket, WhatsAppMessage
from app.db.models.enums import (
    ConversationState,
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    TicketStatus,
)
from app.db.models.outbox import OutboxEntry
from app.services.faq_embeddings import EmbeddingProvider
from app.services.faq_retrieval import (
    FaqRetrievalOutcome,
    FaqRetrievalResult,
    retrieve_approved_faq,
)
from app.services.ticket_workflow import ACTIVE_TICKET_STATUSES, escalate_inbound_text


class InboundOutcome(StrEnum):
    FAQ_ANSWER = "FAQ_ANSWER"
    HUMAN_SUPPORT = "HUMAN_SUPPORT"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class InboundHandlingResult:
    outcome: InboundOutcome
    conversation_id: UUID
    inbound_message_id: UUID
    outbound_message_id: UUID | None = None
    ticket_id: UUID | None = None
    faq_result: FaqRetrievalResult | None = None


async def queue_bot_text(
    database: AsyncSession,
    *,
    project_id: str,
    conversation_id: UUID,
    ticket_id: UUID | None,
    recipient: str,
    text: str,
) -> WhatsAppMessage:
    client_reference = f"bot-{uuid4()}"
    message = WhatsAppMessage(
        project_id=project_id,
        conversation_id=conversation_id,
        ticket_id=ticket_id,
        client_reference=client_reference,
        direction=MessageDirection.OUTBOUND,
        sender_type=MessageSenderType.BOT,
        message_type=MessageType.TEXT,
        text_content=text,
        delivery_status=DeliveryStatus.QUEUED,
    )
    database.add(message)
    await database.flush()
    database.add(
        OutboxEntry(
            project_id=project_id,
            message_id=message.id,
            idempotency_key=client_reference,
            payload={
                "kind": "text",
                "project_id": project_id,
                "recipient": recipient,
                "text": text,
                "client_reference": client_reference,
            },
        )
    )
    return message


async def handle_inbound_text(
    database: AsyncSession,
    *,
    project: ProjectConfig,
    whatsapp_user_id: str,
    text: str,
    meta_message_id: str,
    phone_number_e164: str | None = None,
    received_at: datetime | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> InboundHandlingResult:
    now = received_at or datetime.now(UTC)
    project_id = project.project_id.value
    duplicate = await database.scalar(
        select(WhatsAppMessage).where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.meta_message_id == meta_message_id,
        )
    )
    if duplicate is not None:
        return InboundHandlingResult(
            outcome=InboundOutcome.DUPLICATE,
            conversation_id=duplicate.conversation_id,
            inbound_message_id=duplicate.id,
            ticket_id=duplicate.ticket_id,
        )

    conversation = await database.scalar(
        select(Conversation)
        .where(
            Conversation.project_id == project_id,
            Conversation.whatsapp_user_id == whatsapp_user_id,
        )
        .with_for_update()
    )
    human_ticket: Ticket | None = None
    if conversation is not None:
        human_ticket = await database.scalar(
            select(Ticket)
            .where(
                Ticket.project_id == project_id,
                Ticket.conversation_id == conversation.id,
                Ticket.status.in_(ACTIVE_TICKET_STATUSES),
            )
            .with_for_update()
        )
        if human_ticket is None:
            human_ticket = await database.scalar(
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
    if human_ticket is not None:
        escalated = await escalate_inbound_text(
            database,
            project_id=project_id,
            whatsapp_user_id=whatsapp_user_id,
            phone_number_e164=phone_number_e164,
            text=text,
            meta_message_id=meta_message_id,
            received_at=now,
        )
        return InboundHandlingResult(
            outcome=InboundOutcome.HUMAN_SUPPORT,
            conversation_id=escalated.conversation.id,
            inbound_message_id=escalated.message.id,
            ticket_id=escalated.ticket.id,
        )

    faq_result = await retrieve_approved_faq(
        database,
        project_id=project_id,
        question=text,
        configuration=project.faq_retrieval,
        embedding_provider=embedding_provider,
        now=now,
    )
    if faq_result.outcome == FaqRetrievalOutcome.ESCALATE:
        escalated = await escalate_inbound_text(
            database,
            project_id=project_id,
            whatsapp_user_id=whatsapp_user_id,
            phone_number_e164=phone_number_e164,
            text=text,
            meta_message_id=meta_message_id,
            received_at=now,
        )
        outbound = await queue_bot_text(
            database,
            project_id=project_id,
            conversation_id=escalated.conversation.id,
            ticket_id=escalated.ticket.id,
            recipient=whatsapp_user_id,
            text=project.messages.fallback,
        )
        return InboundHandlingResult(
            outcome=InboundOutcome.HUMAN_SUPPORT,
            conversation_id=escalated.conversation.id,
            inbound_message_id=escalated.message.id,
            outbound_message_id=outbound.id,
            ticket_id=escalated.ticket.id,
            faq_result=faq_result,
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
    inbound = WhatsAppMessage(
        project_id=project_id,
        conversation_id=conversation.id,
        meta_message_id=meta_message_id,
        direction=MessageDirection.INBOUND,
        sender_type=MessageSenderType.USER,
        message_type=MessageType.TEXT,
        text_content=text,
        delivery_status=DeliveryStatus.RECEIVED,
        provider_timestamp=now,
    )
    database.add(inbound)
    conversation.state = ConversationState.BOT
    conversation.last_inbound_at = now
    await database.flush()
    if faq_result.approved_answer is None:
        raise RuntimeError("A matched FAQ must contain its stored approved answer")
    outbound = await queue_bot_text(
        database,
        project_id=project_id,
        conversation_id=conversation.id,
        ticket_id=None,
        recipient=whatsapp_user_id,
        text=faq_result.approved_answer,
    )
    return InboundHandlingResult(
        outcome=InboundOutcome.FAQ_ANSWER,
        conversation_id=conversation.id,
        inbound_message_id=inbound.id,
        outbound_message_id=outbound.id,
        faq_result=faq_result,
    )
