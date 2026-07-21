import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.project_config import ProjectId
from app.db.models.conversation import WhatsAppMessage
from app.db.models.enums import DeliveryStatus, OutboxStatus
from app.db.models.outbox import OutboxEntry
from app.integrations.whatsapp.base import OutboundText, WhatsAppClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedOutboundMessage:
    entry_id: UUID
    project_id: str
    attempt_count: int
    payload: dict


class OutboxProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: WhatsAppClient,
        *,
        worker_id: str,
        claim_seconds: int,
        maximum_attempts: int,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._worker_id = worker_id
        self._claim_seconds = claim_seconds
        self._maximum_attempts = maximum_attempts

    async def process_next(self) -> bool:
        claimed = await self._claim_next()
        if claimed is None:
            return False
        try:
            payload = claimed.payload
            payload_project = ProjectId(payload["project_id"])
            if payload_project.value != claimed.project_id:
                raise ValueError("Outbox payload project does not match its owning row")
            outbound = OutboundText(
                project_id=payload_project,
                recipient=str(payload["recipient"]),
                text=str(payload["text"]),
                client_reference=str(payload["client_reference"]),
            )
            result = await self._client.send_text(outbound)
            if not result.accepted:
                raise RuntimeError("WhatsApp provider rejected the outbound message")
        except Exception as exc:  # The failure is persisted before the worker continues.
            logger.warning("Outbound delivery attempt failed", exc_info=exc)
            await self._record_failure(claimed, exc)
            return True
        await self._record_success(claimed, result.provider_message_id)
        return True

    async def _claim_next(self) -> ClaimedOutboundMessage | None:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as database:
            entry = await database.scalar(
                select(OutboxEntry)
                .where(
                    OutboxEntry.attempt_count < self._maximum_attempts,
                    or_(
                        and_(
                            OutboxEntry.status == OutboxStatus.PENDING,
                            OutboxEntry.available_at <= now,
                        ),
                        and_(
                            OutboxEntry.status == OutboxStatus.PROCESSING,
                            OutboxEntry.claimed_until.is_not(None),
                            OutboxEntry.claimed_until <= now,
                        ),
                    ),
                )
                .order_by(OutboxEntry.available_at, OutboxEntry.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if entry is None:
                return None
            entry.status = OutboxStatus.PROCESSING
            entry.claimed_by = self._worker_id
            entry.claimed_at = now
            entry.claimed_until = now + timedelta(seconds=self._claim_seconds)
            entry.attempt_count += 1
            return ClaimedOutboundMessage(
                entry_id=entry.id,
                project_id=entry.project_id,
                attempt_count=entry.attempt_count,
                payload=entry.payload,
            )

    async def _record_success(
        self,
        claimed: ClaimedOutboundMessage,
        provider_message_id: str,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as database:
            entry = await self._locked_claim(database, claimed)
            if entry is None:
                return
            message = await database.scalar(
                select(WhatsAppMessage).where(
                    WhatsAppMessage.project_id == claimed.project_id,
                    WhatsAppMessage.id == entry.message_id,
                )
            )
            if message is None:
                raise RuntimeError("Outbox message no longer exists")
            entry.status = OutboxStatus.SENT
            entry.sent_at = now
            entry.claimed_until = None
            message.meta_message_id = provider_message_id
            message.delivery_status = DeliveryStatus.SENT
            message.sent_at = now

    async def _record_failure(
        self,
        claimed: ClaimedOutboundMessage,
        error: Exception,
    ) -> None:
        now = datetime.now(UTC)
        error_code = type(error).__name__[:128]
        error_summary = str(error)[:512] or "Outbound delivery failed"
        async with self._session_factory.begin() as database:
            entry = await self._locked_claim(database, claimed)
            if entry is None:
                return
            terminal = entry.attempt_count >= self._maximum_attempts
            if terminal:
                entry.status = OutboxStatus.FAILED
                entry.failed_at = now
                entry.terminal_error_code = error_code
                entry.terminal_error_summary = error_summary
                message = await database.scalar(
                    select(WhatsAppMessage).where(
                        WhatsAppMessage.project_id == claimed.project_id,
                        WhatsAppMessage.id == entry.message_id,
                    )
                )
                if message is not None:
                    message.delivery_status = DeliveryStatus.FAILED
                    message.failed_at = now
                    message.error_code = error_code
                    message.error_summary = error_summary
            else:
                entry.status = OutboxStatus.PENDING
                delay_seconds = min(15 * (2 ** (entry.attempt_count - 1)), 900)
                entry.available_at = now + timedelta(seconds=delay_seconds)
            entry.claimed_by = None
            entry.claimed_at = None
            entry.claimed_until = None

    async def _locked_claim(
        self,
        database: AsyncSession,
        claimed: ClaimedOutboundMessage,
    ) -> OutboxEntry | None:
        entry = await database.scalar(
            select(OutboxEntry)
            .where(
                OutboxEntry.project_id == claimed.project_id,
                OutboxEntry.id == claimed.entry_id,
            )
            .with_for_update()
        )
        if (
            entry is None
            or entry.status != OutboxStatus.PROCESSING
            or entry.claimed_by != self._worker_id
        ):
            return None
        return entry
