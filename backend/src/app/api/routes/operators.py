from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthContext,
    ProjectMembershipContext,
    get_database_session,
    require_authenticated_csrf,
    require_project_administrator,
)
from app.api.schemas.auth import (
    MembershipStatusRequest,
    OperatorCreateRequest,
    OperatorCreateResponse,
    OperatorResponse,
    PasswordResetIssuedResponse,
)
from app.db.models.auth import (
    OperatorAccount,
    OperatorProjectMembership,
    PasswordResetCredential,
)
from app.db.models.enums import OperatorRole
from app.security.passwords import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
)
from app.security.tokens import generate_opaque_token, hash_token
from app.services.audit import record_audit_event
from app.services.authentication import consume_password_reset_credentials, revoke_account_sessions

router = APIRouter()


def operator_response(
    account: OperatorAccount,
    membership: OperatorProjectMembership,
) -> OperatorResponse:
    return OperatorResponse(
        account_id=account.id,
        membership_id=membership.id,
        email=account.email,
        role=membership.role,
        membership_active=membership.is_active,
        account_disabled=account.disabled_at is not None,
        must_change_password=account.must_change_password,
    )


async def target_membership(
    database: AsyncSession,
    project_id: str,
    account_id: UUID,
) -> tuple[OperatorAccount, OperatorProjectMembership]:
    row = (
        await database.execute(
            select(OperatorAccount, OperatorProjectMembership)
            .join(
                OperatorProjectMembership,
                OperatorProjectMembership.operator_account_id == OperatorAccount.id,
            )
            .where(
                OperatorAccount.id == account_id,
                OperatorProjectMembership.project_id == project_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator inexistent")
    return row[0], row[1]


async def require_global_account_authority(
    database: AsyncSession,
    actor_account_id: UUID,
    target_account_id: UUID,
) -> set[str]:
    target_projects = set(
        await database.scalars(
            select(OperatorProjectMembership.project_id).where(
                OperatorProjectMembership.operator_account_id == target_account_id,
                OperatorProjectMembership.is_active.is_(True),
            )
        )
    )
    administrator_projects = set(
        await database.scalars(
            select(OperatorProjectMembership.project_id).where(
                OperatorProjectMembership.operator_account_id == actor_account_id,
                OperatorProjectMembership.role == OperatorRole.ADMINISTRATOR,
                OperatorProjectMembership.is_active.is_(True),
            )
        )
    )
    if not target_projects.issubset(administrator_projects):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contul are acces la un proiect pe care nu îl administrați",
        )
    return target_projects


@router.get("", response_model=list[OperatorResponse])
async def list_operators(
    project_id: str,
    _: ProjectMembershipContext = Depends(require_project_administrator),
    database: AsyncSession = Depends(get_database_session),
) -> list[OperatorResponse]:
    rows = await database.execute(
        select(OperatorAccount, OperatorProjectMembership)
        .join(
            OperatorProjectMembership,
            OperatorProjectMembership.operator_account_id == OperatorAccount.id,
        )
        .where(OperatorProjectMembership.project_id == project_id)
        .order_by(OperatorAccount.email)
    )
    return [operator_response(account, membership) for account, membership in rows.all()]


@router.post("", response_model=OperatorCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_operator(
    project_id: str,
    payload: OperatorCreateRequest,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    csrf_auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> OperatorCreateResponse:
    if csrf_auth.account.id != context.auth.account.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sesiune invalidă")
    account = await database.scalar(
        select(OperatorAccount).where(OperatorAccount.email == payload.email)
    )
    temporary_password: str | None = None
    action = "operator.membership_created"
    if account is None:
        temporary_password = payload.temporary_password or generate_temporary_password()
        try:
            password_hash = hash_password(temporary_password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        account = OperatorAccount(
            email=payload.email,
            password_hash=password_hash,
            must_change_password=True,
        )
        database.add(account)
        await database.flush()
        action = "operator.account_created"
    elif account.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contul este dezactivat")
    elif await database.scalar(
        select(OperatorProjectMembership).where(
            OperatorProjectMembership.project_id == project_id,
            OperatorProjectMembership.operator_account_id == account.id,
        )
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contul are deja acces la proiect")
    membership = OperatorProjectMembership(
        project_id=project_id,
        operator_account_id=account.id,
        role=payload.role,
        is_active=True,
    )
    database.add(membership)
    await database.flush()
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=context.auth.account.id,
        actor_membership_id=context.membership.id,
        action=action,
        outcome="success",
        target_type="operator_account",
        target_id=str(account.id),
        metadata={"role": payload.role.value},
    )
    await database.commit()
    base = operator_response(account, membership)
    return OperatorCreateResponse(**base.model_dump(), temporary_password=temporary_password)


@router.patch("/{account_id}/membership", response_model=OperatorResponse)
async def change_membership_status(
    project_id: str,
    account_id: UUID,
    payload: MembershipStatusRequest,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    _: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> OperatorResponse:
    account, membership = await target_membership(database, project_id, account_id)
    if account.id == context.auth.account.id and not payload.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nu vă puteți dezactiva propriul acces")
    membership.is_active = payload.is_active
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=context.auth.account.id,
        actor_membership_id=context.membership.id,
        action="operator.membership_enabled" if payload.is_active else "operator.membership_disabled",
        outcome="success",
        target_type="operator_project_membership",
        target_id=str(membership.id),
    )
    await database.commit()
    return operator_response(account, membership)


@router.post("/{account_id}/password-reset", response_model=PasswordResetIssuedResponse)
async def issue_password_reset(
    project_id: str,
    account_id: UUID,
    request: Request,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    _: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> PasswordResetIssuedResponse:
    account, _membership = await target_membership(database, project_id, account_id)
    if account.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contul este dezactivat")
    await require_global_account_authority(
        database,
        context.auth.account.id,
        account.id,
    )
    raw_token = generate_opaque_token()
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        minutes=request.app.state.settings.password_reset_minutes
    )
    await consume_password_reset_credentials(database, account.id, consumed_at=now)
    database.add(
        PasswordResetCredential(
            operator_account_id=account.id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
            created_by_membership_id=context.membership.id,
            project_id=project_id,
        )
    )
    account.must_change_password = True
    await revoke_account_sessions(database, account.id, "administrator_password_reset")
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=context.auth.account.id,
        actor_membership_id=context.membership.id,
        action="operator.password_reset_issued",
        outcome="success",
        target_type="operator_account",
        target_id=str(account.id),
    )
    await database.commit()
    return PasswordResetIssuedResponse(reset_token=raw_token, expires_at=expires_at)


@router.post("/{account_id}/disable", response_model=OperatorResponse)
async def disable_account(
    project_id: str,
    account_id: UUID,
    context: ProjectMembershipContext = Depends(require_project_administrator),
    _: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> OperatorResponse:
    account, membership = await target_membership(database, project_id, account_id)
    if account.id == context.auth.account.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nu vă puteți dezactiva propriul cont")

    await require_global_account_authority(
        database,
        context.auth.account.id,
        account.id,
    )

    account.disabled_at = datetime.now(UTC)
    await revoke_account_sessions(database, account.id, "account_disabled")
    await record_audit_event(
        database,
        project_id=project_id,
        actor_account_id=context.auth.account.id,
        actor_membership_id=context.membership.id,
        action="operator.account_disabled",
        outcome="success",
        target_type="operator_account",
        target_id=str(account.id),
    )
    await database.commit()
    return operator_response(account, membership)
