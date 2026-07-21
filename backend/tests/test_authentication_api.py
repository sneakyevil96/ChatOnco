import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("argon2")
pytest.importorskip("pgvector")

from app.api.dependencies import get_database_session
from app.db.models.audit import AuditEvent
from app.db.models.auth import (
    OperatorAccount,
    OperatorProjectMembership,
    OperatorSession,
    PasswordResetCredential,
)
from app.db.models.enums import OperatorRole
from app.db.session import create_database_engine
from app.main import create_app
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="PostgreSQL integration tests are disabled",
)

ORIGIN = "http://localhost:8080"
TEMPORARY_PASSWORD = "Synthetic-Temporary-Password-2026"


@asynccontextmanager
async def authenticated_test_context() -> AsyncIterator[tuple[AsyncClient, object]]:
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()

        async def override_database() -> AsyncIterator[AsyncSession]:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                try:
                    yield database
                except Exception:
                    await database.rollback()
                    raise

        app = create_app()
        app.dependency_overrides[get_database_session] = override_database
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                yield client, connection
        await outer_transaction.rollback()
    await engine.dispose()


async def create_account(
    connection,
    *,
    email: str,
    project_id: str = "ONCODIR",
    role: OperatorRole = OperatorRole.OPERATOR,
    must_change_password: bool = False,
) -> OperatorAccount:
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as database:
        account = OperatorAccount(
            email=email,
            password_hash=hash_password(TEMPORARY_PASSWORD),
            must_change_password=must_change_password,
        )
        database.add(account)
        await database.flush()
        database.add(
            OperatorProjectMembership(
                project_id=project_id,
                operator_account_id=account.id,
                role=role,
                is_active=True,
            )
        )
        await database.commit()
        return account


async def csrf_token(client: AsyncClient) -> str:
    response = await client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


async def login(client: AsyncClient, email: str, password: str = TEMPORARY_PASSWORD):
    csrf = await csrf_token(client)
    return await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )


def test_login_sets_securely_scoped_session_and_filters_projects() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            await create_account(connection, email="phase3-operator@example.invalid")
            response = await login(client, "phase3-operator@example.invalid")

            assert response.status_code == 200
            assert response.json()["memberships"][0]["project_id"] == "ONCODIR"
            session_cookie = next(
                value for value in response.headers.get_list("set-cookie") if value.startswith("screening_session=")
            )
            assert "HttpOnly" in session_cookie
            assert "SameSite=lax" in session_cookie
            assert "Secure" not in session_cookie

            projects = await client.get("/api/v1/projects")
            assert projects.status_code == 200
            assert [item["project_id"] for item in projects.json()] == ["ONCODIR"]
            forbidden = await client.get("/api/v1/projects/ONCOSCREEN/operators")
            assert forbidden.status_code == 403

    asyncio.run(scenario())


