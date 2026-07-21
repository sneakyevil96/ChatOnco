import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.db.models.auth import OperatorAccount, OperatorProjectMembership, OperatorSession
from app.db.models.enums import OperatorRole
from app.db.models.project import Project
from app.security.tokens import hash_token, verify_signed_csrf_token


@dataclass(frozen=True, slots=True)
class AuthContext:
    account: OperatorAccount
    operator_session: OperatorSession


@dataclass(frozen=True, slots=True)
class ProjectMembershipContext:
    auth: AuthContext
    membership: OperatorProjectMembership


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.database_session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def validate_request_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.browser_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origine invalidă")


def validate_signed_request_csrf(request: Request, settings: Settings) -> str:
    validate_request_origin(request, settings)
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("x-csrf-token")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Protecție CSRF invalidă")
    if not verify_signed_csrf_token(
        cookie_token,
        settings.csrf_signing_key,
        settings.csrf_token_minutes * 60,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Protecție CSRF expirată")
    return cookie_token


async def require_signed_csrf(request: Request) -> str:
    return validate_signed_request_csrf(request, request.app.state.settings)


async def get_current_auth(
    request: Request,
    database: AsyncSession = Depends(get_database_session),
) -> AuthContext:
    settings: Settings = request.app.state.settings
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autentificare necesară")

    operator_session = await database.scalar(
        select(OperatorSession).where(OperatorSession.token_hash == hash_token(raw_token))
    )
    if operator_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesiune invalidă")

    account = await database.get(OperatorAccount, operator_session.operator_account_id)
    now = datetime.now(UTC)
    if (
        account is None
        or account.disabled_at is not None
        or operator_session.revoked_at is not None
        or operator_session.idle_expires_at <= now
        or operator_session.absolute_expires_at <= now
    ):
        if operator_session.revoked_at is None:
            operator_session.revoked_at = now
            operator_session.revocation_reason = "expired_or_account_disabled"
            await database.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesiune expirată")

    operator_session.last_seen_at = now
    operator_session.idle_expires_at = min(
        now + timedelta(minutes=settings.session_idle_minutes),
        operator_session.absolute_expires_at,
    )
    await database.commit()
    return AuthContext(account=account, operator_session=operator_session)


async def require_authenticated_csrf(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
) -> AuthContext:
    token = validate_signed_request_csrf(request, request.app.state.settings)
    if not hmac.compare_digest(hash_token(token), auth.operator_session.csrf_secret_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Protecție CSRF invalidă")
    return auth


async def require_password_changed(
    auth: AuthContext = Depends(get_current_auth),
) -> AuthContext:
    if auth.account.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Schimbarea parolei este obligatorie",
        )
    return auth


async def require_project_membership(
    project_id: str,
    auth: AuthContext = Depends(require_password_changed),
    database: AsyncSession = Depends(get_database_session),
) -> ProjectMembershipContext:
    membership = await database.scalar(
        select(OperatorProjectMembership)
        .join(Project, Project.id == OperatorProjectMembership.project_id)
        .where(
            OperatorProjectMembership.project_id == project_id,
            OperatorProjectMembership.operator_account_id == auth.account.id,
            OperatorProjectMembership.is_active.is_(True),
            Project.is_enabled.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acces neautorizat")
    return ProjectMembershipContext(auth=auth, membership=membership)


async def require_project_administrator(
    context: ProjectMembershipContext = Depends(require_project_membership),
) -> ProjectMembershipContext:
    if context.membership.role != OperatorRole.ADMINISTRATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol de administrator necesar")
    return context
