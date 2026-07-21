from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import AuthenticatedUserResponse, MembershipResponse
from app.core.project_config import ProjectCatalog, ProjectId
from app.db.models.auth import (
    LoginRateLimit,
    OperatorAccount,
    OperatorProjectMembership,
    OperatorSession,
    PasswordResetCredential,
)
from app.security.tokens import keyed_hash


async def build_authenticated_user(
    database: AsyncSession,
    account: OperatorAccount,
    catalog: ProjectCatalog,
) -> AuthenticatedUserResponse:
    memberships = list(
        await database.scalars(
            select(OperatorProjectMembership)
            .where(
                OperatorProjectMembership.operator_account_id == account.id,
                OperatorProjectMembership.is_active.is_(True),
            )
            .order_by(OperatorProjectMembership.project_id)
        )
    )
    return AuthenticatedUserResponse(
        account_id=account.id,
        email=account.email,
        must_change_password=account.must_change_password,
        memberships=[
            MembershipResponse(
                membership_id=membership.id,
                project_id=membership.project_id,
                project_name=catalog.get(ProjectId(membership.project_id)).public_name,
                role=membership.role,
            )
            for membership in memberships
        ],
    )


def login_bucket_hash(email: str, client_host: str, security_key: str) -> str:
    return keyed_hash(f"{email}|{client_host}", security_key)


async def register_login_attempt(
    database: AsyncSession,
    *,
    bucket_hash: str,
    now: datetime,
    maximum_attempts: int,
    window_minutes: int,
) -> bool:
    bucket = await database.scalar(
        select(LoginRateLimit)
        .where(LoginRateLimit.bucket_hash == bucket_hash)
        .with_for_update()
    )
    window = timedelta(minutes=window_minutes)
    if bucket is None:
        database.add(
            LoginRateLimit(
                bucket_hash=bucket_hash,
                attempt_count=1,
                window_started_at=now,
            )
        )
        await database.flush()
        return True
    if bucket.blocked_until and bucket.blocked_until > now:
        return False
    if bucket.window_started_at + window <= now:
        bucket.window_started_at = now
        bucket.attempt_count = 1
        bucket.blocked_until = None
        return True
    bucket.attempt_count += 1
    if bucket.attempt_count > maximum_attempts:
        bucket.blocked_until = bucket.window_started_at + window
        return False
    return True


async def clear_login_rate_limit(database: AsyncSession, bucket_hash: str) -> None:
    await database.execute(delete(LoginRateLimit).where(LoginRateLimit.bucket_hash == bucket_hash))


async def revoke_account_sessions(
    database: AsyncSession,
    account_id: UUID,
    reason: str,
    *,
    except_session_id: UUID | None = None,
) -> None:
    sessions = list(
        await database.scalars(
            select(OperatorSession).where(
                OperatorSession.operator_account_id == account_id,
                OperatorSession.revoked_at.is_(None),
            )
        )
    )
    now = datetime.now(UTC)
    for operator_session in sessions:
        if except_session_id and operator_session.id == except_session_id:
            continue
        operator_session.revoked_at = now
        operator_session.revocation_reason = reason


async def consume_password_reset_credentials(
    database: AsyncSession,
    account_id: UUID,
    *,
    consumed_at: datetime | None = None,
) -> None:
    await database.execute(
        update(PasswordResetCredential)
        .where(
            PasswordResetCredential.operator_account_id == account_id,
            PasswordResetCredential.consumed_at.is_(None),
        )
        .values(consumed_at=consumed_at or datetime.now(UTC))
    )
