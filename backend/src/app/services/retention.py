from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_config import ProjectConfig
from app.db.models.audit import AuditEvent
from app.db.models.auth import LoginRateLimit, OperatorSession, PasswordResetCredential
from app.db.models.conversation import (
    Conversation,
    InternalNote,
    OperatorNotification,
    Ticket,
    WhatsAppMessage,
)
from app.db.models.enums import OutboxStatus, TicketStatus
from app.db.models.outbox import OutboxEntry
from app.db.models.whatsapp import WhatsAppWebhookEvent
from app.services.audit import record_audit_event


INACTIVE_TICKET_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)
DELIVERY_INTENT_STATUSES = (OutboxStatus.PENDING, OutboxStatus.PROCESSING)


@dataclass(frozen=True, slots=True)
class ProjectRetentionResult:
    project_id: str
    messages_redacted: int = 0
    message_records_deleted: int = 0
    outbox_payloads_redacted: int = 0
    internal_notes_deleted: int = 0
    notifications_deleted: int = 0
    tickets_deleted: int = 0
    conversations_deleted: int = 0
    webhook_events_deleted: int = 0
    audit_events_deleted: int = 0


@dataclass(frozen=True, slots=True)
class SecurityCleanupResult:
    sessions_deleted: int = 0
    reset_credentials_deleted: int = 0
    rate_limit_buckets_deleted: int = 0
    global_audit_events_deleted: int = 0


async def _ids(database: AsyncSession, statement, limit: int) -> list:
    return list((await database.scalars(statement.limit(limit))).all())


