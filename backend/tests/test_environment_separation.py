import json

from app.commands.validate_environment_separation import (
    EnvironmentManifest,
    validate_separation,
)


def manifest(environment: str) -> EnvironmentManifest:
    participant_data_allowed = environment == "production"
    return EnvironmentManifest.model_validate(
        {
            "environment": environment,
            "participant_data_allowed": participant_data_allowed,
            "public_origin": f"https://{environment}.example.invalid",
            "database_identity": f"{environment}-database",
            "project_configuration_identity": f"{environment}-project-config",
            "csrf_secret_identity": f"{environment}-csrf",
            "security_hash_secret_identity": f"{environment}-security-hash",
            "backup_key_identity": f"{environment}-backup-key",
            "backup_destination_identity": f"{environment}-backup-destination",
            "storage_volume_identity": f"{environment}-storage",
            "meta_credential_identities": [f"{environment}-meta-credential"],
            "meta_phone_number_identities": [f"{environment}-meta-number"],
        }
    )


def test_distinct_staging_and_production_manifests_pass() -> None:
    assert validate_separation(manifest("staging"), manifest("production")) == []


def test_shared_protected_resources_and_staging_participant_data_are_rejected() -> None:
    staging_payload = json.loads(manifest("staging").model_dump_json())
    production = manifest("production")
    staging_payload["participant_data_allowed"] = True
    staging_payload["database_identity"] = production.database_identity
    staging_payload["backup_key_identity"] = production.backup_key_identity
    staging_payload["meta_credential_identities"] = list(
        production.meta_credential_identities
    )
    errors = validate_separation(
        EnvironmentManifest.model_validate(staging_payload),
        production,
    )
    assert "Staging must prohibit participant data" in errors
    assert "Staging and production share database_identity" in errors
    assert "Staging and production share backup_key_identity" in errors
    assert "Staging and production share a Meta credential identity" in errors
