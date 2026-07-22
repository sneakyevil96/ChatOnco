from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import TemplateStatus, database_enum
from app.db.models.mixins import ProjectOwnedMixin, TimestampMixin, UuidPrimaryKeyMixin


class WhatsAppWebhookEvent(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    """Minimal durable webhook ledger; raw webhook bodies are never retained."""

    __tablename__ = "whatsapp_webhook_events"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "event_key"),
    )

    event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(256), index=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectWhatsAppConfiguration(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "project_whatsapp_configurations"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id"),
        UniqueConstraint("phone_number_id"),
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    phone_number_id: Mapped[str | None] = mapped_column(String(128))
    waba_id: Mapped[str | None] = mapped_column(String(128))
    meta_app_id: Mapped[str | None] = mapped_column(String(128))
    credential_binding: Mapped[str | None] = mapped_column(String(160))
    webhook_binding: Mapped[str | None] = mapped_column(String(160))


class WhatsAppTemplate(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "template_name", "language_code"),
    )

    template_name: Mapped[str] = mapped_column(String(512), nullable=False)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[TemplateStatus] = mapped_column(
        database_enum(TemplateStatus, "template_status"),
        nullable=False,
    )
    meta_template_id: Mapped[str | None] = mapped_column(String(128))
    approved_body_snapshot: Mapped[str | None] = mapped_column(Text)
    variables_schema: Mapped[dict | None] = mapped_column(JSONB)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
