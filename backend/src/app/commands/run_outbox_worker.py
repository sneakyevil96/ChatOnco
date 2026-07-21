import asyncio
import logging
import socket
from uuid import uuid4

from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.integrations.whatsapp.factory import create_whatsapp_client
from app.services.outbox_processor import OutboxProcessor


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    engine = create_database_engine(settings.database_url)
    processor = OutboxProcessor(
        create_session_factory(engine),
        create_whatsapp_client(settings.whatsapp_provider),
        worker_id=f"{socket.gethostname()}-{uuid4().hex[:8]}",
        claim_seconds=settings.outbox_claim_seconds,
        maximum_attempts=settings.outbox_max_attempts,
    )
    try:
        while True:
            try:
                processed = await processor.process_next()
            except Exception:
                logging.exception("Outbox polling failed")
                processed = False
            if not processed:
                await asyncio.sleep(settings.outbox_poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
