from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ProjectMembershipContext, get_database_session, require_project_administrator
from app.api.schemas.operations import (
    AuditEventPageResponse,
    AuditEventResponse,
    DeliveryFailureSummary,
    OperationalSummaryResponse,
    RetentionPolicySummary,
)
from app.core.project_config import ProjectCatalog, ProjectId
from app.db.models.audit import AuditEvent
from app.db.models.conversation import Ticket, WhatsAppMessage
from app.db.models.enums import DeliveryStatus, OutboxStatus, TicketStatus
from app.db.models.outbox import OutboxEntry
from app.db.models.whatsapp import WhatsAppWebhookEvent


router = APIRouter()
INACTIVE_TICKET_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)


@router.get("/summary", response_model=OperationalSummaryResponse)
async def operational_summary(
    project_id: str,
    request: Request,
    _context: ProjectMembershipContext = Depends(require_project_administrator),
    database: AsyncSession = Depends(get_database_session),
) -> OperationalSummaryResponse:
    now = datetime.now(UTC)
    settings = request.app.state.settings
    catalog: ProjectCatalog = request.app.state.project_catalog
    project = catalog.get(ProjectId(project_id))
    stale_cutoff = now - timedelta(minutes=settings.operations_stale_outbox_minutes)
    message_cutoff = now - timedelta(days=project.retention.message_content_days)
    ticket_cutoff = now - timedelta(days=project.retention.tickets_and_notes_days)

    pending_outbox = await database.scalar(
        select(func.count()).select_from(OutboxEntry).where(
            OutboxEntry.project_id == project_id,
            OutboxEntry.status.in_((OutboxStatus.PENDING, OutboxStatus.PROCESSING)),
        )
    )
    stale_outbox = await database.scalar(
        select(func.count()).select_from(OutboxEntry).where(
            OutboxEntry.project_id == project_id,
            or_(
                and_(
                    OutboxEntry.status == OutboxStatus.PENDING,
                    OutboxEntry.available_at < stale_cutoff,
                ),
                and_(
                    OutboxEntry.status == OutboxStatus.PROCESSING,
                    OutboxEntry.claimed_until.is_not(None),
                    OutboxEntry.claimed_until < now,
                ),
            ),
        )
    )
    failed_outbox = await database.scalar(
        select(func.count()).select_from(OutboxEntry).where(
            OutboxEntry.project_id == project_id,
            OutboxEntry.status == OutboxStatus.FAILED,
        )
    )
    oldest_pending_at = await database.scalar(
        select(func.min(OutboxEntry.created_at)).where(
            OutboxEntry.project_id == project_id,
            OutboxEntry.status.in_((OutboxStatus.PENDING, OutboxStatus.PROCESSING)),
        )
    )
    unprocessed_webhooks = await database.scalar(
        select(func.count()).select_from(WhatsAppWebhookEvent).where(
            WhatsAppWebhookEvent.project_id == project_id,
            WhatsAppWebhookEvent.processed_at.is_(None),
        )
    )
    recent_failure_count = await database.scalar(
        select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.delivery_status == DeliveryStatus.FAILED,
            WhatsAppMessage.failed_at >= now - timedelta(hours=24),
        )
    )
    messages_due = await database.scalar(
        select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.project_id == project_id,
            WhatsAppMessage.created_at < message_cutoff,
            WhatsAppMessage.content_redacted_at.is_(None),
            or_(
                WhatsAppMessage.text_content.is_not(None),
                WhatsAppMessage.attachment_metadata.is_not(None),
            ),
        )
    )
    tickets_due = await database.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.project_id == project_id,
            Ticket.status.in_(INACTIVE_TICKET_STATUSES),
            Ticket.last_activity_at < ticket_cutoff,
        )
    )
    last_retention = await database.scalar(
        select(AuditEvent.created_at)
        .where(
            AuditEvent.project_id == project_id,
            AuditEvent.action == "retention.project_applied",
            AuditEvent.outcome == "success",
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    failure_rows = (
        await database.execute(
            select(WhatsAppMessage, Ticket.reference)
            .outerjoin(
                Ticket,
                (Ticket.project_id == WhatsAppMessage.project_id)
                & (Ticket.id == WhatsAppMessage.ticket_id),
            )
            .where(
                WhatsAppMessage.project_id == project_id,
                WhatsAppMessage.delivery_status == DeliveryStatus.FAILED,
            )
            .order_by(WhatsAppMessage.failed_at.desc().nullslast())
            .limit(10)
        )
    ).all()
    return OperationalSummaryResponse(
        project_id=project_id,
        generated_at=now,
        pending_outbox=pending_outbox or 0,
        stale_outbox=stale_outbox or 0,
        failed_outbox=failed_outbox or 0,
        oldest_pending_at=oldest_pending_at,
        unprocessed_webhook_events=unprocessed_webhooks or 0,
        delivery_failures_last_24_hours=recent_failure_count or 0,
        messages_due_for_redaction=messages_due or 0,
        inactive_tickets_due_for_retention=tickets_due or 0,
        last_retention_run_at=last_retention,
        retention=RetentionPolicySummary(
            message_content_days=project.retention.message_content_days,
            tickets_and_notes_days=project.retention.tickets_and_notes_days,
            audit_events_days=project.retention.audit_events_days,
            application_logs_days=project.retention.application_logs_days,
            backups_days=project.retention.backups_days,
        ),
        recent_delivery_failures=[
            DeliveryFailureSummary(
                message_id=message.id,
                ticket_id=message.ticket_id,
                ticket_reference=reference,
                failed_at=message.failed_at,
                error_code=message.error_code,
                error_summary=message.error_summary,
            )
            for message, reference in failure_rows
        ],
    )


@router.get("/audit-events", response_model=AuditEventPageResponse)
async def audit_events(
    project_id: str,
    action: str | None = Query(default=None, max_length=160),
    outcome: str | None = Query(default=None, max_length=32),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _context: ProjectMembershipContext = Depends(require_project_administrator),
    database: AsyncSession = Depends(get_database_session),
) -> AuditEventPageResponse:
    filters = [AuditEvent.project_id == project_id]
    if action:
        filters.append(AuditEvent.action == action)
    if outcome:
        filters.append(AuditEvent.outcome == outcome)
    total = await database.scalar(
        select(func.count()).select_from(AuditEvent).where(*filters)
    )
    events = (
        await database.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return AuditEventPageResponse(
        items=[
            AuditEventResponse(
                event_id=event.id,
                created_at=event.created_at,
                actor_account_id=event.actor_account_id,
                actor_membership_id=event.actor_membership_id,
                action=event.action,
                target_type=event.target_type,
                target_id=event.target_id,
                outcome=event.outcome,
                request_id=event.request_id,
                metadata=event.event_metadata,
            )
            for event in events
        ],
        offset=offset,
        limit=limit,
        total=total or 0,
    )
