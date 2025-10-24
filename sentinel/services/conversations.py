"""Conversation tracking and context management for natural bot interactions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import discord

from ..db import Database

logger = logging.getLogger(__name__)

# Keywords that signal the user wants to end the conversation
EXIT_KEYWORDS = [
    "nevermind",
    "never mind",
    "stop",
    "quit",
    "cancel",
    "forget it",
    "ignore that",
    "not you",
    "wasn't talking to you",
]


@dataclass
class ConversationContext:
    """Active conversation details."""

    conversation_id: int
    participants: list[int]
    thread_id: Optional[int]
    last_activity: datetime
    message_history: list[dict]


class ConversationManager:
    """Manages conversational context and threading logic."""

    def __init__(self, database: Database, bot_user_id: int):
        self._db = database
        self._bot_user_id = bot_user_id

    async def should_respond(
        self,
        message: discord.Message,
        bot_mentioned: bool,
    ) -> tuple[bool, Optional[int]]:
        """
        Determine if the bot should respond to a message.

        Returns:
            (should_respond, conversation_id) tuple
        """
        if message.author.bot:
            return False, None

        # Always respond if bot is mentioned
        if bot_mentioned:
            return True, None

        # Check if message is in a thread
        thread_id = message.channel.id if isinstance(message.channel, discord.Thread) else None

        # If in a thread, check if we have an active conversation for it
        if thread_id:
            conv = await self._db.find_active_conversation(
                guild_id=message.guild.id,
                channel_id=message.channel.parent.id
                if hasattr(message.channel, "parent")
                else message.channel.id,
                user_id=message.author.id,
                thread_id=thread_id,
            )
            if conv:
                return True, conv["conversation_id"]

        # Check if user mentions other users (not the bot)
        # If they mention someone else, it's a new/different conversation
        other_user_mentions = [
            u for u in message.mentions if u.id != self._bot_user_id and u.id != message.author.id
        ]
        if other_user_mentions:
            # User is talking to someone else, not continuing with the bot
            return False, None

        # Check if user has a RECENT conversation (within 1 minute for quick continuation)
        conv = await self._db.find_active_conversation(
            guild_id=message.guild.id,
            channel_id=message.channel.id if not thread_id else message.channel.parent.id,
            user_id=message.author.id,
            thread_id=thread_id,
        )

        if conv:
            # Check how recent the last activity was
            last_activity = conv.get("last_activity_at")
            if last_activity:
                # Ensure timezone aware
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)
                time_since_last = (now - last_activity).total_seconds()

                logger.debug(
                    f"Conversation {conv.get('conversation_id')}: last_activity={last_activity}, "
                    f"now={now}, time_since_last={time_since_last:.1f}s"
                )

                # Only continue if within 1 minute (60 seconds)
                if time_since_last > 60:
                    logger.debug(
                        f"Conversation too old ({time_since_last:.1f}s > 60s), not continuing"
                    )
                    return False, None

            # Check for exit keywords
            if self._contains_exit_keyword(message.content):
                await self._db.end_conversation(conv["conversation_id"])
                return False, None

            # Continue the conversation
            logger.debug(f"Continuing conversation {conv.get('conversation_id')}")
            return True, conv["conversation_id"]

        return False, None

    async def start_or_continue_conversation(
        self,
        message: discord.Message,
        conversation_id: Optional[int] = None,
    ) -> int:
        """
        Start a new conversation or continue an existing one.

        Returns the conversation_id.
        """
        thread_id = message.channel.id if isinstance(message.channel, discord.Thread) else None
        channel_id = message.channel.parent.id if thread_id else message.channel.id

        if conversation_id is None:
            # Start new conversation
            conversation_id = await self._db.start_conversation(
                guild_id=message.guild.id,
                channel_id=channel_id,
                starter_user_id=message.author.id,
                starter_message_id=message.id,
                thread_id=thread_id,
            )
        else:
            # Add user as participant if not already
            await self._db.add_conversation_participant(conversation_id, message.author.id)

        # Store the user's message
        await self._db.add_conversation_message(
            conversation_id=conversation_id,
            message_id=message.id,
            author_id=message.author.id,
            author_name=str(message.author),
            content=message.content,
            is_bot=False,
        )

        return conversation_id

    async def record_bot_response(
        self,
        conversation_id: int,
        message: discord.Message,
    ) -> None:
        """Record the bot's response in the conversation."""
        await self._db.add_conversation_message(
            conversation_id=conversation_id,
            message_id=message.id,
            author_id=self._bot_user_id,
            author_name=str(message.author),
            content=message.content,
            is_bot=True,
        )

    async def get_conversation_history(
        self,
        conversation_id: int,
        limit: int = 10,
    ) -> list[dict]:
        """Get recent messages from a conversation for context."""
        return await self._db.get_conversation_messages(conversation_id, limit)

    async def should_use_thread(
        self,
        channel: discord.abc.MessageableChannel,
        lookback_minutes: int = 10,
    ) -> bool:
        """
        Decide if we should reply in a thread based on channel activity.

        A channel is considered "busy" if it has had multiple users post
        within the lookback period.
        """
        if isinstance(channel, discord.Thread):
            # Already in a thread
            return False

        try:
            # Look at recent messages
            messages = []
            async for msg in channel.history(limit=20):
                age_minutes = (datetime.now(timezone.utc) - msg.created_at).total_seconds() / 60
                if age_minutes > lookback_minutes:
                    break
                messages.append(msg)

            # Count unique authors (excluding bots)
            unique_authors = set(m.author.id for m in messages if not m.author.bot)

            # If 3+ people have posted recently, it's busy
            return len(unique_authors) >= 3

        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not check channel history for thread decision")
            return False

    async def handle_mention_tracking(
        self,
        message: discord.Message,
        conversation_id: int,
    ) -> None:
        """Track when users mention each other to join conversations."""
        for mentioned_user in message.mentions:
            if mentioned_user.id != self._bot_user_id and mentioned_user.id != message.author.id:
                await self._db.add_conversation_participant(conversation_id, mentioned_user.id)

    def _contains_exit_keyword(self, content: str) -> bool:
        """Check if message contains an exit keyword."""
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in EXIT_KEYWORDS)

    async def cleanup_old_conversations(self) -> int:
        """Clean up conversations older than 24 hours."""
        return await self._db.cleanup_stale_conversations(max_age_hours=24)