async def apply_project_retention(
    database: AsyncSession,
    *,
    project: ProjectConfig,
    now: datetime | None = None,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> ProjectRetentionResult:
    current_time = now or datetime.now(UTC)
    project_id = project.project_id.value
    message_cutoff = current_time - timedelta(days=project.retention.message_content_days)
    metadata_cutoff = current_time - timedelta(days=project.retention.tickets_and_notes_days)
    audit_cutoff = current_time - timedelta(days=project.retention.audit_events_days)

    messages_to_redact = await _ids(
        database,
        select(WhatsAppMessage.id).where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.created_at < message_cutoff,
            WhatsAppMessage.content_redacted_at.is_(None),
            or_(
                WhatsAppMessage.text_content.is_not(None),
                WhatsAppMessage.attachment_metadata.is_not(None),
            ),
        ),
        batch_size,
    )
    outbox_payloads_redacted = 0
    if messages_to_redact:
        outbox_payload_ids = await _ids(
            database,
            select(OutboxEntry.id).where(
                OutboxEntry.project_id == project_id,
                OutboxEntry.message_id.in_(messages_to_redact),
                OutboxEntry.status.in_((OutboxStatus.SENT, OutboxStatus.FAILED)),
            ),
            batch_size,
        )
        outbox_payloads_redacted = len(outbox_payload_ids)
        if not dry_run:
            await database.execute(
                update(WhatsAppMessage)
                .where(
                    WhatsAppMessage.project_id == project_id,
                    WhatsAppMessage.id.in_(messages_to_redact),
                )
                .values(
                    text_content=None,
                    attachment_metadata=None,
                    content_redacted_at=current_time,
                )
            )
            if outbox_payload_ids:
                await database.execute(
                    update(OutboxEntry)
                    .where(
                        OutboxEntry.project_id == project_id,
                        OutboxEntry.id.in_(outbox_payload_ids),
                    )
                    .values(payload={"redacted": True, "project_id": project_id})
                )

    protected_by_delivery = exists(
        select(OutboxEntry.id).where(
            OutboxEntry.project_id == WhatsAppMessage.project_id,
            OutboxEntry.message_id == WhatsAppMessage.id,
            OutboxEntry.status.in_(DELIVERY_INTENT_STATUSES),
        )
    )
    old_message_ids = await _ids(
        database,
        select(WhatsAppMessage.id).where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.created_at < metadata_cutoff,
            ~protected_by_delivery,
        ),
        batch_size,
    )
    if old_message_ids and not dry_run:
        await database.execute(
            delete(OutboxEntry).where(
                OutboxEntry.project_id == project_id,
                OutboxEntry.message_id.in_(old_message_ids),
            )
        )
        await database.execute(
            delete(WhatsAppMessage).where(
                WhatsAppMessage.project_id == project_id,
                WhatsAppMessage.id.in_(old_message_ids),
            )
        )

    old_note_ids = await _ids(
        database,
        select(InternalNote.id).where(
            InternalNote.project_id == project_id,
            InternalNote.created_at < metadata_cutoff,
        ),
        batch_size,
    )
    old_notification_ids = await _ids(
        database,
        select(OperatorNotification.id).where(
            OperatorNotification.project_id == project_id,
            OperatorNotification.created_at < metadata_cutoff,
        ),
        batch_size,
    )
    if not dry_run:
        if old_note_ids:
            await database.execute(
                delete(InternalNote).where(
                    InternalNote.project_id == project_id,
                    InternalNote.id.in_(old_note_ids),
                )
            )
        if old_notification_ids:
            await database.execute(
                delete(OperatorNotification).where(
                    OperatorNotification.project_id == project_id,
                    OperatorNotification.id.in_(old_notification_ids),
                )
            )

    remaining_ticket_message = exists(
        select(WhatsAppMessage.id).where(
            WhatsAppMessage.project_id == Ticket.project_id,
            WhatsAppMessage.ticket_id == Ticket.id,
        )
    )
    ticket_ids = await _ids(
        database,
        select(Ticket.id).where(
            Ticket.project_id == project_id,
            Ticket.status.in_(INACTIVE_TICKET_STATUSES),
            Ticket.last_activity_at < metadata_cutoff,
            ~remaining_ticket_message,
        ),
        batch_size,
    )
    if ticket_ids and not dry_run:
        await database.execute(
            delete(InternalNote).where(
                InternalNote.project_id == project_id,
                InternalNote.ticket_id.in_(ticket_ids),
            )
        )
        await database.execute(
            delete(OperatorNotification).where(
                OperatorNotification.project_id == project_id,
                OperatorNotification.ticket_id.in_(ticket_ids),
            )
        )
        await database.execute(
            delete(Ticket).where(
                Ticket.project_id == project_id,
                Ticket.id.in_(ticket_ids),
            )
        )

    has_ticket = exists(
        select(Ticket.id).where(
            Ticket.project_id == Conversation.project_id,
            Ticket.conversation_id == Conversation.id,
        )
    )
    has_message = exists(
        select(WhatsAppMessage.id).where(
            WhatsAppMessage.project_id == Conversation.project_id,
            WhatsAppMessage.conversation_id == Conversation.id,
        )
    )
    conversation_ids = await _ids(
        database,
        select(Conversation.id).where(
            Conversation.project_id == project_id,
            func.coalesce(Conversation.last_inbound_at, Conversation.created_at)
            < metadata_cutoff,
            ~has_ticket,
            ~has_message,
        ),
        batch_size,
    )
    if conversation_ids and not dry_run:
        await database.execute(
            delete(Conversation).where(
                Conversation.project_id == project_id,
                Conversation.id.in_(conversation_ids),
            )
        )

    webhook_event_ids = await _ids(
        database,
        select(WhatsAppWebhookEvent.id).where(
            WhatsAppWebhookEvent.project_id == project_id,
            WhatsAppWebhookEvent.created_at < metadata_cutoff,
        ),
        batch_size,
    )
    old_audit_ids = await _ids(
        database,
        select(AuditEvent.id).where(
            AuditEvent.project_id == project_id,
            AuditEvent.created_at < audit_cutoff,
        ),
        batch_size,
    )
    if not dry_run:
        if webhook_event_ids:
            await database.execute(
                delete(WhatsAppWebhookEvent).where(
                    WhatsAppWebhookEvent.project_id == project_id,
                    WhatsAppWebhookEvent.id.in_(webhook_event_ids),
                )
            )
        if old_audit_ids:
            await database.execute(
                delete(AuditEvent).where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.id.in_(old_audit_ids),
                )
            )

    result = ProjectRetentionResult(
        project_id=project_id,
        messages_redacted=len(messages_to_redact),
        message_records_deleted=len(old_message_ids),
        outbox_payloads_redacted=outbox_payloads_redacted,
        internal_notes_deleted=len(old_note_ids),
        notifications_deleted=len(old_notification_ids),
        tickets_deleted=len(ticket_ids),
        conversations_deleted=len(conversation_ids),
        webhook_events_deleted=len(webhook_event_ids),
        audit_events_deleted=len(old_audit_ids),
    )
    if not dry_run:
        await record_audit_event(
            database,
            project_id=project_id,
            action="retention.project_applied",
            outcome="success",
            target_type="project",
            target_id=project_id,
            metadata={
                **asdict(result),
                "message_cutoff": message_cutoff.isoformat(),
                "metadata_cutoff": metadata_cutoff.isoformat(),
                "audit_cutoff": audit_cutoff.isoformat(),
            },
        )
    return result


