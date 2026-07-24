import json
import os
import stat

from app.core.project_config import ProjectCatalog
from app.core.settings import get_settings


def validate() -> tuple[list[str], list[str]]:
    settings = get_settings()
    catalog = ProjectCatalog.load(settings.project_config_dir)
    errors: list[str] = []
    warnings: list[str] = []
    if settings.app_env != "production":
        warnings.append("This is not a production environment; production-only checks are advisory")
    for label, confirmed in (
        ("HTTPS termination", settings.https_termination_confirmed),
        ("encrypted storage volumes", settings.storage_encryption_confirmed),
        ("encrypted backups", settings.backup_encryption_confirmed),
        ("separate backup destination", settings.backup_destination_separate_confirmed),
        ("successful restore test", settings.backup_restore_test_confirmed),
    ):
        if not confirmed:
            errors.append(f"Operational confirmation missing: {label}")
    for project in catalog.all():
        if project.content_status == "development_placeholder":
            errors.append(f"{project.project_id.value} still uses placeholder public content")
        if not project.whatsapp.enabled:
            errors.append(f"{project.project_id.value} WhatsApp integration is disabled")
    if settings.whatsapp_provider != "meta":
        errors.append("WHATSAPP_PROVIDER must be meta for production participant messaging")
    for label, secret_file in (
        ("Application", settings.application_secret_file),
        ("WhatsApp", settings.whatsapp_secret_file),
    ):
        if secret_file is not None and secret_file.is_file() and os.name != "nt":
            mode = stat.S_IMODE(secret_file.stat().st_mode)
            if mode & 0o077:
                errors.append(
                    f"{label} secret file permissions allow group or other access"
                )
    if settings.whatsapp_provider == "meta" and (
        settings.whatsapp_secret_file is None
        or not settings.whatsapp_secret_file.is_file()
    ):
        errors.append("WhatsApp secret file is unavailable")
    return errors, warnings


def main() -> None:
    errors, warnings = validate()
    print(json.dumps({"errors": errors, "warnings": warnings}, indent=2, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
