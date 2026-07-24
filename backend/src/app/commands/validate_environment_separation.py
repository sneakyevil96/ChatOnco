import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EnvironmentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["staging", "production"]
    participant_data_allowed: bool
    public_origin: HttpUrl
    database_identity: str = Field(min_length=1)
    project_configuration_identity: str = Field(min_length=1)
    csrf_secret_identity: str = Field(min_length=1)
    security_hash_secret_identity: str = Field(min_length=1)
    backup_key_identity: str = Field(min_length=1)
    backup_destination_identity: str = Field(min_length=1)
    storage_volume_identity: str = Field(min_length=1)
    meta_credential_identities: set[str] = Field(default_factory=set)
    meta_phone_number_identities: set[str] = Field(default_factory=set)


SCALAR_ISOLATION_FIELDS = (
    "database_identity",
    "project_configuration_identity",
    "csrf_secret_identity",
    "security_hash_secret_identity",
    "backup_key_identity",
    "backup_destination_identity",
    "storage_volume_identity",
)


def load_manifest(path: Path) -> EnvironmentManifest:
    return EnvironmentManifest.model_validate_json(path.read_text(encoding="utf-8"))


def validate_separation(
    staging: EnvironmentManifest,
    production: EnvironmentManifest,
) -> list[str]:
    errors: list[str] = []
    if staging.environment != "staging":
        errors.append("The staging manifest must declare environment=staging")
    if production.environment != "production":
        errors.append("The production manifest must declare environment=production")
    if staging.participant_data_allowed:
        errors.append("Staging must prohibit participant data")
    if not production.participant_data_allowed:
        errors.append("Production must explicitly declare whether participant data is allowed")
    if str(staging.public_origin).rstrip("/") == str(production.public_origin).rstrip("/"):
        errors.append("Staging and production public origins must differ")
    for field_name in SCALAR_ISOLATION_FIELDS:
        if getattr(staging, field_name) == getattr(production, field_name):
            errors.append(f"Staging and production share {field_name}")
    shared_credentials = (
        staging.meta_credential_identities & production.meta_credential_identities
    )
    if shared_credentials:
        errors.append("Staging and production share a Meta credential identity")
    shared_phone_ids = (
        staging.meta_phone_number_identities & production.meta_phone_number_identities
    )
    if shared_phone_ids:
        errors.append("Staging and production share a Meta phone-number identity")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reject staging and production manifests that share protected resources."
    )
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--production", required=True, type=Path)
    arguments = parser.parse_args()
    staging = load_manifest(arguments.staging)
    production = load_manifest(arguments.production)
    errors = validate_separation(staging, production)
    print(
        json.dumps(
            {
                "status": "failed" if errors else "ok",
                "errors": errors,
                "staging_origin": str(staging.public_origin),
                "production_origin": str(production.public_origin),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
