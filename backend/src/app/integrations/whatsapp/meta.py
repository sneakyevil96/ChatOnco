from typing import Any

import httpx

from app.core.project_config import ProjectCatalog, ProjectId
from app.integrations.whatsapp.base import (
    OutboundTemplate,
    OutboundText,
    SendResult,
    WhatsAppProviderError,
)
from app.integrations.whatsapp.secrets import MetaSecretCatalog


class MetaWhatsAppClient:
    def __init__(
        self,
        project_catalog: ProjectCatalog,
        secret_catalog: MetaSecretCatalog,
        *,
        graph_api_version: str,
        graph_api_base_url: str,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._projects = project_catalog
        self._secrets = secret_catalog
        self._version = graph_api_version.strip("/")
        self._base_url = graph_api_base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = http_client is None

    def _project_settings(self, project_id: ProjectId) -> tuple[str, str]:
        project = self._projects.get(project_id)
        whatsapp = project.whatsapp
        if not whatsapp.enabled or not whatsapp.phone_number_id or not whatsapp.credential_binding:
            raise WhatsAppProviderError(
                "WhatsApp is not enabled for this project",
                code="project_not_configured",
                retryable=False,
            )
        try:
            access_token = self._secrets.access_token(whatsapp.credential_binding)
        except ValueError as exc:
            raise WhatsAppProviderError(
                "Meta credentials are not configured for this project",
                code="credentials_not_configured",
                retryable=False,
            ) from exc
        return whatsapp.phone_number_id, access_token

    async def _send(self, project_id: ProjectId, payload: dict[str, Any]) -> SendResult:
        try:
            phone_number_id, access_token = self._project_settings(project_id)
            response = await self._client.post(
                f"{self._base_url}/{self._version}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        except WhatsAppProviderError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WhatsAppProviderError(
                "Meta request did not complete",
                code=type(exc).__name__,
                retryable=True,
            ) from exc
        if response.is_error:
            try:
                error_body = response.json()
                error = error_body.get("error", {}) if isinstance(error_body, dict) else {}
            except ValueError:
                error = {}
            code = str(error.get("code") or response.status_code)
            summary = str(error.get("message") or "Meta rejected the outbound message")[:512]
            retryable = (
                error.get("is_transient") is True
                or response.status_code in {408, 429}
                or response.status_code >= 500
            )
            raise WhatsAppProviderError(summary, code=code, retryable=retryable)
        try:
            body = response.json()
            provider_message_id = body["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise WhatsAppProviderError(
                "Meta response did not contain a message ID",
                code="invalid_provider_response",
                retryable=True,
            ) from exc
        return SendResult(provider_message_id=str(provider_message_id), accepted=True)

    async def send_text(self, message: OutboundText) -> SendResult:
        return await self._send(
            message.project_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": message.recipient,
                "type": "text",
                "text": {"preview_url": False, "body": message.text},
                "biz_opaque_callback_data": message.client_reference,
            },
        )

    async def send_template(self, message: OutboundTemplate) -> SendResult:
        components: list[dict[str, Any]] = []
        if message.body_parameters:
            components.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value}
                        for value in message.body_parameters
                    ],
                }
            )
        template_payload: dict[str, Any] = {
            "name": message.template_name,
            "language": {"code": message.language_code},
        }
        if components:
            template_payload["components"] = components
        return await self._send(
            message.project_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": message.recipient,
                "type": "template",
                "template": template_payload,
                "biz_opaque_callback_data": message.client_reference,
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
