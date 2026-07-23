import json
import logging

import pytest
from pydantic import ValidationError

from app.core.logging import PrivacySafeJsonFormatter
from app.core.settings import Settings


def production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "csrf_signing_key": "production-specific-csrf-key",
        "security_hash_key": "production-specific-security-key",
        "database_url": "postgresql+psycopg://service:secret@postgres/screening",
        "allowed_browser_origins": "https://screening.example.invalid",
        "operator_panel_access_mode": "vpn",
        "restricted_panel_mfa_risk_accepted": True,
        "api_docs_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_public_panel_until_mfa_is_implemented() -> None:
    with pytest.raises(ValidationError, match="MFA"):
        production_settings(operator_panel_access_mode="public")


def test_production_requires_https_origins_and_explicit_restricted_access_acceptance() -> None:
    with pytest.raises(ValidationError, match="risk acceptance"):
        production_settings(restricted_panel_mfa_risk_accepted=False)
    with pytest.raises(ValidationError, match="HTTPS"):
        production_settings(allowed_browser_origins="http://screening.example.invalid")


def test_privacy_safe_formatter_ignores_unapproved_extra_fields_and_exception_text() -> None:
    formatter = PrivacySafeJsonFormatter()
    try:
        raise RuntimeError("sensitive synthetic body")
    except RuntimeError:
        record = logging.LogRecord(
            name="synthetic",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="operation.failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
    record.message_content = "must not appear"
    record.request_id = "safe-request-id"
    payload = json.loads(formatter.format(record))
    assert payload["event"] == "operation.failed"
    assert payload["request_id"] == "safe-request-id"
    assert payload["exception_type"] == "RuntimeError"
    assert "sensitive synthetic body" not in json.dumps(payload)
    assert "message_content" not in payload
