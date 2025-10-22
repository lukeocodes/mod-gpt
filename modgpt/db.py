"""Database integration for persistent moderation records."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class ModerationRecord:
    """Structured data describing a moderation event."""

    guild_id: int
    action_type: str
    summary: str
    channel_id: Optional[int] = None
    target_user_id: Optional[int] = None
    target_username: Optional[str] = None
    reason: Optional[str] = None
    message_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class Database:
    """Thin asyncpg wrapper that initialises tables and writes/reads persistent data."""

    def __init__(self, database_url: Optional[str]):
        self._url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def is_enabled(self) -> bool:
        return bool(self._url)

    async def connect(self) -> None:
        if not self._url:
            logger.info("Database URL not configured; persistent audit logging disabled.")
            return

        try:
            self._pool = await asyncpg.create_pool(self._url, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    create table if not exists moderation_actions (
                        id bigserial primary key,
                        created_at timestamptz not null default now(),
                        guild_id bigint not null,
                        channel_id bigint,
                        action_type text not null,
                        summary text not null,
                        target_user_id bigint,
                        target_username text,
                        reason text,
                        message_id bigint,
                        metadata jsonb
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists context_channels (
                        channel_id bigint primary key,
                        label text not null,
                        notes text
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists automations (
                        channel_id bigint primary key,
                        trigger_summary text not null,
                        action text not null,
                        justification text not null,
                        keywords jsonb not null default '[]'::jsonb,
                        active boolean not null default true
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists bot_config (
                        key text primary key,
                        value jsonb not null
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists persona_profile (
                        id integer primary key default 1,
                        name text not null,
                        description text not null,
                        conversation_style text not null,
                        interests jsonb not null
                    );
                    """
                )
                await conn.execute(
                    """
                    insert into persona_profile (id, name, description, conversation_style, interests)
                    values (
                        1,
                        'ModGPT',
                        'A diligent, fair Discord moderator who values context.',
                        'Friendly, concise, proactive when needed, otherwise quietly attentive.',
                        '[]'::jsonb
                    )
                    on conflict (id) do nothing;
                    """
                )
                await conn.execute(
                    """
                    create table if not exists channel_activity (
                        channel_id bigint primary key,
                        guild_id bigint not null,
                        guild_name text not null,
                        channel_name text not null,
                        last_message_at timestamptz,
                        last_user_message_at timestamptz,
                        last_bot_message_at timestamptz,
                        last_spark_at timestamptz,
                        last_review_at timestamptz,
                        message_count bigint not null default 0,
                        updated_at timestamptz not null default now()
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists member_engagement (
                        member_id bigint not null,
                        guild_id bigint not null,
                        username text not null,
                        joined_at timestamptz not null,
                        welcomed_at timestamptz,
                        primary key (member_id, guild_id)
                    );
                    """
                )
                await conn.execute(
                    """
                    create table if not exists memories (
                        memory_id bigserial primary key,
                        created_at timestamptz not null default now(),
                        guild_id bigint not null,
                        author_id bigint,
                        author_name text,
                        content text not null
                    );
                    """
                )
        except Exception:
            logger.exception("Failed to initialise database connection; audit logging disabled.")
            if self._pool:
                await self._pool.close()
            self._pool = None

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    async def record_moderation(self, record: ModerationRecord) -> None:
        if not self._pool:
            return
        metadata_json = json.dumps(record.metadata) if record.metadata else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into moderation_actions (
                    guild_id,
                    channel_id,
                    action_type,
                    summary,
                    target_user_id,
                    target_username,
                    reason,
                    message_id,
                    metadata
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9);
                """,
                record.guild_id,
                record.channel_id,
                record.action_type,
                record.summary,
                record.target_user_id,
                record.target_username,
                record.reason,
                record.message_id,
                metadata_json,
            )

    async def _get_config_value(self, key: str) -> Optional[Any]:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("select value from bot_config where key = $1;", key)
        if not row:
            return None
        value = row["value"]
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    async def _set_config_value(self, key: str, value: Optional[Dict[str, Any]]) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            if value is None:
                await conn.execute("delete from bot_config where key = $1;", key)
            else:
                await conn.execute(
                    """
                    insert into bot_config (key, value)
                    values ($1, $2::jsonb)
                    on conflict (key)
                    do update set value = excluded.value;
                    """,
                    key,
                    json.dumps(value),
                )

    async def record_channel_activity(
        self,
        guild_id: int,
        guild_name: str,
        channel_id: int,
        channel_name: str,
        *,
        timestamp: Optional[datetime] = None,
        user_message: bool = False,
        bot_message: bool = False,
        spark: bool = False,
        review: bool = False,
    ) -> None:
        if not self._pool:
            return
        ts = timestamp or datetime.utcnow().replace(tzinfo=timezone.utc)
        last_message_at = ts if (user_message or bot_message) else None
        last_user_message_at = ts if user_message else None
        last_bot_message_at = ts if bot_message else None
        last_spark_at = ts if spark else None
        last_review_at = ts if review else None
        message_increment = 1 if user_message else 0
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into channel_activity (
                    channel_id,
                    guild_id,
                    guild_name,
                    channel_name,
                    last_message_at,
                    last_user_message_at,
                    last_bot_message_at,
                    last_spark_at,
                    last_review_at,
                    message_count,
                    updated_at
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
                on conflict (channel_id)
                do update set
                    guild_name = excluded.guild_name,
                    channel_name = excluded.channel_name,
                    last_message_at = greatest(
                        coalesce(channel_activity.last_message_at, excluded.last_message_at),
                        coalesce(excluded.last_message_at, channel_activity.last_message_at)
                    ),
                    last_user_message_at = coalesce(excluded.last_user_message_at, channel_activity.last_user_message_at),
                    last_bot_message_at = coalesce(excluded.last_bot_message_at, channel_activity.last_bot_message_at),
                    last_spark_at = coalesce(excluded.last_spark_at, channel_activity.last_spark_at),
                    last_review_at = coalesce(excluded.last_review_at, channel_activity.last_review_at),
                    message_count = channel_activity.message_count + excluded.message_count,
                    updated_at = now();
                """,
                channel_id,
                guild_id,
                guild_name,
                channel_name,
                last_message_at,
                last_user_message_at,
                last_bot_message_at,
                last_spark_at,
                last_review_at,
                message_increment,
            )

    async def fetch_channel_activity(self, guild_id: int) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                select channel_id,
                       channel_name,
                       last_message_at,
                       last_user_message_at,
                       last_bot_message_at,
                       last_spark_at,
                       last_review_at,
                       message_count,
                       updated_at
                from channel_activity
                where guild_id = $1
                order by last_message_at desc nulls last, channel_name;
                """,
                guild_id,
            )

    async def record_member_join(
        self,
        guild_id: int,
        member_id: int,
        username: str,
        joined_at: datetime,
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into member_engagement (member_id, guild_id, username, joined_at)
                values ($1, $2, $3, $4)
                on conflict (member_id, guild_id)
                do update set
                    username = excluded.username,
                    joined_at = excluded.joined_at
                ;
                """,
                member_id,
                guild_id,
                username,
                joined_at,
            )

    async def mark_member_welcomed(
        self,
        guild_id: int,
        member_id: int,
        welcomed_at: Optional[datetime] = None,
    ) -> None:
        if not self._pool:
            return
        ts = welcomed_at or datetime.utcnow().replace(tzinfo=timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update member_engagement
                set welcomed_at = $3
                where member_id = $1 and guild_id = $2;
                """,
                member_id,
                guild_id,
                ts,
            )

    async def fetch_unwelcomed_members(
        self,
        guild_id: int,
        *,
        max_age: Optional[timedelta] = None,
    ) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        limit_clause = ""
        params: list[Any] = [guild_id]
        if max_age:
            cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - max_age
            limit_clause = "and joined_at >= $2"
            params.append(cutoff)
        query = f"""
            select member_id, username, joined_at
            from member_engagement
            where guild_id = $1
              and welcomed_at is null
              {limit_clause}
            order by joined_at asc;
        """
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *params)

    async def fetch_recent_actions(
        self,
        guild_id: int,
        *,
        limit: int = 10,
    ) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                select created_at,
                       action_type,
                       summary,
                       target_user_id,
                       target_username,
                       channel_id
                from moderation_actions
                where guild_id = $1
                order by created_at desc
                limit $2;
                """,
                guild_id,
                limit,
            )

    async def fetch_context_channels(self) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                "select channel_id, label, notes from context_channels order by channel_id;"
            )

    async def upsert_context_channel(
        self, channel_id: int, label: str, notes: Optional[str]
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into context_channels (channel_id, label, notes)
                values ($1, $2, $3)
                on conflict (channel_id)
                do update set label = excluded.label, notes = excluded.notes;
                """,
                channel_id,
                label,
                notes,
            )

    async def delete_context_channel(self, channel_id: int) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("delete from context_channels where channel_id = $1;", channel_id)

    async def fetch_logs_channel(self) -> Optional[int]:
        value = await self._get_config_value("logs_channel_id")
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("channel_id")
        if isinstance(value, int):
            return value
        return None

    async def set_logs_channel(self, channel_id: Optional[int]) -> None:
        payload = {"channel_id": channel_id} if channel_id is not None else None
        await self._set_config_value("logs_channel_id", payload)

    async def fetch_persona(self) -> Optional[asyncpg.Record]:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                """
                select name, description, conversation_style, interests
                from persona_profile
                where id = 1;
                """
            )

    async def set_persona(
        self,
        name: str,
        description: str,
        conversation_style: str,
        interests: list[str],
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into persona_profile (id, name, description, conversation_style, interests)
                values (1, $1, $2, $3, $4::jsonb)
                on conflict (id)
                do update set
                    name = excluded.name,
                    description = excluded.description,
                    conversation_style = excluded.conversation_style,
                    interests = excluded.interests;
                """,
                name,
                description,
                conversation_style,
                json.dumps(interests),
            )

    async def fetch_automations(self) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                select channel_id, trigger_summary, action, justification, keywords, active
                from automations
                order by channel_id;
                """
            )

    async def upsert_automation(
        self,
        channel_id: int,
        trigger_summary: str,
        action: str,
        justification: str,
        active: bool = True,
        keywords: Optional[List[str]] = None,
    ) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into automations (channel_id, trigger_summary, action, justification, keywords, active)
                values ($1, $2, $3, $4, $5::jsonb, $6)
                on conflict (channel_id)
                do update set
                    trigger_summary = excluded.trigger_summary,
                    action = excluded.action,
                    justification = excluded.justification,
                    keywords = excluded.keywords,
                    active = excluded.active;
                """,
                channel_id,
                trigger_summary,
                action,
                justification,
                json.dumps(keywords or []),
                active,
            )

    async def deactivate_automation(self, channel_id: int) -> None:
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "update automations set active = false where channel_id = $1;",
                channel_id,
            )

    async def get_command_prefix(self) -> Optional[str]:
        value = await self._get_config_value("command_prefix")
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("prefix")
        if isinstance(value, str):
            return value
        return None

    async def set_command_prefix(self, prefix: Optional[str]) -> None:
        payload = {"prefix": prefix} if prefix is not None else None
        await self._set_config_value("command_prefix", payload)

    async def get_bot_nickname(self) -> Optional[str]:
        value = await self._get_config_value("bot_nickname")
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get("nickname")
        if isinstance(value, str):
            return value
        return None

    async def set_bot_nickname(self, nickname: Optional[str]) -> None:
        payload = {"nickname": nickname} if nickname is not None else None
        await self._set_config_value("bot_nickname", payload)

    async def get_dry_run(self) -> bool:
        value = await self._get_config_value("dry_run")
        if isinstance(value, dict):
            return bool(value.get("enabled", False))
        if isinstance(value, bool):
            return value
        return False

    async def set_dry_run(self, enabled: bool) -> None:
        payload = {"enabled": enabled}
        await self._set_config_value("dry_run", payload)

    async def add_memory(
        self,
        guild_id: int,
        content: str,
        author: str,
        author_id: int,
    ) -> asyncpg.Record:
        if not self._pool:
            raise RuntimeError("Database not configured")
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                """
                insert into memories (guild_id, author_id, author_name, content)
                values ($1, $2, $3, $4)
                returning memory_id, guild_id, author_id, author_name, content, created_at;
                """,
                guild_id,
                author_id,
                author,
                content,
            )

    async def fetch_memories(self) -> list[asyncpg.Record]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                """
                select memory_id, guild_id, author_id, author_name, content, created_at
                from memories
                order by created_at desc;
                """
            )

    async def delete_memory(self, guild_id: int, memory_id: int) -> bool:
        if not self._pool:
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "delete from memories where memory_id = $1 and guild_id = $2;",
                memory_id,
                guild_id,
            )
        return result.endswith(" 1")
