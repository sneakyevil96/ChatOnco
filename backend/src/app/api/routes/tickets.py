from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthContext,
    ProjectMembershipContext,
    get_database_session,
    require_authenticated_csrf,
    require_project_administrator,
    require_project_membership,
)
from app.api.schemas.tickets import (
    InternalNoteCreateRequest,
    InternalNoteResponse,
    OperatorNotificationResponse,
    TicketActionResponse,
    TicketAssigneeResponse,
    TicketDetailResponse,
    TicketListItemResponse,
    TicketMessageResponse,
    TicketQueue,
    TicketReassignRequest,
    TicketReplyRequest,
)
from app.core.project_config import ProjectId
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.conversation import (
    Conversation,
    InternalNote,
    OperatorNotification,
    Ticket,
    WhatsAppMessage,
)
from app.db.models.enums import (
    ConversationState,
    DeliveryStatus,
    MessageDirection,
    MessageSenderType,
    MessageType,
    NotificationType,
    OperatorRole,
    TicketStatus,
)
from app.db.models.outbox import OutboxEntry
from app.services.audit import record_audit_event
from app.services.ticket_workflow import (
    ACTIVE_TICKET_STATUSES,
    INACTIVE_TICKET_STATUSES,
    mask_phone_number,
    membership_is_active,
    touch_ticket,
)

router = APIRouter()


def require_same_csrf_context(
    project_context: ProjectMembershipContext,
    csrf_auth: AuthContext,
) -> None:
    if project_context.auth.account.id != csrf_auth.account.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sesiune invalidă")


def ticket_action_response(ticket: Ticket) -> TicketActionResponse:
    return TicketActionResponse(
        ticket_id=ticket.id,
        status=ticket.status,
        assigned_membership_id=ticket.assigned_membership_id,
        row_version=ticket.row_version,
    )


def ensure_can_view(ticket: Ticket, context: ProjectMembershipContext) -> None:
    if context.membership.role == OperatorRole.ADMINISTRATOR:
        return
    if ticket.status == TicketStatus.NEW and ticket.assigned_membership_id is None:
        return
    if ticket.assigned_membership_id == context.membership.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acces neautorizat la tichet")


def ensure_can_manage(ticket: Ticket, context: ProjectMembershipContext) -> None:
    if context.membership.role == OperatorRole.ADMINISTRATOR:
        return
    if ticket.assigned_membership_id == context.membership.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tichetul nu vă este atribuit")


