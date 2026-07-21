from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import (
    ConversationState,
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    NotificationType,
    TicketStatus,
    database_enum,
)
from app.db.models.mixins import ProjectOwnedMixin, TimestampMixin, UuidPrimaryKeyMixin


class Conversation(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "whatsapp_user_id"),
    )

    whatsapp_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number_e164: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[ConversationState] = mapped_column(
        database_enum(ConversationState, "conversation_state"),
        nullable=False,
        server_default=ConversationState.BOT.value,
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_warning_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsupported_warning_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class Ticket(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "reference"),
        ForeignKeyConstraint(
            ["project_id", "conversation_id"],
            ["conversations.project_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "assigned_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_tickets_one_active_per_conversation",
            "project_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('NEW', 'CLAIMED', 'WAITING_USER')"),
        ),
    )

    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[TicketStatus] = mapped_column(
        database_enum(TicketStatus, "ticket_status"),
        nullable=False,
        server_default=TicketStatus.NEW.value,
    )
    assigned_membership_id: Mapped[UUID | None] = mapped_column(index=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_user_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WhatsAppMessage(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        UniqueConstraint("project_id", "meta_message_id"),
        ForeignKeyConstraint(
            ["project_id", "conversation_id"],
            ["conversations.project_id", "conversations.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "operator_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ticket_id: Mapped[UUID | None] = mapped_column(index=True)
    operator_membership_id: Mapped[UUID | None] = mapped_column(index=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(256))
    client_reference: Mapped[str | None] = mapped_column(String(128))
    direction: Mapped[MessageDirection] = mapped_column(
        database_enum(MessageDirection, "message_direction"), nullable=False
    )
    sender_type: Mapped[MessageSenderType] = mapped_column(
        database_enum(MessageSenderType, "message_sender_type"), nullable=False
    )
    message_type: Mapped[MessageType] = mapped_column(
        database_enum(MessageType, "message_type"), nullable=False
    )
    text_content: Mapped[str | None] = mapped_column(Text)
    attachment_metadata: Mapped[dict | None] = mapped_column(JSONB)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        database_enum(DeliveryStatus, "delivery_status"), nullable=False
    )
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_summary: Mapped[str | None] = mapped_column(String(512))


class InternalNote(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "internal_notes"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "author_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
    )

    ticket_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    author_membership_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperatorNotification(
    UuidPrimaryKeyMixin,
    ProjectOwnedMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "operator_notifications"
    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(
            ["project_id", "ticket_id"],
            ["tickets.project_id", "tickets.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "recipient_membership_id"],
            ["operator_project_memberships.project_id", "operator_project_memberships.id"],
            ondelete="RESTRICT",
        ),
    )

    ticket_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    recipient_membership_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    notification_type: Mapped[NotificationType] = mapped_column(
        database_enum(NotificationType, "notification_type"), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

