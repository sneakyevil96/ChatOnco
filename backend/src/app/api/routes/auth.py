from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthContext,
    get_current_auth,
    get_database_session,
    require_authenticated_csrf,
    require_signed_csrf,
)
from app.api.schemas.auth import (
    AuthenticatedUserResponse,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetCompletionRequest,
)
from app.core.project_config import ProjectCatalog
from app.core.settings import Settings
from app.db.models.auth import OperatorAccount, OperatorSession, PasswordResetCredential
from app.security.cookies import clear_auth_cookies, set_csrf_cookie, set_session_cookie
from app.security.passwords import (
    PasswordPolicyError,
    hash_password,
    verify_password,
    verify_unknown_account_password,
)
from app.security.tokens import generate_opaque_token, hash_token, issue_signed_csrf_token
from app.services.audit import record_audit_event
from app.services.authentication import (
    build_authenticated_user,
    clear_login_rate_limit,
    consume_password_reset_credentials,
    login_bucket_hash,
    register_login_attempt,
    revoke_account_sessions,
)

router = APIRouter()


@router.get("/csrf")
async def issue_csrf(
    request: Request,
    response: Response,
    database: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    token = issue_signed_csrf_token(settings.csrf_signing_key)
    raw_session = request.cookies.get(settings.session_cookie_name)
    if raw_session:
        operator_session = await database.scalar(
            select(OperatorSession).where(
                OperatorSession.token_hash == hash_token(raw_session),
                OperatorSession.revoked_at.is_(None),
            )
        )
        if operator_session is not None:
            operator_session.csrf_secret_hash = hash_token(token)
            await database.commit()
    set_csrf_cookie(response, token, settings)
    return {"csrf_token": token}


@router.post("/login", response_model=AuthenticatedUserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    _: str = Depends(require_signed_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> AuthenticatedUserResponse:
    settings: Settings = request.app.state.settings
    now = datetime.now(UTC)
    client_host = request.client.host if request.client else "unknown"
    bucket_hash = login_bucket_hash(payload.email, client_host, settings.security_hash_key)
    allowed = await register_login_attempt(
        database,
        bucket_hash=bucket_hash,
        now=now,
        maximum_attempts=settings.login_rate_limit_attempts,
        window_minutes=settings.login_rate_limit_window_minutes,
    )
    if not allowed:
        await record_audit_event(
            database,
            action="authentication.login_rate_limited",
            outcome="denied",
            metadata={"bucket": bucket_hash[:12]},
        )
        await database.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Prea multe încercări")

    account = await database.scalar(
        select(OperatorAccount)
        .where(OperatorAccount.email == payload.email)
        .with_for_update()
    )
    if account is None:
        verify_unknown_account_password(payload.password)
        await record_audit_event(
            database,
            action="authentication.login_failed",
            outcome="denied",
            metadata={"bucket": bucket_hash[:12]},
        )
        await database.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Date de autentificare invalide")

    locked = account.locked_until is not None and account.locked_until > now
    password_valid = verify_password(account.password_hash, payload.password)
    if account.disabled_at is not None or locked or not password_valid:
        if not locked and account.disabled_at is None:
            account.failed_login_attempts += 1
            if account.failed_login_attempts >= settings.failed_logins_before_lockout:
                delay = settings.initial_lockout_minutes * (2 ** min(account.lockout_count, 5))
                account.locked_until = now + timedelta(minutes=delay)
                account.lockout_count += 1
                account.failed_login_attempts = 0
        await record_audit_event(
            database,
            action="authentication.login_failed",
            outcome="denied",
            actor_account_id=account.id,
            target_type="operator_account",
            target_id=str(account.id),
        )
        await database.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Date de autentificare invalide")

    account.failed_login_attempts = 0
    account.locked_until = None
    account.last_login_at = now
    await clear_login_rate_limit(database, bucket_hash)

    raw_session = generate_opaque_token()
    csrf_token = issue_signed_csrf_token(settings.csrf_signing_key)
    operator_session = OperatorSession(
        operator_account_id=account.id,
        token_hash=hash_token(raw_session),
        csrf_secret_hash=hash_token(csrf_token),
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
        absolute_expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )
    database.add(operator_session)
    await database.flush()
    await record_audit_event(
        database,
        action="authentication.login",
        outcome="success",
        actor_account_id=account.id,
        target_type="operator_session",
        target_id=str(operator_session.id),
    )
    await database.commit()

    set_session_cookie(response, raw_session, settings)
    set_csrf_cookie(response, csrf_token, settings)
    catalog: ProjectCatalog = request.app.state.project_catalog
    return await build_authenticated_user(database, account, catalog)


@router.get("/me", response_model=AuthenticatedUserResponse)
async def current_user(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    database: AsyncSession = Depends(get_database_session),
) -> AuthenticatedUserResponse:
    return await build_authenticated_user(
        database,
        auth.account,
        request.app.state.project_catalog,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> None:
    now = datetime.now(UTC)
    auth.operator_session.revoked_at = now
    auth.operator_session.revocation_reason = "logout"
    await record_audit_event(
        database,
        action="authentication.logout",
        outcome="success",
        actor_account_id=auth.account.id,
        target_type="operator_session",
        target_id=str(auth.operator_session.id),
    )
    await database.commit()
    clear_auth_cookies(response, request.app.state.settings)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_authenticated_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> None:
    if not verify_password(auth.account.password_hash, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parola curentă este incorectă")
    try:
        new_hash = hash_password(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if verify_password(auth.account.password_hash, payload.new_password):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Alegeți o parolă nouă")

    auth.account.password_hash = new_hash
    auth.account.must_change_password = False
    auth.account.password_changed_at = datetime.now(UTC)
    await consume_password_reset_credentials(database, auth.account.id)
    await revoke_account_sessions(database, auth.account.id, "password_changed")
    await record_audit_event(
        database,
        action="authentication.password_changed",
        outcome="success",
        actor_account_id=auth.account.id,
        target_type="operator_account",
        target_id=str(auth.account.id),
    )
    await database.commit()
    clear_auth_cookies(response, request.app.state.settings)


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def complete_password_reset(
    payload: PasswordResetCompletionRequest,
    request: Request,
    response: Response,
    _: str = Depends(require_signed_csrf),
    database: AsyncSession = Depends(get_database_session),
) -> None:
    credential = await database.scalar(
        select(PasswordResetCredential)
        .where(PasswordResetCredential.token_hash == hash_token(payload.reset_token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    account = (
        await database.get(OperatorAccount, credential.operator_account_id)
        if credential is not None
        else None
    )
    if (
        credential is None
        or account is None
        or account.email != payload.email
        or credential.consumed_at is not None
        or credential.expires_at <= now
        or account.disabled_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resetarea parolei nu este validă")
    try:
        account.password_hash = hash_password(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    account.must_change_password = False
    account.password_changed_at = now
    await consume_password_reset_credentials(database, account.id, consumed_at=now)
    await revoke_account_sessions(database, account.id, "password_reset_completed")
    await record_audit_event(
        database,
        project_id=credential.project_id,
        action="authentication.password_reset_completed",
        outcome="success",
        actor_account_id=account.id,
        target_type="operator_account",
        target_id=str(account.id),
    )
    await database.commit()
    clear_auth_cookies(response, request.app.state.settings)
