"""Entry-point for running the Sentinel AI Discord bot."""

from __future__ import annotations

import asyncio
import logging

from sentinel import create_bot
from sentinel.db import Database
from sentinel.health import start_health_server
from sentinel.models.config import load_settings
from sentinel.services.llm import LLMClient
from sentinel.services.registration import RegistrationService
from sentinel.services.state import StateStore


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def async_main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = load_settings()
    database = Database(settings.database_url)
    await database.connect()

    # Initialize machine registration service
    registration_service = None
    if settings.machine_id:
        registration_service = RegistrationService(
            database=database,
            machine_id=settings.machine_id,
            version=settings.version,
        )
        await registration_service.register()
        await registration_service.start_heartbeat()
    else:
        logger.warning("No MACHINE_ID set - machine registration disabled")

    state = StateStore(database=database)
    await state.load()
    snapshot = await state.get_state()
    llm_config = snapshot.llm
    llm = LLMClient(
        api_key=llm_config.api_key,
        model=llm_config.model,
        base_url=llm_config.base_url,
    )

    bot = create_bot(settings, state, llm, database)
    health_server = await start_health_server(
        settings.health_host, settings.health_port, state, database, registration_service
    )
    try:
        await bot.start(settings.discord_token)
    finally:
        if registration_service:
            await registration_service.shutdown()
        health_server.close()
        await health_server.wait_closed()
        await database.close()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
