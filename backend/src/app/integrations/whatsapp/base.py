from dataclasses import dataclass
from typing import Protocol

from app.core.project_config import ProjectId


@dataclass(frozen=True, slots=True)
class OutboundText:
    project_id: ProjectId
    recipient: str
    text: str
    client_reference: str


@dataclass(frozen=True, slots=True)
class SendResult:
    provider_message_id: str
    accepted: bool


class WhatsAppClient(Protocol):
    async def send_text(self, message: OutboundText) -> SendResult: ...

