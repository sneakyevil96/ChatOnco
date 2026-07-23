import json
import logging
import sys
from datetime import UTC, datetime


SAFE_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "project_id",
    "event_code",
    "worker_id",
)


class PrivacySafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str, *, structured: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if structured:
        handler.setFormatter(PrivacySafeJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logging.basicConfig(
        level=level.upper(),
        handlers=[handler],
        force=True,
    )