def test_forced_password_change_revokes_the_current_session() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            account = await create_account(
                connection,
                email="phase3-forced-change@example.invalid",
                must_change_password=True,
            )
            response = await login(client, account.email)
            assert response.status_code == 200
            assert response.json()["must_change_password"] is True
            assert (await client.get("/api/v1/projects")).status_code == 403

            token = client.cookies.get("screening_csrf")
            changed = await client.post(
                "/api/v1/auth/password/change",
                json={
                    "current_password": TEMPORARY_PASSWORD,
                    "new_password": "Synthetic-New-Secure-Password-2026",
                },
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert changed.status_code == 204
            assert (await client.get("/api/v1/auth/me")).status_code == 401

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                refreshed = await database.get(OperatorAccount, account.id)
                assert refreshed is not None
                assert refreshed.must_change_password is False
                assert verify_password(refreshed.password_hash, "Synthetic-New-Secure-Password-2026")

    asyncio.run(scenario())


def test_csrf_is_required_for_authenticated_state_changes() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            await create_account(connection, email="phase3-csrf@example.invalid")
            assert (await login(client, "phase3-csrf@example.invalid")).status_code == 200

            rejected = await client.post(
                "/api/v1/auth/logout",
                headers={"Origin": ORIGIN, "X-CSRF-Token": "invalid"},
            )
            assert rejected.status_code == 403
            assert (await client.get("/api/v1/auth/me")).status_code == 200

    asyncio.run(scenario())


def test_five_failed_logins_lock_the_account() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            account = await create_account(connection, email="phase3-lockout@example.invalid")
            for _ in range(5):
                response = await login(client, account.email, "Incorrect-password")
                assert response.status_code == 401

            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                refreshed = await database.get(OperatorAccount, account.id)
                assert refreshed is not None
                assert refreshed.locked_until is not None
                assert refreshed.lockout_count == 1

    asyncio.run(scenario())


def test_project_administrator_can_create_only_project_scoped_accounts() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            administrator = await create_account(
                connection,
                email="phase3-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            assert (await login(client, administrator.email)).status_code == 200
            token = client.cookies.get("screening_csrf")
            created = await client.post(
                "/api/v1/projects/ONCODIR/operators",
                json={"email": "phase3-created@example.invalid", "role": "operator"},
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert created.status_code == 201
            assert created.json()["temporary_password"]

            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as database:
                account = await database.scalar(
                    select(OperatorAccount).where(
                        OperatorAccount.email == "phase3-created@example.invalid"
                    )
                )
                assert account is not None
                assert account.password_hash != created.json()["temporary_password"]
                event = await database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "operator.account_created",
                        AuditEvent.target_id == str(account.id),
                    )
                )
                assert event is not None
                assert event.project_id == "ONCODIR"

    asyncio.run(scenario())


def test_expired_session_is_rejected_and_revoked() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            account = await create_account(connection, email="phase3-expired@example.invalid")
            raw_token = "synthetic-expired-session-token"
            now = datetime.now(UTC)
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as database:
                operator_session = OperatorSession(
                    operator_account_id=account.id,
                    token_hash=hash_token(raw_token),
                    csrf_secret_hash=hash_token("synthetic-csrf"),
                    last_seen_at=now - timedelta(hours=2),
                    idle_expires_at=now - timedelta(minutes=1),
                    absolute_expires_at=now + timedelta(hours=1),
                )
                database.add(operator_session)
                await database.commit()
                session_id = operator_session.id
            client.cookies.set("screening_session", raw_token)

            assert (await client.get("/api/v1/auth/me")).status_code == 401
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as database:
                revoked = await database.get(OperatorSession, session_id)
                assert revoked is not None
                assert revoked.revoked_at is not None

    asyncio.run(scenario())


def test_disabling_an_account_invalidates_its_existing_session() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            account = await create_account(connection, email="phase3-disabled@example.invalid")
            assert (await login(client, account.email)).status_code == 200
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as database:
                refreshed = await database.get(OperatorAccount, account.id)
                assert refreshed is not None
                refreshed.disabled_at = datetime.now(UTC)
                await database.commit()

            assert (await client.get("/api/v1/auth/me")).status_code == 401

    asyncio.run(scenario())


def test_only_the_latest_password_reset_credential_can_be_used_once() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            administrator = await create_account(
                connection,
                email="phase3-reset-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            target = await create_account(
                connection,
                email="phase3-reset-target@example.invalid",
            )
            assert (await login(client, administrator.email)).status_code == 200
            token = client.cookies.get("screening_csrf")
            reset_url = f"/api/v1/projects/ONCODIR/operators/{target.id}/password-reset"

            first = await client.post(
                reset_url,
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            second = await client.post(
                reset_url,
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert first.status_code == 200
            assert second.status_code == 200

            first_rejected = await client.post(
                "/api/v1/auth/password/reset",
                json={
                    "email": target.email,
                    "reset_token": first.json()["reset_token"],
                    "new_password": "Synthetic-Reset-Password-2026",
                },
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert first_rejected.status_code == 400

            completed = await client.post(
                "/api/v1/auth/password/reset",
                json={
                    "email": target.email,
                    "reset_token": second.json()["reset_token"],
                    "new_password": "Synthetic-Reset-Password-2026",
                },
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert completed.status_code == 204

            token = await csrf_token(client)
            reused = await client.post(
                "/api/v1/auth/password/reset",
                json={
                    "email": target.email,
                    "reset_token": second.json()["reset_token"],
                    "new_password": "Another-Synthetic-Password-2026",
                },
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert reused.status_code == 400

            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                credentials = list(
                    await database.scalars(
                        select(PasswordResetCredential).where(
                            PasswordResetCredential.operator_account_id == target.id
                        )
                    )
                )
                assert len(credentials) == 2
                assert all(credential.consumed_at is not None for credential in credentials)

    asyncio.run(scenario())


def test_project_admin_cannot_reset_a_cross_project_account_without_full_authority() -> None:
    async def scenario() -> None:
        async with authenticated_test_context() as (client, connection):
            administrator = await create_account(
                connection,
                email="phase3-isolation-admin@example.invalid",
                role=OperatorRole.ADMINISTRATOR,
            )
            target = await create_account(
                connection,
                email="phase3-isolation-target@example.invalid",
                project_id="ONCOSCREEN",
            )
            async with AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as database:
                database.add(
                    OperatorProjectMembership(
                        project_id="ONCODIR",
                        operator_account_id=target.id,
                        role=OperatorRole.OPERATOR,
                        is_active=True,
                    )
                )
                await database.commit()

            assert (await login(client, administrator.email)).status_code == 200
            token = client.cookies.get("screening_csrf")
            response = await client.post(
                f"/api/v1/projects/ONCODIR/operators/{target.id}/password-reset",
                headers={"Origin": ORIGIN, "X-CSRF-Token": token},
            )
            assert response.status_code == 403

    asyncio.run(scenario())
