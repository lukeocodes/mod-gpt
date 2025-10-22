"""Prompt templates for the moderation reasoning workflow."""

from __future__ import annotations

import uuid
from typing import Dict

from .state import BotState


def _wrap_with_guardrails(content: str) -> str:
    guard_tag = str(uuid.uuid4())
    return f"<{guard_tag}>{content}</{guard_tag}>"


def build_system_prompt(state: BotState, built_in_prompt: str | None = None) -> str:
    persona = state.persona
    context_lines = []
    if state.context_channels:
        for channel in state.context_channels.values():
            context_lines.append(f"- #{channel.label}: {channel.notes or 'No additional notes.'}")
    else:
        context_lines.append("No context channels are currently configured.")

    memory_lines = []
    if state.memories:
        for note in state.memories[:20]:
            memory_lines.append(
                f"- ({note.guild_id}) {note.content} — added by {note.author} on {note.created_at}"
            )
    else:
        memory_lines.append("No persistent memories recorded.")

    dry_run_status = "ENABLED" if state.dry_run else "DISABLED"

    segments = [
        built_in_prompt or "",
        f"You are {persona.name}, an autonomous Discord moderation agent with full administrative authority granted by the server owner.",
        "Core principles:",
        "- Protect community safety while valuing free, inclusive conversation.",
        "- Leverage reference material from configured channels to justify decisions.",
        "- Act transparently: log every action with a rationale.",
        "- When uncertain, gather more context before escalating.",
        "- Use provided functions to take concrete actions. Never invent capabilities.",
        "",
        "Persona traits:",
        f"- Description: {persona.description}",
        f"- Interests: {', '.join(persona.interests) if persona.interests else 'None listed'}",
        f"- Conversation style: {persona.conversation_style}",
        "",
        "Server context channels:",
        "\n".join(context_lines),
        "",
        "Persistent memories:",
        "\n".join(memory_lines),
        "",
        f"Dry-run status: {dry_run_status}. When enabled, describe intended actions instead of executing them.",
    ]

    body = "\n".join(segment for segment in segments if segment)
    return _wrap_with_guardrails(body)


def build_event_prompt(event_name: str, payload: Dict[str, str]) -> str:
    lines = [f"Event type: {event_name}"]
    for key, value in payload.items():
        lines.append(f"{key}: {value}")
    lines.append("Decide on next steps using the available tools.")
    return _wrap_with_guardrails("\n".join(lines))
