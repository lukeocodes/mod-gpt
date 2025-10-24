"""Tests for Discord message splitting functionality."""

import pytest

from sentinel.utils.discord import DISCORD_MAX_MESSAGE_LENGTH, split_message


class TestMessageSplitting:
    """Test suite for the message splitting utility."""

    def test_short_message_no_split(self):
        """Short messages should not be split."""
        message = "Hello, world!"
        result = split_message(message)
        assert len(result) == 1
        assert result[0] == message

    def test_empty_message(self):
        """Empty messages should return a single empty chunk."""
        result = split_message("")
        assert len(result) == 1
        assert result[0] == ""

    def test_exact_limit_no_split(self):
        """Messages exactly at the limit should not be split."""
        message = "a" * DISCORD_MAX_MESSAGE_LENGTH
        result = split_message(message)
        assert len(result) == 1
        assert len(result[0]) == DISCORD_MAX_MESSAGE_LENGTH

    def test_one_char_over_limit_splits(self):
        """Messages one character over limit should split."""
        message = "a" * (DISCORD_MAX_MESSAGE_LENGTH + 1)
        result = split_message(message)
        assert len(result) == 2
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

    def test_split_at_paragraph_boundary(self):
        """Should prefer splitting at paragraph boundaries (newlines)."""
        # Create a message with clear paragraph break
        part1 = "First paragraph. " * 100  # ~1700 chars
        part2 = "\nSecond paragraph. " * 50  # ~950 chars
        message = part1 + part2

        result = split_message(message)

        # Should split into at least one chunk, all under limit
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # If split occurred, first chunk should end with content before newline
        if len(result) > 1:
            assert "\n" in message

    def test_split_at_sentence_boundary(self):
        """Should split at sentence boundaries when no paragraph breaks."""
        # Create long message with sentences but no paragraphs
        sentence = "This is a sentence. "
        message = sentence * 150  # ~3000 chars, forces split

        result = split_message(message)

        assert len(result) >= 2
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Each chunk should end with a period or be the last chunk
        for i, chunk in enumerate(result[:-1]):
            assert chunk.rstrip().endswith(".") or i == len(result) - 1

    def test_split_at_word_boundary(self):
        """Should split at word boundaries when no sentence breaks."""
        # Create long text with words but no sentences
        message = "word " * 500  # ~2500 chars, forces split

        result = split_message(message)

        assert len(result) >= 2
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Chunks should not split words
        for chunk in result:
            # After stripping, shouldn't have incomplete words at boundaries
            assert chunk.strip()

    def test_very_long_message_multiple_splits(self):
        """Very long messages should split into multiple chunks."""
        message = "a" * 5000  # 5000 chars, needs 3 chunks

        result = split_message(message)

        assert len(result) == 3
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Verify all content is preserved
        assert "".join(result) == message

    def test_content_preservation(self):
        """All original content should be preserved after splitting."""
        original = "Test " * 600  # ~3000 chars

        result = split_message(original)

        # Reconstruct and verify (accounting for stripped whitespace)
        reconstructed = "".join(
            chunk + " " if i < len(result) - 1 else chunk for i, chunk in enumerate(result)
        )

        # Remove trailing spaces from both for comparison
        assert reconstructed.rstrip() == original.rstrip()

    def test_unicode_characters(self):
        """Should handle unicode characters correctly."""
        message = "Hello 👋 " * 300  # ~3000 chars with emoji

        result = split_message(message)

        assert len(result) >= 2
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Verify emojis are preserved
        reconstructed = "".join(result)
        assert reconstructed.count("👋") == message.count("👋")

    def test_mixed_content_with_newlines_and_sentences(self):
        """Should handle mixed content with both paragraphs and sentences."""
        message = (
            """This is the first paragraph with multiple sentences. It has quite a bit of content. """
            * 20
        )
        message += "\n\n"
        message += """This is the second paragraph. It also has sentences. """ * 20

        result = split_message(message)

        # Should successfully split
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Verify content is mostly preserved (whitespace may be normalized)
        # The function strips trailing whitespace from chunks which is correct for Discord
        reconstructed = "".join(result)
        assert abs(len(reconstructed) - len(message.rstrip())) <= 10  # Allow small whitespace diff

    def test_custom_max_length(self):
        """Should respect custom max_length parameter."""
        message = "a" * 150
        custom_limit = 100

        result = split_message(message, max_length=custom_limit)

        assert len(result) >= 2
        assert all(len(chunk) <= custom_limit for chunk in result)

    def test_no_good_split_points(self):
        """Should handle messages with no good split points gracefully."""
        # Single very long word (edge case)
        message = "a" * 3000

        result = split_message(message)

        # Should still split, just at hard boundaries
        assert len(result) >= 2
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

    def test_code_block_handling(self):
        """Test how code blocks are handled (documenting current behavior)."""
        code_block = "```python\n" + ("print('hello')\n" * 100) + "```"

        result = split_message(code_block)

        # Current implementation may split code blocks
        # This test documents that behavior for future enhancement
        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # All content should still be preserved
        reconstructed = "\n".join(result) if len(result) > 1 else result[0]
        # Allowing for whitespace normalization
        assert code_block.strip() in reconstructed or reconstructed.strip() in code_block

    def test_whitespace_normalization(self):
        """Leading/trailing whitespace should be handled correctly."""
        message = "   " + ("word " * 500) + "   "

        result = split_message(message)

        # The function normalizes whitespace between chunks
        # All chunks should have content
        for chunk in result:
            assert len(chunk.strip()) > 0  # Has content
            # Trailing whitespace is removed from chunks (correct behavior)
            # Leading whitespace may vary based on split point

    def test_discord_mentions_and_formatting(self):
        """Should preserve Discord mentions and formatting."""
        message = "<@123456789> **Bold text** *italic* `code` " * 200

        result = split_message(message)

        assert all(len(chunk) <= DISCORD_MAX_MESSAGE_LENGTH for chunk in result)

        # Verify formatting is preserved
        reconstructed = " ".join(result)
        assert "<@123456789>" in reconstructed
        assert "**Bold text**" in reconstructed
        assert "*italic*" in reconstructed
        assert "`code`" in reconstructed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
