"""Agent router that delegates Discord events to specialised agents."""

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

from ..db import Database
from ..llm import LLMClient
from ..state import StateStore
from .engagement import EngagementAgent
from .moderation import ModerationAgent


class AgentRouter:
    """Single entry-point for Discord events."""

    def __init__(self, bot: commands.Bot, state: StateStore, llm: LLMClient, database: Database):
        self.moderation = ModerationAgent(bot, state, llm, database)
        self.engagement = EngagementAgent(bot, state, llm, database)

    async def on_message(self, message: discord.Message) -> None:
        await self.moderation.handle_message(message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        await self.moderation.handle_message_edit(before, after)

    async def on_member_join(self, member: discord.Member) -> None:
        await self.moderation.handle_member_join(member)

    async def on_member_remove(self, member: discord.Member) -> None:
        await self.moderation.handle_member_remove(member)

    async def on_scheduled_tick(self, guild: discord.Guild) -> None:
        await self.moderation.handle_scheduled_tick(guild)

    async def spark_conversation(
        self,
        channel: discord.abc.MessageableChannel,
        topic_hint: Optional[str] = None,
        trigger_summary: Optional[str] = None,
    ) -> None:
        await self.engagement.spark_conversation(
            channel=channel, topic_hint=topic_hint, trigger_summary=trigger_summary
        )
