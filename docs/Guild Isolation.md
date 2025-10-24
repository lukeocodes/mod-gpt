# Guild Isolation

**Sentinel AI** ensures that server-specific data (context channels and memories) are properly isolated between Discord guilds/servers to prevent cross-contamination of information.

## Overview

When the bot is added to multiple Discord servers, data is managed at different scopes:

### Guild-Specific Data (Always Isolated)

- **Context channels** - Server rules, guidelines, and reference channels
- **Memories** - Administrator-created notes and instructions
- **Guild-specific heuristics** - Custom patterns for detecting violations in a specific server

### Global Data (Shared Across All Servers)

- **Persona** - Bot personality and conversation style
- **LLM configuration** - API key, model, base URL
- **Dry-run mode** - Whether to actually take actions or just describe them
- **Logs channel** - Where moderation logs are sent
- **Global heuristics** - Common patterns (fraud, spam, etc.) that apply everywhere

### Hybrid Data (Can Be Either)

- **Heuristic rules** - Can be global (`guild_id = NULL`) or guild-specific (`guild_id = <server_id>`)
  - Global heuristics catch universal violations (phishing, common scams, spam patterns)
  - Guild-specific heuristics catch server-specific rule violations

## Database Schema

### Context Channels

Context channels are stored with a `guild_id` to ensure they're associated with a specific server:

```sql
CREATE TABLE context_channels (
    channel_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    label TEXT NOT NULL,
    notes TEXT,
    recent_messages TEXT,
    last_fetched TIMESTAMPTZ
);

CREATE INDEX idx_context_channels_guild ON context_channels(guild_id);
```

### Memories

Memories are also guild-scoped:

```sql
CREATE TABLE memories (
    memory_id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    guild_id BIGINT NOT NULL,
    author_id BIGINT,
    author_name TEXT,
    content TEXT NOT NULL
);
```

## Implementation Details

### State Management

The `StateStore.get_state()` method accepts an optional `guild_id` parameter:

```python
# Get state filtered to a specific guild
state = await state_store.get_state(guild_id=message.guild.id)

# Get full state (for admin operations)
state = await state_store.get_state(guild_id=None)
```

When a `guild_id` is provided, the returned `BotState` object contains only:

- Context channels that belong to that guild
- Memories created in that guild
- Global settings (persona, llm, dry_run, etc.)

### System Prompt Generation

The system prompt is built from the guild-filtered state:

```python
# In moderation.py
state = await self._state.get_state(guild_id=message.guild.id)
system_prompt = build_system_prompt(state, built_in_prompt=state.built_in_prompt)
```

This ensures the LLM only has access to context channels and memories relevant to the current server.

### Heuristics (Hybrid: Can Be Global or Guild-Specific)

Heuristic rules are the **only data type** that supports both global and guild-specific scopes:

```sql
CREATE TABLE heuristic_rules (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT,  -- NULL for global rules, or specific guild_id
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    confidence FLOAT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE
);
```

#### Global Heuristics (`guild_id = NULL`)

Apply to **all servers** where the bot is installed:

- **Common fraud patterns** - "free nitro", phishing links, crypto scams
- **Universal spam** - Excessive caps, repeated characters, known spam phrases
- **Platform-wide violations** - Discord TOS violations, illegal content patterns

Example:

```python
# Created by seed_global_heuristics() on startup
await database.insert_heuristic_rule(
    guild_id=None,  # Global rule
    rule_type="fraud_scam",
    pattern=r"free[\s_-]*nitro",
    pattern_type="regex",
    confidence=0.95,
    severity="high",
    reason="Classic Discord Nitro scam pattern"
)
```

#### Guild-Specific Heuristics (`guild_id = <server_id>`)

Apply to **one specific server only**:

- **Custom server rules** - Server-specific banned words or topics
- **Community-specific patterns** - Inside jokes that became problematic
- **Server culture** - What's acceptable in Server A might not be in Server B

Example:

```python
# Created by /generate-heuristics or when moderators flag violations
await database.insert_heuristic_rule(
    guild_id=123456789,  # Specific server
    rule_type="custom_rule",
    pattern="spoiler",
    pattern_type="contains",
    confidence=0.85,
    severity="medium",
    reason="This server requires spoiler tags for game content"
)
```

#### How Heuristics Are Applied

When checking a message for violations, the bot fetches **both** global and guild-specific rules:

```python
# Fetches:
# 1. All global rules (guild_id IS NULL)
# 2. Rules specific to this server (guild_id = message.guild.id)
heuristics = await database.fetch_active_heuristics(
    guild_id=message.guild.id,
    min_confidence=0.0
)
```

This gives you:

