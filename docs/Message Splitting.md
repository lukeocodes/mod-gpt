# Message Splitting

## Overview

Discord enforces a maximum message length of 2,000 characters per message. When the bot generates responses that exceed this limit, the message splitting feature automatically divides the content into multiple messages while maintaining readability.

## Architecture Decision

**Decision**: Implement automatic message splitting at the message sending layer

**Rationale**:

- **User Experience**: Long responses should be delivered completely rather than truncated
- **Transparency**: Multiple messages maintain the bot's complete thought process
- **Natural Boundaries**: Smart splitting at paragraphs, sentences, or words maintains context
- **Automatic**: No LLM intervention required - handled at the infrastructure level

**Date**: 2025-10-24

## How It Works

### Split Algorithm

The message splitting utility (`sentinel/utils/discord.py`) uses a hierarchical approach to find natural split points:

1. **First Priority - Paragraph Boundaries**: Splits at newlines (`\n`) if found in the latter half of the allowed length
2. **Second Priority - Sentence Boundaries**: Splits at periods followed by spaces if no good newline exists
3. **Third Priority - Word Boundaries**: Splits at spaces to avoid breaking words
4. **Last Resort**: Hard splits at the character limit (rare, only for very long words/URLs)

### Message Sending Behavior

When `send_message` is called with content exceeding 2,000 characters:

1. Content is split into chunks using the smart splitting algorithm
2. Each chunk is sent as a separate message in sequence
3. Only the first message uses the reply reference (if provided)
4. All messages are recorded for analytics and conversation tracking
5. The last message is used as the conversation continuation point

### Example

```python
# Input: 3,500 character message
long_message = "..." * 3500

# Output: 2 messages
# Message 1: ~2,000 characters (split at paragraph)
# Message 2: ~1,500 characters (remaining content)
```

## Implementation Details

### Key Components

1. **`sentinel/utils/discord.py:split_message()`**

   - Core splitting logic
   - Configurable max length (defaults to 2,000)
   - Returns list of message chunks

2. **`sentinel/services/moderation.py:_tool_send_message()`**
   - Calls `split_message()` before sending
   - Sends each chunk sequentially
   - Handles reply references and threading for split messages

### Edge Cases Handled

- **Empty chunks**: Stripped whitespace means no empty messages are sent
- **Single word longer than limit**: Falls back to hard split (extremely rare)
- **Code blocks**: May be split mid-block (future enhancement: preserve code blocks)
- **Mentions/formatting**: Preserved across splits (Discord handles this automatically)

## Configuration

No configuration is required - message splitting is automatic and always enabled.

### Constants

- `DISCORD_MAX_MESSAGE_LENGTH = 2000` (defined in `sentinel/utils/discord.py`)
- Can be adjusted if Discord changes their limits

## Testing

The splitting algorithm can be tested independently:

```python
from sentinel.utils.discord import split_message

# Test short message (no split needed)
assert split_message("Hello") == ["Hello"]

# Test long message (requires split)
long_msg = "a" * 3000
chunks = split_message(long_msg)
assert len(chunks) == 2
assert all(len(chunk) <= 2000 for chunk in chunks)

# Test natural boundaries
paragraph_msg = ("Paragraph 1.\n" * 100) + ("Paragraph 2.\n" * 100)
chunks = split_message(paragraph_msg)
# Should split at paragraph boundaries
```

## Future Enhancements

1. **Code Block Preservation**: Detect triple-backtick code blocks and avoid splitting inside them
2. **Embed Support**: Handle embeds differently (embeds have different length limits)
3. **Continuation Indicators**: Add "..." or "(continued)" markers between split messages
4. **Smart Numbering**: For list-based responses, ensure lists aren't split awkwardly

## Related Documentation

- [Architecture Overview](./Architecture%20Overview.md) - Overall bot architecture
- [Heuristics System](./Heuristics%20System.md) - How bot learns patterns
- Discord API Limits: https://discord.com/developers/docs/resources/channel#create-message

## Troubleshooting

### Messages are being cut off mid-sentence

This shouldn't happen with the current implementation, but if it does:

1. Check if the message contains very long paragraphs (>1000 characters) with no natural boundaries
2. Verify the split algorithm is finding sentence/word boundaries correctly
3. Add logging to see where splits are occurring

### Bot is sending too many messages

If the bot is generating excessively long responses (multiple splits):

1. Consider adjusting the system prompt to encourage more concise responses
2. Review the LLM's output to understand why it's generating such long content
3. This is working as intended - the alternative is truncation

### Split messages lose context

The split algorithm preserves all content - no truncation occurs. If context appears lost:

1. Verify the conversation manager is tracking the last message correctly
2. Check that reply references are working for the first chunk
3. Ensure threading behavior is correct for multi-message responses
