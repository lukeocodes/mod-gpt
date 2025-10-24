"""Discord bot wiring for Sentinel AI."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from .commands.context_menu import register_context_menu_commands
from .commands.slash import register_slash_commands
from .db import Database
from .models.config import BotSettings
from .services.llm import LLMClient
from .services.moderation import ModerationAgent
from .services.state import StateStore

logger = logging.getLogger(__name__)


def create_bot(
    settings: BotSettings,
    state: StateStore,
    llm: LLMClient,
    database: Database,
) -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    # Using slash commands exclusively - no text command prefix needed
    bot = commands.Bot(
        command_prefix="!",  # Required by discord.py but unused (slash commands only)
        intents=intents,
        help_command=None,
    )

    # Store database reference for slash commands to access
    bot.database = database  # type: ignore

    moderation = ModerationAgent(bot, state, llm, database)

    # Register slash commands
    register_slash_commands(bot.tree, state, moderation, llm)

    # Register context menu commands
    register_context_menu_commands(bot.tree, moderation)

    @tasks.loop(minutes=30)
    async def scheduled_tick() -> None:
        if not bot.is_ready():
            return
        for guild in bot.guilds:
            await moderation.handle_scheduled_tick(guild)

    @scheduled_tick.before_loop
    async def before_scheduled_tick() -> None:
        await bot.wait_until_ready()

    @bot.event
    async def setup_hook() -> None:  # type: ignore[override]
        await state.load()
        storage = "database" if database.is_connected else "in-memory"
        logger.info("State initialised using %s storage", storage)
        if not scheduled_tick.is_running():
            scheduled_tick.start()

        # Sync slash and context menu commands
        try:
            logger.info("Syncing commands to Discord...")
            synced = await bot.tree.sync()
            logger.info("✅ Synced %d commands to Discord (slash + context menus)", len(synced))
            for cmd in synced:
                logger.debug("  - %s (%s)", cmd.name, cmd.type.name)
        except Exception:
            logger.exception("Failed to sync commands to Discord")

    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s", bot.user)
        current_state = await state.get_state()
        nickname = current_state.bot_nickname
        if nickname:
            for guild in bot.guilds:
                me = guild.me
                if me and me.nick != nickname:
                    try:
                        await me.edit(nick=nickname)
                    except discord.Forbidden:
                        logger.warning(
                            "Insufficient permissions to update nickname in guild %s", guild.id
                        )
                    except discord.HTTPException:
                        logger.exception("Failed to update nickname in guild %s", guild.id)

        # Seed global fraud heuristics (run once, idempotent)
        logger.info("Seeding global fraud heuristics...")
        try:
            from .utils.seed_heuristics import seed_global_heuristics

            seeded = await seed_global_heuristics(database)
            if seeded > 0:
                logger.info("Seeded %d global fraud heuristics", seeded)
            else:
                logger.info("Global fraud heuristics already seeded")
        except Exception:
            logger.exception("Failed to seed global heuristics on startup")

        # Refresh all context channels on startup
        logger.info("Refreshing context channels...")
        try:
            refreshed = await state.refresh_all_context_channels(bot, llm)
            if refreshed > 0:
                logger.info("Successfully refreshed %d context channel(s)", refreshed)
        except Exception:
            logger.exception("Failed to refresh context channels on startup")

        # Generate heuristics from context channels and memories
        logger.info("Generating heuristics from server context...")
        try:
            for guild in bot.guilds:
                generated = await moderation.generate_heuristics_from_context(guild)
                if generated > 0:
                    logger.info("Generated %d heuristics for guild %s", generated, guild.name)
        except Exception:
            logger.exception("Failed to generate heuristics on startup")

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await bot.process_commands(message)

        # Auto-refresh context channel if message is in one
        current_state = await state.get_state()
        if message.channel.id in current_state.context_channels:
            logger.info("Message added to context channel %s, refreshing...", message.channel.id)
            try:
                await state.refresh_context_channel(message.channel.id, bot, llm)
            except Exception:
                logger.exception("Failed to auto-refresh context channel")

        await moderation.handle_message(message)

    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        # Auto-refresh context channel if edited message is in one
        current_state = await state.get_state()
        if after.channel.id in current_state.context_channels:
            logger.info("Message edited in context channel %s, refreshing...", after.channel.id)
            try:
                await state.refresh_context_channel(after.channel.id, bot, llm)
            except Exception:
                logger.exception("Failed to auto-refresh context channel")

        await moderation.handle_message_edit(before, after)

    @bot.event
    async def on_message_delete(message: discord.Message) -> None:
        # Auto-refresh context channel if deleted message was in one
        current_state = await state.get_state()
        if message.channel.id in current_state.context_channels:
            logger.info(
                "Message deleted from context channel %s, refreshing...", message.channel.id
            )
            try:
                await state.refresh_context_channel(message.channel.id, bot, llm)
            except Exception:
                logger.exception("Failed to auto-refresh context channel")

    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        await moderation.handle_member_join(member)

    return bot
