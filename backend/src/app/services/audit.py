from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditEvent


async def record_audit_event(
    session: AsyncSession,
    *,
    action: str,
    outcome: str,
    project_id: str | None = None,
    actor_account_id: UUID | None = None,
    actor_membership_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        project_id=project_id,
        actor_account_id=actor_account_id,
        actor_membership_id=actor_membership_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id,
        event_metadata=metadata or {},
    )
    session.add(event)
    await session.flush()
    return event

