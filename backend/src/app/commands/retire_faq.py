import argparse
import asyncio

from sqlalchemy import select

from app.core.project_config import ProjectId
from app.core.settings import get_settings
from app.db.models.auth import OperatorAccount, OperatorProjectMembership
from app.db.models.enums import OperatorRole
from app.db.session import create_database_engine, create_session_factory
from app.services.faq_import import retire_published_faq


async def retire(
    project_id: ProjectId,
    administrator_email: str,
    logical_key: str,
    reason: str,
) -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as database:
            row = (
                await database.execute(
                    select(OperatorAccount, OperatorProjectMembership)
                    .join(
                        OperatorProjectMembership,
                        OperatorProjectMembership.operator_account_id == OperatorAccount.id,
                    )
                    .where(
                        OperatorAccount.email == administrator_email.strip().casefold(),
                        OperatorAccount.disabled_at.is_(None),
                        OperatorProjectMembership.project_id == project_id.value,
                        OperatorProjectMembership.role == OperatorRole.ADMINISTRATOR,
                        OperatorProjectMembership.is_active.is_(True),
                    )
                )
            ).one_or_none()
            if row is None:
                raise RuntimeError("An active project administrator account is required")
            version_id = await retire_published_faq(
                database,
                project_id=project_id.value,
                logical_key=logical_key,
                reason=reason,
                administrator_account_id=row[0].id,
                administrator_membership_id=row[1].id,
            )
        print(f"Retired FAQ version {version_id}.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Immediately withdraw a published FAQ.")
    parser.add_argument("--project", required=True, choices=[item.value for item in ProjectId])
    parser.add_argument("--administrator-email", required=True)
    parser.add_argument("--logical-key", required=True)
    parser.add_argument("--reason", required=True)
    arguments = parser.parse_args()
    asyncio.run(
        retire(
            ProjectId(arguments.project),
            arguments.administrator_email,
            arguments.logical_key,
            arguments.reason,
        )
    )


if __name__ == "__main__":
    main()
