"""Moderation agent that reasons over Discord events."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

from ..db import Database, ModerationRecord
from ..llm import LLMClient, LLMUnavailable
from ..prompts import build_event_prompt, build_system_prompt
from ..state import AutomationRule, BotState, StateStore

logger = logging.getLogger(__name__)


MODERATION_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "take_moderation_action",
            "description": "Take an administrative action like deleting a message, warning, timeout, kick, or ban.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["delete_message", "warn", "timeout", "kick", "ban", "flag"],
                    },
                    "target_user_id": {"type": "string", "description": "Discord user ID."},
                    "reason": {
                        "type": "string",
                        "description": "Short justification referencing rules or server guidance.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Timeout duration in minutes when using timeout action.",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message to delete or reference in logs.",
                    },
                },
                "required": ["action", "target_user_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a text response in channel or DM to steer conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel to send the message. Use message channel when intervening publicly.",
                    },
                    "message": {"type": "string"},
                    "is_dm": {
                        "type": "boolean",
                        "description": "True to DM the target user from the moderation context.",
                        "default": False,
                    },
                    "target_user_id": {
                        "type": "string",
                        "description": "Required when sending a DM.",
                    },
                    "reply_to_message_id": {
                        "type": "string",
                        "description": "Optional message ID to reply to or use when threading.",
                    },
                    "reply_in_thread": {
                        "type": "boolean",
                        "description": "Set true to respond in a dedicated thread if available.",
                        "default": False,
                    },
                    "thread_name": {
                        "type": "string",
                        "description": "Optional name when creating a new thread.",
                    },
                    "context_tag": {
                        "type": "string",
                        "description": "Optional tag describing the purpose of the message (e.g. spark, welcome, review, reminder).",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escalate a situation to human moderators with a summary when unsure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "default": "medium",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


@dataclass
class EventContext:
    """Context passed to tool execution."""

    bot: commands.Bot
    guild: discord.Guild
    channel: Optional[discord.abc.GuildChannel] = None
    message: Optional[discord.Message] = None
    member: Optional[discord.Member] = None
    recent_messages: Optional[List[Dict[str, Any]]] = None
    reply_to: Optional[discord.Message] = None
    dry_run: bool = False


class ModerationAgent:
    """Coordinates moderation reasoning and tool execution."""

    def __init__(self, bot: commands.Bot, state: StateStore, llm: LLMClient, database: Database):
        self._bot = bot
        self._state = state
        self._llm = llm
        self._db = database

    async def handle_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return
        await self._record_channel_activity_message(message)

        reply_target = await self._resolve_reply_context(message)
        recent_messages, recent_summary = await self._gather_recent_messages(
            message.channel, include_current=True, current_message_id=message.id
        )

        state = await self._state.get_state()
        context = EventContext(
            bot=self._bot,
            guild=message.guild,
            channel=message.channel,
            message=message,
            recent_messages=recent_messages,
            reply_to=reply_target,
            dry_run=state.dry_run,
        )

        if await self._apply_automation_if_needed(message, state):
            return

        payload = self._build_message_payload(message, state, recent_summary, reply_target)
        await self._reason_about_event("message_create", payload, state, context)

    async def handle_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if after.author.bot:
            return
        if after.guild is None:
            return

        reply_target = await self._resolve_reply_context(after)
        recent_messages, recent_summary = await self._gather_recent_messages(
            after.channel, include_current=False, current_message_id=after.id
        )
        state = await self._state.get_state()
        context = EventContext(
            bot=self._bot,
            guild=after.guild,
            channel=after.channel,
            message=after,
            recent_messages=recent_messages,
            reply_to=reply_target,
            dry_run=state.dry_run,
        )
        payload = self._build_message_edit_payload(before, after, state, recent_summary, reply_target)
        await self._reason_about_event("message_edit", payload, state, context)

    async def handle_member_join(self, member: discord.Member) -> None:
        state = await self._state.get_state()
        guild = member.guild
        context = EventContext(bot=self._bot, guild=guild, member=member, dry_run=state.dry_run)
        payload = {
            "member": f"{member} ({member.id})",
            "created_at": member.created_at.isoformat() if member.created_at else "unknown",
            "joined_at": member.joined_at.isoformat() if member.joined_at else "pending",
            "roles": ", ".join(role.name for role in member.roles if role.name != "@everyone")
            or "none",
            "server": f"{guild.name} ({guild.id})",
            "current_time": discord.utils.utcnow().isoformat(),
        }
        await self._record_member_join(member)
        await self._reason_about_event("member_join", payload, state, context)

    async def handle_member_remove(self, member: discord.Member) -> None:
        state = await self._state.get_state()
        guild = member.guild
        context = EventContext(bot=self._bot, guild=guild, member=member, dry_run=state.dry_run)
        payload = {
            "member": f"{member} ({member.id})",
            "roles": ", ".join(role.name for role in member.roles if role.name != "@everyone")
            or "none",
            "joined_at": member.joined_at.isoformat() if member.joined_at else "unknown",
            "server": f"{guild.name} ({guild.id})",
            "current_time": discord.utils.utcnow().isoformat(),
        }
        await self._reason_about_event("member_remove", payload, state, context)

    async def handle_scheduled_tick(self, guild: discord.Guild) -> None:
        state = await self._state.get_state()
        payload = await self._build_scheduled_payload(guild, state)
        context = EventContext(bot=self._bot, guild=guild, dry_run=state.dry_run)
        await self._reason_about_event("scheduled_tick", payload, state, context)

    async def _apply_automation_if_needed(self, message: discord.Message, state: BotState) -> bool:
        rule = state.automations.get(message.channel.id)
        if not rule or not rule.active:
            return False

        matched_keywords: List[str] = []
        if rule.keywords:
            content = (message.content or "").lower()
            matched_keywords = [kw for kw in rule.keywords if kw.lower() in content]
            if not matched_keywords:
                return False

        dry_run = state.dry_run
        metadata = {
            "automation_rule": rule.trigger_summary,
            "automation_action": rule.action,
        }
        if matched_keywords:
            metadata["matched_keywords"] = matched_keywords

        if rule.action == "kick":
            summary = (
                f"Kicked {message.author} for automation rule in #{message.channel}. Reason: {rule.justification}"
            )
            if dry_run:
                await self._log_action(
                    message.guild,
                    f"[DRY-RUN] Would kick {message.author} due to automation in #{message.channel}.",
                    action_type="kick",
                    channel=message.channel,
                    target_member=message.author,
                    reason=rule.justification,
                    message=message,
                    metadata=metadata,
                    dry_run=True,
                )
                return True

            notification = await message.channel.send(
                f"{message.author.mention}, this channel is restricted. You will be removed."
            )
            await self._record_bot_channel_activity(
                message.guild,
                message.channel,
                notification,
                context_tag="automation_notice",
            )
            try:
                await message.author.kick(reason=rule.justification)
            except discord.Forbidden:
                logger.warning("Failed to kick member %s", message.author.id)
            await self._log_action(
                message.guild,
                summary,
                action_type="kick",
                channel=message.channel,
                target_member=message.author,
                reason=rule.justification,
                message=message,
                metadata=metadata,
            )
            return True

        if rule.action == "delete_message":
            summary = (
                f"Deleted message in #{message.channel} per automation rule. Reason: {rule.justification}"
            )
            metadata_with_content = dict(metadata)
            metadata_with_content["original_content"] = message.content
            if dry_run:
                await self._log_action(
                    message.guild,
                    f"[DRY-RUN] Would delete message from {message.author} in #{message.channel}.",
                    action_type="delete_message",
                    channel=message.channel,
                    target_member=message.author,
                    reason=rule.justification,
                    message_id=message.id,
                    metadata=metadata_with_content,
                    dry_run=True,
                )
                return True

            try:
                await message.delete()
            except discord.Forbidden:
                logger.warning("Failed to delete message %s", message.id)
            await self._log_action(
                message.guild,
                summary,
                action_type="delete_message",
                channel=message.channel,
                target_member=message.author,
                reason=rule.justification,
                message_id=message.id,
                metadata=metadata_with_content,
            )
            return True

        return False

    async def _reason_about_event(
        self,
        event_name: str,
        payload: Dict[str, str],
        state: BotState,
        context: EventContext,
    ) -> None:
        built_in = getattr(state, "built_in_prompt", None)
        system_prompt = build_system_prompt(state, built_in_prompt=built_in)
        user_prompt = build_event_prompt(event_name, payload)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            choice = await self._llm.run(messages, tools=MODERATION_TOOLS)
        except LLMUnavailable:
            logger.info("LLM unavailable; skipping reasoning for %s", event_name)
            return
        except Exception:
            logger.exception("LLM moderation run failed")
            return

        tool_calls = self._llm.extract_tool_calls(choice)
        for call in tool_calls:
            await self._execute_tool_call(call, context)

    async def _execute_tool_call(self, call: Dict[str, Any], context: EventContext) -> None:
        name = call.get("name")
        arguments_raw = call.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_raw)
        except json.JSONDecodeError:
            logger.warning("Invalid tool arguments for %s: %s", name, arguments_raw)
            return

        if name == "take_moderation_action":
            await self._tool_take_moderation_action(arguments, context)
        elif name == "send_message":
            await self._tool_send_message(arguments, context)
        elif name == "escalate_to_human":
            await self._tool_escalate(arguments, context)
        else:
            logger.warning("Unknown tool call received: %s", name)

    async def _tool_take_moderation_action(self, args: Dict[str, Any], context: EventContext) -> None:
        action = args.get("action")
        reason = args.get("reason", "No reason provided.")
        target_user_id = args.get("target_user_id")
        if not action or not target_user_id:
            logger.warning("Missing action/target in moderation action")
            return

        guild = context.guild
        if guild is None:
            return

        member = guild.get_member(int(target_user_id))
        if member is None:
            logger.warning("Could not find member %s in guild %s", target_user_id, guild.id)
            return

        dry_run = context.dry_run
        base_metadata = {"trigger": "llm_tool", "tool": "take_moderation_action"}

        if action == "delete_message":
            message_id = args.get("message_id")
            if context.message and str(context.message.id) == message_id:
                if dry_run:
                    metadata_delete = dict(base_metadata)
                    metadata_delete["original_content"] = context.message.content
                    await self._log_action(
                        guild,
                        f"Would delete message from {member} in #{context.channel}. Reason: {reason}",
                        action_type="delete_message",
                        channel=context.channel,
                        target_member=member,
                        reason=reason,
                        message=context.message,
                        metadata=metadata_delete,
                        dry_run=True,
                    )
                    return
                try:
                    await context.message.delete()
                except discord.Forbidden:
                    logger.warning("Failed to delete message %s", message_id)
            metadata_delete = dict(base_metadata)
            metadata_delete["original_content"] = context.message.content if context.message else None
            await self._log_action(
                guild,
                f"Deleted message from {member}. Reason: {reason}",
                action_type="delete_message",
                channel=context.channel,
                target_member=member,
                reason=reason,
                message=context.message,
                metadata=metadata_delete,
            )
            return

        if action == "warn":
            if dry_run:
                await self._log_action(
                    guild,
                    f"Would warn {member}. Reason: {reason}",
                    action_type="warn",
                    channel=context.channel,
                    target_member=member,
                    reason=reason,
                    metadata=base_metadata,
                    dry_run=True,
                )
                return
            await self._send_dm(member, f"Moderator warning: {reason}")
            await self._log_action(
                guild,
                f"Issued warning to {member}. Reason: {reason}",
                action_type="warn",
                channel=context.channel,
                target_member=member,
                reason=reason,
                metadata=base_metadata,
            )
            return

        if action == "timeout":
            duration = args.get("duration_minutes", 10)
            if dry_run:
                metadata_timeout = dict(base_metadata)
                metadata_timeout["duration_minutes"] = duration
                await self._log_action(
                    guild,
                    f"Would timeout {member} for {duration} minutes. Reason: {reason}",
                    action_type="timeout",
                    channel=context.channel,
                    target_member=member,
                    reason=reason,
                    metadata=metadata_timeout,
                    dry_run=True,
                )
                return
            try:
                until = discord.utils.utcnow() + timedelta(minutes=int(duration))
                await member.timeout(until=until, reason=reason)
            except AttributeError:
                until = discord.utils.utcnow() + timedelta(minutes=int(duration))
                await member.edit(timed_out_until=until, reason=reason)
            except discord.Forbidden:
                logger.warning("Failed to timeout member %s", member.id)
            await self._log_action(
                guild,
                f"Timed out {member} for {duration} minutes. Reason: {reason}",
                action_type="timeout",
                channel=context.channel,
                target_member=member,
                reason=reason,
                metadata={
                    **base_metadata,
                    "duration_minutes": duration,
                },
            )
            return

        if action == "kick":
            if dry_run:
                await self._log_action(
                    guild,
                    f"Would kick {member}. Reason: {reason}",
                    action_type="kick",
                    channel=context.channel,
                    target_member=member,
                    reason=reason,
                    metadata=base_metadata,
                    dry_run=True,
                )
                return
            try:
                await member.kick(reason=reason)
            except discord.Forbidden:
                logger.warning("Failed to kick member %s", member.id)
            await self._log_action(
                guild,
                f"Kicked {member}. Reason: {reason}",
                action_type="kick",
                channel=context.channel,
                target_member=member,
                reason=reason,
                metadata=base_metadata,
            )
            return

        if action == "ban":
            if dry_run:
                await self._log_action(
                    guild,
                    f"Would ban {member}. Reason: {reason}",
                    action_type="ban",
                    channel=context.channel,
                    target_member=member,
                    reason=reason,
                    metadata=base_metadata,
                    dry_run=True,
                )
                return
            try:
                await member.ban(reason=reason, delete_message_days=1)
            except discord.Forbidden:
                logger.warning("Failed to ban member %s", member.id)
            await self._log_action(
                guild,
                f"Banned {member}. Reason: {reason}",
                action_type="ban",
                channel=context.channel,
                target_member=member,
                reason=reason,
                metadata=base_metadata,
            )
            return

        if action == "flag":
            if dry_run:
                await self._log_action(
                    guild,
                    f"Would flag {member}. Reason: {reason}",
                    action_type="flag",
                    channel=context.channel,
                    target_member=member,
                    reason=reason,
                    metadata=base_metadata,
                    dry_run=True,
                )
                return
            await self._log_action(
                guild,
                f"Flagged {member}. Reason: {reason}",
                action_type="flag",
                channel=context.channel,
                target_member=member,
                reason=reason,
                metadata=base_metadata,
            )

    async def _tool_send_message(self, args: Dict[str, Any], context: EventContext) -> None:
        message_content = args.get("message")
        if not message_content:
            return

        is_dm = args.get("is_dm", False)
        target_user_id = args.get("target_user_id")
        context_tag = args.get("context_tag")
        reply_message_id = args.get("reply_to_message_id")
        explicit_thread_choice = args.get("reply_in_thread")
        thread_name = args.get("thread_name")
        dry_run = context.dry_run

        if is_dm:
            if not target_user_id:
                logger.warning("send_message DM requested without target_user_id")
                return
            guild = context.guild
            if guild is None:
                return
            try:
                target_member_int = int(target_user_id)
            except (TypeError, ValueError):
                logger.warning("Invalid target_user_id supplied for DM: %s", target_user_id)
                return
            member = guild.get_member(target_member_int)
            if member is None:
                logger.warning("Member %s not found for DM", target_user_id)
                return
            if dry_run:
                metadata = {
                    "trigger": "llm_tool",
                    "tool": "send_message",
                    "tag": context_tag,
                    "target_user_id": target_user_id,
                }
                await self._log_action(
                    guild,
                    f"[DRY-RUN] Would DM {member}: {message_content}",
                    action_type="dm",
                    target_member=member,
                    metadata=metadata,
                    dry_run=True,
                )
                return
            dm_message = await member.send(message_content)
            await self._log_action(
                guild,
                f"Sent DM to {member}: {message_content}",
                action_type="dm",
                target_member=member,
                metadata={
                    "trigger": "llm_tool",
                    "tool": "send_message",
                    "tag": context_tag,
                },
            )
            if context_tag == "welcome" and self._db and self._db.is_enabled:
                await self._db.mark_member_welcomed(
                    guild.id, member.id, self._ensure_aware(dm_message.created_at)
                )
            return

        channel_id = args.get("channel_id")
        resolved_channel: Optional[discord.abc.MessageableChannel] = None
        if channel_id:
            resolved_channel = context.bot.get_channel(int(channel_id))
            if resolved_channel is None:
                try:
                    resolved_channel = await context.bot.fetch_channel(int(channel_id))
                except (discord.Forbidden, discord.HTTPException):
                    resolved_channel = None
        elif context.channel:
            resolved_channel = context.channel
        if resolved_channel is None:
            logger.warning("send_message could not resolve channel")
            return
        guild = context.guild
        if guild is None and isinstance(resolved_channel, discord.abc.GuildChannel):
            guild = resolved_channel.guild
        if guild is None:
            logger.warning("send_message has no guild context to execute within")
            return

        if dry_run:
            channel_label = getattr(resolved_channel, "name", str(getattr(resolved_channel, "id", "channel")))
            metadata = {
                "trigger": "llm_tool",
                "tool": "send_message",
                "tag": context_tag,
                "channel_id": getattr(resolved_channel, "id", None),
            }
            await self._log_action(
                guild,
                f"[DRY-RUN] Would post in #{channel_label}: {message_content}",
                action_type="message",
                channel=resolved_channel if isinstance(resolved_channel, discord.abc.GuildChannel) else context.channel,
                metadata=metadata,
                dry_run=True,
            )
            return

        reference_message: Optional[discord.Message] = None
        if reply_message_id:
            try:
                reply_target_id = int(reply_message_id)
            except (TypeError, ValueError):
                reference_message = None
            else:
                try:
                    target_channel = resolved_channel
                    if isinstance(target_channel, discord.Thread) and target_channel.parent:
                        target_channel = target_channel
                    if isinstance(target_channel, (discord.TextChannel, discord.Thread)):
                        reference_message = await target_channel.fetch_message(reply_target_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    reference_message = None
        elif context.message:
            reference_message = context.message

        same_channel_context = (
            context.message is not None
            and isinstance(resolved_channel, discord.abc.GuildChannel)
            and isinstance(context.channel, discord.abc.GuildChannel)
            and context.channel.id == resolved_channel.id
        )
        reply_in_thread: Optional[bool]
        if same_channel_context and not isinstance(resolved_channel, discord.Thread):
            reply_in_thread = self._should_reply_in_thread(context, explicit_thread_choice)
        else:
            reply_in_thread = explicit_thread_choice

        send_channel: discord.abc.MessageableChannel = resolved_channel
        if reply_in_thread and reference_message:
            base_message = reference_message
            base_channel = base_message.channel
            if isinstance(base_channel, discord.Thread):
                send_channel = base_channel
            else:
                thread = getattr(base_message, "thread", None)
                if thread and not thread.archived:
                    send_channel = thread
                else:
                    try:
                        thread_title = self._generate_thread_name(thread_name, base_message)
                        thread = await base_message.create_thread(name=thread_title)
                        send_channel = thread
                    except (discord.Forbidden, discord.HTTPException):
                        logger.warning("Unable to create thread for reply; falling back to channel")
                        send_channel = resolved_channel
        elif reply_in_thread and not reference_message:
            reply_in_thread = False

        reference = None
        if not reply_in_thread and reference_message and hasattr(send_channel, "send"):
            try:
                reference = reference_message.to_reference(fail_if_not_exists=False)
            except AttributeError:
                reference = None

        try:
            sent_message = await send_channel.send(message_content, reference=reference)
        except discord.Forbidden:
            logger.warning("Insufficient permissions to send message in %s", send_channel)
            return
        except discord.HTTPException:
            logger.exception("Failed to send message in %s", send_channel)
            return

        channel_for_log = (
            send_channel if isinstance(send_channel, discord.abc.GuildChannel) else resolved_channel
        )
        channel_label = getattr(channel_for_log, "name", str(channel_for_log.id))
        metadata = {"trigger": "llm_tool", "tool": "send_message"}
        if context_tag:
            metadata["tag"] = context_tag

        await self._log_action(
            guild,
            f"Sent message in #{channel_label}: {message_content}",
            action_type="message",
            channel=channel_for_log if isinstance(channel_for_log, discord.abc.GuildChannel) else context.channel,
            metadata=metadata,
        )
        if isinstance(channel_for_log, discord.abc.GuildChannel):
            await self._record_bot_channel_activity(guild, channel_for_log, sent_message, context_tag)
        if context_tag == "welcome" and target_user_id and self._db and self._db.is_enabled:
            try:
                welcomed_member_id = int(target_user_id)
            except (TypeError, ValueError):
                welcomed_member_id = None
            if welcomed_member_id is not None:
                await self._db.mark_member_welcomed(
                    guild.id, welcomed_member_id, self._ensure_aware(sent_message.created_at)
                )

    async def _tool_escalate(self, args: Dict[str, Any], context: EventContext) -> None:
        summary = args.get("summary")
        if not summary or context.guild is None:
            return
        priority = args.get("priority", "medium")
        await self._log_action(
            context.guild,
            f"Escalation requested (priority {priority}): {summary}",
            action_type="escalate",
            metadata={"priority": priority, "trigger": "llm_tool", "tool": "escalate_to_human"},
            dry_run=context.dry_run,
        )

    async def _record_channel_activity_message(self, message: discord.Message) -> None:
        if not self._db or not self._db.is_enabled or message.guild is None:
            return
        channel_name = getattr(message.channel, "name", str(message.channel.id))
        await self._db.record_channel_activity(
            guild_id=message.guild.id,
            guild_name=message.guild.name,
            channel_id=message.channel.id,
            channel_name=channel_name,
            timestamp=self._ensure_aware(message.created_at),
            user_message=not message.author.bot,
        )

    async def _record_bot_channel_activity(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        sent_message: Optional[discord.Message],
        context_tag: Optional[str] = None,
    ) -> None:
        if not self._db or not self._db.is_enabled:
            return
        timestamp = self._ensure_aware(sent_message.created_at if sent_message else None)
        channel_name = getattr(channel, "name", str(channel.id))
        spark = context_tag == "spark"
        review = context_tag in {"review", "reminder"}
        await self._db.record_channel_activity(
            guild_id=guild.id,
            guild_name=guild.name,
            channel_id=channel.id,
            channel_name=channel_name,
            timestamp=timestamp,
            bot_message=True,
            spark=spark,
            review=review,
        )
        if isinstance(channel, discord.Thread) and channel.parent:
            parent = channel.parent
            parent_name = getattr(parent, "name", str(parent.id))
            await self._db.record_channel_activity(
                guild_id=guild.id,
                guild_name=guild.name,
                channel_id=parent.id,
                channel_name=parent_name,
                timestamp=timestamp,
                bot_message=True,
                spark=spark,
                review=review,
            )

    async def _record_member_join(self, member: discord.Member) -> None:
        if not self._db or not self._db.is_enabled:
            return
        joined_at = self._ensure_aware(member.joined_at)
        await self._db.record_member_join(
            guild_id=member.guild.id,
            member_id=member.id,
            username=str(member),
            joined_at=joined_at,
        )

    async def _resolve_reply_context(self, message: discord.Message) -> Optional[discord.Message]:
        reference = message.reference
        if not reference:
            return None
        if reference.cached_message:
            return reference.cached_message
        target_id = reference.message_id
        if not target_id:
            return None
        try:
            channel = message.channel
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                return await channel.fetch_message(target_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        except discord.HTTPException:
            logger.debug("Failed to fetch referenced message %s", target_id)
        return None

    async def _gather_recent_messages(
        self,
        channel: Optional[discord.abc.Messageable],
        *,
        include_current: bool,
        limit: int = 6,
        current_message_id: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return [], "Recent history unavailable for this channel type."
        messages: List[discord.Message] = []
        try:
            async for msg in channel.history(limit=limit):
                if not include_current and current_message_id and msg.id == current_message_id:
                    continue
                messages.append(msg)
        except (discord.Forbidden, discord.HTTPException):
            return [], "Unable to retrieve recent messages due to permissions."

        now = discord.utils.utcnow().replace(tzinfo=timezone.utc)
        serialised: List[Dict[str, Any]] = []
        lines: List[str] = []
        for msg in messages:
            created_at = self._ensure_aware(msg.created_at)
            serialised.append(
                {
                    "message_id": msg.id,
                    "author_id": msg.author.id,
                    "author_name": str(msg.author),
                    "created_at": created_at,
                    "is_bot": msg.author.bot,
                    "content": msg.content,
                }
            )
            highlight = " (current event)" if current_message_id and msg.id == current_message_id else ""
            lines.append(
                f"{self._format_relative_time(created_at, now)} ago | {msg.author}: {self._shorten_content(msg.content)}{highlight}"
            )

        summary = "\n".join(lines[:limit]) if lines else "No recent activity captured."
        return serialised, summary

    def _shorten_content(self, content: str, limit: int = 140) -> str:
        if not content:
            return "[no text content]"
        text = content.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _format_relative_time(self, dt: Optional[datetime], now: datetime) -> str:
        if dt is None:
            return "never"
        delta = now - dt
        seconds = max(int(delta.total_seconds()), 0)
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"

    def _format_reply_context(self, reply_target: Optional[discord.Message]) -> str:
        if not reply_target:
            return "Not a direct reply."
        created_at = self._ensure_aware(reply_target.created_at).isoformat()
        snippet = self._shorten_content(reply_target.content)
        author = getattr(reply_target.author, "display_name", str(reply_target.author))
        return f"Replying to {author} ({reply_target.id}) from {created_at}: {snippet}"

    def _ensure_aware(self, dt: Optional[datetime]) -> datetime:
        if dt is None:
            return discord.utils.utcnow().replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _should_reply_in_thread(self, context: EventContext, explicit: Optional[bool]) -> bool:
        if explicit is not None:
            return explicit
        message = context.message
        if not message:
            return False
        channel = message.channel
        if isinstance(channel, discord.Thread):
            return False
        recent = context.recent_messages or []
        now = discord.utils.utcnow().replace(tzinfo=timezone.utc)
        active_participants = {
            entry["author_id"]
            for entry in recent
            if (now - entry["created_at"]).total_seconds() <= 300
        }
        if len(active_participants) >= 3:
            return True
        if context.reply_to:
            age = (
                self._ensure_aware(message.created_at) - self._ensure_aware(context.reply_to.created_at)
            ).total_seconds()
            if age > 3600:
                return True
        return False

    def _generate_thread_name(self, base: Optional[str], message: Optional[discord.Message]) -> str:
        if base and base.strip():
            return base.strip()[:100]
        if message:
            author = getattr(message.author, "display_name", str(message.author))
            return f"Follow-up with {author}"[:100]
        return "ModGPT Discussion"

    async def _build_scheduled_payload(self, guild: discord.Guild, state: BotState) -> Dict[str, str]:
        now = discord.utils.utcnow().replace(tzinfo=timezone.utc)
        channel_summary = "No channel activity recorded yet."
        spark_candidates: List[str] = []
        pending_summary = "All recent joiners acknowledged."
        actions_summary = "No recent moderation actions logged."

        if self._db and self._db.is_enabled:
            activity_rows = await self._db.fetch_channel_activity(guild.id)
            unwelcomed = await self._db.fetch_unwelcomed_members(guild.id, max_age=timedelta(days=7))
            recent_actions = await self._db.fetch_recent_actions(guild.id, limit=10)
            if activity_rows:
                channel_summary, spark_candidates = self._summarize_channel_activity(activity_rows, now)
            if unwelcomed:
                pending_summary = self._summarize_pending_welcomes(unwelcomed, now)
            if recent_actions:
                actions_summary = self._summarize_recent_actions(recent_actions, now)

        return {
            "server": f"{guild.name} ({guild.id})",
            "current_time": now.isoformat(),
            "channel_activity": channel_summary,
            "pending_welcomes": pending_summary,
            "recent_actions": actions_summary,
            "dry_run_mode": "enabled" if state.dry_run else "disabled",
            "persona": state.persona.description,
            "spark_candidates": "\n".join(spark_candidates) if spark_candidates else "None identified",
        }

    def _summarize_channel_activity(self, rows: List[Any], now: datetime) -> Tuple[str, List[str]]:
        lines: List[str] = []
        candidates: List[str] = []
        for row in rows[:10]:
            mapping = dict(row)
            channel_name = mapping.get("channel_name") or str(mapping.get("channel_id"))
            last_user_dt = self._ensure_optional(mapping.get("last_user_message_at"))
            last_user = self._format_relative_time(last_user_dt, now)
            last_bot = self._format_relative_time(
                self._ensure_optional(mapping.get("last_bot_message_at")), now
            )
            last_spark = self._format_relative_time(
                self._ensure_optional(mapping.get("last_spark_at")), now
            )
            stale_flag = ""
            if last_user_dt and (now - last_user_dt).total_seconds() > 86400:
                stale_flag = " ⚠️"
                candidates.append(f"#{channel_name} (last user {last_user} ago)")
            lines.append(
                f"#{channel_name}: user {last_user}, bot {last_bot}, spark {last_spark}, messages {mapping.get('message_count', 0)}{stale_flag}"
            )
        summary = "\n".join(lines) if lines else "No recent channel activity available."
        return summary, candidates

    def _summarize_pending_welcomes(self, rows: List[Any], now: datetime) -> str:
        lines = []
        for row in rows[:10]:
            mapping = dict(row)
            joined_at = self._ensure_optional(mapping.get("joined_at"))
            rel = self._format_relative_time(joined_at, now)
            lines.append(f"{mapping.get('username')} ({mapping.get('member_id')}) joined {rel} ago")
        if len(rows) > 10:
            lines.append(f"... and {len(rows) - 10} more awaiting welcome")
        return "\n".join(lines)

    def _summarize_recent_actions(self, rows: List[Any], now: datetime) -> str:
        lines = []
        for row in rows:
            mapping = dict(row)
            created_at = self._ensure_optional(mapping.get("created_at"))
            rel = self._format_relative_time(created_at, now)
            lines.append(f"{rel} ago: {mapping.get('action_type')} -> {mapping.get('summary')}")
        return "\n".join(lines)

    def _ensure_optional(self, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._ensure_aware(value)
        return None

    def _build_message_payload(
        self,
        message: discord.Message,
        state: BotState,
        recent_summary: str,
        reply_target: Optional[discord.Message],
    ) -> Dict[str, str]:
        automations = self._matching_automations(message.channel.id, state)
        now = discord.utils.utcnow().replace(tzinfo=timezone.utc)
        created_at = self._ensure_aware(message.created_at)
        reply_text = self._format_reply_context(reply_target)
        return {
            "author": f"{message.author} ({message.author.id})",
            "channel": f"#{getattr(message.channel, 'name', message.channel.id)} ({message.channel.id})",
            "server": f"{message.guild.name} ({message.guild.id})",
            "timestamp": created_at.isoformat(),
            "current_time": now.isoformat(),
            "content": message.content,
            "replying_to": reply_text,
            "channel_topic": getattr(message.channel, "topic", "") or "No topic.",
            "recent_messages": recent_summary or "Unable to load recent history.",
            "referenced_context_channels": ", ".join(
                f"#{ctx.label}" for ctx in state.context_channels.values()
            )
            or "none",
            "automations": ", ".join(
                f"{rule.action} -> {rule.trigger_summary}" +
                (f" [keywords: {', '.join(rule.keywords)}]" if rule.keywords else "")
                for rule in automations
            )
            or "none",
            "dry_run_mode": "enabled" if state.dry_run else "disabled",
        }

    def _build_message_edit_payload(
        self,
        before: discord.Message,
        after: discord.Message,
        state: BotState,
        recent_summary: str,
        reply_target: Optional[discord.Message],
    ) -> Dict[str, str]:
        now = discord.utils.utcnow().replace(tzinfo=timezone.utc)
        created_at = self._ensure_aware(after.created_at)
        reply_text = self._format_reply_context(reply_target)
        return {
            "author": f"{after.author} ({after.author.id})",
            "channel": f"#{getattr(after.channel, 'name', after.channel.id)} ({after.channel.id})",
            "server": f"{after.guild.name} ({after.guild.id})",
            "edited_at": now.isoformat(),
            "original_timestamp": created_at.isoformat(),
            "replying_to": reply_text,
            "before": before.content,
            "after": after.content,
            "recent_messages": recent_summary or "Unable to load recent history.",
            "channel_topic": getattr(after.channel, "topic", "") or "No topic.",
            "dry_run_mode": "enabled" if state.dry_run else "disabled",
        }

    def _matching_automations(self, channel_id: int, state: BotState) -> List[AutomationRule]:
        rule = state.automations.get(channel_id)
        if not rule or not rule.active:
            return []
        return [rule]

    async def _send_dm(self, member: discord.Member, message: str) -> None:
        try:
            await member.send(message)
        except discord.Forbidden:
            logger.warning("Failed to DM member %s", member.id)

    async def _log_action(
        self,
        guild: discord.Guild,
        summary: str,
        *,
        action_type: str = "info",
        channel: Optional[discord.abc.GuildChannel] = None,
        channel_id: Optional[int] = None,
        target_member: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        message: Optional[discord.Message] = None,
        message_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> None:
        resolved_channel_id = channel.id if channel else channel_id
        resolved_message_id = message.id if message else message_id
        target_user_id = target_member.id if target_member else None
        target_username = str(target_member) if target_member else None

        if self._db and self._db.is_enabled:
            db_metadata = dict(metadata or {})
            if dry_run:
                db_metadata["dry_run"] = True
            record = ModerationRecord(
                guild_id=guild.id,
                channel_id=resolved_channel_id,
                action_type=action_type,
                summary=summary,
                target_user_id=target_user_id,
                target_username=target_username,
                reason=reason,
                message_id=resolved_message_id,
                metadata=db_metadata,
            )
            try:
                await self._db.record_moderation(record)
            except Exception:
                logger.exception("Failed to persist moderation record")

        log_summary = summary
        if dry_run and not summary.startswith("[DRY-RUN]"):
            log_summary = f"[DRY-RUN] {summary}"

        state = await self._state.get_state()
        logs_channel_id = state.logs_channel_id
        if not logs_channel_id:
            logger.info("[log] %s", log_summary)
            return
        channel = guild.get_channel(logs_channel_id)
        if channel is None:
            logger.warning("Logs channel %s not found", logs_channel_id)
            return
        embed = discord.Embed(description=log_summary)
        await channel.send(embed=embed)
