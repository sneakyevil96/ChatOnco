from hashlib import sha256

from app.integrations.whatsapp.base import OutboundText, SendResult


class MockWhatsAppClient:
    """Deterministic local/test provider that performs no network requests."""

    async def send_text(self, message: OutboundText) -> SendResult:
        fingerprint = sha256(
            f"{message.project_id}:{message.client_reference}".encode()
        ).hexdigest()[:24]
        return SendResult(
            provider_message_id=f"mock-{fingerprint}",
            accepted=True,
        )

