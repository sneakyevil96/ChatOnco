from app.integrations.whatsapp.base import WhatsAppClient
from app.integrations.whatsapp.mock import MockWhatsAppClient


def create_whatsapp_client(provider: str) -> WhatsAppClient:
    if provider == "mock":
        return MockWhatsAppClient()
    raise ValueError(f"Unsupported WhatsApp provider: {provider}")

