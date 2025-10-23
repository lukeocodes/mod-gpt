# Configuration Guide

This guide covers all configuration options for **mod-gpt**.

## Environment Variables

Configuration is managed through environment variables (`.env` file or system environment).

### Required Variables

#### `DISCORD_TOKEN`

Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications).

**How to obtain:**

1. Go to Discord Developer Portal
2. Create a new application (or use existing)
3. Navigate to "Bot" section
4. Copy the token (reset if needed)

**Example:**

```bash
DISCORD_TOKEN=your_discord_bot_token_here
```

#### `DATABASE_URL`

PostgreSQL connection string for persistent storage.

**Format:**

```bash
DATABASE_URL=postgresql://username:password@host:port/database
```

**Examples:**

- Local: `postgresql://postgres:password@localhost:5432/modgpt`
- Supabase: `postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres`
- Heroku: `postgresql://user:pass@ec2-xxx.compute-1.amazonaws.com:5432/dbname`

**SSL Support:**

- Supabase URLs automatically use SSL with certificate verification
- Other providers: Append `?sslmode=require` if needed

### Optional Variables

#### `HEALTH_HOST`

Host for the health check HTTP server.

**Default:** `0.0.0.0` (listen on all interfaces)

**Example:**

```bash
HEALTH_HOST=127.0.0.1  # Local only
```

#### `HEALTH_PORT`

Port for the health check HTTP server.

**Default:** `8080`

**Example:**

```bash
HEALTH_PORT=3000
```

**Health Endpoints:**

- `GET /health` → `{"status": "ok", ...}`
- `GET /healthz` → `{"status": "ok", ...}`
- `GET /` → `{"status": "ok", ...}`

## Discord Bot Configuration

### Required Intents

The bot requires the following Discord intents:

- `guilds`: Access to guild information
- `members`: Access to member join/leave events
- `message_content`: Read message content for moderation

**Enable in Discord Developer Portal:**

1. Go to your application
2. Navigate to "Bot" section
3. Scroll to "Privileged Gateway Intents"
4. Enable:
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT

### Required Permissions

The bot needs these permissions to function:

- `Read Messages/View Channels`: See messages
- `Send Messages`: Respond to users
- `Manage Messages`: Delete violating messages
- `Moderate Members`: Timeout users
- `Kick Members`: Kick violators
- `Ban Members`: Ban serious offenders
- `Manage Threads`: Create conversation threads
- `Read Message History`: Fetch context channel content
- `Manage Nicknames`: Set bot's own nickname

**Permission Integer:** `1099780063302` (all required permissions)

**Invite Link:**

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_CLIENT_ID&permissions=1099780063302&scope=bot%20applications.commands
```

Replace `YOUR_BOT_CLIENT_ID` with your bot's client ID from the Developer Portal.

## In-Discord Configuration

After inviting the bot, use slash commands to configure server-specific settings.

### 1. Set Up Context Channels

Context channels contain server rules, guidelines, and information the bot should reference.

```
/add-channel
  channel: #rules
  description: Server rules and community guidelines
```

**Recommendations:**

- Add `#rules` or `#guidelines` channel
- Add `#announcements` for server policies
- Add `#mod-guidelines` if you have moderator-specific rules
- Limit to 3-5 channels (too many can dilute focus)

**The bot will:**

- Fetch recent messages (up to 50)
- Summarize content using LLM
- Include summary in system prompt for all decisions
- Auto-refresh when messages are added/edited/deleted

### 2. Configure Persona

Customize the bot's personality and behavior.

```
/set-persona
  name: ModBot
  description: A friendly but firm Discord moderator who values community safety
  interests: gaming, tech, helping users
  style: Concise, professional, proactive when needed
```

**Tips:**

- Match your server's tone (casual vs. formal)
- List relevant interests for better engagement
- Be specific about when to be proactive vs. hands-off

### 3. Set Logs Channel

Designate a channel for moderation logs (optional but recommended).

```
/set-logs-channel
  channel: #mod-logs
```

**Logged events:**

- All moderation actions (deletes, warns, timeouts, kicks, bans)
- Heuristic matches
- LLM reasoning summaries
- Conversation thread creation

### 4. Configure LLM (Required for AI features)

