# Per-Guild Configuration

**Sentinel AI** supports full per-guild (server) configuration, allowing each Discord server to have its own independent settings, persona, context channels, memories, and more. This ensures complete data isolation and prevents cross-contamination of information between servers.

## Overview

When the bot is added to multiple Discord servers, configuration and data are managed at two distinct scopes:

### Guild-Specific Data (Isolated Per Server)

- **Context channels** - Server rules, guidelines, and reference channels
- **Memories** - Administrator-created notes and instructions
- **Persona** - Bot personality and conversation style
- **Logs channel** - Where moderation logs are sent
- **Bot nickname** - Display name in the server
- **Dry-run mode** - Whether to simulate actions or execute them
- **Proactive moderation** - Whether to check all messages or only when mentioned
- **Built-in prompt** - Custom system prompt instructions
- **Guild-specific heuristics** - Custom patterns for detecting violations
- **Moderation actions** - Audit log of actions taken
- **Conversation threads** - User interaction history

### Global Data (Shared Across All Servers)

- **LLM settings** - API key, model, base URL (single configuration for all servers)
- **Global heuristics** - Common fraud/spam patterns that apply everywhere

### Hybrid Data

- **Heuristic rules** - Can be global (`guild_id = NULL`) or guild-specific (`guild_id = <server_id>`)
  - Global heuristics catch universal violations (phishing, common scams, spam patterns)
  - Guild-specific heuristics catch server-specific rule violations

## Database Schema

### Guild Configuration Table

Stores per-guild settings:

