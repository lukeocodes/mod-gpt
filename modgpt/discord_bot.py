"""Discord bot wiring for mod-gpt."""

from __future__ import annotations

import logging
from typing import List, Optional

import discord
from discord.ext import commands, tasks

from .agents import AgentRouter
from .config import BotSettings
from .db import Database
from .llm import LLMClient
from .state import (
    AutomationRule,
    ContextChannel,
    PersonaProfile,
    StateStore,
    DEFAULT_COMMAND_PREFIX,
)

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

    async def dynamic_prefix(bot_obj: commands.Bot, message: discord.Message):
        snapshot = await state.get_state()
        prefix = snapshot.command_prefix or DEFAULT_COMMAND_PREFIX
        return commands.when_mentioned_or(prefix)(bot_obj, message)

    bot = commands.Bot(
        command_prefix=dynamic_prefix,
        intents=intents,
        help_command=None,
    )

    router = AgentRouter(bot, state, llm, database)

    @tasks.loop(minutes=30)
    async def scheduled_tick() -> None:
        if not bot.is_ready():
            return
        for guild in bot.guilds:
            await router.on_scheduled_tick(guild)

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
                        logger.warning("Insufficient permissions to update nickname in guild %s", guild.id)
                    except discord.HTTPException:
                        logger.exception("Failed to update nickname in guild %s", guild.id)

    @bot.event
    async def on_message(message: discord.Message) -> None:
        await bot.process_commands(message)
        await router.on_message(message)

    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        await router.on_message_edit(before, after)

    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        await router.on_member_join(member)

    @bot.event
    async def on_member_remove(member: discord.Member) -> None:
        await router.on_member_remove(member)

    @bot.command(name="help")
    async def help_command(ctx: commands.Context) -> None:
        snapshot = await state.get_state()
        prefix = snapshot.command_prefix or DEFAULT_COMMAND_PREFIX
        content = (
            f"ModGPT commands (mention or `{prefix}`):\n"
            "- `add-channel #channel optional description`\n"
            "- `remove-channel #channel`\n"
            "- `list-channels`\n"
            "- `set-logs #channel`\n"
            "- `remember Important guideline`\n"
            "- `list-memories`\n"
            "- `forget-memory 12`\n"
            "- `set-persona Name | description | style`\n"
            "- `set-interests interest1, interest2`\n"
            "- `set-automation #channel action short-summary | reason`\n"
            "- `disable-automation #channel`\n"
            "- `set-prefix new_prefix` (blank to reset)\n"
            "- `set-nickname Friendly ModGPT` (blank to clear)\n"
            "- `set-dry-run on/off`\n"
            "- `spark [optional topic hint]`\n"
            "- `run-cron` (forces an immediate scheduled check)\n"
        )
        await ctx.send(content)

    @bot.command(name="add-channel")
    @commands.has_permissions(manage_guild=True)
    async def add_channel(
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        description: Optional[str] = None,
    ) -> None:
        context_channel = ContextChannel(
            channel_id=channel.id,
            label=channel.name,
            notes=description.strip() if description else None,
        )
        await state.add_context_channel(context_channel)
        await ctx.send(
            f"Added #{channel.name} as a context channel. Notes: {context_channel.notes or 'none'}."
        )

    @bot.command(name="remove-channel")
    @commands.has_permissions(manage_guild=True)
    async def remove_channel(ctx: commands.Context, channel: discord.TextChannel) -> None:
        removed = await state.remove_context_channel(channel.id)
        if removed:
            await ctx.send(f"Removed #{channel.name} from context channels.")
        else:
            await ctx.send(f"#{channel.name} was not registered.")

    @bot.command(name="list-channels")
    async def list_channels(ctx: commands.Context) -> None:
        current_state = await state.get_state()
        if not current_state.context_channels:
            await ctx.send("No context channels configured yet.")
            return
        lines = []
        for ctx_channel in current_state.context_channels.values():
            lines.append(f"- #{ctx_channel.label} ({ctx_channel.channel_id}): {ctx_channel.notes or 'no notes'}")
        await ctx.send("\n".join(lines))

    @bot.command(name="set-logs")
    @commands.has_permissions(manage_guild=True)
    async def set_logs(ctx: commands.Context, channel: discord.TextChannel) -> None:
        await state.set_logs_channel(channel.id)
        await ctx.send(f"Logs channel set to #{channel.name}.")

    @bot.command(name="remember")
    @commands.has_permissions(manage_guild=True)
    async def remember(ctx: commands.Context, *, note: str) -> None:
        if ctx.guild is None:
            await ctx.send("Memories can only be stored inside a server.")
            return
        content = note.strip()
        if not content:
            await ctx.send("Please provide the text you want me to remember.")
            return
        memory = await state.add_memory(
            guild_id=ctx.guild.id,
            content=content,
            author=str(ctx.author),
            author_id=ctx.author.id,
        )
        await ctx.send(f"Stored memory #{memory.memory_id}: {memory.content}")

    @bot.command(name="list-memories")
    @commands.has_permissions(manage_guild=True)
    async def list_memories(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("This command must be used inside a server.")
            return
        memories = await state.list_memories(ctx.guild.id)
        if not memories:
            await ctx.send("No memories recorded yet.")
            return
        lines = [
            f"#{memory.memory_id} – {memory.content} (by {memory.author} on {memory.created_at})"
            for memory in memories[:10]
        ]
        if len(memories) > 10:
            lines.append(f"...and {len(memories) - 10} more")
        await ctx.send("\n".join(lines))

    @bot.command(name="forget-memory")
    @commands.has_permissions(manage_guild=True)
    async def forget_memory(ctx: commands.Context, memory_id: int) -> None:
        if ctx.guild is None:
            await ctx.send("This command must be used inside a server.")
            return
        removed = await state.remove_memory(ctx.guild.id, memory_id)
        if removed:
            await ctx.send(f"Forgot memory #{memory_id}.")
        else:
            await ctx.send(f"No memory found with id #{memory_id}.")

    @bot.command(name="set-prefix")
    @commands.has_permissions(manage_guild=True)
    async def set_prefix(ctx: commands.Context, *, prefix: Optional[str] = None) -> None:
        normalized = prefix.strip() if prefix and prefix.strip() else None
        await state.set_command_prefix(normalized)
        snapshot = await state.get_state()
        effective_prefix = snapshot.command_prefix or DEFAULT_COMMAND_PREFIX
        if normalized:
            await ctx.send(
                f"Command prefix updated to `{effective_prefix}`. Mentioning the bot still works."
            )
        else:
            await ctx.send(
                f"Command prefix reset to default `{DEFAULT_COMMAND_PREFIX}`. Mentioning the bot still works."
            )

    @bot.command(name="set-nickname")
    @commands.has_permissions(manage_guild=True)
    async def set_nickname(ctx: commands.Context, *, nickname: Optional[str] = None) -> None:
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        cleaned = nickname.strip() if nickname and nickname.strip() else None
        me = ctx.guild.me
        if me:
            try:
                await me.edit(nick=cleaned)
            except discord.Forbidden:
                await ctx.send("I need permission to manage my nickname to apply that change.")
                return
            except discord.HTTPException:
                await ctx.send("Something went wrong while updating the nickname. Try again later.")
                return
        else:
            await ctx.send("I couldn't access my member profile to change the nickname right now.")
            return
        await state.set_bot_nickname(cleaned)
        if cleaned:
            await ctx.send(f"Nickname updated to `{cleaned}`.")
        else:
            await ctx.send("Nickname cleared; the default account name will be used.")

    @bot.command(name="set-dry-run")
    @commands.has_permissions(manage_guild=True)
    async def set_dry_run(ctx: commands.Context, mode: Optional[str] = None) -> None:
        current_state = await state.get_state()
        if mode is None:
            await ctx.send(
                f"Dry-run mode is currently {'enabled' if current_state.dry_run else 'disabled'}."
            )
            return
        normalized = mode.lower().strip()
        if normalized in {"on", "enable", "enabled", "true", "yes"}:
            await state.set_dry_run(True)
            await ctx.send("Dry-run mode enabled. Actions will be simulated and logged only.")
        elif normalized in {"off", "disable", "disabled", "false", "no"}:
            await state.set_dry_run(False)
            await ctx.send("Dry-run mode disabled. Actions will execute normally.")
        else:
            await ctx.send("Please specify `on` or `off`.")

    @bot.command(name="set-persona")
    @commands.has_permissions(manage_guild=True)
    async def set_persona(ctx: commands.Context, *, payload: str) -> None:
        parts = [part.strip() for part in payload.split("|")]
        name = parts[0] if parts else "ModGPT"
        description = parts[1] if len(parts) > 1 else "A diligent moderator."
        style = parts[2] if len(parts) > 2 else "Friendly yet firm."
        current = (await state.get_state()).persona
        persona = PersonaProfile(
            name=name,
            description=description,
            conversation_style=style,
            interests=current.interests,
        )
        await state.set_persona(persona)
        await ctx.send(
            f"Persona updated. Name: {persona.name}. Description: {persona.description}. Style: {persona.conversation_style}"
        )

    @bot.command(name="set-interests")
    @commands.has_permissions(manage_guild=True)
    async def set_interests(ctx: commands.Context, *, interests: str) -> None:
        items = [item.strip() for item in interests.split(",") if item.strip()]
        current = await state.get_state()
        persona = PersonaProfile(
            name=current.persona.name,
            description=current.persona.description,
            conversation_style=current.persona.conversation_style,
            interests=items,
        )
        await state.set_persona(persona)
        await ctx.send(f"Persona interests updated: {', '.join(items) if items else 'none'}")

    @bot.command(name="set-automation")
    @commands.has_permissions(manage_guild=True)
    async def set_automation(
        ctx: commands.Context,
        channel: discord.TextChannel,
        action: str,
        *,
        summary_and_reason: str,
    ) -> None:
        if action not in {"kick", "ban", "delete_message", "warn", "timeout"}:
            await ctx.send("Invalid action. Choose from kick, ban, delete_message, warn, timeout.")
            return
        keywords: List[str] = []
        parts = [part.strip() for part in summary_and_reason.split("|")]
        summary = parts[0] if parts else f"Automation for #{channel.name}"
        if len(parts) > 1 and not parts[1].lower().startswith("keywords="):
            reason = parts[1]
        else:
            reason = f"Automation triggered in #{channel.name}"
        for segment in parts[1:]:
            if segment.lower().startswith("keywords="):
                keyword_values = segment.split("=", 1)[1]
                keywords = [word.strip() for word in keyword_values.split(",") if word.strip()]
            elif segment and segment != reason:
                reason = segment
        rule = AutomationRule(
            channel_id=channel.id,
            trigger_summary=summary,
            action=action,
            justification=reason,
            keywords=keywords,
        )
        await state.upsert_automation(rule)
        await ctx.send(
            f"Automation configured for #{channel.name}: action={action}, summary={summary}, reason={reason}"
            + (f", keywords={', '.join(keywords)}" if keywords else "")
        )

    @bot.command(name="disable-automation")
    @commands.has_permissions(manage_guild=True)
    async def disable_automation(ctx: commands.Context, channel: discord.TextChannel) -> None:
        removed = await state.deactivate_automation(channel.id)
        if removed:
            await ctx.send(f"Automation disabled for #{channel.name}.")
        else:
            await ctx.send(f"No automation rule found for #{channel.name}.")

    @bot.command(name="spark")
    async def spark(ctx: commands.Context, *, topic_hint: Optional[str] = None) -> None:
        target_channel = ctx.channel
        await router.spark_conversation(target_channel, topic_hint=topic_hint)
        if ctx.guild:
            await ctx.send("Conversation sparked.")

    @bot.command(name="run-cron")
    @commands.has_permissions(manage_guild=True)
    async def run_cron(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("This command must be used inside a server.")
            return
        await router.on_scheduled_tick(ctx.guild)
        await ctx.send("Scheduled tasks evaluated.")

    return bot