LLM credentials are stored in the database and configured at runtime using slash commands.

```
/set-llm
  api_key: sk-proj-...
  model: gpt-4o-mini
  base_url: (optional)
```

**How to obtain API key:**

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Navigate to API Keys
3. Create new secret key

**Recommended Models:**

- `gpt-4o-mini`: Fast, cost-effective, good for most use cases
- `gpt-4o`: More capable, higher cost
- `gpt-4-turbo`: Legacy option, slower but thorough

**Alternative Providers:**
For OpenAI-compatible APIs (Azure, local models), set `base_url`:

```
/set-llm
  api_key: your-key
  model: gpt-4o-mini
  base_url: https://your-org.openai.azure.com/
```

**Note:** Bot will function without LLM configuration but won't perform autonomous moderation or have conversations. Only manual commands will work.

### 5. Add Memories

Persistent instructions for the bot to remember.

```
/add-memory
  content: Always warn users before issuing timeouts unless the violation is critical (threats, illegal content, etc.)
```

**Use cases:**

- Server-specific moderation philosophy
- Special handling for certain situations
- Reminders about community culture
- Exceptions to general rules

**Examples:**

- "Our server allows mild profanity but not slurs"
- "Users promoting their content in #self-promo are fine, elsewhere is spam"
- "Crypto discussions are off-topic except in #off-topic"

### 6. Set Bot Nickname (Optional)

```
/set-nickname
  nickname: SafetyBot
```

Applied to all servers the bot is in.

### 7. Enable/Disable Dry-Run Mode

Test configuration without real actions.

```
/set-dry-run enabled
```

**When enabled:**

- Bot describes intended actions in chat
- No messages are deleted
- No users are timed out, kicked, or banned
- All reasoning is still logged

**Use for:**

- Testing new heuristics
- Validating context channel setup
- Training new moderators
- Debugging unexpected behavior

**Disable when ready:**

```
/set-dry-run disabled
```

### 8. Configure Proactive Moderation

Toggle whether bot checks all messages or only when mentioned.

```
/set-proactive-moderation disabled
```

**Enabled (default):** Bot checks every message for violations  
**Disabled:** Bot only acts when mentioned or via commands

**Disable if:**

- You only want manual reviews
- Server is very active (cost concerns)
- Using bot as assistant rather than autonomous moderator

## Slash Commands Reference

| Command                     | Permissions Required | Description                        |
| --------------------------- | -------------------- | ---------------------------------- |
| `/add-channel`              | Manage Server        | Add a context channel              |
| `/remove-channel`           | Manage Server        | Remove a context channel           |
| `/list-channels`            | None                 | View all context channels          |
| `/refresh-channel`          | Manage Server        | Manually refresh a context channel |
| `/set-persona`              | Manage Server        | Configure bot personality          |
| `/view-persona`             | None                 | View current persona settings      |
| `/set-logs-channel`         | Manage Server        | Set moderation logs channel        |
| `/add-memory`               | Manage Server        | Add a persistent instruction       |
| `/remove-memory`            | Manage Server        | Remove a memory by ID              |
| `/list-memories`            | None                 | View all memories                  |
| `/set-nickname`             | Manage Server        | Set bot's nickname                 |
| `/set-llm`                  | Manage Server        | Configure LLM settings             |
| `/set-dry-run`              | Manage Server        | Enable/disable dry-run mode        |
| `/set-proactive-moderation` | Manage Server        | Enable/disable proactive checking  |
| `/list-heuristics`          | Manage Messages      | View active heuristic rules        |
| `/add-heuristic`            | Manage Messages      | Manually add a heuristic           |
| `/disable-heuristic`        | Manage Messages      | Disable a heuristic                |
| `/view-actions`             | Manage Messages      | View recent moderation actions     |
| `/analyze-message`          | Manage Messages      | Manually analyze a message         |

## Context Menu Commands

Right-click any message to access:

| Command                 | Permissions Required | Description                                                          |
| ----------------------- | -------------------- | -------------------------------------------------------------------- |
| **Flag for Moderation** | Manage Messages      | Flag a message that should have been caught; teaches bot the pattern |

## Best Practices

### Initial Setup

