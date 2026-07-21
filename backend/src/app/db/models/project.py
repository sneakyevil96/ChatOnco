from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import ProjectOwnedMixin, TimestampMixin, UuidPrimaryKeyMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    public_name: Mapped[str] = mapped_column(String(160), nullable=False)
    content_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="development_placeholder"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class RetentionPolicy(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "version"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint("message_content_days > 0", name="positive_message_content_days"),
        CheckConstraint("tickets_and_notes_days > 0", name="positive_tickets_notes_days"),
        CheckConstraint("audit_events_days > 0", name="positive_audit_days"),
        CheckConstraint("application_logs_days > 0", name="positive_log_days"),
        CheckConstraint("backups_days > 0", name="positive_backup_days"),
        CheckConstraint(
            "privacy_warning_inactivity_days > 0",
            name="positive_privacy_warning_inactivity_days",
        ),
        CheckConstraint("resolved_ticket_reopen_days >= 0", name="valid_reopen_days"),
        Index(
            "uq_retention_policies_one_current_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    message_content_days: Mapped[int] = mapped_column(Integer, nullable=False)
    tickets_and_notes_days: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_events_days: Mapped[int] = mapped_column(Integer, nullable=False)
    application_logs_days: Mapped[int] = mapped_column(Integer, nullable=False)
    backups_days: Mapped[int] = mapped_column(Integer, nullable=False)
    privacy_warning_inactivity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_ticket_reopen_days: Mapped[int] = mapped_column(Integer, nullable=False)
