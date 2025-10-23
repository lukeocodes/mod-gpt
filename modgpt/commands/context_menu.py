"""Context menu command definitions for ModGPT."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


def register_context_menu_commands(tree: app_commands.CommandTree, moderation) -> None:
    """Register all context menu commands to the command tree."""

    @tree.context_menu(name="Flag for Moderation")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def flag_message(interaction: discord.Interaction, message: discord.Message) -> None:
        """Flag a message that should have been caught by moderation."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used inside a server.", ephemeral=True
            )
            return

        # Show modal to collect reason
        class FlagReasonModal(discord.ui.Modal, title="Flag Message for Moderation"):
            reason = discord.ui.TextInput(
                label="Why should this have been caught?",
                placeholder="e.g., Contains spam, Violates rule #3, Uses offensive language...",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=500,
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)

                try:
                    # Generate heuristic from this feedback
                    generated = await moderation.generate_heuristic_from_feedback(
                        guild=interaction.guild,
                        message=message,
                        reason=self.reason.value,
                    )

                    if generated:
                        await modal_interaction.followup.send(
                            f"✅ Thank you! Generated a new heuristic to catch similar messages.\n"
                            f"**Pattern:** `{generated['pattern']}`\n"
                            f"**Type:** {generated['pattern_type']}\n"
                            f"**Severity:** {generated['severity']}",
                            ephemeral=True,
                        )
                    else:
                        await modal_interaction.followup.send(
                            "✅ Thank you for the feedback! The bot will learn from this.",
                            ephemeral=True,
                        )
                except Exception as e:
                    logger.exception("Failed to generate heuristic from feedback")
                    await modal_interaction.followup.send(
                        f"❌ Failed to generate heuristic: {e}",
                        ephemeral=True,
                    )

        await interaction.response.send_modal(FlagReasonModal())