```sql
CREATE TABLE guild_config (
    guild_id BIGINT PRIMARY KEY,
    logs_channel_id BIGINT,
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    proactive_moderation BOOLEAN NOT NULL DEFAULT TRUE,
    bot_nickname TEXT,
    built_in_prompt TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Persona Profile Table

Each guild has its own persona:

```sql
CREATE TABLE persona_profile (
    guild_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    conversation_style TEXT NOT NULL,
    interests JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Context Channels Table

Context channels are stored with a `guild_id`:

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

### Memories Table

Memories are guild-scoped:

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

### Heuristic Rules Table

Heuristics can be global or guild-specific:

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

### Other Guild-Scoped Tables

- `moderation_actions` - Has `guild_id`
- `conversation_threads` - Has `guild_id`
- `conversation_messages` - Has `guild_id` via thread

## State Management

### Loading Guild State

The `StateStore.get_state(guild_id)` method loads configuration on-demand from the database:

```python
# For guild-specific operations (most common)
state = await state_store.get_state(guild_id=message.guild.id)

# For global operations (LLM settings, health checks)
state = await state_store.get_state(guild_id=None)
```

When a `guild_id` is provided, the returned `BotState` object contains:

- Context channels that belong to that guild
- Memories created in that guild
- Persona configured for that guild
- Guild-specific configuration (logs channel, dry-run, etc.)
- Global settings (LLM configuration)

### Guild-Specific Methods

All configuration methods require `guild_id`:

```python
# Configuration
await state.set_logs_channel(guild_id, channel_id)
await state.set_persona(guild_id, persona)
await state.set_dry_run(guild_id, enabled)
await state.set_proactive_moderation(guild_id, enabled)
await state.set_bot_nickname(guild_id, nickname)
await state.set_built_in_prompt(guild_id, prompt)

# Context channels
await state.add_context_channel(channel)  # channel.guild_id must be set
await state.remove_context_channel(channel_id)

# Memories
await state.add_memory(guild_id, content, author, author_id)
await state.remove_memory(guild_id, memory_id)
```

### Database Queries

All database methods fetch guild-specific data:

```python
# Fetch methods
await db.fetch_persona(guild_id)
await db.fetch_guild_config(guild_id)
await db.fetch_context_channels(guild_id)
await db.fetch_memories(guild_id)

# Update methods
await db.set_persona(guild_id, ...)
await db.upsert_guild_config(guild_id, ...)
```

### Performance Considerations

**Trade-off:** Configuration is fetched from the database on every message instead of caching in memory.

**Why it's okay:**

- PostgreSQL is fast for simple lookups by primary key
- Guild configs are small (few KB)
- Simplifies code (no cache invalidation logic needed)
- Enables true multi-tenancy
- Can add caching layer later if needed

**If performance becomes an issue:**

```python
# Add simple in-memory cache with TTL
self._guild_config_cache = {}  # guild_id -> (config, timestamp)
```

## Slash Commands

All slash commands operate on guild-specific configuration:

### Configuration Commands

- `/set-logs` - Sets logs channel for current guild
- `/set-persona` - Sets persona for current guild
- `/set-interests` - Sets persona interests for current guild
- `/set-nickname` - Sets bot nickname for current guild
- `/set-dry-run` - Sets dry-run mode for current guild
- `/set-proactive-moderation` - Sets proactive moderation for current guild
- `/set-built-in-prompt` - Sets custom prompt for current guild

### Context & Memory Commands

- `/add-channel` - Adds context channel to current guild
- `/remove-channel` - Removes context channel from current guild
- `/list-channels` - Lists channels for current guild only
- `/refresh-channel` - Refreshes a context channel in current guild
- `/remember` - Adds memory to current guild
- `/forget-memory` - Removes memory from current guild
- `/list-memories` - Lists memories for current guild only

### Heuristic Commands

- `/list-heuristics` - Shows both global and guild-specific heuristics
- `/generate-heuristics` - Generates guild-specific heuristics from context
- `/enable-heuristic` - Enables a heuristic rule
- `/disable-heuristic` - Disables a heuristic rule

## Implementation Details

### Message Handlers

All message handlers in `moderation.py` fetch guild-specific state:

```python
# In handle_message, handle_message_edit, etc.
state = await self._state.get_state(guild_id=message.guild.id)
```

This ensures each message is processed with the correct guild's configuration.

### System Prompt Generation

The system prompt is built from guild-filtered state:

```python
# In moderation.py
state = await self._state.get_state(guild_id=message.guild.id)
system_prompt = build_system_prompt(state, built_in_prompt=state.built_in_prompt)
```

This ensures the LLM only has access to context channels and memories relevant to the current server.

### Bot Initialization

On startup, the bot applies per-guild settings:

```python
# In bot.py on_ready event
for guild in bot.guilds:
    guild_state = await state.get_state(guild_id=guild.id)
    nickname = guild_state.bot_nickname
    if nickname:
        me = guild.me
        if me and me.nick != nickname:
            try:
                await me.edit(nick=nickname)
            except discord.Forbidden:
                logger.warning(f"Can't set nickname in guild {guild.id}")
```

### Context Channel Auto-Refresh

When messages are added/edited/deleted in context channels, they're automatically refreshed:

```python
# In bot.py message handlers
if message.guild:
    current_state = await state.get_state(guild_id=message.guild.id)
    if message.channel.id in current_state.context_channels:
        await state.refresh_context_channel(message.channel.id, bot, llm)
```

## Heuristics: Global vs Guild-Specific

### Global Heuristics (`guild_id = NULL`)

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

### Guild-Specific Heuristics (`guild_id = <server_id>`)

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

### How Heuristics Are Applied

When checking a message, the bot fetches **both** global and guild-specific rules:

```python
# Fetches:
# 1. All global rules (guild_id IS NULL)
# 2. Rules specific to this server (guild_id = message.guild.id)
heuristics = await database.fetch_active_heuristics(
    guild_id=message.guild.id,
    min_confidence=0.0
)
```

Benefits:

- **Consistent baseline protection** across all servers (global rules)
- **Flexibility to customize** per-server rules as needed
- **No rule conflicts** between servers (guild-specific rules stay isolated)

## Data Scope Summary

| Data Type            | Scope                    | Table                  | Key Field                |
| -------------------- | ------------------------ | ---------------------- | ------------------------ |
| Context Channels     | Per-Guild                | `context_channels`     | `guild_id`               |
| Memories             | Per-Guild                | `memories`             | `guild_id`               |
| Persona              | Per-Guild                | `persona_profile`      | `guild_id` (PK)          |
| Logs Channel         | Per-Guild                | `guild_config`         | `guild_id` (PK)          |
| Dry-Run Mode         | Per-Guild                | `guild_config`         | `guild_id` (PK)          |
| Bot Nickname         | Per-Guild                | `guild_config`         | `guild_id` (PK)          |
| Built-in Prompt      | Per-Guild                | `guild_config`         | `guild_id` (PK)          |
| Proactive Moderation | Per-Guild                | `guild_config`         | `guild_id` (PK)          |
| Moderation Actions   | Per-Guild                | `moderation_actions`   | `guild_id`               |
| Conversation Threads | Per-Guild                | `conversation_threads` | `guild_id`               |
| Heuristic Rules      | Global OR Guild-specific | `heuristic_rules`      | `guild_id` (NULL=global) |
| LLM Settings         | Global                   | `bot_config`           | N/A                      |

## Testing Guild Isolation

To verify guild isolation is working correctly:

### Setup

1. Add the bot to two different test servers (Server A and Server B)

### Server A Configuration

```
/set-persona name:"Guardian A" description:"Strict moderator" style:"Formal and direct"
/add-channel channel:#rules-a description:"Server A rules"
/remember note:"This server prohibits all advertising"
/set-nickname nickname:"Guardian"
```

### Server B Configuration

```
/set-persona name:"Helper B" description:"Friendly assistant" style:"Casual and helpful"
/add-channel channel:#welcome-b description:"Server B welcome guide"
/remember note:"This server allows self-promotion in #promo"
/set-nickname nickname:"Helper"
```

### Verification

- `/list-channels` in Server A shows only Server A's channels
- `/list-channels` in Server B shows only Server B's channels
- Bot in Server A has nickname "Guardian"
- Bot in Server B has nickname "Helper"
- Bot responses in Server A reference only Server A's context and memories
- Bot responses in Server B reference only Server B's context and memories

## Architecture Benefits

### Before (Global State)

- Single persona across all servers
- Context channels visible to all servers
- Memories mixed between servers
- One logs channel for everything
- Configuration applied globally

### After (Per-Guild)

- Each server has its own persona
- Context channels isolated per server
- Memories scoped to specific server
- Each server has its own logs channel
- Each server configured independently

### Advantages

1. **Privacy** - Server A cannot see Server B's context channels or memories
2. **Relevance** - The bot only considers context relevant to the current server
3. **Scalability** - Each server can customize settings independently
4. **Security** - Prevents information leakage between servers
5. **Flexibility** - Global heuristics provide baseline protection while allowing per-server customization
6. **Consistency** - All servers benefit from improved global fraud/spam patterns

## Troubleshooting

### Bot references wrong server's data

**Symptom:** Bot mentions channels or rules from a different server when responding.

**Cause:** Not passing `guild_id` to `get_state()`

**Fix:** Ensure all calls include the guild_id:

```python
# ❌ Wrong - uses global/minimal state
state = await self._state.get_state()

# ✅ Correct - uses guild-specific state
state = await self._state.get_state(guild_id=message.guild.id)
```

### Context channels not showing

**Symptom:** `/list-channels` shows no channels even though they were added.

**Cause:** Channels have wrong or missing `guild_id` in database.

**Fix:** Check database and verify guild_id:

```sql
SELECT channel_id, guild_id, label FROM context_channels;
```

### Data not persisting

**Cause:** Database not connected.

**Fix:** Check `DATABASE_URL` environment variable and verify connection.

### Persona showing as default

**Cause:** No persona configured for guild yet.

**Fix:** Run `/set-persona` to configure persona for the guild.

### Guild config not found

**Cause:** First time accessing guild, no config row exists yet.

**Fix:** Configuration is created on-demand with defaults. Use slash commands to set values.

## Migration Instructions

### Fresh Installation

For new deployments, the bot will automatically create the correct schema on first run.

### Migrating from Legacy Data

If you have an existing deployment with global configuration:

**YOU MUST DROP THE DATABASE** before deploying this version. There's no automated migration path.

```sql
-- Drop all tables
DROP TABLE IF EXISTS conversation_messages CASCADE;
DROP TABLE IF EXISTS conversation_threads CASCADE;
DROP TABLE IF EXISTS heuristic_feedback CASCADE;
DROP TABLE IF EXISTS heuristic_rules CASCADE;
DROP TABLE IF EXISTS memories CASCADE;
DROP TABLE IF EXISTS member_engagement CASCADE;
DROP TABLE IF EXISTS channel_activity CASCADE;
DROP TABLE IF EXISTS persona_profile CASCADE;
DROP TABLE IF EXISTS automations CASCADE;
DROP TABLE IF EXISTS context_channels CASCADE;
DROP TABLE IF EXISTS moderation_actions CASCADE;
DROP TABLE IF EXISTS bot_config CASCADE;
DROP TABLE IF EXISTS guild_config CASCADE;

-- The bot will recreate all tables on first run
```

### Deployment Steps

1. **Backup any important data** (memories, context channels, persona settings)
2. **Drop the database** as shown above
3. **Deploy the new code**
4. **Bot will auto-create new schema** on startup
5. **Reconfigure each guild:**
   - `/set-persona` - Set persona for each server
   - `/add-channel` - Re-add context channels
   - `/remember` - Re-add memories
   - `/set-logs` - Set logs channel
   - Other settings as needed

## Code Examples

### Getting Guild State

```python
# In message handlers
state = await self._state.get_state(guild_id=message.guild.id)

# In slash commands
state = await state.get_state(guild_id=interaction.guild.id)

# For health checks (no guild context)
state = await state.get_state(guild_id=None)  # Returns minimal state
```

### Setting Guild Config

```python
# Set persona for a guild
await state.set_persona(guild_id, persona)

# Set logs channel
await state.set_logs_channel(guild_id, channel_id)

# Set dry-run mode
await state.set_dry_run(guild_id, enabled)
```

### Adding Guild Data

```python
# Add context channel
channel = ContextChannel(
    channel_id=channel.id,
    guild_id=guild.id,  # Required
    label=channel.name,
    notes=description,
    recent_messages=recent_messages,
    last_fetched=datetime.now(timezone.utc).isoformat(),
)
await state.add_context_channel(channel)

# Add memory
await state.add_memory(
    guild_id=guild.id,  # Required
    content=content,
    author=author,
    author_id=author_id,
)
```

## Future Enhancements

Potential improvements:

1. **Caching layer** - Cache guild configs in memory with TTL
2. **Bulk operations** - Load all guilds' configs at startup for faster first access
3. **Guild defaults** - Set default configs that new guilds inherit
4. **Config export/import** - Copy settings from one guild to another
5. **Per-guild LLM settings** - Allow different API keys per guild (enterprise feature)
6. **Migration tool** - Automatically fix legacy data with missing guild_id
7. **Heuristic analytics** - Dashboard showing which rules trigger most often per guild

## Files Modified

Implementation touches these key files:

1. `sentinel/db.py` - Database schema and methods
2. `sentinel/services/state.py` - State management (major refactor)
3. `sentinel/services/moderation.py` - Pass guild_id to get_state()
4. `sentinel/commands/slash.py` - Update commands with guild_id
5. `sentinel/bot.py` - Per-guild nickname logic and context refresh
6. `sentinel/health.py` - Health endpoint uses global state

## Summary

This implementation provides true multi-tenancy for Sentinel AI:

- ✅ Each guild is completely isolated
- ✅ Per-guild configuration for all settings
- ✅ Global heuristics work across all guilds
- ✅ No data leakage between servers
- ✅ Simple, maintainable architecture
- ✅ Easy to add new per-guild settings

The bot is now ready to serve multiple independent Discord communities with confidence that their data won't mix!
