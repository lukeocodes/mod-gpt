"""Persistent state management for mod-gpt."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .db import Database

DEFAULT_COMMAND_PREFIX = "!modgpt"


class ContextChannel(BaseModel):
    """Reference to a channel containing static guidance."""

    channel_id: int
    label: str
    notes: Optional[str] = None


class PersonaProfile(BaseModel):
    """Persona configuration for the bot."""

    name: str = "ModGPT"
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
    command_prefix: str = DEFAULT_COMMAND_PREFIX
    bot_nickname: Optional[str] = None
    memories: List[MemoryNote] = Field(default_factory=list)
    dry_run: bool = False


class StateStore:
    """Thread-safe state manager backed by database."""

    def __init__(self, database: Optional[Database] = None, built_in_prompt: Optional[str] = None):
        self._lock = asyncio.Lock()
        self._db = database
        self._built_in_prompt = built_in_prompt
        self._state = BotState(built_in_prompt=built_in_prompt)

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
                self._state.memories = [n for n in self._state.memories if n.memory_id != note.memory_id]
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
            self._state.memories = [n for n in self._state.memories if n.memory_id != note.memory_id]
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

    @property
    def built_in_prompt(self) -> Optional[str]:
        return self._built_in_prompt

    async def set_command_prefix(self, prefix: Optional[str]) -> None:
        async with self._lock:
            normalized = (
                prefix.strip()
                if prefix and prefix.strip()
                else DEFAULT_COMMAND_PREFIX
            )
            self._state.command_prefix = normalized
            if self._uses_db:
                db_value = normalized if normalized != DEFAULT_COMMAND_PREFIX else None
                await self._db.set_command_prefix(db_value)
            await self._write_locked()

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
        command_prefix = await self._db.get_command_prefix()
        bot_nickname = await self._db.get_bot_nickname()
        memories_rows = await self._db.fetch_memories()
        dry_run_enabled = await self._db.get_dry_run()

        context_channels = {
            row["channel_id"]: ContextChannel(
                channel_id=row["channel_id"],
                label=row["label"],
                notes=row["notes"],
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
                    created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
                )
            )

        self._state = BotState(
            context_channels=context_channels,
            persona=persona,
            logs_channel_id=logs_channel_id,
            automations=automations,
            command_prefix=command_prefix or DEFAULT_COMMAND_PREFIX,
            bot_nickname=bot_nickname,
            memories=memories,
            dry_run=dry_run_enabled,
            built_in_prompt=self._built_in_prompt,
        )
        return True


def format_context_channels(channels: Dict[int, ContextChannel]) -> str:
    """Helper to stringify configured context channels for prompts."""

    if not channels:
        return "No context channels configured yet."

    lines = [
        f"- #{ctx.label} (id={channel_id}): {ctx.notes or 'No notes provided.'}"
        for channel_id, ctx in channels.items()
    ]
    return "\n".join(lines)
