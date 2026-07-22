import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


SUPPORTED_STATUS_VALUES = {"sent", "delivered", "read", "failed"}
SUPPORTED_INTERACTIVE_TYPES = {"button_reply", "list_reply"}


class MetaWebhookPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MetaInboundMessage:
    phone_number_id: str
    message_id: str
    sender_id: str
    timestamp: datetime
    kind: str
    text: str | None = None
    interactive_action_id: str | None = None
    interactive_title: str | None = None
    attachment_metadata: dict | None = None

    @property
    def event_key(self) -> str:
        return f"message:{self.message_id}"


@dataclass(frozen=True, slots=True)
class MetaDeliveryStatus:
    phone_number_id: str
    message_id: str
    status: str
    timestamp: datetime
    error_code: str | None = None
    error_summary: str | None = None

    @property
    def event_key(self) -> str:
        return f"status:{self.message_id}:{self.status}:{int(self.timestamp.timestamp())}"


@dataclass(frozen=True, slots=True)
class ParsedMetaWebhook:
    inbound_messages: tuple[MetaInboundMessage, ...]
    delivery_statuses: tuple[MetaDeliveryStatus, ...]

    @property
    def phone_number_ids(self) -> frozenset[str]:
        return frozenset(
            event.phone_number_id
            for event in (*self.inbound_messages, *self.delivery_statuses)
        )


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=")
    if len(supplied) != 64:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied.lower())


def _timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise MetaWebhookPayloadError("Invalid Meta webhook timestamp") from exc


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetaWebhookPayloadError(f"Missing or invalid {field}")
    return value


def _minimal_attachment_metadata(message: dict[str, Any], kind: str) -> dict:
    media = message.get(kind)
    result: dict[str, Any] = {"provider_type": kind}
    if not isinstance(media, dict):
        return result
    for source, target in (
        ("id", "media_id"),
        ("mime_type", "mime_type"),
        ("sha256", "sha256"),
        ("filename", "filename"),
    ):
        value = media.get(source)
        if isinstance(value, str) and value:
            result[target] = value[:512]
    if isinstance(media.get("caption"), str) and media["caption"]:
        result["caption_present"] = True
    return result


def _parse_message(phone_number_id: str, message: dict[str, Any]) -> MetaInboundMessage:
    message_id = _required_text(message.get("id"), "message ID")
    sender_id = _required_text(message.get("from"), "message sender")
    timestamp = _timestamp(message.get("timestamp"))
    kind = _required_text(message.get("type"), "message type")
    if kind == "text":
        text_value = message.get("text")
        text = text_value.get("body") if isinstance(text_value, dict) else None
        return MetaInboundMessage(
            phone_number_id=phone_number_id,
            message_id=message_id,
            sender_id=sender_id,
            timestamp=timestamp,
            kind=kind,
            text=_required_text(text, "text body"),
        )
    if kind == "interactive":
        interactive = message.get("interactive")
        if isinstance(interactive, dict):
            interactive_type = interactive.get("type")
            reply = interactive.get(str(interactive_type))
            if interactive_type in SUPPORTED_INTERACTIVE_TYPES and isinstance(reply, dict):
                return MetaInboundMessage(
                    phone_number_id=phone_number_id,
                    message_id=message_id,
                    sender_id=sender_id,
                    timestamp=timestamp,
                    kind=kind,
                    interactive_action_id=_required_text(reply.get("id"), "interactive reply ID"),
                    interactive_title=(
                        str(reply["title"])[:512]
                        if isinstance(reply.get("title"), str)
                        else None
                    ),
                    attachment_metadata={
                        "interactive_type": interactive_type,
                        "action_id": str(reply["id"])[:512],
                    },
                )
    return MetaInboundMessage(
        phone_number_id=phone_number_id,
        message_id=message_id,
        sender_id=sender_id,
        timestamp=timestamp,
        kind=kind,
        attachment_metadata=_minimal_attachment_metadata(message, kind),
    )


def _parse_status(phone_number_id: str, status: dict[str, Any]) -> MetaDeliveryStatus | None:
    status_value = status.get("status")
    if status_value not in SUPPORTED_STATUS_VALUES:
        return None
    error_code = None
    error_summary = None
    errors = status.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        error = errors[0]
        if error.get("code") is not None:
            error_code = str(error["code"])[:128]
        detail = error.get("error_data")
        detail_text = detail.get("details") if isinstance(detail, dict) else None
        summary = detail_text or error.get("message") or error.get("title")
        if summary is not None:
            error_summary = str(summary)[:512]
    return MetaDeliveryStatus(
        phone_number_id=phone_number_id,
        message_id=_required_text(status.get("id"), "status message ID"),
        status=str(status_value),
        timestamp=_timestamp(status.get("timestamp")),
        error_code=error_code,
        error_summary=error_summary,
    )


def parse_meta_webhook(raw_body: bytes) -> ParsedMetaWebhook:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetaWebhookPayloadError("Malformed Meta webhook JSON") from exc
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise MetaWebhookPayloadError("Unexpected Meta webhook object")
    inbound: list[MetaInboundMessage] = []
    statuses: list[MetaDeliveryStatus] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise MetaWebhookPayloadError("Meta webhook entry must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = (
                metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            )
            phone_number_id = _required_text(phone_number_id, "receiving phone-number ID")
            for message in value.get("messages", []):
                if isinstance(message, dict):
                    inbound.append(_parse_message(phone_number_id, message))
            for status in value.get("statuses", []):
                if isinstance(status, dict):
                    parsed = _parse_status(phone_number_id, status)
                    if parsed is not None:
                        statuses.append(parsed)
    return ParsedMetaWebhook(tuple(inbound), tuple(statuses))
