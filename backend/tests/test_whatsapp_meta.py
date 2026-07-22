import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from app.core.project_config import ProjectCatalog, ProjectId, WhatsAppConfig
from app.integrations.whatsapp.base import OutboundTemplate, OutboundText, WhatsAppProviderError
from app.integrations.whatsapp.meta import MetaWhatsAppClient
from app.integrations.whatsapp.secrets import MetaBindingSecrets, MetaSecretCatalog
from app.integrations.whatsapp.webhook import parse_meta_webhook, verify_meta_signature
from app.services.privacy_detection import contains_obvious_sensitive_content


PROJECT_CONFIG_DIR = Path(__file__).parents[1] / "config" / "projects"


def enabled_catalog() -> ProjectCatalog:
    source = ProjectCatalog.load(PROJECT_CONFIG_DIR)
    oncodir = source.get(ProjectId.ONCODIR).model_copy(
        update={
            "whatsapp": WhatsAppConfig(
                enabled=True,
                phone_number_id="synthetic-phone-id",
                credential_binding="synthetic-credentials",
                webhook_binding="synthetic-webhook",
            )
        }
    )
    return ProjectCatalog(
        {
            ProjectId.ONCODIR: oncodir,
            ProjectId.ONCOSCREEN: source.get(ProjectId.ONCOSCREEN),
        }
    )


def secrets() -> MetaSecretCatalog:
    return MetaSecretCatalog(
        {
            "synthetic-credentials": MetaBindingSecrets(access_token="synthetic-access-token"),
            "synthetic-webhook": MetaBindingSecrets(
                app_secret="synthetic-app-secret",
                verify_token="synthetic-verify-token",
            ),
        }
    )


def webhook_payload(*, message: dict | None = None, status: dict | None = None) -> bytes:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "40000000000",
            "phone_number_id": "synthetic-phone-id",
        },
    }
    if message is not None:
        value["messages"] = [message]
    if status is not None:
        value["statuses"] = [status]
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "synthetic-waba", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()


def test_signature_validation_uses_the_exact_raw_body() -> None:
    body = b'{"synthetic":true}'
    signature = "sha256=" + hmac.new(
        b"synthetic-app-secret", body, hashlib.sha256
    ).hexdigest()
    assert verify_meta_signature(body, signature, "synthetic-app-secret")
    assert not verify_meta_signature(body + b" ", signature, "synthetic-app-secret")
    assert not verify_meta_signature(body, "sha256=invalid", "synthetic-app-secret")


def test_parser_keeps_only_minimal_unsupported_attachment_metadata() -> None:
    parsed = parse_meta_webhook(
        webhook_payload(
            message={
                "from": "40700000111",
                "id": "wamid.synthetic-media",
                "timestamp": "1784678400",
                "type": "document",
                "document": {
                    "id": "synthetic-media-id",
                    "mime_type": "application/pdf",
                    "sha256": "synthetic-sha256",
                    "filename": "synthetic.pdf",
                    "caption": "content that must not be retained",
                },
            }
        )
    )
    message = parsed.inbound_messages[0]
    assert message.kind == "document"
    assert message.attachment_metadata == {
        "provider_type": "document",
        "media_id": "synthetic-media-id",
        "mime_type": "application/pdf",
        "sha256": "synthetic-sha256",
        "filename": "synthetic.pdf",
        "caption_present": True,
    }


def test_parser_extracts_delivery_error_without_retaining_the_full_payload() -> None:
    parsed = parse_meta_webhook(
        webhook_payload(
            status={
                "id": "wamid.synthetic-outbound",
                "status": "failed",
                "timestamp": "1784678401",
                "recipient_id": "40700000111",
                "errors": [
                    {
                        "code": 131000,
                        "title": "Synthetic failure",
                        "error_data": {"details": "Synthetic delivery detail"},
                    }
                ],
            }
        )
    )
    delivery = parsed.delivery_statuses[0]
    assert delivery.error_code == "131000"
    assert delivery.error_summary == "Synthetic delivery detail"


def test_meta_client_sends_text_and_template_to_the_project_phone_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-access-token"
        return httpx.Response(200, json={"messages": [{"id": f"wamid.synthetic-{len(requests)}"}]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MetaWhatsAppClient(
                enabled_catalog(),
                secrets(),
                graph_api_version="v-test",
                graph_api_base_url="https://graph.facebook.test",
                timeout_seconds=1,
                http_client=http_client,
            )
            text_result = await client.send_text(
                OutboundText(
                    project_id=ProjectId.ONCODIR,
                    recipient="40700000111",
                    text="Mesaj sintetic",
                    client_reference="synthetic-text",
                )
            )
            template_result = await client.send_template(
                OutboundTemplate(
                    project_id=ProjectId.ONCODIR,
                    recipient="40700000111",
                    template_name="synthetic_template",
                    language_code="ro",
                    body_parameters=("valoare",),
                    client_reference="synthetic-template",
                )
            )
            assert text_result.provider_message_id == "wamid.synthetic-1"
            assert template_result.provider_message_id == "wamid.synthetic-2"

    asyncio.run(scenario())
    assert all(request.url.path == "/v-test/synthetic-phone-id/messages" for request in requests)
    assert json.loads(requests[0].content)["type"] == "text"
    assert json.loads(requests[1].content)["type"] == "template"


def test_non_transient_meta_error_is_terminal() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": 131047, "message": "Synthetic window error", "is_transient": False}},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MetaWhatsAppClient(
                enabled_catalog(),
                secrets(),
                graph_api_version="v-test",
                graph_api_base_url="https://graph.facebook.test",
                timeout_seconds=1,
                http_client=http_client,
            )
            with pytest.raises(WhatsAppProviderError) as error:
                await client.send_text(
                    OutboundText(
                        project_id=ProjectId.ONCODIR,
                        recipient="40700000111",
                        text="Mesaj sintetic",
                        client_reference="synthetic-terminal",
                    )
                )
            assert error.value.code == "131047"
            assert error.value.retryable is False

    asyncio.run(scenario())


def test_sensitive_content_detection_is_conservative() -> None:
    first_twelve = "180010122114"
    checksum = sum(
        int(digit) * int(weight)
        for digit, weight in zip(first_twelve, "279146358279")
    ) % 11
    if checksum == 10:
        checksum = 1
    assert contains_obvious_sensitive_content(f"CNP {first_twelve}{checksum}")
    assert contains_obvious_sensitive_content("Am trimis un bilet de externare")
    assert not contains_obvious_sensitive_content("Care sunt documentele administrative necesare?")
