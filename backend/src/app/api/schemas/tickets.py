from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.enums import (
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    NotificationType,
    OperatorRole,
    TicketStatus,
)


TicketQueue = Literal["new", "mine", "resolved", "all"]


class TicketAssigneeResponse(BaseModel):
    membership_id: UUID
    email: str
    role: OperatorRole


class TicketListItemResponse(BaseModel):
    ticket_id: UUID
    reference: str
    created_at: datetime
    last_activity_at: datetime
    latest_message_preview: str | None
    status: TicketStatus
    assigned_operator: TicketAssigneeResponse | None
    masked_phone_number: str | None
    row_version: int


class TicketMessageResponse(BaseModel):
    message_id: UUID
    ticket_id: UUID | None
    direction: MessageDirection
    sender_type: MessageSenderType
    message_type: MessageType
    text_content: str | None
    attachment_metadata: dict | None
    delivery_status: DeliveryStatus
    operator_membership_id: UUID | None
    created_at: datetime
    provider_timestamp: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_summary: str | None


class InternalNoteResponse(BaseModel):
    note_id: UUID
    author_membership_id: UUID
    author_email: str
    content: str
    created_at: datetime


class TicketDetailResponse(TicketListItemResponse):
    conversation_id: UUID
    conversation_state: str
    last_inbound_at: datetime | None
    customer_service_window_open: bool
    customer_service_window_expires_at: datetime | None
    reopen_until: datetime | None
    messages: list[TicketMessageResponse]
    internal_notes: list[InternalNoteResponse]


class TicketActionResponse(BaseModel):
    ticket_id: UUID
    status: TicketStatus
    assigned_membership_id: UUID | None
    row_version: int


class TicketReassignRequest(BaseModel):
    membership_id: UUID


class TicketReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class InternalNoteCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class OperatorNotificationResponse(BaseModel):
    notification_id: UUID
    ticket_id: UUID
    ticket_reference: str
    notification_type: NotificationType
    created_at: datetime
    read_at: datetime | None
