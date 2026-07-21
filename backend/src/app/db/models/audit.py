from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UuidPrimaryKeyMixin


class AuditEvent(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(
            ["project_id", "actor_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
    )

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operator_accounts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_membership_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(160))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

