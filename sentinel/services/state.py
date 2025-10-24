"""Persistent state management for Sentinel AI."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..db import Database


class ContextChannel(BaseModel):
    """Reference to a channel containing static guidance."""

    channel_id: int
    guild_id: int
    label: str
    notes: Optional[str] = None
    recent_messages: Optional[str] = None  # Summary of recent messages from the channel
    last_fetched: Optional[str] = None  # ISO timestamp of when messages were last fetched


class PersonaProfile(BaseModel):
    """Persona configuration for the bot."""

    name: str = "Sentinel"
    description: str = "A diligent, fair Discord moderator who values context."
    interests: List[str] = Field(default_factory=list)
    conversation_style: str = (
        "Friendly, concise, proactive when needed, otherwise quietly attentive."
    )


class AutomationRule(BaseModel):
    """Dynamic policy for a channel or trigger."""

    channel_id: int
    trigger_summary: str
    action: str
    justification: str
    active: bool = True
    keywords: List[str] = Field(default_factory=list)


class LLMSettings(BaseModel):
    """Stored configuration for LLM access."""

    api_key: Optional[str] = None
    model: Optional[str] = "gpt-4o-mini"
    base_url: Optional[str] = None


class MemoryNote(BaseModel):
    """Persistent instructions or reminders set by administrators."""

    memory_id: int
    guild_id: int
    content: str
    author: str
    author_id: int
    created_at: str


class BotState(BaseModel):
    """Snapshot of the bot's configuration and automation state."""

    context_channels: Dict[int, ContextChannel] = Field(default_factory=dict)
    persona: PersonaProfile = Field(default_factory=PersonaProfile)
    logs_channel_id: Optional[int] = None
    automations: Dict[int, AutomationRule] = Field(default_factory=dict)
    bot_nickname: Optional[str] = None
    memories: List[MemoryNote] = Field(default_factory=list)
    dry_run: bool = False
    proactive_moderation: bool = True  # Check all messages for violations (not just mentions)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    built_in_prompt: Optional[str] = None


