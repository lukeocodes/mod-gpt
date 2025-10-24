# Database Schema

**Sentinel AI** uses PostgreSQL for persistent storage of moderation actions, heuristics, conversations, and bot state.

## Tables

### `moderation_actions`

Audit log of all moderation actions taken by the bot.

```sql
CREATE TABLE moderation_actions (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    guild_id BIGINT NOT NULL,
    channel_id BIGINT,
    action_type VARCHAR(50) NOT NULL,
    target_user_id BIGINT,
    target_username VARCHAR(255),
    summary TEXT NOT NULL,
    reason TEXT,
    message_id BIGINT,
    metadata JSONB
);

CREATE INDEX idx_moderation_actions_guild ON moderation_actions(guild_id, created_at DESC);
CREATE INDEX idx_moderation_actions_user ON moderation_actions(target_user_id, created_at DESC);
CREATE INDEX idx_moderation_actions_type ON moderation_actions(action_type, created_at DESC);
```

**Fields:**

- `id`: Auto-incrementing primary key
- `created_at`: Timestamp of the action
- `guild_id`: Discord server ID
- `channel_id`: Discord channel ID (nullable)
- `action_type`: Type of action (delete_message, warn, timeout, kick, ban, flag, message_sent, etc.)
- `target_user_id`: User affected by the action (nullable)
- `target_username`: Username at time of action
- `summary`: Human-readable description of what happened
- `reason`: Justification for the action
- `message_id`: Discord message ID (nullable)
- `metadata`: Additional structured data (JSON)

### `heuristic_rules`

Pattern-based detection rules for fast-path moderation.

```sql
CREATE TABLE heuristic_rules (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    guild_id BIGINT,  -- NULL for global rules
    rule_type VARCHAR(100) NOT NULL,
    pattern TEXT NOT NULL,
    pattern_type VARCHAR(50) NOT NULL,  -- exact, regex, fuzzy, contains
    confidence REAL NOT NULL,  -- 0.0 to 1.0
    severity VARCHAR(50) NOT NULL,  -- low, medium, high, critical
    reason TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB
);

CREATE INDEX idx_heuristic_rules_guild ON heuristic_rules(guild_id, active);
CREATE INDEX idx_heuristic_rules_type ON heuristic_rules(rule_type, active);
CREATE INDEX idx_heuristic_rules_pattern ON heuristic_rules(pattern_type, active);
```

**Fields:**

- `id`: Auto-incrementing primary key
- `created_at`: When the rule was created
- `guild_id`: Server ID (NULL = global rule applies to all servers)
- `rule_type`: Category (fraud_scam, spam, hate_speech, harassment, etc.)
- `pattern`: The pattern to match (word, phrase, regex, etc.)
- `pattern_type`: How to match (exact, regex, fuzzy, contains)
- `confidence`: How confident the pattern indicates a violation (0.0-1.0)
- `severity`: Impact level (low, medium, high, critical)
- `reason`: Why this pattern is problematic
- `active`: Whether to use this rule (allows soft deletion)
- `metadata`: Additional data (source, examples, etc.)

**Pattern Types:**

- `exact`: Word boundaries required (e.g., "spam" matches " spam " but not "spammer")
- `regex`: Regular expression pattern (e.g., `r"free[\s_\-]*nitro"`)
- `fuzzy`: Allows typos and variations (Levenshtein distance)
- `contains`: Simple substring match (case-insensitive)

### `conversations`

Tracks multi-turn conversations between users and the bot.

```sql
CREATE TABLE conversations (
    conversation_id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    thread_id BIGINT,  -- Discord thread ID if conversation moved to thread
    starter_user_id BIGINT NOT NULL,
    starter_message_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE INDEX idx_conversations_active ON conversations(guild_id, channel_id, ended_at)
    WHERE ended_at IS NULL;
CREATE INDEX idx_conversations_thread ON conversations(thread_id)
    WHERE thread_id IS NOT NULL;
CREATE INDEX idx_conversations_user ON conversations(starter_user_id, ended_at);
```

**Fields:**

- `conversation_id`: Auto-incrementing primary key
- `guild_id`: Discord server ID
- `channel_id`: Original channel where conversation started
- `thread_id`: Thread ID if conversation moved to a thread
- `starter_user_id`: User who initiated the conversation
- `starter_message_id`: First message in the conversation
- `created_at`: When conversation started
- `last_activity_at`: Last message timestamp (for timeout detection)
- `ended_at`: When conversation ended (NULL = active)
- `metadata`: Additional data (exit reason, etc.)

### `conversation_participants`

Links users to conversations (many-to-many relationship).

```sql
CREATE TABLE conversation_participants (
    conversation_id BIGINT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, user_id)
);

CREATE INDEX idx_conversation_participants_user ON conversation_participants(user_id);
```

**Fields:**

- `conversation_id`: Foreign key to conversations table
- `user_id`: Discord user ID
- `joined_at`: When user joined the conversation

### `conversation_messages`

