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
class OutboundTemplate:
    project_id: ProjectId
    recipient: str
    template_name: str
    language_code: str
    body_parameters: tuple[str, ...]
    client_reference: str


@dataclass(frozen=True, slots=True)
class SendResult:
    provider_message_id: str
    accepted: bool


class WhatsAppProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code[:128]
        self.retryable = retryable


class WhatsAppClient(Protocol):
    async def send_text(self, message: OutboundText) -> SendResult: ...

    async def send_template(self, message: OutboundTemplate) -> SendResult: ...

    async def aclose(self) -> None: ...
