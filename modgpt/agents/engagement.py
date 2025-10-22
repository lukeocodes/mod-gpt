"""Engagement agent used for persona-driven conversation starters."""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Dict, Optional

import discord
from discord.ext import commands

from ..db import Database
from ..llm import LLMClient, LLMUnavailable
from ..prompts import build_system_prompt
from ..state import StateStore

logger = logging.getLogger(__name__)


class EngagementAgent:
    """Generates persona-aligned conversation starters."""

    def __init__(self, bot: commands.Bot, state: StateStore, llm: LLMClient, database: Database):
        self._bot = bot
        self._state = state
        self._llm = llm
        self._db = database

    async def spark_conversation(
        self,
        channel: discord.abc.MessageableChannel,
        topic_hint: Optional[str] = None,
        trigger_summary: Optional[str] = None,
    ) -> None:
        state = await self._state.get_state()
        system_prompt = build_system_prompt(state, built_in_prompt=state.built_in_prompt) + "\nRespond with a short conversation opener."
        persona = state.persona
        payload: Dict[str, str] = {
            "objective": "Start a conversation in the channel while aligning with persona interests.",
            "persona_interests": ", ".join(persona.interests) or "None specified",
        }
        if topic_hint:
            payload["topic_hint"] = topic_hint
        if trigger_summary:
            payload["trigger_summary"] = trigger_summary

        user_message = "\n".join(f"{key}: {value}" for key, value in payload.items())

        try:
            choice = await self._llm.run(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                tools=None,
                max_tokens=400,
            )
            content = choice.get("message", {}).get("content")
        except LLMUnavailable:
            content = None
        except Exception:
            logger.exception("Engagement agent failed to generate conversation")
            content = None

        if not content:
            fallback_topic = topic_hint or persona.interests[:1] or ["community updates"]
            if isinstance(fallback_topic, list):
                fallback = fallback_topic[0]
            else:
                fallback = fallback_topic
            content = f"Hey everyone! Curious to hear your thoughts about {fallback} today."

        message = await channel.send(content)
        await self._record_spark_activity(channel, message)

    async def _record_spark_activity(
        self, channel: discord.abc.MessageableChannel, message: discord.Message
    ) -> None:
        if not self._db or not self._db.is_enabled:
            return
        if not isinstance(channel, discord.abc.GuildChannel):
            return
        guild = channel.guild
        timestamp = message.created_at.replace(tzinfo=timezone.utc) if message.created_at else discord.utils.utcnow().replace(tzinfo=timezone.utc)
        await self._db.record_channel_activity(
            guild_id=guild.id,
            guild_name=guild.name,
            channel_id=channel.id,
            channel_name=getattr(channel, "name", str(channel.id)),
            timestamp=timestamp,
            bot_message=True,
            spark=True,
        )
        if isinstance(channel, discord.Thread) and channel.parent:
            parent = channel.parent
            await self._db.record_channel_activity(
                guild_id=guild.id,
                guild_name=guild.name,
                channel_id=parent.id,
                channel_name=getattr(parent, "name", str(parent.id)),
                timestamp=timestamp,
                bot_message=True,
                spark=True,
            )
