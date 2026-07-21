import argparse
import asyncio

from app.core.project_config import ProjectId
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.faq_import import expire_due_faq_versions


async def expire(project_ids: list[ProjectId]) -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as database:
            total = 0
            for project_id in project_ids:
                expired = await expire_due_faq_versions(
                    database,
                    project_id=project_id.value,
                )
                total += len(expired)
        print(f"Expired {total} FAQ versions.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expire published FAQ versions whose configured validity has ended."
    )
    parser.add_argument(
        "--project",
        choices=[item.value for item in ProjectId],
        help="Limit processing to one project; otherwise process both projects.",
    )
    arguments = parser.parse_args()
    projects = [ProjectId(arguments.project)] if arguments.project else list(ProjectId)
    asyncio.run(expire(projects))


if __name__ == "__main__":
    main()
