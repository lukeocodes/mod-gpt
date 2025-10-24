"""Discord-specific utility functions."""

from __future__ import annotations

from typing import List

# Discord's maximum message length
DISCORD_MAX_MESSAGE_LENGTH = 2000


def split_message(content: str, max_length: int = DISCORD_MAX_MESSAGE_LENGTH) -> List[str]:
    """Split a message into chunks that fit within Discord's character limit.

    This function intelligently splits messages at natural boundaries (newlines,
    sentences, words) to maintain readability while respecting Discord's 2000
    character limit per message.

    Args:
        content: The message content to split
        max_length: Maximum length per chunk (default: 2000 for Discord)

    Returns:
        List of message chunks, each under max_length characters

    Examples:
        >>> split_message("Short message")
        ["Short message"]

        >>> long_msg = "a" * 3000
        >>> chunks = split_message(long_msg)
        >>> len(chunks)
        2
        >>> all(len(chunk) <= 2000 for chunk in chunks)
        True
    """
    if len(content) <= max_length:
        return [content]

    chunks: List[str] = []
    remaining = content

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find the best split point within max_length
        split_point = max_length

        # Try to split at a newline (paragraph boundary)
        newline_pos = remaining.rfind("\n", 0, max_length)
        if newline_pos > max_length * 0.5:  # Only use if it's past halfway point
            split_point = newline_pos + 1  # Include the newline in current chunk

        # If no good newline, try to split at a sentence boundary
        elif "." in remaining[:max_length]:
            # Look for sentence endings: period followed by space or end
            for i in range(max_length - 1, int(max_length * 0.5), -1):
                if remaining[i] == "." and (i + 1 >= len(remaining) or remaining[i + 1] in " \n"):
                    split_point = i + 1
                    break

        # If no sentence boundary, try to split at a word boundary
        else:
            space_pos = remaining.rfind(" ", 0, max_length)
            if space_pos > max_length * 0.5:  # Only use if it's past halfway point
                split_point = space_pos + 1  # Include the space

        # Extract the chunk and update remaining
        chunk = remaining[:split_point].rstrip()
        if chunk:  # Only add non-empty chunks
            chunks.append(chunk)

        remaining = remaining[split_point:].lstrip()

    return chunks
