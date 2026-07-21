import asyncio

from app.core.project_config import ProjectId
from app.integrations.whatsapp.base import OutboundText
from app.integrations.whatsapp.factory import create_whatsapp_client


def test_mock_provider_is_deterministic_and_network_free() -> None:
    client = create_whatsapp_client("mock")
    message = OutboundText(
        project_id=ProjectId.ONCODIR,
        recipient="synthetic-recipient",
        text="Mesaj sintetic",
        client_reference="synthetic-reference",
    )

    first = asyncio.run(client.send_text(message))
    second = asyncio.run(client.send_text(message))

    assert first.accepted is True
    assert first.provider_message_id == second.provider_message_id
    assert first.provider_message_id.startswith("mock-")
