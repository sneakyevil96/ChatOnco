import argparse
import asyncio
import json
from dataclasses import asdict

from sqlalchemy import text

from app.core.project_config import ProjectCatalog, ProjectId
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retention import apply_project_retention, apply_security_state_cleanup


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Apply configurable privacy retention policies")
    command.add_argument("--project", choices=[item.value for item in ProjectId])
    command.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the command is a rollback-only dry run.",
    )
    return command


async def run(project_id: str | None, *, apply: bool) -> None:
    settings = get_settings()
    catalog = ProjectCatalog.load(settings.project_config_dir)
    projects = (
        (catalog.get(ProjectId(project_id)),)
        if project_id is not None
        else catalog.all()
    )
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as database:
            locked = await database.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtext('screening-retention'))")
            )
            if not locked:
                raise RuntimeError("Another retention run is already active")
            output = []
            for project in projects:
                result = await apply_project_retention(
                    database,
                    project=project,
                    batch_size=settings.retention_batch_size,
                    dry_run=not apply,
                )
                output.append(asdict(result))
            global_audit_days = max(
                project.retention.audit_events_days for project in catalog.all()
            )
            security = await apply_security_state_cleanup(
                database,
                global_audit_days=global_audit_days,
                cleanup_grace_days=settings.security_state_cleanup_days,
                batch_size=settings.retention_batch_size,
                dry_run=not apply,
            )
            if apply:
                await database.commit()
            else:
                await database.rollback()
            print(
                json.dumps(
                    {
                        "mode": "apply" if apply else "dry-run",
                        "projects": output,
                        "security_state": asdict(security),
                    },
                    sort_keys=True,
                )
            )
    finally:
        await engine.dispose()


def main() -> None:
    arguments = parser().parse_args()
    asyncio.run(run(arguments.project, apply=arguments.apply))


if __name__ == "__main__":
    main()
