import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select

from app.api.schemas.auth import normalize_email
from app.core.project_config import ProjectId
from app.core.settings import get_settings
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.enums import OperatorRole
from app.db.models.project import Project
from app.db.session import create_database_engine, create_session_factory
from app.security.passwords import generate_temporary_password, hash_password
from app.services.audit import record_audit_event


async def bootstrap(project_id: ProjectId, email: str, prompt_password: bool) -> str:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    temporary_password = getpass("Temporary password: ") if prompt_password else generate_temporary_password()
    normalized_email = normalize_email(email)
    try:
        async with session_factory.begin() as database:
            project = await database.get(Project, project_id.value)
            if project is None:
                raise RuntimeError("Project configuration is not synchronized")
            if await database.scalar(
                select(OperatorAccount).where(OperatorAccount.email == normalized_email)
            ):
                raise RuntimeError("An account with this email already exists")
            account = OperatorAccount(
                email=normalized_email,
                password_hash=hash_password(temporary_password),
                must_change_password=True,
            )
            database.add(account)
            await database.flush()
            membership = OperatorProjectMembership(
                project_id=project_id.value,
                operator_account_id=account.id,
                role=OperatorRole.ADMINISTRATOR,
                is_active=True,
            )
            database.add(membership)
            await database.flush()
            await record_audit_event(
                database,
                project_id=project_id.value,
                actor_account_id=account.id,
                actor_membership_id=membership.id,
                action="security.first_administrator_bootstrapped",
                outcome="success",
                target_type="operator_account",
                target_id=str(account.id),
            )
    finally:
        await engine.dispose()
    return temporary_password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first project administrator outside the public API."
    )
    parser.add_argument("--project", required=True, choices=[item.value for item in ProjectId])
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Prompt securely instead of generating a temporary password.",
    )
    arguments = parser.parse_args()
    temporary_password = asyncio.run(
        bootstrap(ProjectId(arguments.project), arguments.email, arguments.prompt_password)
    )
    if not arguments.prompt_password:
        print("Temporary credential (shown once):")
        print(temporary_password)
    print("The administrator must change the password at first login.")


if __name__ == "__main__":
    main()