- **Consistent baseline protection** across all servers (global rules)
- **Flexibility to customize** per-server rules as needed
- **No rule conflicts** between servers (guild-specific rules stay isolated)

## Command Behavior

### Adding Context Channels

When using `/add-channel`, the bot automatically associates the channel with the current guild:

```python
context_channel = ContextChannel(
    channel_id=channel.id,
    guild_id=interaction.guild.id,  # Automatically scoped
    label=channel.name,
    notes=description,
    recent_messages=recent_messages,
    last_fetched=datetime.now(timezone.utc).isoformat(),
)
```

### Listing Context Channels

The `/list-channels` command only shows channels for the current guild:

```python
current_state = await state.get_state(guild_id=interaction.guild.id)
# Only returns channels for this guild
```

### Adding Memories

The `/remember` command automatically scopes memories to the current guild:

```python
await state.add_memory(
    guild_id=interaction.guild.id,
    content=note,
    author=interaction.user.name,
    author_id=interaction.user.id,
)
```

## Migration from Legacy Data

If you have context channels or memories created before guild isolation was implemented, they may have `guild_id = NULL` or `guild_id = 0`.

To fix legacy data:

```sql
-- Update context channels with missing guild_id
-- (Replace <GUILD_ID> and <CHANNEL_ID> with actual values)
UPDATE context_channels
SET guild_id = <GUILD_ID>
WHERE channel_id = <CHANNEL_ID> AND guild_id IS NULL;

-- Update memories with missing guild_id
UPDATE memories
SET guild_id = <GUILD_ID>
WHERE guild_id = 0 OR guild_id IS NULL;
```

## Testing Guild Isolation

To verify guild isolation is working:

1. Add the bot to two different test servers
2. Add a context channel (e.g., `#rules`) in Server A
3. Add a different context channel (e.g., `#guidelines`) in Server B
4. Use `/list-channels` in Server A - should only show Server A's channels
5. Use `/list-channels` in Server B - should only show Server B's channels
6. Ask the bot a question in Server A - it should only reference Server A's context channels
7. Ask the bot a question in Server B - it should only reference Server B's context channels

## Architecture Benefits

Guild isolation provides:

1. **Privacy** - Server A cannot see Server B's context channels or memories
2. **Relevance** - The bot only considers context relevant to the current server
3. **Scalability** - Each server can customize context and rules independently
4. **Security** - Prevents information leakage between servers
5. **Flexibility** - Global heuristics provide baseline protection while allowing per-server customization
6. **Consistency** - All servers benefit from improved global fraud/spam patterns

## Common Issues

### Bot Mentions Wrong Server's Channels

**Symptom:** Bot references channels or rules from a different server when responding.

**Cause:** The bot is using global state instead of guild-filtered state.

**Fix:** Ensure all calls to `get_state()` in message handlers pass `guild_id`:

```python
# ❌ Wrong - uses global state
state = await self._state.get_state()

# ✅ Correct - uses guild-specific state
state = await self._state.get_state(guild_id=message.guild.id)
```

### Context Channels Not Showing

**Symptom:** `/list-channels` shows no channels even though they were added.

**Cause:** Legacy channels with `guild_id = NULL` or wrong guild_id.

**Fix:** Check database and update guild_id:

```sql
SELECT channel_id, guild_id, label FROM context_channels;
```

## Data Scope Summary

| Data Type          | Scope                    | Why                                             |
| ------------------ | ------------------------ | ----------------------------------------------- |
| Context Channels   | Guild-specific           | Server rules/guidelines are unique per server   |
| Memories           | Guild-specific           | Admin instructions are server-specific          |
| Heuristic Rules    | Global OR Guild-specific | Common patterns (global) + custom rules (guild) |
| Persona            | Global                   | Consistent bot personality across servers       |
| LLM Settings       | Global                   | Single API key/model configuration              |
| Dry-run Mode       | Global                   | Testing mode applies everywhere                 |
| Logs Channel       | Global                   | Single monitoring location                      |
| Moderation Actions | Guild-specific           | Audit log per server (via guild_id)             |
| Conversations      | Guild-specific           | User interactions are per-server (via guild_id) |

## Future Enhancements

Potential improvements to guild isolation:

- **Per-guild persona customization** (currently global) - Allow different bot personalities per server
- **Per-guild LLM settings** (currently global) - Different API keys or models per server
- **Per-guild dry-run mode** (currently global) - Test mode in one server without affecting others
- **Guild-specific logs channels** (currently global) - Separate audit logs per server
- **Migration tool** to automatically fix legacy data with missing guild_id
- **Heuristic analytics** showing which global vs guild-specific rules trigger most often