async def load_ticket_and_conversation(
    database: AsyncSession,
    project_id: str,
    ticket_id: UUID,
    *,
    for_update: bool = False,
) -> tuple[Ticket, Conversation]:
    statement = (
        select(Ticket, Conversation)
        .join(
            Conversation,
            (Conversation.project_id == Ticket.project_id)
            & (Conversation.id == Ticket.conversation_id),
        )
        .where(Ticket.project_id == project_id, Ticket.id == ticket_id)
    )
    if for_update:
        statement = statement.with_for_update(of=Ticket)
    row = (await database.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tichet inexistent")
    return row[0], row[1]


async def assignee_response(
    database: AsyncSession,
    project_id: str,
    membership_id: UUID | None,
) -> TicketAssigneeResponse | None:
    if membership_id is None:
        return None
    row = (
        await database.execute(
            select(OperatorProjectMembership, OperatorAccount)
            .join(
                OperatorAccount,
                OperatorAccount.id == OperatorProjectMembership.operator_account_id,
            )
            .where(
                OperatorProjectMembership.project_id == project_id,
                OperatorProjectMembership.id == membership_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return TicketAssigneeResponse(
        membership_id=row[0].id,
        email=row[1].email,
        role=row[0].role,
    )


async def list_item_response(
    database: AsyncSession,
    ticket: Ticket,
    conversation: Conversation,
    latest_preview: str | None,
) -> TicketListItemResponse:
    return TicketListItemResponse(
        ticket_id=ticket.id,
        reference=ticket.reference,
        created_at=ticket.created_at,
        last_activity_at=ticket.last_activity_at,
        latest_message_preview=latest_preview,
        status=ticket.status,
        assigned_operator=await assignee_response(
            database,
            ticket.project_id,
            ticket.assigned_membership_id,
        ),
        masked_phone_number=mask_phone_number(
            conversation.phone_number_e164 or conversation.whatsapp_user_id
        ),
        row_version=ticket.row_version,
    )


async def audit_ticket_action(
    database: AsyncSession,
    context: ProjectMembershipContext,
    ticket: Ticket,
    action: str,
    *,
    metadata: dict | None = None,
) -> None:
    await record_audit_event(
        database,
        project_id=ticket.project_id,
        actor_account_id=context.auth.account.id,
        actor_membership_id=context.membership.id,
        action=action,
        outcome="success",
        target_type="ticket",
        target_id=str(ticket.id),
        metadata=metadata,
    )


@router.get("", response_model=list[TicketListItemResponse])
async def list_tickets(
    project_id: str,
    queue: TicketQueue = Query(default="new"),
    limit: int = Query(default=100, ge=1, le=200),
    context: ProjectMembershipContext = Depends(require_project_membership),
    database: AsyncSession = Depends(get_database_session),
) -> list[TicketListItemResponse]:
    if queue == "all" and context.membership.role != OperatorRole.ADMINISTRATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol de administrator necesar")

    latest_preview = (
        select(
            case(
                (
                    WhatsAppMessage.text_content.is_not(None),
                    func.left(WhatsAppMessage.text_content, 160),
                ),
                else_=literal("[Mesaj fără conținut text]"),
            )
        )
        .where(
            WhatsAppMessage.project_id == Ticket.project_id,
            WhatsAppMessage.conversation_id == Ticket.conversation_id,
        )
        .order_by(WhatsAppMessage.created_at.desc(), WhatsAppMessage.id.desc())
        .limit(1)
        .correlate(Ticket)
        .scalar_subquery()
    )
    statement = (
        select(Ticket, Conversation, latest_preview)
        .join(
            Conversation,
            (Conversation.project_id == Ticket.project_id)
            & (Conversation.id == Ticket.conversation_id),
        )
        .where(Ticket.project_id == project_id)
    )
    if queue == "new":
        statement = statement.where(
            Ticket.status == TicketStatus.NEW,
            Ticket.assigned_membership_id.is_(None),
        )
    elif queue == "mine":
        statement = statement.where(
            Ticket.status.in_(ACTIVE_TICKET_STATUSES),
            Ticket.assigned_membership_id == context.membership.id,
        )
    elif queue == "resolved":
        statement = statement.where(Ticket.status.in_(INACTIVE_TICKET_STATUSES))
        if context.membership.role != OperatorRole.ADMINISTRATOR:
            statement = statement.where(Ticket.assigned_membership_id == context.membership.id)
    elif queue == "all":
        statement = statement.where(Ticket.status.in_(ACTIVE_TICKET_STATUSES))

    rows = (
        await database.execute(
            statement.order_by(Ticket.last_activity_at.desc(), Ticket.id.desc()).limit(limit)
        )
    ).all()
    return [
        await list_item_response(database, ticket, conversation, preview)
        for ticket, conversation, preview in rows
    ]


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def ticket_detail(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_membership),
    database: AsyncSession = Depends(get_database_session),
) -> TicketDetailResponse:
    ticket, conversation = await load_ticket_and_conversation(database, project_id, ticket_id)
    ensure_can_view(ticket, context)
    messages = list(
        await database.scalars(
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.project_id == project_id,
                WhatsAppMessage.conversation_id == conversation.id,
            )
            .order_by(WhatsAppMessage.created_at, WhatsAppMessage.id)
        )
    )
    note_rows = (
        await database.execute(
            select(InternalNote, OperatorAccount.email)
            .join(
                OperatorProjectMembership,
                (OperatorProjectMembership.project_id == InternalNote.project_id)
                & (OperatorProjectMembership.id == InternalNote.author_membership_id),
            )
            .join(
                OperatorAccount,
                OperatorAccount.id == OperatorProjectMembership.operator_account_id,
            )
            .where(
                InternalNote.project_id == project_id,
                InternalNote.ticket_id == ticket.id,
                InternalNote.redacted_at.is_(None),
            )
            .order_by(InternalNote.created_at, InternalNote.id)
        )
    ).all()
    expires_at = (
        conversation.last_inbound_at + timedelta(hours=24)
        if conversation.last_inbound_at
        else None
    )
    now = datetime.now(UTC)
    latest_preview = None
    if messages:
        latest = messages[-1]
        latest_preview = (
            latest.text_content[:160]
            if latest.text_content and latest.content_redacted_at is None
            else "[Mesaj fără conținut text]"
        )
    base = await list_item_response(database, ticket, conversation, latest_preview)
    return TicketDetailResponse(
        **base.model_dump(),
        conversation_id=conversation.id,
        conversation_state=conversation.state.value,
        last_inbound_at=conversation.last_inbound_at,
        customer_service_window_open=expires_at is not None and expires_at >= now,
        customer_service_window_expires_at=expires_at,
        reopen_until=ticket.reopen_until,
        messages=[
            TicketMessageResponse(
                message_id=message.id,
                ticket_id=message.ticket_id,
                direction=message.direction,
                sender_type=message.sender_type,
                message_type=message.message_type,
                text_content=(
                    message.text_content if message.content_redacted_at is None else None
                ),
                attachment_metadata=message.attachment_metadata,
                delivery_status=message.delivery_status,
                operator_membership_id=message.operator_membership_id,
                created_at=message.created_at,
                provider_timestamp=message.provider_timestamp,
                sent_at=message.sent_at,
                delivered_at=message.delivered_at,
                read_at=message.read_at,
                failed_at=message.failed_at,
                error_code=message.error_code,
                error_summary=message.error_summary,
            )
            for message in messages
        ],
        internal_notes=[
            InternalNoteResponse(
                note_id=note.id,
                author_membership_id=note.author_membership_id,
                author_email=email,
                content=note.content,
                created_at=note.created_at,
            )
            for note, email in note_rows
        ],
    )


@router.post("/{ticket_id}/claim", response_model=TicketActionResponse)
async def claim_ticket(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status != TicketStatus.NEW or ticket.assigned_membership_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul a fost deja preluat")
    now = datetime.now(UTC)
    ticket.status = TicketStatus.CLAIMED
    ticket.assigned_membership_id = context.membership.id
    ticket.claimed_at = now
    conversation.state = ConversationState.HUMAN_ACTIVE
    touch_ticket(ticket, now)
    await audit_ticket_action(database, context, ticket, "ticket.claimed")
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/release", response_model=TicketActionResponse)
async def release_ticket(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status not in ACTIVE_TICKET_STATUSES or ticket.assigned_membership_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul nu este atribuit")
    ensure_can_manage(ticket, context)
    previous_assignment = ticket.assigned_membership_id
    now = datetime.now(UTC)
    ticket.status = TicketStatus.NEW
    ticket.assigned_membership_id = None
    ticket.claimed_at = None
    ticket.waiting_user_at = None
    conversation.state = ConversationState.WAITING_HUMAN
    touch_ticket(ticket, now)
    await audit_ticket_action(
        database,
        context,
        ticket,
        "ticket.released",
        metadata={"previous_membership_id": str(previous_assignment)},
    )
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/reassign", response_model=TicketActionResponse)
async def reassign_ticket(
    project_id: str,
    ticket_id: UUID,
    payload: TicketReassignRequest,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status not in ACTIVE_TICKET_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul nu este activ")
    target = await database.scalar(
        select(OperatorProjectMembership)
        .join(OperatorAccount, OperatorAccount.id == OperatorProjectMembership.operator_account_id)
        .where(
            OperatorProjectMembership.project_id == project_id,
            OperatorProjectMembership.id == payload.membership_id,
            OperatorProjectMembership.is_active.is_(True),
            OperatorAccount.disabled_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Operator indisponibil")
    previous_assignment = ticket.assigned_membership_id
    now = datetime.now(UTC)
    ticket.status = TicketStatus.CLAIMED
    ticket.assigned_membership_id = target.id
    ticket.claimed_at = now
    ticket.waiting_user_at = None
    conversation.state = ConversationState.HUMAN_ACTIVE
    touch_ticket(ticket, now)
    if previous_assignment != target.id:
        database.add(
            OperatorNotification(
                project_id=project_id,
                ticket_id=ticket.id,
                recipient_membership_id=target.id,
                notification_type=NotificationType.TICKET_ASSIGNED,
            )
        )
    await audit_ticket_action(
        database,
        context,
        ticket,
        "ticket.reassigned",
        metadata={
            "previous_membership_id": str(previous_assignment) if previous_assignment else None,
            "new_membership_id": str(target.id),
        },
    )
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/waiting-user", response_model=TicketActionResponse)
async def mark_waiting_user(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status not in ACTIVE_TICKET_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul nu este activ")
    ensure_can_manage(ticket, context)
    if ticket.assigned_membership_id is None:
        ticket.assigned_membership_id = context.membership.id
        ticket.claimed_at = datetime.now(UTC)
    now = datetime.now(UTC)
    ticket.status = TicketStatus.WAITING_USER
    ticket.waiting_user_at = now
    conversation.state = ConversationState.WAITING_USER
    touch_ticket(ticket, now)
    await audit_ticket_action(database, context, ticket, "ticket.waiting_for_user")
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/resolve", response_model=TicketActionResponse)
async def resolve_ticket(
    project_id: str,
    ticket_id: UUID,
    request: Request,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status not in ACTIVE_TICKET_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul nu este activ")
    ensure_can_manage(ticket, context)
    now = datetime.now(UTC)
    reopen_days = request.app.state.project_catalog.get(
        ProjectId(project_id)
    ).retention.resolved_ticket_reopen_days
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = now
    ticket.reopen_until = now + timedelta(days=reopen_days)
    ticket.waiting_user_at = None
    conversation.state = ConversationState.CLOSED
    touch_ticket(ticket, now)
    await audit_ticket_action(
        database,
        context,
        ticket,
        "ticket.resolved",
        metadata={"reopen_until": ticket.reopen_until.isoformat()},
    )
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/close", response_model=TicketActionResponse)
async def close_ticket(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul este deja închis")
    now = datetime.now(UTC)
    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = now
    ticket.reopen_until = None
    ticket.waiting_user_at = None
    touch_ticket(ticket, now)
    other_active = await database.scalar(
        select(Ticket).where(
            Ticket.project_id == project_id,
            Ticket.conversation_id == conversation.id,
            Ticket.id != ticket.id,
            Ticket.status.in_(ACTIVE_TICKET_STATUSES),
        )
    )
    if other_active is None:
        conversation.state = ConversationState.CLOSED
    await audit_ticket_action(database, context, ticket, "ticket.closed")
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/reopen", response_model=TicketActionResponse)
async def reopen_ticket(
    project_id: str,
    ticket_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketActionResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status != TicketStatus.RESOLVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Doar tichetele rezolvate pot fi redeschise")
    active_ticket = await database.scalar(
        select(Ticket).where(
            Ticket.project_id == project_id,
            Ticket.conversation_id == conversation.id,
            Ticket.id != ticket.id,
            Ticket.status.in_(ACTIVE_TICKET_STATUSES),
        )
    )
    if active_ticket is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversația are deja un tichet activ",
        )
    now = datetime.now(UTC)
    if await membership_is_active(database, project_id, ticket.assigned_membership_id):
        ticket.status = TicketStatus.CLAIMED
        ticket.claimed_at = now
        conversation.state = ConversationState.HUMAN_ACTIVE
        database.add(
            OperatorNotification(
                project_id=project_id,
                ticket_id=ticket.id,
                recipient_membership_id=ticket.assigned_membership_id,
                notification_type=NotificationType.TICKET_REOPENED,
            )
        )
    else:
        ticket.status = TicketStatus.NEW
        ticket.assigned_membership_id = None
        ticket.claimed_at = None
        conversation.state = ConversationState.WAITING_HUMAN
    ticket.resolved_at = None
    ticket.reopen_until = None
    touch_ticket(ticket, now)
    await audit_ticket_action(database, context, ticket, "ticket.manually_reopened")
    await database.commit()
    return ticket_action_response(ticket)


@router.post("/{ticket_id}/notes", response_model=InternalNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_internal_note(
    project_id: str,
    ticket_id: UUID,
    payload: InternalNoteCreateRequest,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> InternalNoteResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, _conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    ensure_can_manage(ticket, context)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nota este goală")
    note = InternalNote(
        project_id=project_id,
        ticket_id=ticket.id,
        author_membership_id=context.membership.id,
        content=content,
    )
    database.add(note)
    touch_ticket(ticket, datetime.now(UTC))
    await database.flush()
    await audit_ticket_action(database, context, ticket, "ticket.internal_note_added")
    await database.commit()
    return InternalNoteResponse(
        note_id=note.id,
        author_membership_id=note.author_membership_id,
        author_email=context.auth.account.email,
        content=note.content,
        created_at=note.created_at,
    )


@router.post("/{ticket_id}/reply", response_model=TicketMessageResponse, status_code=status.HTTP_201_CREATED)
async def reply_to_ticket(
    project_id: str,
    ticket_id: UUID,
    payload: TicketReplyRequest,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> TicketMessageResponse:
    require_same_csrf_context(context, csrf_auth)
    ticket, conversation = await load_ticket_and_conversation(
        database, project_id, ticket_id, for_update=True
    )
    if ticket.status not in ACTIVE_TICKET_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tichetul nu este activ")
    ensure_can_manage(ticket, context)
    now = datetime.now(UTC)
    window_expires = (
        conversation.last_inbound_at + timedelta(hours=24)
        if conversation.last_inbound_at
        else None
    )
    if window_expires is None or window_expires < now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fereastra WhatsApp de 24 de ore este închisă; este necesar un șablon aprobat",
        )
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Răspunsul este gol")
    if ticket.assigned_membership_id is None:
        ticket.assigned_membership_id = context.membership.id
        ticket.claimed_at = now
    client_reference = f"operator-{uuid4()}"
    message = WhatsAppMessage(
        project_id=project_id,
        conversation_id=conversation.id,
        ticket_id=ticket.id,
        operator_membership_id=context.membership.id,
        client_reference=client_reference,
        direction=MessageDirection.OUTBOUND,
        sender_type=MessageSenderType.OPERATOR,
        message_type=MessageType.TEXT,
        text_content=text,
        delivery_status=DeliveryStatus.QUEUED,
    )
    database.add(message)
    await database.flush()
    database.add(
        OutboxEntry(
            project_id=project_id,
            message_id=message.id,
            idempotency_key=client_reference,
            payload={
                "kind": "text",
                "project_id": project_id,
                "recipient": conversation.whatsapp_user_id,
                "text": text,
                "client_reference": client_reference,
            },
        )
    )
    ticket.status = TicketStatus.CLAIMED
    ticket.waiting_user_at = None
    conversation.state = ConversationState.HUMAN_ACTIVE
    touch_ticket(ticket, now)
    await audit_ticket_action(database, context, ticket, "ticket.operator_reply_queued")
    await database.commit()
    return TicketMessageResponse(
        message_id=message.id,
        ticket_id=message.ticket_id,
        direction=message.direction,
        sender_type=message.sender_type,
        message_type=message.message_type,
        text_content=message.text_content,
        attachment_metadata=message.attachment_metadata,
        delivery_status=message.delivery_status,
        operator_membership_id=message.operator_membership_id,
        created_at=message.created_at,
        provider_timestamp=message.provider_timestamp,
        sent_at=message.sent_at,
        delivered_at=message.delivered_at,
        read_at=message.read_at,
        failed_at=message.failed_at,
        error_code=message.error_code,
        error_summary=message.error_summary,
    )


@router.get("/notifications/unread", response_model=list[OperatorNotificationResponse])
async def unread_notifications(
    project_id: str,
    context: ProjectMembershipContext = Depends(require_project_membership),
    database: AsyncSession = Depends(get_database_session),
) -> list[OperatorNotificationResponse]:
    rows = (
        await database.execute(
            select(OperatorNotification, Ticket.reference)
            .join(
                Ticket,
                (Ticket.project_id == OperatorNotification.project_id)
                & (Ticket.id == OperatorNotification.ticket_id),
            )
            .where(
                OperatorNotification.project_id == project_id,
                OperatorNotification.recipient_membership_id == context.membership.id,
                OperatorNotification.read_at.is_(None),
                OperatorNotification.dismissed_at.is_(None),
            )
            .order_by(OperatorNotification.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        OperatorNotificationResponse(
            notification_id=notification.id,
            ticket_id=notification.ticket_id,
            ticket_reference=reference,
            notification_type=notification.notification_type,
            created_at=notification.created_at,
            read_at=notification.read_at,
        )
        for notification, reference in rows
    ]


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(
    project_id: str,
    notification_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_membership),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> None:
    require_same_csrf_context(context, csrf_auth)
    notification = await database.scalar(
        select(OperatorNotification)
        .where(
            OperatorNotification.project_id == project_id,
            OperatorNotification.id == notification_id,
            OperatorNotification.recipient_membership_id == context.membership.id,
        )
        .with_for_update()
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificare inexistentă")
    notification.read_at = datetime.now(UTC)
    await database.commit()
