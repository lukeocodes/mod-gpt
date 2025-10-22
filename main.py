"""Entry-point for running the mod-gpt Discord bot."""

from __future__ import annotations

import asyncio
import logging

from modgpt import create_bot
from modgpt.config import load_settings
from modgpt.db import Database
from modgpt.health import start_health_server
from modgpt.llm import LLMClient
from modgpt.state import StateStore


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
    state = StateStore(database=database, built_in_prompt=settings.built_in_prompt)
    llm = LLMClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
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
