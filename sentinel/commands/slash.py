"""Slash command definitions for Sentinel AI admin/config."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import discord
from discord import app_commands

from ..services.state import (
    AutomationRule,
    ContextChannel,
    LLMSettings,
    PersonaProfile,
    StateStore,
)

logger = logging.getLogger(__name__)


def register_slash_commands(
    tree: app_commands.CommandTree, state: StateStore, moderation, llm_client
) -> None:
    """Register all slash commands to the command tree."""

    @tree.command(name="add-channel", description="Add a context channel for the bot to reference")
    @app_commands.describe(
        channel="The channel to add as context",
        description="Optional notes about this channel's purpose",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        description: Optional[str] = None,
    ) -> None:
        # Defer response since fetching messages may take time
        await interaction.response.defer(ephemeral=True)

        # Fetch recent messages from the channel and summarize
        from ..services.state import fetch_channel_context
        from datetime import datetime, timezone

        recent_messages = await fetch_channel_context(
            channel, message_limit=50, llm_client=llm_client
        )

        context_channel = ContextChannel(
            channel_id=channel.id,
            guild_id=interaction.guild.id,
            label=channel.name,
            notes=description.strip() if description else None,
            recent_messages=recent_messages,
            last_fetched=datetime.now(timezone.utc).isoformat(),
        )
        await state.add_context_channel(context_channel)

        await interaction.followup.send(
            f"✅ Added {channel.mention} as a context channel.\n"
            f"📝 Notes: {context_channel.notes or 'none'}\n"
            f"🤖 Recent channel activity has been analyzed and summarized for context.",
            ephemeral=True,
        )

    @tree.command(name="remove-channel", description="Remove a context channel")
    @app_commands.describe(channel="The channel to remove from context")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_channel(
        interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        removed = await state.remove_context_channel(channel.id)
        if removed:
            await interaction.response.send_message(
                f"✅ Removed {channel.mention} from context channels.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {channel.mention} was not registered.", ephemeral=True
            )

    @tree.command(name="list-channels", description="List all context channels")
    async def list_channels(interaction: discord.Interaction) -> None:
        current_state = await state.get_state(guild_id=interaction.guild.id)
        if not current_state.context_channels:
            await interaction.response.send_message(
                "No context channels configured yet.", ephemeral=True
            )
            return
        lines = ["**Context Channels:**"]
        for ctx_channel in current_state.context_channels.values():
            last_fetched = ctx_channel.last_fetched or "never"
            if ctx_channel.last_fetched:
                from datetime import datetime

                try:
                    dt = datetime.fromisoformat(ctx_channel.last_fetched)
                    last_fetched = dt.strftime("%Y-%m-%d %H:%M UTC")
                except Exception:
                    pass
            lines.append(
                f"• <#{ctx_channel.channel_id}> ({ctx_channel.channel_id})\n"
                f"  Notes: {ctx_channel.notes or 'no notes'}\n"
                f"  Last updated: {last_fetched}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="refresh-channel", description="Refresh message context for a channel")
    @app_commands.describe(channel="The context channel to refresh")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def refresh_channel(
        interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        # Defer response since fetching messages may take time
        await interaction.response.defer(ephemeral=True)

        current_state = await state.get_state(guild_id=interaction.guild.id)
        if channel.id not in current_state.context_channels:
            await interaction.followup.send(
                f"❌ {channel.mention} is not a registered context channel. "
                f"Use `/add-channel` to add it first.",
                ephemeral=True,
            )
            return

        # Fetch fresh messages and summarize
        from ..services.state import fetch_channel_context
        from datetime import datetime, timezone

        recent_messages = await fetch_channel_context(
            channel, message_limit=50, llm_client=llm_client
        )

        # Update the existing context channel
        ctx_channel = current_state.context_channels[channel.id]
        updated_channel = ContextChannel(
            channel_id=ctx_channel.channel_id,
            guild_id=ctx_channel.guild_id,
            label=ctx_channel.label,
            notes=ctx_channel.notes,
            recent_messages=recent_messages,
            last_fetched=datetime.now(timezone.utc).isoformat(),
        )
        await state.add_context_channel(updated_channel)

        await interaction.followup.send(
            f"✅ Refreshed context for {channel.mention}\n"
            f"🤖 Recent channel activity has been re-analyzed and summarized.",
            ephemeral=True,
        )

    @tree.command(name="set-logs", description="Set the channel for bot logs")
    @app_commands.describe(channel="Channel where logs should be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_logs(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await state.set_logs_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ Logs channel set to {channel.mention} for this server.", ephemeral=True
        )

    @tree.command(name="remember", description="Add a persistent memory/instruction for the bot")
    @app_commands.describe(note="The instruction or guideline to remember")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remember(interaction: discord.Interaction, note: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Memories can only be stored inside a server.", ephemeral=True
            )
            return
        content = note.strip()
        if not content:
            await interaction.response.send_message(
                "❌ Please provide the text you want me to remember.", ephemeral=True
            )
            return
        memory = await state.add_memory(
            guild_id=interaction.guild.id,
            content=content,
            author=str(interaction.user),
            author_id=interaction.user.id,
        )
        await interaction.response.send_message(
            f"✅ Stored memory #{memory.memory_id}: {memory.content}", ephemeral=True
        )

    @tree.command(name="list-memories", description="Show all persistent memories")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_memories(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command must be used inside a server.", ephemeral=True
            )
            return
        memories = await state.list_memories(interaction.guild.id)
        if not memories:
            await interaction.response.send_message("No memories recorded yet.", ephemeral=True)
            return
        lines = ["**Memories:**"]
        for memory in memories[:10]:
            lines.append(f"#{memory.memory_id} – {memory.content} (by {memory.author})")
        if len(memories) > 10:
            lines.append(f"...and {len(memories) - 10} more")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="forget-memory", description="Remove a persistent memory")
    @app_commands.describe(memory_id="The ID of the memory to forget")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def forget_memory(interaction: discord.Interaction, memory_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command must be used inside a server.", ephemeral=True
            )
            return
        removed = await state.remove_memory(interaction.guild.id, memory_id)
        if removed:
            await interaction.response.send_message(
                f"✅ Forgot memory #{memory_id}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No memory found with id #{memory_id}.", ephemeral=True
            )

    @tree.command(name="set-built-in-prompt", description="Set a deployment-wide prompt")
    @app_commands.describe(prompt="The prompt text (leave empty to clear)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_built_in_prompt(
        interaction: discord.Interaction, prompt: Optional[str] = None
    ) -> None:
        value = prompt.strip() if prompt and prompt.strip() else None
        await state.set_built_in_prompt(value)
        if value:
            await interaction.response.send_message("✅ Built-in prompt updated.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "✅ Built-in prompt cleared; using internal defaults only.", ephemeral=True
            )

    @tree.command(name="set-llm", description="Configure LLM settings")
    @app_commands.describe(
        api_key="OpenAI API key (or use 'None' to clear)",
        model="Model name (e.g. gpt-4o-mini)",
        base_url="Custom API base URL",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_llm(
        interaction: discord.Interaction,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        if not any([api_key, model, base_url]):
            await interaction.response.send_message(
                "❌ Please provide at least one setting to update.", ephemeral=True
            )
            return

        def _normalize(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            cleaned = value.strip()
            if cleaned.lower() in {"none", "null", ""}:
                return None
            return cleaned

        current = (await state.get_state()).llm
        updated = LLMSettings(
            api_key=_normalize(api_key) if api_key is not None else current.api_key,
            model=_normalize(model) if model is not None else current.model,
            base_url=_normalize(base_url) if base_url is not None else current.base_url,
        )
        await state.set_llm_settings(updated)

        # Refresh the LLM client with new settings
        llm_client.update_config(
            api_key=updated.api_key,
            model=updated.model or "gpt-4o-mini",
            base_url=updated.base_url,
        )

        masked_key = (updated.api_key[:4] + "…") if updated.api_key else "<unset>"
        await interaction.response.send_message(
            f"✅ LLM settings updated and applied immediately.\n"
            f"• API Key: {masked_key}\n"
            f"• Model: {updated.model or 'gpt-4o-mini'}\n"
            f"• Base URL: {updated.base_url or 'default'}",
            ephemeral=True,
        )

    @tree.command(name="llm-status", description="Check current LLM configuration")
    async def llm_status(interaction: discord.Interaction) -> None:
        snapshot = await state.get_state()
        llm_conf = snapshot.llm
        masked_key = (llm_conf.api_key[:4] + "…") if llm_conf.api_key else "<unset>"
        await interaction.response.send_message(
            f"**LLM Status:**\n"
            f"• API Key: {masked_key}\n"
            f"• Model: {llm_conf.model or 'gpt-4o-mini'}\n"
            f"• Base URL: {llm_conf.base_url or 'default'}",
            ephemeral=True,
        )

    @tree.command(name="set-nickname", description="Change the bot's nickname")
    @app_commands.describe(nickname="New nickname (leave empty to clear)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_nickname(
        interaction: discord.Interaction, nickname: Optional[str] = None
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return
        cleaned = nickname.strip() if nickname and nickname.strip() else None
        me = interaction.guild.me
        if me:
            try:
                await me.edit(nick=cleaned)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I need permission to manage my nickname to apply that change.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                await interaction.response.send_message(
                    "❌ Something went wrong while updating the nickname. Try again later.",
                    ephemeral=True,
                )
                return
        else:
            await interaction.response.send_message(
                "❌ I couldn't access my member profile to change the nickname right now.",
                ephemeral=True,
            )
            return
        await state.set_bot_nickname(interaction.guild.id, cleaned)
        if cleaned:
            await interaction.response.send_message(
                f"✅ Nickname updated to `{cleaned}` for this server.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ Nickname cleared for this server; the default account name will be used.",
                ephemeral=True,
            )

    @tree.command(name="set-dry-run", description="Toggle dry-run mode")
    @app_commands.describe(enabled="True to enable, False to disable")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_dry_run(interaction: discord.Interaction, enabled: bool) -> None:
        await state.set_dry_run(enabled)
        if enabled:
            await interaction.response.send_message(
                "✅ Dry-run mode enabled. Actions will be simulated and logged only.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "✅ Dry-run mode disabled. Actions will execute normally.", ephemeral=True
            )

    @tree.command(
        name="set-proactive-moderation",
        description="Toggle proactive moderation (check all messages for violations)",
    )
    @app_commands.describe(
        enabled="True to enable (bot checks all messages), False to disable (only mentioned/conversational)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_proactive_moderation(interaction: discord.Interaction, enabled: bool) -> None:
        await state.set_proactive_moderation(enabled)
        if enabled:
            await interaction.response.send_message(
                "✅ Proactive moderation enabled. Bot will check ALL messages for rule violations.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "✅ Proactive moderation disabled. Bot will only check when mentioned or in conversations.",
                ephemeral=True,
            )

    @tree.command(name="set-persona", description="Configure the bot's persona")
    @app_commands.describe(
        name="Bot's name", description="Description of the bot's role", style="Conversation style"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_persona(
        interaction: discord.Interaction,
        name: str,
        description: str,
        style: str,
    ) -> None:
        try:
            current = (await state.get_state(guild_id=interaction.guild.id)).persona
            persona = PersonaProfile(
                name=name,
                description=description,
                conversation_style=style,
                interests=current.interests,
            )
            await state.set_persona(interaction.guild.id, persona)
            await interaction.response.send_message(
                f"✅ Persona updated for this server.\n• Name: {persona.name}\n• Description: {persona.description}\n• Style: {persona.conversation_style}",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Failed to set persona")
            await interaction.response.send_message(
                f"❌ Failed to set persona: {str(e)}", ephemeral=True
            )

    @tree.command(name="set-interests", description="Set persona interests")
    @app_commands.describe(interests="Comma-separated list of interests")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_interests(interaction: discord.Interaction, interests: str) -> None:
        items = [item.strip() for item in interests.split(",") if item.strip()]
        current = await state.get_state(guild_id=interaction.guild.id)
        persona = PersonaProfile(
            name=current.persona.name,
            description=current.persona.description,
            conversation_style=current.persona.conversation_style,
            interests=items,
        )
        await state.set_persona(interaction.guild.id, persona)
        await interaction.response.send_message(
            f"✅ Persona interests updated for this server: {', '.join(items) if items else 'none'}",
            ephemeral=True,
        )

    @tree.command(name="set-automation", description="Configure channel automation rules")
    @app_commands.describe(
        channel="The channel to automate",
        action="Action to take (kick, ban, delete_message, warn, timeout)",
        summary="Short description of the rule",
        reason="Justification for the action",
        keywords="Comma-separated keywords to trigger (optional)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_automation(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        action: str,
        summary: str,
        reason: str,
        keywords: Optional[str] = None,
    ) -> None:
        if action not in {"kick", "ban", "delete_message", "warn", "timeout"}:
            await interaction.response.send_message(
                "❌ Invalid action. Choose from: kick, ban, delete_message, warn, timeout.",
                ephemeral=True,
            )
            return
        keyword_list: List[str] = []
        if keywords:
            keyword_list = [word.strip() for word in keywords.split(",") if word.strip()]

        rule = AutomationRule(
            channel_id=channel.id,
            trigger_summary=summary,
            action=action,
            justification=reason,
            keywords=keyword_list,
        )
        await state.upsert_automation(rule)
        msg = f"✅ Automation configured for {channel.mention}:\n• Action: {action}\n• Summary: {summary}\n• Reason: {reason}"
        if keyword_list:
            msg += f"\n• Keywords: {', '.join(keyword_list)}"
        await interaction.response.send_message(msg, ephemeral=True)

    @tree.command(name="disable-automation", description="Disable automation for a channel")
    @app_commands.describe(channel="The channel to disable automation for")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_automation(
        interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        removed = await state.deactivate_automation(channel.id)
        if removed:
            await interaction.response.send_message(
                f"✅ Automation disabled for {channel.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No automation rule found for {channel.mention}.", ephemeral=True
            )

    @tree.command(name="run-cron", description="Force an immediate scheduled maintenance check")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def run_cron(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await moderation.handle_scheduled_tick(interaction.guild)
        await interaction.followup.send("✅ Scheduled maintenance check completed.", ephemeral=True)

    @tree.command(name="sync", description="Manually sync bot commands to Discord")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_commands(interaction: discord.Interaction) -> None:
        """Manually sync slash and context menu commands to Discord."""
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await tree.sync()
            await interaction.followup.send(
                f"✅ Synced {len(synced)} commands to Discord.\n"
                f"Commands may take a few minutes to appear in the UI.",
                ephemeral=True,
            )
            logger.info("Manually synced %d commands via /sync command", len(synced))
        except Exception as e:
            logger.exception("Failed to sync commands via /sync command")
            await interaction.followup.send(f"❌ Failed to sync commands: {e}", ephemeral=True)

    @tree.command(name="list-heuristics", description="List active heuristic rules")
    @app_commands.describe(
        rule_type="Filter by rule type (e.g., spam, scam, harassment)",
        show_inactive="Show inactive heuristics too",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_heuristics(
        interaction: discord.Interaction,
        rule_type: Optional[str] = None,
        show_inactive: bool = False,
    ) -> None:
        """List heuristic rules for this server."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from ..db import Database

        db: Database = interaction.client.database  # type: ignore

        try:
            # Fetch heuristics (both guild-specific and global)
            heuristics = await db.fetch_active_heuristics(
                guild_id=interaction.guild.id, min_confidence=0.0
            )

            if not show_inactive:
                heuristics = [h for h in heuristics if h.get("active", True)]

            if rule_type:
                heuristics = [
                    h for h in heuristics if h.get("rule_type", "").lower() == rule_type.lower()
                ]

            if not heuristics:
                filter_msg = f" (type: {rule_type})" if rule_type else ""
                await interaction.followup.send(
                    f"ℹ️ No heuristics found{filter_msg}.", ephemeral=True
                )
                return

            # Group by rule type
            by_type: Dict[str, List] = {}
            for h in heuristics:
                rt = h.get("rule_type", "unknown")
                if rt not in by_type:
                    by_type[rt] = []
                by_type[rt].append(h)

            # Build response
            lines = [f"**Heuristics for {interaction.guild.name}**\n"]

            for rt, rules in sorted(by_type.items()):
                lines.append(f"**{rt}** ({len(rules)} rules):")
                for r in rules[:5]:  # Limit to 5 per type to avoid message length
                    scope = "🌍 global" if r.get("guild_id") is None else "🏠 server"
                    active = "✅" if r.get("active", True) else "❌"
                    pattern = r.get("pattern", "")
                    if len(pattern) > 30:
                        pattern = pattern[:27] + "..."
                    lines.append(
                        f"  {active} `{r.get('id')}` | {scope} | `{r.get('pattern_type')}` | "
                        f"`{pattern}` (conf: {r.get('confidence', 0):.2f})"
                    )
                if len(rules) > 5:
                    lines.append(f"  ... and {len(rules) - 5} more")
                lines.append("")

            total = len(heuristics)
            global_count = sum(1 for h in heuristics if h.get("guild_id") is None)
            server_count = total - global_count

            lines.append(
                f"**Total:** {total} heuristics ({global_count} global, {server_count} server-specific)"
            )

            response = "\n".join(lines)
            if len(response) > 2000:
                response = response[:1997] + "..."

            await interaction.followup.send(response, ephemeral=True)

        except Exception as e:
            logger.exception("Failed to list heuristics")
            await interaction.followup.send(f"❌ Failed to list heuristics: {e}", ephemeral=True)

    @tree.command(name="disable-heuristic", description="Disable a heuristic rule")
    @app_commands.describe(heuristic_id="The ID of the heuristic to disable")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_heuristic(interaction: discord.Interaction, heuristic_id: int) -> None:
        """Disable a heuristic rule."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from ..db import Database

        db: Database = interaction.client.database  # type: ignore

        try:
            await db.toggle_heuristic_active(heuristic_id, False)
            await interaction.followup.send(
                f"✅ Disabled heuristic rule {heuristic_id}.", ephemeral=True
            )
            logger.info(
                "User %s disabled heuristic %s in guild %s",
                interaction.user.id,
                heuristic_id,
                interaction.guild.id,
            )
        except Exception as e:
            logger.exception("Failed to disable heuristic")
            await interaction.followup.send(f"❌ Failed to disable heuristic: {e}", ephemeral=True)

    @tree.command(name="enable-heuristic", description="Enable a heuristic rule")
    @app_commands.describe(heuristic_id="The ID of the heuristic to enable")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable_heuristic(interaction: discord.Interaction, heuristic_id: int) -> None:
        """Enable a heuristic rule."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from ..db import Database

        db: Database = interaction.client.database  # type: ignore

        try:
            await db.toggle_heuristic_active(heuristic_id, True)
            await interaction.followup.send(
                f"✅ Enabled heuristic rule {heuristic_id}.", ephemeral=True
            )
            logger.info(
                "User %s enabled heuristic %s in guild %s",
                interaction.user.id,
                heuristic_id,
                interaction.guild.id,
            )
        except Exception as e:
            logger.exception("Failed to enable heuristic")
            await interaction.followup.send(f"❌ Failed to enable heuristic: {e}", ephemeral=True)

    @tree.command(name="generate-heuristics", description="Generate new heuristics from context")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def generate_heuristics(interaction: discord.Interaction) -> None:
        """Manually trigger heuristic generation from context channels and memories."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            generated = await moderation.generate_heuristics_from_context(interaction.guild)

            if generated > 0:
                await interaction.followup.send(
                    f"✅ Generated {generated} new heuristic rule(s) from server context.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "ℹ️ No new heuristics generated. Existing rules may already cover the context.",
                    ephemeral=True,
                )

            logger.info(
                "User %s triggered heuristic generation in guild %s: %d generated",
                interaction.user.id,
                interaction.guild.id,
                generated,
            )
        except Exception as e:
            logger.exception("Failed to generate heuristics")
            await interaction.followup.send(
                f"❌ Failed to generate heuristics: {e}", ephemeral=True
            )