class StateStore:
    """Thread-safe state manager backed by database.

    All configuration is now guild-specific and loaded on-demand.
    The only global data is LLM settings and global heuristics.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        built_in_prompt: Optional[str] = None,
        initial_llm_settings: Optional[LLMSettings] = None,
    ):
        self._lock = asyncio.Lock()
        self._db = database
        self._default_built_in_prompt = built_in_prompt
        initial_llm = (initial_llm_settings or LLMSettings()).model_copy()
        self._initial_llm_settings = initial_llm

    async def load(self) -> None:
        """Initialize LLM settings from database if available."""
        if not self._uses_db:
            return

        async with self._lock:
            # Only load global LLM settings at startup
            stored_llm = await self._db.get_llm_settings()
            if stored_llm and stored_llm.get("api_key"):
                # Database has settings, use them
                pass
            elif self._initial_llm_settings.api_key:
                # Initialize database with provided settings
                await self._db.set_llm_settings(
                    api_key=self._initial_llm_settings.api_key,
                    model=self._initial_llm_settings.model,
                    base_url=self._initial_llm_settings.base_url,
                )

    async def save(self) -> None:
        """Compatibility hook; state writes happen immediately on mutation."""
        pass

    async def get_state(self, guild_id: Optional[int] = None) -> BotState:
        """Get bot state for a specific guild.

        Args:
            guild_id: Guild ID to get state for. Required for per-guild config.

        Returns:
            BotState with guild-specific configuration
        """
        if not self._uses_db:
            # No database, return minimal default state
            return BotState(
                llm=self._initial_llm_settings.model_copy(),
                built_in_prompt=self._default_built_in_prompt,
            )

        if guild_id is None:
            # No guild context - return minimal state with just LLM settings
            async with self._lock:
                stored_llm = await self._db.get_llm_settings()
                llm_settings = (
                    LLMSettings(**stored_llm)
                    if stored_llm
                    else self._initial_llm_settings.model_copy()
                )
                if not llm_settings.api_key:
                    llm_settings = self._initial_llm_settings.model_copy()
                if not llm_settings.model:
                    llm_settings.model = "gpt-4o-mini"
                return BotState(
                    llm=llm_settings,
                    built_in_prompt=self._default_built_in_prompt,
                )

        # Fetch all guild-specific data
        async with self._lock:
            # 1. Guild config (logs, dry_run, nickname, prompt)
            guild_config = await self._db.fetch_guild_config(guild_id)
            logs_channel_id = guild_config.get("logs_channel_id") if guild_config else None
            dry_run = guild_config.get("dry_run", False) if guild_config else False
            proactive_moderation = (
                guild_config.get("proactive_moderation", True) if guild_config else True
            )
            bot_nickname = guild_config.get("bot_nickname") if guild_config else None
            built_in_prompt = (
                guild_config.get("built_in_prompt")
                if guild_config
                else self._default_built_in_prompt
            )

            # 2. Persona for this guild
            persona_row = await self._db.fetch_persona(guild_id)
            if persona_row:
                interests = persona_row["interests"] or []
                if isinstance(interests, str):
                    try:
                        interests = json.loads(interests)
                    except json.JSONDecodeError:
                        interests = []
                persona = PersonaProfile(
                    name=persona_row["name"],
                    description=persona_row["description"],
                    conversation_style=persona_row["conversation_style"],
                    interests=list(interests),
                )
            else:
                # Default persona
                persona = PersonaProfile()

            # 3. Context channels for this guild
            context_rows = await self._db.fetch_context_channels(guild_id=guild_id)
            context_channels = {
                row["channel_id"]: ContextChannel(
                    channel_id=row["channel_id"],
                    guild_id=row["guild_id"],
                    label=row["label"],
                    notes=row["notes"],
                    recent_messages=row.get("recent_messages"),
                    last_fetched=row.get("last_fetched").isoformat()
                    if row.get("last_fetched")
                    else None,
                )
                for row in context_rows
            }

            # 4. Memories for this guild
            memories_rows = await self._db.fetch_memories(guild_id=guild_id)
            memories: List[MemoryNote] = []
            for row in memories_rows:
                mapping = dict(row)
                created = mapping.get("created_at")
                memories.append(
                    MemoryNote(
                        memory_id=mapping.get("memory_id"),
                        guild_id=mapping.get("guild_id"),
                        content=mapping.get("content", ""),
                        author=mapping.get("author_name", "Unknown"),
                        author_id=mapping.get("author_id", 0),
                        created_at=created.isoformat()
                        if isinstance(created, datetime)
                        else str(created or ""),
                    )
                )

            # 5. Automations (global, but could be filtered by guild if needed)
            automation_rows = await self._db.fetch_automations()
            automations: Dict[int, AutomationRule] = {}
            for row in automation_rows:
                mapping = dict(row)
                rule = AutomationRule(
                    channel_id=mapping.get("channel_id"),
                    trigger_summary=mapping.get("trigger_summary", ""),
                    action=mapping.get("action", ""),
                    justification=mapping.get("justification", ""),
                    active=mapping.get("active", True),
                    keywords=list(mapping.get("keywords") or []),
                )
                automations[rule.channel_id] = rule

            # 6. LLM settings (global)
            stored_llm = await self._db.get_llm_settings()
            llm_settings = (
                LLMSettings(**stored_llm) if stored_llm else self._initial_llm_settings.model_copy()
            )
            if not llm_settings.api_key:
                llm_settings = self._initial_llm_settings.model_copy()
            if not llm_settings.model:
                llm_settings.model = "gpt-4o-mini"

            return BotState(
                context_channels=context_channels,
                persona=persona,
                logs_channel_id=logs_channel_id,
                automations=automations,
                bot_nickname=bot_nickname,
                memories=memories,
                dry_run=dry_run,
                proactive_moderation=proactive_moderation,
                llm=llm_settings,
                built_in_prompt=built_in_prompt,
            )

    async def add_context_channel(self, channel: ContextChannel) -> None:
        """Add or update a context channel for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_context_channel(
                channel_id=channel.channel_id,
                guild_id=channel.guild_id,
                label=channel.label,
                notes=channel.notes,
                recent_messages=channel.recent_messages,
                last_fetched=channel.last_fetched,
            )

    async def remove_context_channel(self, channel_id: int) -> bool:
        """Remove a context channel."""
        if not self._uses_db:
            return False
        async with self._lock:
            await self._db.delete_context_channel(channel_id)
            return True

    async def refresh_context_channel(self, channel_id: int, bot, llm_client) -> bool:
        """Refresh the content summary for a specific context channel.

        Args:
            channel_id: Discord channel ID to refresh
            bot: Discord bot instance to fetch the channel
            llm_client: LLM client for summarization

        Returns:
            True if refreshed successfully, False if channel not found
        """
        # Fetch channel from Discord to determine guild_id
        try:
            channel = bot.get_channel(channel_id)
            if not channel or not hasattr(channel, "guild"):
                return False

            guild_id = channel.guild.id

            # Get current state for this guild
            async with self._lock:
                current_state = await self.get_state(guild_id=guild_id)
                if channel_id not in current_state.context_channels:
                    return False

                ctx = current_state.context_channels[channel_id]

            from datetime import datetime
            from datetime import timezone as tz

            recent_messages = await fetch_channel_context(
                channel, message_limit=50, llm_client=llm_client
            )

            # Update with new content
            updated_channel = ContextChannel(
                channel_id=ctx.channel_id,
                guild_id=ctx.guild_id,
                label=ctx.label,
                notes=ctx.notes,
                recent_messages=recent_messages,
                last_fetched=datetime.now(tz.utc).isoformat(),
            )

            await self.add_context_channel(updated_channel)
            return True

        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Failed to refresh context channel {channel_id}: {e}"
            )
            return False

    async def refresh_all_context_channels(self, bot, llm_client) -> int:
        """Refresh all context channels across all guilds at startup or on-demand.

        Args:
            bot: Discord bot instance
            llm_client: LLM client for summarization

        Returns:
            Number of channels successfully refreshed
        """
        import logging

        logger = logging.getLogger(__name__)

        refreshed = 0
        total_channels = 0

        # Iterate through all guilds and refresh their context channels
        for guild in bot.guilds:
            guild_state = await self.get_state(guild_id=guild.id)
            if not guild_state.context_channels:
                continue

            total_channels += len(guild_state.context_channels)
            for channel_id in list(guild_state.context_channels.keys()):
                try:
                    if await self.refresh_context_channel(channel_id, bot, llm_client):
                        refreshed += 1
                        logger.info(f"Refreshed context channel {channel_id} in guild {guild.id}")
                except Exception as e:
                    logger.warning(
                        f"Failed to refresh context channel {channel_id} in guild {guild.id}: {e}"
                    )

        if total_channels > 0:
            logger.info(
                f"Refreshed {refreshed}/{total_channels} context channels across all guilds"
            )
        return refreshed

    async def set_logs_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        """Set the logs channel for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_guild_config(guild_id=guild_id, logs_channel_id=channel_id)

    async def upsert_automation(self, rule: AutomationRule) -> None:
        """Add or update an automation rule."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_automation(
                channel_id=rule.channel_id,
                trigger_summary=rule.trigger_summary,
                action=rule.action,
                justification=rule.justification,
                active=rule.active,
                keywords=rule.keywords,
            )

    async def deactivate_automation(self, channel_id: int) -> bool:
        """Deactivate an automation rule."""
        if not self._uses_db:
            return False
        async with self._lock:
            await self._db.deactivate_automation(channel_id)
            return True

    async def set_persona(self, guild_id: int, persona: PersonaProfile) -> None:
        """Set the persona for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.set_persona(
                guild_id=guild_id,
                name=persona.name,
                description=persona.description,
                conversation_style=persona.conversation_style,
                interests=persona.interests,
            )

    async def add_memory(
        self,
        guild_id: int,
        content: str,
        author: str,
        author_id: int,
    ) -> MemoryNote:
        """Add a memory note for a guild."""
        if not self._uses_db:
            # Without database, create in-memory note
            note = MemoryNote(
                memory_id=1,
                guild_id=guild_id,
                content=content,
                author=author,
                author_id=author_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            return note

        async with self._lock:
            record = await self._db.add_memory(
                guild_id=guild_id,
                content=content,
                author=author,
                author_id=author_id,
            )
            note = MemoryNote(
                memory_id=record["memory_id"],
                guild_id=record["guild_id"],
                content=record["content"],
                author=record["author_name"],
                author_id=record["author_id"],
                created_at=record["created_at"].isoformat() if record["created_at"] else "",
            )
            return note

    async def list_memories(self, guild_id: int) -> List[MemoryNote]:
        """List all memories for a guild."""
        if not self._uses_db:
            return []
        async with self._lock:
            memories_rows = await self._db.fetch_memories(guild_id=guild_id)
            memories: List[MemoryNote] = []
            for row in memories_rows:
                mapping = dict(row)
                created = mapping.get("created_at")
                memories.append(
                    MemoryNote(
                        memory_id=mapping.get("memory_id"),
                        guild_id=mapping.get("guild_id"),
                        content=mapping.get("content", ""),
                        author=mapping.get("author_name", "Unknown"),
                        author_id=mapping.get("author_id", 0),
                        created_at=created.isoformat()
                        if isinstance(created, datetime)
                        else str(created or ""),
                    )
                )
            return memories

    async def remove_memory(self, guild_id: int, memory_id: int) -> bool:
        """Remove a memory from a guild."""
        if not self._uses_db:
            return False
        async with self._lock:
            return await self._db.delete_memory(guild_id, memory_id)

    async def set_dry_run(self, guild_id: int, enabled: bool) -> None:
        """Set dry-run mode for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_guild_config(guild_id=guild_id, dry_run=enabled)

    async def set_proactive_moderation(self, guild_id: int, enabled: bool) -> None:
        """Set proactive moderation mode for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_guild_config(guild_id=guild_id, proactive_moderation=enabled)

    @property
    def built_in_prompt(self) -> Optional[str]:
        """Get the default built-in prompt."""
        return self._default_built_in_prompt

    async def set_built_in_prompt(self, guild_id: int, prompt: Optional[str]) -> None:
        """Set the built-in prompt for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            await self._db.upsert_guild_config(guild_id=guild_id, built_in_prompt=prompt)

    async def set_llm_settings(self, settings: LLMSettings) -> None:
        async with self._lock:
            settings = settings.model_copy()
            self._initial_llm_settings = settings
            if self._uses_db:
                await self._db.set_llm_settings(
                    api_key=settings.api_key,
                    model=settings.model,
                    base_url=settings.base_url,
                )

    # Legacy: command_prefix removed - using slash commands exclusively

    async def set_bot_nickname(self, guild_id: int, nickname: Optional[str]) -> None:
        """Set the bot nickname for a guild."""
        if not self._uses_db:
            return
        async with self._lock:
            cleaned = nickname.strip() if nickname and nickname.strip() else None
            await self._db.upsert_guild_config(guild_id=guild_id, bot_nickname=cleaned)

    @property
    def _uses_db(self) -> bool:
        return self._db is not None and self._db.is_connected


