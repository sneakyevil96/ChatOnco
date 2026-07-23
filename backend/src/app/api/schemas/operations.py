from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RetentionPolicySummary(BaseModel):
    message_content_days: int
    tickets_and_notes_days: int
    audit_events_days: int
    application_logs_days: int
    backups_days: int


class DeliveryFailureSummary(BaseModel):
    message_id: UUID
    ticket_id: UUID | None
    ticket_reference: str | None
    failed_at: datetime | None
    error_code: str | None
    error_summary: str | None


class OperationalSummaryResponse(BaseModel):
    project_id: str
    generated_at: datetime
    pending_outbox: int
    stale_outbox: int
    failed_outbox: int
    oldest_pending_at: datetime | None
    unprocessed_webhook_events: int
    delivery_failures_last_24_hours: int
    messages_due_for_redaction: int
    inactive_tickets_due_for_retention: int
    last_retention_run_at: datetime | None
    retention: RetentionPolicySummary
    recent_delivery_failures: list[DeliveryFailureSummary]


class AuditEventResponse(BaseModel):
    event_id: UUID
    created_at: datetime
    actor_account_id: UUID | None
    actor_membership_id: UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    request_id: str | None
    metadata: dict


class AuditEventPageResponse(BaseModel):
    items: list[AuditEventResponse]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int
