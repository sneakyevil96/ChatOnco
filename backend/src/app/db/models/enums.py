from enum import StrEnum

from sqlalchemy import Enum


class OperatorRole(StrEnum):
    OPERATOR = "operator"
    ADMINISTRATOR = "administrator"


class ConversationState(StrEnum):
    BOT = "BOT"
    WAITING_HUMAN = "WAITING_HUMAN"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    WAITING_USER = "WAITING_USER"
    CLOSED = "CLOSED"


class TicketStatus(StrEnum):
    NEW = "NEW"
    CLAIMED = "CLAIMED"
    WAITING_USER = "WAITING_USER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageSenderType(StrEnum):
    USER = "user"
    BOT = "bot"
    OPERATOR = "operator"
    SYSTEM = "system"


class MessageType(StrEnum):
    TEXT = "text"
    TEMPLATE = "template"
    INTERACTIVE = "interactive"
    UNSUPPORTED = "unsupported"
    SYSTEM = "system"


class DeliveryStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class FaqPublicationStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"
    EXPIRED = "expired"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class NotificationType(StrEnum):
    USER_REPLIED = "user_replied"
    TICKET_REOPENED = "ticket_reopened"
    TICKET_ASSIGNED = "ticket_assigned"


def database_enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
