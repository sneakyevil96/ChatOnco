from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import OutboxStatus, database_enum
from app.db.models.mixins import ProjectOwnedMixin, TimestampMixin, UuidPrimaryKeyMixin


class OutboxEntry(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "outbox_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["project_id", "message_id"],
            ["whatsapp_messages.project_id", "whatsapp_messages.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "template_id"],
            ["whatsapp_templates.project_id", "whatsapp_templates.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_outbox_entries_claimable",
            "status",
            "available_at",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )

    message_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    template_id: Mapped[UUID | None] = mapped_column(index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        database_enum(OutboxStatus, "outbox_status"),
        nullable=False,
        server_default=OutboxStatus.PENDING.value,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(160))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_error_code: Mapped[str | None] = mapped_column(String(128))
    terminal_error_summary: Mapped[str | None] = mapped_column(String(512))