1. **Set up database** (PostgreSQL instance)
2. **Create bot** in Discord Developer Portal
3. **Enable intents** (Members, Message Content)
4. **Invite bot** with correct permissions
5. **Set environment variables** (token, database URL only)
6. **Start bot** and verify health endpoint
7. **Configure LLM** via `/set-llm` command (stored in database)
8. **Add context channels** (rules, guidelines)
9. **Wait for heuristic generation** (check logs)
10. **Enable dry-run mode** for testing
11. **Test with sample messages**
12. **Disable dry-run** when satisfied
13. **Monitor logs channel** for first few days

### Ongoing Maintenance

- **Review logs weekly** for false positives/negatives
- **Update context channels** when rules change
- **Add memories** as you discover edge cases
- **Flag missed messages** to improve learning
- **Disable low-value heuristics** if causing issues
- **Check `/view-actions`** to understand bot's decisions

### Cost Optimization

- Use `gpt-4o-mini` (10-20x cheaper than GPT-4)
- Add specific heuristics to reduce LLM calls
- Disable proactive moderation in low-risk channels
- Set context channel message limit to 30-50 (not 100+)
- Avoid extremely large context channels (>500 messages)

### Security

- **Never commit `.env` file** to version control
- **Use bot token secrets** in production (Fly.io secrets, etc.)
- **Rotate tokens** if exposed
- **Limit bot permissions** to minimum required
- **Restrict slash commands** to moderators/admins
- **Review moderation logs** for abuse

## Deployment

### Local Development

```bash
# Install dependencies
pip install -e .

# Set environment variables
export DISCORD_TOKEN=...
export DATABASE_URL=...
export OPENAI_API_KEY=...

# Run bot
python main.py
```

### Docker

```bash
# Build image
docker build -t mod-gpt .

# Run container
docker run -d \
  --name mod-gpt \
  -e DISCORD_TOKEN=... \
  -e DATABASE_URL=... \
  -e OPENAI_API_KEY=... \
  -p 8080:8080 \
  mod-gpt
```

### Fly.io

```bash
# Set secrets
fly secrets set DISCORD_TOKEN=...
fly secrets set DATABASE_URL=...
fly secrets set OPENAI_API_KEY=...

# Deploy
fly deploy
```

**Health check is automatically configured** via `fly.toml`.

### Other Platforms

Bot works on any platform supporting:

- Python 3.10+
- PostgreSQL database
- Outbound HTTPS (Discord, OpenAI)
- Health check endpoint (optional)

**Tested on:**

- Fly.io
- Heroku
- Railway
- DigitalOcean App Platform
- AWS ECS/Fargate

## Troubleshooting

### Bot not responding

- ✅ Check `DISCORD_TOKEN` is valid
- ✅ Verify intents are enabled (Members, Message Content)
- ✅ Ensure bot has `Send Messages` permission
- ✅ Check logs for errors
- ✅ Try mentioning bot directly

### LLM not working

- ✅ Check LLM is configured: `/llm-status`
- ✅ Configure if needed: `/set-llm api_key:sk-... model:gpt-4o-mini`
- ✅ Verify API has credits/quota at platform.openai.com
- ✅ Check model name is correct
- ✅ Review logs for API errors
- ✅ Try updating credentials: `/set-llm api_key:new-key`

### Database errors

- ✅ Verify `DATABASE_URL` format
- ✅ Check database is running
- ✅ Test connection: `psql $DATABASE_URL`
- ✅ Ensure SSL is configured for cloud providers
- ✅ Check database user has CREATE TABLE permissions

### Commands not showing

- ✅ Wait 5-10 minutes for Discord to sync
- ✅ Check bot logs for sync errors
- ✅ Try kicking and re-inviting bot
- ✅ Verify bot has `applications.commands` scope

### False positives

- ✅ Enable dry-run mode
- ✅ Review matched heuristics
- ✅ Lower confidence scores
- ✅ Disable problematic heuristics
- ✅ Add clarifying memories

### False negatives

- ✅ Use "Flag for Moderation" to teach bot
- ✅ Add specific heuristics manually
- ✅ Check proactive moderation is enabled
- ✅ Review context channels for contradictions
- ✅ Ensure LLM is configured correctly
