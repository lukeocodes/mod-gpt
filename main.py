"""Entry-point for running the Sentinel AI Discord bot."""

from __future__ import annotations

import asyncio
import logging

from sentinel import create_bot
from sentinel.models.config import load_settings
from sentinel.db import Database
from sentinel.health import start_health_server
from sentinel.services.llm import LLMClient
from sentinel.services.state import StateStore


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def async_main() -> None:
    configure_logging()
    settings = load_settings()
    database = Database(settings.database_url)
    await database.connect()
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
        settings.health_host, settings.health_port, state, database
    )
    try:
        await bot.start(settings.discord_token)
    finally:
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