Individual messages within conversations for context.

```sql
CREATE TABLE conversation_messages (
    message_id BIGINT PRIMARY KEY,  -- Discord message ID
    conversation_id BIGINT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL,
    author_name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    is_bot BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversation_messages_conversation ON conversation_messages(conversation_id, created_at DESC);
```

**Fields:**

- `message_id`: Discord message ID (primary key)
- `conversation_id`: Foreign key to conversations table
- `author_id`: Discord user ID of message author
- `author_name`: Username at time of message
- `content`: Message text
- `is_bot`: Whether message was from the bot
- `created_at`: When message was sent

### `bot_state`

Persistent bot configuration (single row).

```sql
CREATE TABLE bot_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    state_data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (id = 1)  -- Ensure only one row
);
```

**Fields:**

- `id`: Always 1 (enforced by CHECK constraint)
- `state_data`: Complete BotState serialized as JSON
- `updated_at`: Last modification timestamp

**State Data Structure (JSON):**

```json
{
  "context_channels": {
    "123456789": {
      "channel_id": 123456789,
      "label": "rules",
      "notes": "Server rules and guidelines",
      "recent_messages": "Summary of channel content...",
      "last_fetched": "2025-10-23T12:00:00Z"
    }
  },
  "persona": {
    "name": "Sentinel",
    "description": "A diligent, fair Discord moderator...",
    "interests": ["community safety", "transparency"],
    "conversation_style": "Friendly, concise..."
  },
  "logs_channel_id": 987654321,
  "bot_nickname": "ModBot",
  "memories": [
    {
      "memory_id": 1,
      "guild_id": 111222333,
      "content": "Always warn before timeout...",
      "author": "AdminUser",
      "author_id": 444555666,
      "created_at": "2025-10-23T10:00:00Z"
    }
  ],
  "dry_run": false,
  "proactive_moderation": true,
  "llm": {
    "api_key": "sk-...",
    "model": "gpt-4o-mini",
    "base_url": null
  }
}
```

## Queries & Analytics

### Recent Moderation Actions

```sql
SELECT action_type, target_username, reason, created_at
FROM moderation_actions
WHERE guild_id = $1
ORDER BY created_at DESC
LIMIT 50;
```

### Top Violated Heuristics

```sql
SELECT h.rule_type, h.pattern, COUNT(m.id) AS violation_count
FROM heuristic_rules h
LEFT JOIN moderation_actions m
    ON m.metadata->>'matched_heuristic_id' = h.id::text
WHERE h.guild_id = $1 OR h.guild_id IS NULL
GROUP BY h.id
ORDER BY violation_count DESC
LIMIT 20;
```

### User Moderation History

```sql
SELECT action_type, reason, created_at, summary
FROM moderation_actions
WHERE target_user_id = $1
ORDER BY created_at DESC;
```

### Active Conversations

```sql
SELECT c.conversation_id, c.channel_id, c.thread_id,
       u.user_id, c.last_activity_at
FROM conversations c
JOIN conversation_participants u ON c.conversation_id = u.conversation_id
WHERE c.guild_id = $1 AND c.ended_at IS NULL
ORDER BY c.last_activity_at DESC;
```

## Maintenance

### Cleanup Stale Conversations

Conversations older than 24 hours are automatically cleaned up:

```sql
UPDATE conversations
SET ended_at = NOW()
WHERE ended_at IS NULL
  AND last_activity_at < NOW() - INTERVAL '24 hours';
```

### Archive Old Actions

Optionally partition or archive moderation_actions older than 90 days:

```sql
-- Example: Move to archive table
INSERT INTO moderation_actions_archive
SELECT * FROM moderation_actions
WHERE created_at < NOW() - INTERVAL '90 days';

DELETE FROM moderation_actions
WHERE created_at < NOW() - INTERVAL '90 days';
```

## Migrations

The bot automatically creates tables on first connection. Future schema changes should be handled with migrations:

1. Add new columns with `ALTER TABLE ... ADD COLUMN ...`
2. Use `DEFAULT` values for existing rows
3. Backfill data if necessary
4. Update application code to use new columns
5. Remove old columns if safe

**Example Migration:**

```sql
-- Add a new column for heuristic confidence tracking
ALTER TABLE heuristic_rules
ADD COLUMN hit_count INTEGER DEFAULT 0;

-- Add index for performance
CREATE INDEX idx_heuristic_rules_hits
ON heuristic_rules(hit_count DESC)
WHERE active = TRUE;
```

## Backup & Recovery

**Recommended backup strategy:**

- Daily automated backups via PostgreSQL's `pg_dump`
- Replicate to cloud storage (S3, GCS, etc.)
- Test recovery process monthly
- Keep at least 30 days of backups

**Backup Command:**

```bash
pg_dump $DATABASE_URL > sentinel-backup-$(date +%Y%m%d).sql
```

**Restore Command:**

```bash
psql $DATABASE_URL < sentinel-backup-20251023.sql
```