async def fetch_channel_context(channel, message_limit: int = 50, llm_client=None) -> str:
    """Fetch recent messages from a channel and summarize them as context.

    Args:
        channel: Discord channel object
        message_limit: Number of recent messages to fetch (default: 50)
        llm_client: Optional LLM client for summarization

    Returns:
        Summarized string containing key points from recent messages
    """
    import discord

    try:
        messages = []
        async for message in channel.history(limit=message_limit, oldest_first=False):
            # Skip bot messages
            if message.author.bot:
                continue

            # Format message with timestamp and author
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M")
            content = message.content[:500]  # Get more content for better summarization
            if len(message.content) > 500:
                content += "..."
            messages.append(f"[{timestamp}] {message.author.name}: {content}")

        if not messages:
            return "No recent messages found in this channel."

        # Reverse to show chronological order (oldest to newest)
        messages.reverse()

        # Get the raw message text
        raw_messages = "\n".join(messages[-50:])  # Use up to 50 messages for summarization

        # If LLM client is available, summarize the messages
        if llm_client:
            try:
                from .llm import LLMUnavailable

                summary_prompt = f"""Summarize the following Discord channel messages into a concise overview.
Focus on:
- Main topics of discussion
- Key decisions or announcements
- Important rules or guidelines mentioned
- Common questions or concerns
- Overall channel purpose and activity

Keep the summary under 300 words.

Messages:
{raw_messages}

Provide a clear, factual summary:"""

                result = await llm_client.run(
                    [{"role": "user", "content": summary_prompt}],
                    max_tokens=500,
                )

                summary = result.get("message", {}).get("content", "").strip()
                if summary:
                    return summary

            except LLMUnavailable:
                # Fall back to raw messages if LLM unavailable
                pass
            except Exception as e:
                # Fall back to raw messages on any error
                import logging

                logging.getLogger(__name__).warning(f"Failed to summarize channel context: {e}")

        # Fallback: return condensed version without LLM summarization
        # Just show the last 15 messages
        return "\n".join(messages[-15:])

    except discord.Forbidden:
        return "Unable to read message history (missing permissions)."
    except Exception as e:
        return f"Error fetching messages: {str(e)}"


def format_context_channels(channels: Dict[int, ContextChannel]) -> str:
    """Helper to stringify configured context channels for prompts."""

    if not channels:
        return "No context channels configured yet."

    lines = [
        f"- #{ctx.label} (id={channel_id}): {ctx.notes or 'No notes provided.'}"
        for channel_id, ctx in channels.items()
    ]
    return "\n".join(lines)
