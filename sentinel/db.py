"""Database integration for persistent moderation records."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import certifi
import psycopg2
from psycopg2.extensions import connection as PsycopgConnection
from psycopg2.extras import RealDictCursor

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
    """Thread-safe psycopg2 wrapper that initialises tables and executes queries via asyncio."""

    def __init__(self, database_url: Optional[str]):
        self._url = database_url
        self._conn: Optional[PsycopgConnection] = None
        self._lock = asyncio.Lock()

    @property
    def is_enabled(self) -> bool:
        return bool(self._url)

    async def connect(self) -> None:
        if not self._url:
            logger.info("Database URL not configured; persistent audit logging disabled.")
            return
        async with self._lock:
            if self._conn and not self._conn.closed:
                return
            try:
                ssl_args = {}
                if "supabase.co" in self._url:
                    ssl_args = {"sslmode": "verify-full", "sslrootcert": certifi.where()}
                self._conn = await asyncio.to_thread(
                    lambda: psycopg2.connect(dsn=self._url, **ssl_args)
                )
                await self._initialise_schema()
            except Exception:
                logger.exception(
                    "Failed to initialise database connection; audit logging disabled."
                )
                if self._conn and not self._conn.closed:
                    self._conn.close()
                self._conn = None

    async def close(self) -> None:
        async with self._lock:
            if self._conn and not self._conn.closed:
                await asyncio.to_thread(self._conn.close)
            self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    async def _ensure_connection(self) -> Optional[PsycopgConnection]:
        if not self._url:
            return None
        if not self.is_connected:
            await self.connect()
        return self._conn

    async def _initialise_schema(self) -> None:
        if self._conn is None:
            return
        await asyncio.to_thread(self._run_initial_schema_statements, self._conn)

    def _run_initial_schema_statements(self, conn: PsycopgConnection) -> None:
        with conn, conn.cursor() as cur:
            cur.execute(
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
            cur.execute(
                """
                create table if not exists context_channels (
                    channel_id bigint primary key,
                    label text not null,
                    notes text
                );
                """
            )
            # Migration: Add recent_messages and last_fetched columns if they don't exist
            cur.execute(
                """
                alter table context_channels 
                add column if not exists recent_messages text,
                add column if not exists last_fetched timestamptz;
                """
            )
            cur.execute(
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
            cur.execute(
                """
                create table if not exists bot_config (
                    key text primary key,
                    value jsonb not null
                );
                """
            )
            # Heuristic rules table - ALL rules come from LLM, stored in DB
            cur.execute(
                """
                create table if not exists heuristic_rules (
                    id bigserial primary key,
                    guild_id bigint,
                    rule_type text not null,
                    pattern text not null,
                    pattern_type text not null,
                    confidence float not null default 0.8,
                    severity text not null default 'medium',
                    reason text,
                    
                    created_by text not null default 'llm',
                    created_at timestamptz not null default now(),
                    last_used_at timestamptz,
                    use_count integer not null default 0,
                    false_positive_count integer not null default 0,
                    
                    active boolean not null default true,
                    requires_review boolean not null default false,
                    
                    version integer not null default 1,
                    replaced_by integer references heuristic_rules(id),
                    
                    constraint unique_pattern unique (guild_id, pattern, pattern_type)
                );
                """
            )
            cur.execute(
                """
                create index if not exists idx_heuristic_rules_active 
                on heuristic_rules(guild_id, active) where active = true;
                """
            )
            cur.execute(
                """
                create index if not exists idx_heuristic_rules_type 
                on heuristic_rules(rule_type, pattern_type);
                """
            )
            # Heuristic feedback table - track performance
            cur.execute(
                """
                create table if not exists heuristic_feedback (
                    id bigserial primary key,
                    rule_id integer not null references heuristic_rules(id),
                    message_id bigint not null,
                    guild_id bigint not null,
                    
                    matched boolean not null,
                    action_taken text,
                    
                    correct boolean,
                    feedback_source text,
                    feedback_notes text,
                    
                    created_at timestamptz not null default now()
                );
                """
            )
            cur.execute(
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
            cur.execute(
                """
                insert into persona_profile (id, name, description, conversation_style, interests)
                values (
                    1,
                    'Sentinel',
                    'A diligent, fair Discord moderator who values context.',
                    'Friendly, concise, proactive when needed, otherwise quietly attentive.',
                    '[]'::jsonb
                )
                on conflict (id) do nothing;
                """
            )
            cur.execute(
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
            cur.execute(
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
            cur.execute(
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
            cur.execute(
                """
                create table if not exists conversation_threads (
                    conversation_id bigserial primary key,
                    guild_id bigint not null,
                    channel_id bigint not null,
                    thread_id bigint,
                    starter_user_id bigint not null,
                    starter_message_id bigint not null,
                    created_at timestamptz not null default now(),
                    last_activity_at timestamptz not null default now(),
                    active boolean not null default true,
                    participants jsonb not null default '[]'::jsonb
                );
                """
            )
            cur.execute(
                """
                create index if not exists idx_conversation_threads_active
                on conversation_threads(guild_id, channel_id, active, last_activity_at desc)
                where active = true;
                """
            )
            cur.execute(
                """
                create table if not exists conversation_messages (
                    message_id bigint primary key,
                    conversation_id bigint not null references conversation_threads(conversation_id) on delete cascade,
                    author_id bigint not null,
                    author_name text not null,
                    content text not null,
                    created_at timestamptz not null default now(),
                    is_bot boolean not null default false
                );
                """
            )
            cur.execute(
                """
                create index if not exists idx_conversation_messages_conversation
                on conversation_messages(conversation_id, created_at);
                """
            )

    async def record_moderation(self, record: ModerationRecord) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        metadata_json = json.dumps(record.metadata) if record.metadata else None
        await asyncio.to_thread(
            self._execute,
            conn,
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
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                record.guild_id,
                record.channel_id,
                record.action_type,
                record.summary,
                record.target_user_id,
                record.target_username,
                record.reason,
                record.message_id,
                metadata_json,
            ),
        )

    async def _get_config_value(self, key: str) -> Optional[Any]:
        row = await self._fetchone("select value from bot_config where key = %s;", (key,))
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
        if value is None:
            await self._execute_async("delete from bot_config where key = %s;", (key,))
            return
        await self._execute_async(
            """
            insert into bot_config (key, value)
            values (%s, %s::jsonb)
            on conflict (key)
            do update set value = excluded.value;
            """,
            (key, json.dumps(value)),
        )

    async def _execute_async(self, query: str, params: tuple[Any, ...] | tuple[()]) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        await asyncio.to_thread(self._execute, conn, query, params)

    def _execute(
        self, conn: PsycopgConnection, query: str, params: tuple[Any, ...] | tuple[()]
    ) -> None:
        with conn, conn.cursor() as cur:
            cur.execute(query, params)

    async def _fetchall(
        self, query: str, params: tuple[Any, ...] | tuple[()]
    ) -> list[dict[str, Any]]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        return await asyncio.to_thread(self._fetchall_sync, conn, query, params)

    def _fetchall_sync(
        self, conn: PsycopgConnection, query: str, params: tuple[Any, ...] | tuple[()]
    ) -> list[dict[str, Any]]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(row) for row in rows]

    async def _fetchone(
        self, query: str, params: tuple[Any, ...] | tuple[()]
    ) -> Optional[dict[str, Any]]:
        conn = await self._ensure_connection()
        if conn is None:
            return None
        return await asyncio.to_thread(self._fetchone_sync, conn, query, params)

    def _fetchone_sync(
        self, conn: PsycopgConnection, query: str, params: tuple[Any, ...] | tuple[()]
    ) -> Optional[dict[str, Any]]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None

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
        conn = await self._ensure_connection()
        if conn is None:
            return
        ts = timestamp or datetime.utcnow().replace(tzinfo=timezone.utc)
        last_message_at = ts if (user_message or bot_message) else None
        last_user_message_at = ts if user_message else None
        last_bot_message_at = ts if bot_message else None
        last_spark_at = ts if spark else None
        last_review_at = ts if review else None
        message_increment = 1 if user_message else 0
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
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
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
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
                    (
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
                    ),
                )

    async def fetch_channel_activity(self, guild_id: int) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
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
                    where guild_id = %s
                    order by last_message_at desc nulls last, channel_name;
                    """,
                    (guild_id,),
                )
                return cur.fetchall()

    async def record_member_join(
        self,
        guild_id: int,
        member_id: int,
        username: str,
        joined_at: datetime,
    ) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                insert into member_engagement (member_id, guild_id, username, joined_at)
                values (%s, %s, %s, %s)
                on conflict (member_id, guild_id)
                do update set
                    username = excluded.username,
                    joined_at = excluded.joined_at
                ;
                """,
                    (member_id, guild_id, username, joined_at),
                )

    async def mark_member_welcomed(
        self,
        guild_id: int,
        member_id: int,
        welcomed_at: Optional[datetime] = None,
    ) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        ts = welcomed_at or datetime.utcnow().replace(tzinfo=timezone.utc)
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
            update member_engagement
            set welcomed_at = %s
            where member_id = %s and guild_id = %s;
            """,
                    (ts, member_id, guild_id),
                )

    async def fetch_unwelcomed_members(
        self,
        guild_id: int,
        *,
        max_age: Optional[timedelta] = None,
    ) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        limit_clause = ""
        params: list[Any] = [guild_id]
        if max_age:
            cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - max_age
            limit_clause = "and joined_at >= %s"
            params.append(cutoff)
        query = f"""
            select member_id, username, joined_at
            from member_engagement
            where guild_id = %s
              and welcomed_at is null
              {limit_clause}
            order by joined_at asc;
        """
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                return cur.fetchall()

    async def fetch_recent_actions(
        self,
        guild_id: int,
        *,
        limit: int = 10,
    ) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    select created_at,
                           action_type,
                           summary,
                           target_user_id,
                           target_username,
                           channel_id
                    from moderation_actions
                    where guild_id = %s
                    order by created_at desc
                    limit %s;
                    """,
                    (guild_id, limit),
                )
                return cur.fetchall()

    async def fetch_context_channels(self) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "select channel_id, label, notes, recent_messages, last_fetched from context_channels order by channel_id;"
                )
                return cur.fetchall()

    async def upsert_context_channel(
        self,
        channel_id: int,
        label: str,
        notes: Optional[str],
        recent_messages: Optional[str] = None,
        last_fetched: Optional[str] = None,
    ) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                insert into context_channels (channel_id, label, notes, recent_messages, last_fetched)
                values (%s, %s, %s, %s, %s)
                on conflict (channel_id)
                do update set label = excluded.label, notes = excluded.notes, 
                              recent_messages = excluded.recent_messages, last_fetched = excluded.last_fetched;
                """,
                    (channel_id, label, notes, recent_messages, last_fetched),
                )

    async def delete_context_channel(self, channel_id: int) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "delete from context_channels where channel_id = %s;",
                    (channel_id,),
                )

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

    async def fetch_persona(self) -> Optional[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return None
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                select name, description, conversation_style, interests
                from persona_profile
                where id = 1;
                """
                )
                return cur.fetchone()

    async def set_persona(
        self,
        name: str,
        description: str,
        conversation_style: str,
        interests: list[str],
    ) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                insert into persona_profile (id, name, description, conversation_style, interests)
                values (1, %s, %s, %s, %s::jsonb)
                on conflict (id)
                do update set
                    name = excluded.name,
                    description = excluded.description,
                    conversation_style = excluded.conversation_style,
                    interests = excluded.interests;
                """,
                    (name, description, conversation_style, json.dumps(interests)),
                )

    async def fetch_automations(self) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                select channel_id, trigger_summary, action, justification, keywords, active
                from automations
                order by channel_id;
                """
                )
                return cur.fetchall()

    async def upsert_automation(
        self,
        channel_id: int,
        trigger_summary: str,
        action: str,
        justification: str,
        active: bool = True,
        keywords: Optional[List[str]] = None,
    ) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                insert into automations (channel_id, trigger_summary, action, justification, keywords, active)
                values (%s, %s, %s, %s, %s::jsonb, %s)
                on conflict (channel_id)
                do update set
                    trigger_summary = excluded.trigger_summary,
                    action = excluded.action,
                    justification = excluded.justification,
                    keywords = excluded.keywords,
                    active = excluded.active;
                """,
                    (
                        channel_id,
                        trigger_summary,
                        action,
                        justification,
                        json.dumps(keywords or []),
                        active,
                    ),
                )

    async def deactivate_automation(self, channel_id: int) -> None:
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "update automations set active = false where channel_id = %s;",
                    (channel_id,),
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

    async def get_built_in_prompt(self) -> Optional[str]:
        value = await self._get_config_value("built_in_prompt")
        if isinstance(value, dict):
            return value.get("prompt")
        if isinstance(value, str):
            return value
        return None

    async def set_built_in_prompt(self, prompt: Optional[str]) -> None:
        payload = {"prompt": prompt} if prompt else None
        await self._set_config_value("built_in_prompt", payload)

    async def get_llm_settings(self) -> Dict[str, Optional[str]]:
        value = await self._get_config_value("llm_settings")
        if isinstance(value, dict):
            return {
                "api_key": value.get("api_key"),
                "model": value.get("model"),
                "base_url": value.get("base_url"),
            }
        return {"api_key": None, "model": None, "base_url": None}

    async def set_llm_settings(
        self,
        *,
        api_key: Optional[str],
        model: Optional[str],
        base_url: Optional[str],
    ) -> None:
        if not api_key and not model and not base_url:
            await self._set_config_value("llm_settings", None)
            return
        payload = {
            "api_key": api_key,
            "model": model,
            "base_url": base_url,
        }
        await self._set_config_value("llm_settings", payload)

    async def add_memory(
        self,
        guild_id: int,
        content: str,
        author: str,
        author_id: int,
    ) -> RealDictCursor:
        conn = await self._ensure_connection()
        if conn is None:
            raise RuntimeError("Database not configured")
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                insert into memories (guild_id, author_id, author_name, content)
                values (%s, %s, %s, %s)
                returning memory_id, guild_id, author_id, author_name, content, created_at;
                """,
                    (guild_id, author_id, author, content),
                )
                return cur.fetchone()

    async def fetch_memories(self) -> list[RealDictCursor]:
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                select memory_id, guild_id, author_id, author_name, content, created_at
                from memories
                order by created_at desc;
                """
                )
                return cur.fetchall()

    async def delete_memory(self, guild_id: int, memory_id: int) -> bool:
        conn = await self._ensure_connection()
        if conn is None:
            return False
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "delete from memories where memory_id = %s and guild_id = %s;",
                    (memory_id, guild_id),
                )
                return cur.rowcount == 1

    async def start_conversation(
        self,
        guild_id: int,
        channel_id: int,
        starter_user_id: int,
        starter_message_id: int,
        thread_id: Optional[int] = None,
    ) -> int:
        """Start a new conversation and return its ID."""
        conn = await self._ensure_connection()
        if conn is None:
            raise RuntimeError("Database not configured")
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    insert into conversation_threads (
                        guild_id, channel_id, thread_id, starter_user_id, starter_message_id, participants
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb)
                    returning conversation_id;
                    """,
                    (
                        guild_id,
                        channel_id,
                        thread_id,
                        starter_user_id,
                        starter_message_id,
                        json.dumps([starter_user_id]),
                    ),
                )
                row = cur.fetchone()
                return row[0] if row else None

    async def add_conversation_participant(self, conversation_id: int, user_id: int) -> None:
        """Add a user to a conversation's participant list if not already present."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update conversation_threads
                    set participants = (
                        select jsonb_agg(distinct value)
                        from jsonb_array_elements(participants || %s::jsonb)
                    ),
                    last_activity_at = now()
                    where conversation_id = %s;
                    """,
                    (json.dumps([user_id]), conversation_id),
                )

    async def add_conversation_message(
        self,
        conversation_id: int,
        message_id: int,
        author_id: int,
        author_name: str,
        content: str,
        is_bot: bool = False,
    ) -> None:
        """Store a message in a conversation."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    insert into conversation_messages (
                        message_id, conversation_id, author_id, author_name, content, is_bot
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (message_id) do nothing;
                    """,
                    (message_id, conversation_id, author_id, author_name, content, is_bot),
                )
                cur.execute(
                    """
                    update conversation_threads
                    set last_activity_at = now()
                    where conversation_id = %s;
                    """,
                    (conversation_id,),
                )

    async def find_active_conversation(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        thread_id: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Find an active conversation for a user in a channel/thread."""
        conn = await self._ensure_connection()
        if conn is None:
            return None
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                # If in a thread, look for conversation by thread_id
                if thread_id:
                    cur.execute(
                        """
                        select conversation_id, participants, thread_id, last_activity_at
                        from conversation_threads
                        where guild_id = %s
                          and thread_id = %s
                          and active = true
                        order by last_activity_at desc
                        limit 1;
                        """,
                        (guild_id, thread_id),
                    )
                else:
                    # Look for recent conversation with this user in the channel
                    cur.execute(
                        """
                        select conversation_id, participants, thread_id, last_activity_at
                        from conversation_threads
                        where guild_id = %s
                          and channel_id = %s
                          and thread_id is null
                          and active = true
                          and last_activity_at > now() - interval '30 minutes'
                          and participants ? %s
                        order by last_activity_at desc
                        limit 1;
                        """,
                        (guild_id, channel_id, str(user_id)),
                    )
                row = cur.fetchone()
                return dict(row) if row else None

    async def get_conversation_messages(
        self, conversation_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get recent messages from a conversation."""
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    select message_id, author_id, author_name, content, is_bot, created_at
                    from conversation_messages
                    where conversation_id = %s
                    order by created_at desc
                    limit %s;
                    """,
                    (conversation_id, limit),
                )
                rows = cur.fetchall()
                return [dict(row) for row in reversed(rows)]

    async def end_conversation(self, conversation_id: int) -> None:
        """Mark a conversation as inactive."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update conversation_threads
                    set active = false
                    where conversation_id = %s;
                    """,
                    (conversation_id,),
                )

    async def cleanup_stale_conversations(self, max_age_hours: int = 24) -> int:
        """Mark old conversations as inactive and return count affected."""
        conn = await self._ensure_connection()
        if conn is None:
            return 0
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update conversation_threads
                    set active = false
                    where active = true
                      and last_activity_at < now() - interval '%s hours'
                    returning conversation_id;
                    """,
                    (max_age_hours,),
                )
                return cur.rowcount

    # Heuristic Rules Operations

    async def fetch_active_heuristics(
        self,
        guild_id: int,
        min_confidence: float = 0.0,
    ) -> list[RealDictCursor]:
        """Fetch active heuristic rules for a guild."""
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    select id, guild_id, rule_type, pattern, pattern_type, confidence,
                           severity, reason, created_by, created_at, last_used_at,
                           use_count, false_positive_count
                    from heuristic_rules
                    where (guild_id = %s or guild_id is null)
                      and active = true
                      and confidence >= %s
                    order by confidence desc, use_count desc;
                    """,
                    (guild_id, min_confidence),
                )
                return cur.fetchall()

    async def insert_heuristic_rule(
        self,
        guild_id: Optional[int],
        rule_type: str,
        pattern: str,
        pattern_type: str,
        confidence: float,
        severity: str,
        reason: Optional[str],
        created_by: str = "llm",
    ) -> tuple[int, bool]:
        """Insert a new heuristic rule and return (ID, is_new).

        Returns:
            tuple[int, bool]: (rule_id, True if newly created, False if already existed)
        """
        conn = await self._ensure_connection()
        if conn is None:
            raise RuntimeError("Database not configured")
        async with self._lock:
            with conn, conn.cursor() as cur:
                # First check if pattern already exists
                cur.execute(
                    """
                    select id, confidence, severity, active
                    from heuristic_rules
                    where guild_id is not distinct from %s
                      and pattern = %s
                      and pattern_type = %s;
                    """,
                    (guild_id, pattern, pattern_type),
                )
                existing = cur.fetchone()

                if existing:
                    existing_id, existing_confidence, existing_severity, is_active = existing
                    scope = "global" if guild_id is None else f"guild {guild_id}"
                    logger.info(
                        "Heuristic already exists (ID: %s, %s): pattern=%r, type=%s, confidence=%.2f, active=%s",
                        existing_id,
                        scope,
                        pattern,
                        pattern_type,
                        existing_confidence,
                        is_active,
                    )

                    # Optionally update confidence/severity if new values are higher
                    if confidence > existing_confidence or (
                        confidence == existing_confidence and severity != existing_severity
                    ):
                        cur.execute(
                            """
                            update heuristic_rules
                            set confidence = greatest(confidence, %s),
                                severity = case
                                    when %s > confidence then %s
                                    else severity
                                end,
                                version = version + 1
                            where id = %s
                            returning id;
                            """,
                            (confidence, confidence, severity, existing_id),
                        )
                        logger.info(
                            "Updated heuristic %s with higher confidence/severity", existing_id
                        )

                    return (existing_id, False)

                # Insert new heuristic
                try:
                    cur.execute(
                        """
                        insert into heuristic_rules (
                            guild_id, rule_type, pattern, pattern_type, confidence,
                            severity, reason, created_by
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s)
                        returning id;
                        """,
                        (
                            guild_id,
                            rule_type,
                            pattern,
                            pattern_type,
                            confidence,
                            severity,
                            reason,
                            created_by,
                        ),
                    )
                    row = cur.fetchone()
                    rule_id = row[0] if row else None
                    scope = "global" if guild_id is None else f"guild {guild_id}"
                    logger.info(
                        "Created new heuristic (ID: %s, %s): pattern=%r, type=%s, confidence=%.2f",
                        rule_id,
                        scope,
                        pattern,
                        pattern_type,
                        confidence,
                    )
                    return (rule_id, True)
                except psycopg2.IntegrityError:
                    # Race condition: pattern was inserted between check and insert
                    conn.rollback()
                    cur.execute(
                        """
                        select id from heuristic_rules
                        where guild_id is not distinct from %s
                          and pattern = %s
                          and pattern_type = %s;
                        """,
                        (guild_id, pattern, pattern_type),
                    )
                    row = cur.fetchone()
                    logger.warning(
                        "Heuristic duplicate detected during insert: %r (%s)", pattern, pattern_type
                    )
                    return (row[0] if row else None, False)

    async def update_heuristic_confidence(self, rule_id: int, adjustment: float) -> None:
        """Adjust confidence score for a heuristic rule."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update heuristic_rules
                    set confidence = greatest(0.0, least(1.0, confidence + %s))
                    where id = %s;
                    """,
                    (adjustment, rule_id),
                )

    async def increment_heuristic_usage(self, rule_id: int) -> None:
        """Increment use count and update last_used_at."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update heuristic_rules
                    set use_count = use_count + 1,
                        last_used_at = now()
                    where id = %s;
                    """,
                    (rule_id,),
                )

    async def increment_false_positive_count(self, rule_id: int) -> None:
        """Increment false positive count for a rule."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update heuristic_rules
                    set false_positive_count = false_positive_count + 1
                    where id = %s;
                    """,
                    (rule_id,),
                )

    async def mark_heuristic_for_review(self, rule_id: int) -> None:
        """Mark a heuristic rule as requiring review."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update heuristic_rules
                    set requires_review = true
                    where id = %s;
                    """,
                    (rule_id,),
                )

    async def disable_heuristic(self, rule_id: int) -> None:
        """Disable a heuristic rule."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update heuristic_rules
                    set active = false
                    where id = %s;
                    """,
                    (rule_id,),
                )

    async def insert_heuristic_feedback(
        self,
        rule_id: int,
        message_id: int,
        guild_id: int,
        matched: bool,
        action_taken: Optional[str],
        correct: Optional[bool] = None,
        feedback_source: Optional[str] = None,
        feedback_notes: Optional[str] = None,
    ) -> None:
        """Record feedback on a heuristic rule match."""
        conn = await self._ensure_connection()
        if conn is None:
            return
        async with self._lock:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    insert into heuristic_feedback (
                        rule_id, message_id, guild_id, matched, action_taken,
                        correct, feedback_source, feedback_notes
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        rule_id,
                        message_id,
                        guild_id,
                        matched,
                        action_taken,
                        correct,
                        feedback_source,
                        feedback_notes,
                    ),
                )

    async def fetch_heuristic_stats(self, rule_id: int) -> Optional[RealDictCursor]:
        """Get statistics for a heuristic rule."""
        conn = await self._ensure_connection()
        if conn is None:
            return None
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    select 
                        hr.*,
                        case when hr.use_count > 0 
                            then hr.false_positive_count::float / hr.use_count 
                            else 0 
                        end as false_positive_rate
                    from heuristic_rules hr
                    where hr.id = %s;
                    """,
                    (rule_id,),
                )
                return cur.fetchone()

    async def fetch_heuristics_for_review(self, guild_id: int) -> list[RealDictCursor]:
        """Fetch heuristics that need review (low confidence or high FP rate)."""
        conn = await self._ensure_connection()
        if conn is None:
            return []
        async with self._lock:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    select 
                        hr.*,
                        case when hr.use_count > 0 
                            then hr.false_positive_count::float / hr.use_count 
                            else 0 
                        end as false_positive_rate
                    from heuristic_rules hr
                    where (hr.guild_id = %s or hr.guild_id is null)
                      and hr.active = true
                      and (
                          hr.requires_review = true
                          or hr.confidence < 0.7
                          or (hr.use_count > 10 and hr.false_positive_count::float / hr.use_count > 0.2)
                      )
                    order by hr.last_used_at desc nulls last
                    limit 20;
                    """,
                    (guild_id,),
                )
                return cur.fetchall()
