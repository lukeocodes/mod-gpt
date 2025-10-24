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
    """Thread-safe state manager backed by database."""

    def __init__(
        self,
        database: Optional[Database] = None,
        built_in_prompt: Optional[str] = None,
        initial_llm_settings: Optional[LLMSettings] = None,
    ):
        self._lock = asyncio.Lock()
        self._db = database
        self._built_in_prompt = built_in_prompt
        initial_llm = (initial_llm_settings or LLMSettings()).model_copy()
        self._initial_llm_settings = initial_llm
        initial_prompt = built_in_prompt
        self._state = BotState(built_in_prompt=initial_prompt, llm=initial_llm.model_copy())

    async def load(self) -> None:
        """Load state from persistent storage if available."""

        async with self._lock:
            if await self._try_load_from_db():
                return

    async def save(self) -> None:
        """Compatibility hook; state writes happen immediately on mutation."""

        async with self._lock:
            if not self._uses_db:
                return

    async def get_state(self) -> BotState:
        async with self._lock:
            self._state.built_in_prompt = self._built_in_prompt
            return BotState.model_validate(self._state.model_dump())

    async def add_context_channel(self, channel: ContextChannel) -> None:
        async with self._lock:
            self._state.context_channels[channel.channel_id] = channel
            if self._uses_db:
                await self._db.upsert_context_channel(
                    channel_id=channel.channel_id,
                    label=channel.label,
                    notes=channel.notes,
                    recent_messages=channel.recent_messages,
                    last_fetched=channel.last_fetched,
                )
            await self._write_locked()

    async def remove_context_channel(self, channel_id: int) -> bool:
        async with self._lock:
            removed = self._state.context_channels.pop(channel_id, None) is not None
            if removed:
                if self._uses_db:
                    await self._db.delete_context_channel(channel_id)
                await self._write_locked()
            return removed

    async def refresh_context_channel(self, channel_id: int, bot, llm_client) -> bool:
        """Refresh the content summary for a specific context channel.

        Args:
            channel_id: Discord channel ID to refresh
            bot: Discord bot instance to fetch the channel
            llm_client: LLM client for summarization

        Returns:
            True if refreshed successfully, False if channel not found
        """
        async with self._lock:
            if channel_id not in self._state.context_channels:
                return False

            ctx = self._state.context_channels[channel_id]

        # Fetch channel from Discord (outside the lock to avoid blocking)
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                return False

            from datetime import datetime
            from datetime import timezone as tz

            recent_messages = await fetch_channel_context(
                channel, message_limit=50, llm_client=llm_client
            )

            # Update with new content
            updated_channel = ContextChannel(
                channel_id=ctx.channel_id,
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
        """Refresh all context channels at startup or on-demand.

        Args:
            bot: Discord bot instance
            llm_client: LLM client for summarization

        Returns:
            Number of channels successfully refreshed
        """
        import logging

        logger = logging.getLogger(__name__)

        state = await self.get_state()
        if not state.context_channels:
            return 0

        refreshed = 0
        for channel_id in list(state.context_channels.keys()):
            try:
                if await self.refresh_context_channel(channel_id, bot, llm_client):
                    refreshed += 1
                    logger.info(f"Refreshed context channel {channel_id}")
            except Exception as e:
                logger.warning(f"Failed to refresh context channel {channel_id}: {e}")

        logger.info(f"Refreshed {refreshed}/{len(state.context_channels)} context channels")
        return refreshed

    async def set_logs_channel(self, channel_id: Optional[int]) -> None:
        async with self._lock:
            self._state.logs_channel_id = channel_id
            if self._uses_db:
                await self._db.set_logs_channel(channel_id)
            await self._write_locked()

    async def upsert_automation(self, rule: AutomationRule) -> None:
        async with self._lock:
            self._state.automations[rule.channel_id] = rule
            if self._uses_db:
                await self._db.upsert_automation(
                    channel_id=rule.channel_id,
                    trigger_summary=rule.trigger_summary,
                    action=rule.action,
                    justification=rule.justification,
                    active=rule.active,
                    keywords=rule.keywords,
                )
            await self._write_locked()

    async def deactivate_automation(self, channel_id: int) -> bool:
        async with self._lock:
            if channel_id not in self._state.automations:
                return False
            self._state.automations[channel_id].active = False
            if self._uses_db:
                await self._db.deactivate_automation(channel_id)
            await self._write_locked()
            return True

    async def set_persona(self, persona: PersonaProfile) -> None:
        async with self._lock:
            self._state.persona = persona
            if self._uses_db:
                await self._db.set_persona(
                    name=persona.name,
                    description=persona.description,
                    conversation_style=persona.conversation_style,
                    interests=persona.interests,
                )
            await self._write_locked()

    async def add_memory(
        self,
        guild_id: int,
        content: str,
        author: str,
        author_id: int,
    ) -> MemoryNote:
        async with self._lock:
            if not self._uses_db:
                memory_id = max((m.memory_id for m in self._state.memories), default=0) + 1
                note = MemoryNote(
                    memory_id=memory_id,
                    guild_id=guild_id,
                    content=content,
                    author=author,
                    author_id=author_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                self._state.memories = [
                    n for n in self._state.memories if n.memory_id != note.memory_id
                ]
                self._state.memories.insert(0, note)
                self._state.memories.sort(key=lambda item: item.created_at, reverse=True)
                return note

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
            self._state.memories = [
                n for n in self._state.memories if n.memory_id != note.memory_id
            ]
            self._state.memories.insert(0, note)
            self._state.memories.sort(key=lambda item: item.created_at, reverse=True)
            return note

    async def list_memories(self, guild_id: int) -> List[MemoryNote]:
        async with self._lock:
            relevant = [note for note in self._state.memories if note.guild_id == guild_id]
            return sorted(relevant, key=lambda note: note.created_at, reverse=True)

    async def remove_memory(self, guild_id: int, memory_id: int) -> bool:
        async with self._lock:
            removed = False
            if self._uses_db:
                removed = await self._db.delete_memory(guild_id, memory_id)
            else:
                removed = any(note.memory_id == memory_id for note in self._state.memories)
            if removed:
                self._state.memories = [
                    note for note in self._state.memories if note.memory_id != memory_id
                ]
            return removed

    async def set_dry_run(self, enabled: bool) -> None:
        async with self._lock:
            self._state.dry_run = enabled
            if self._uses_db:
                await self._db.set_dry_run(enabled)
            await self._write_locked()

    async def set_proactive_moderation(self, enabled: bool) -> None:
        async with self._lock:
            self._state.proactive_moderation = enabled
            # Note: Not currently persisted to database, defaults to True on restart
            # Could be added to DB in future if needed
            await self._write_locked()

    @property
    def built_in_prompt(self) -> Optional[str]:
        return self._built_in_prompt

    async def set_built_in_prompt(self, prompt: Optional[str]) -> None:
        async with self._lock:
            self._built_in_prompt = prompt
            self._state.built_in_prompt = prompt
            if self._uses_db:
                await self._db.set_built_in_prompt(prompt)
            await self._write_locked()

    async def set_llm_settings(self, settings: LLMSettings) -> None:
        async with self._lock:
            settings = settings.model_copy()
            self._initial_llm_settings = settings
            self._state.llm = settings
            if self._uses_db:
                await self._db.set_llm_settings(
                    api_key=settings.api_key,
                    model=settings.model,
                    base_url=settings.base_url,
                )
            await self._write_locked()

    # Legacy: command_prefix removed - using slash commands exclusively

    async def set_bot_nickname(self, nickname: Optional[str]) -> None:
        async with self._lock:
            cleaned = nickname.strip() if nickname and nickname.strip() else None
            self._state.bot_nickname = cleaned
            if self._uses_db:
                await self._db.set_bot_nickname(cleaned)
            await self._write_locked()

    async def _write_locked(self) -> None:
        """Assumes caller holds the lock."""

        if not self._uses_db:
            return

    @property
    def _uses_db(self) -> bool:
        return self._db is not None and self._db.is_connected

    async def _try_load_from_db(self) -> bool:
        if not self._uses_db:
            return False

        context_rows = await self._db.fetch_context_channels()
        persona_row = await self._db.fetch_persona()
        logs_channel_id = await self._db.fetch_logs_channel()
        automation_rows = await self._db.fetch_automations()
        bot_nickname = await self._db.get_bot_nickname()
        memories_rows = await self._db.fetch_memories()
        dry_run_enabled = await self._db.get_dry_run()
        stored_prompt = await self._db.get_built_in_prompt()
        if stored_prompt is None and self._built_in_prompt:
            await self._db.set_built_in_prompt(self._built_in_prompt)
            stored_prompt = self._built_in_prompt
        if stored_prompt is not None:
            self._built_in_prompt = stored_prompt

        stored_llm = await self._db.get_llm_settings()
        llm_settings = LLMSettings(**stored_llm)
        if not llm_settings.api_key and self._initial_llm_settings.api_key:
            await self._db.set_llm_settings(
                api_key=self._initial_llm_settings.api_key,
                model=self._initial_llm_settings.model,
                base_url=self._initial_llm_settings.base_url,
            )
            llm_settings = self._initial_llm_settings
        elif not stored_llm.get("model") and self._initial_llm_settings.model:
            llm_settings.model = self._initial_llm_settings.model
        if not llm_settings.model:
            llm_settings.model = "gpt-4o-mini"

        context_channels = {
            row["channel_id"]: ContextChannel(
                channel_id=row["channel_id"],
                label=row["label"],
                notes=row["notes"],
                recent_messages=row.get("recent_messages"),
                last_fetched=row.get("last_fetched").isoformat()
                if row.get("last_fetched")
                else None,
            )
            for row in context_rows
        }

        persona = PersonaProfile()
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

        llm_settings = llm_settings.model_copy()

        self._state = BotState(
            context_channels=context_channels,
            persona=persona,
            logs_channel_id=logs_channel_id,
            automations=automations,
            bot_nickname=bot_nickname,
            memories=memories,
            dry_run=dry_run_enabled,
            built_in_prompt=self._built_in_prompt,
            llm=llm_settings,
        )
        return True


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
