"""Command registration for Sentinel AI."""

from .context_menu import register_context_menu_commands
from .slash import register_slash_commands

__all__ = ["register_slash_commands", "register_context_menu_commands"]