async def apply_security_state_cleanup(
    database: AsyncSession,
    *,
    global_audit_days: int,
    cleanup_grace_days: int,
    now: datetime | None = None,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> SecurityCleanupResult:
    current_time = now or datetime.now(UTC)
    cleanup_cutoff = current_time - timedelta(days=cleanup_grace_days)
    audit_cutoff = current_time - timedelta(days=global_audit_days)
    session_ids = await _ids(
        database,
        select(OperatorSession.id).where(
            OperatorSession.updated_at < cleanup_cutoff,
            or_(
                OperatorSession.idle_expires_at < current_time,
                OperatorSession.absolute_expires_at < current_time,
                OperatorSession.revoked_at.is_not(None),
            ),
        ),
        batch_size,
    )
    reset_ids = await _ids(
        database,
        select(PasswordResetCredential.id).where(
            PasswordResetCredential.updated_at < cleanup_cutoff,
            or_(
                PasswordResetCredential.expires_at < current_time,
                PasswordResetCredential.consumed_at.is_not(None),
            ),
        ),
        batch_size,
    )
    rate_limit_ids = await _ids(
        database,
        select(LoginRateLimit.bucket_hash).where(
            LoginRateLimit.updated_at < cleanup_cutoff,
            or_(
                LoginRateLimit.blocked_until.is_(None),
                LoginRateLimit.blocked_until < current_time,
            ),
        ),
        batch_size,
    )
    global_audit_ids = await _ids(
        database,
        select(AuditEvent.id).where(
            AuditEvent.project_id.is_(None),
            AuditEvent.created_at < audit_cutoff,
        ),
        batch_size,
    )
    if not dry_run:
        if session_ids:
            await database.execute(delete(OperatorSession).where(OperatorSession.id.in_(session_ids)))
        if reset_ids:
            await database.execute(
                delete(PasswordResetCredential).where(PasswordResetCredential.id.in_(reset_ids))
            )
        if rate_limit_ids:
            await database.execute(
                delete(LoginRateLimit).where(LoginRateLimit.bucket_hash.in_(rate_limit_ids))
            )
        if global_audit_ids:
            await database.execute(delete(AuditEvent).where(AuditEvent.id.in_(global_audit_ids)))
    result = SecurityCleanupResult(
        sessions_deleted=len(session_ids),
        reset_credentials_deleted=len(reset_ids),
        rate_limit_buckets_deleted=len(rate_limit_ids),
        global_audit_events_deleted=len(global_audit_ids),
    )
    if not dry_run:
        await record_audit_event(
            database,
            action="retention.security_state_applied",
            outcome="success",
            target_type="security_state",
            metadata=asdict(result),
        )
    return result
