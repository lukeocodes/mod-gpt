# mod-gpt – AI-Powered Discord Moderation Bot

An intelligent Discord moderation bot that combines fast pattern matching with LLM reasoning to protect your community. Learns from your server's rules and gets smarter over time.

## Quick Start

### Prerequisites

1. **PostgreSQL Database** (Supabase, Railway, Heroku, or self-hosted)
2. **OpenAI API Key** from [platform.openai.com](https://platform.openai.com/) (configured after bot starts)
3. **Discord Bot Token** with **Message Content** and **Server Members** intents enabled

### Installation

```bash
# Install dependencies
pip install -e .

# Create .env file with required variables
cat > .env << EOF
DISCORD_TOKEN=your_discord_bot_token
DATABASE_URL=postgresql://user:password@host:5432/database
EOF

# Run the bot
python main.py
```

### First-Time Setup

1. **Invite bot to server** with required permissions (see docs)
2. **Configure LLM credentials** (stored in database, not environment variables):
   ```
   /set-llm api_key:sk-proj-your-key model:gpt-4o-mini
   ```
3. **Add your rules channel** as context:
   ```
   /add-channel channel:#rules description:Server rules and guidelines
   ```
4. **Wait 30 seconds** for the bot to:
   - Read and understand your rules
   - Generate server-specific heuristics
   - Prepare for moderation
5. **Test in dry-run mode** (optional):
   ```
   /set-dry-run enabled
   ```
6. **Start moderating** - The bot now monitors messages based on YOUR server's rules!

**Important:** The bot learns moderation patterns from the context channels you provide. Point it at channels containing your server rules, guidelines, and community standards.

## Key Features

- **Hybrid Moderation**: Fast pattern matching + LLM reasoning for complex decisions
- **Self-Learning**: Generates server-specific heuristics from your rules
- **Context-Aware**: References your server's channels for decisions
- **Natural Conversations**: Hold conversations, answer questions, assist users
- **Automatic Threading**: Creates threads in busy channels
- **Comprehensive Logging**: Full audit trail in database + logs channel
- **Dry-Run Mode**: Test before enforcement
- **Global Fraud Detection**: 25+ pre-seeded scam patterns (Nitro scams, phishing, etc.)

## How It Works

1. **Fast Path**: Checks messages against heuristics (<10ms)
2. **Smart Path**: LLM analyzes complex cases (~500-1500ms)
3. **Learning**: Generates new patterns from your rules and feedback
4. **Actions**: Deletes, warns, timeouts, kicks, or bans as needed

## Documentation

- **[Architecture Overview](docs/Architecture%20Overview.md)** - System design and components
- **[Configuration Guide](docs/Configuration%20Guide.md)** - All settings and commands
- **[Heuristics System](docs/Heuristics%20System.md)** - Pattern matching and learning
- **[Database Schema](docs/Database%20Schema.md)** - Data structure and queries
- **[Deployment Guide](docs/Deployment%20Guide.md)** - Production deployment

## Common Commands

```
/add-channel         Add a context channel (rules, guidelines, etc.)
/set-persona         Customize bot personality
/set-logs-channel    Set moderation logs channel
/add-memory          Add persistent instruction
/set-dry-run         Toggle test mode
/list-heuristics     View learned patterns
```

**Context Menu:**

- Right-click message → **"Flag for Moderation"** to teach the bot

## Example Workflow

### Setting Up Server Rules

```discord
# Admin adds rules channel
/add-channel channel:#rules description:Server rules and guidelines

# Bot reads channel, finds rules like:
# "1. No spam or advertising"
# "2. No hate speech or slurs"
# "3. Be respectful to all members"

# Bot generates heuristics:
✅ Pattern: "discord\.gg/[a-z0-9]+" (spam detection)
✅ Pattern: "f4g" (hate speech, fuzzy match)
✅ Generated 12 heuristics from #rules
```

### Automatic Moderation

```discord
User: "Free Nitro here! discord.gg/scam123"

# Bot processes:
1. Matches heuristic: "free nitro" (confidence: 0.95)
2. Matches heuristic: "discord.gg/*" (confidence: 0.80)
3. LLM analyzes: "This is a Nitro scam violating Rule #1"
4. Action: Delete message, warn user, log event

🤖 ModGPT: @User, your message was removed. Our server prohibits spam and scam links. Please review #rules.
```

### Continuous Learning

```discord
# Admin flags a message that slipped through
Right-click message → "Flag for Moderation"
Reason: "This violates our no self-promotion rule"

# Bot learns:
✅ Analyzed message pattern
✅ Generated new heuristic
✅ Will catch similar messages in the future
```

## Requirements

- **Python 3.10+**
- **PostgreSQL 12+** (any provider)
- **Discord Bot** with privileged intents:
  - ✅ Server Members Intent
  - ✅ Message Content Intent
- **OpenAI API Key** (or compatible provider)

## Environment Variables

| Variable        | Required | Description                             |
| --------------- | -------- | --------------------------------------- |
| `DISCORD_TOKEN` | Yes      | Bot token from Discord Developer Portal |
| `DATABASE_URL`  | Yes      | PostgreSQL connection string            |
| `HEALTH_HOST`   | No       | Health check host (default: `0.0.0.0`)  |
| `HEALTH_PORT`   | No       | Health check port (default: `8080`)     |

**Note:** LLM credentials (API key, model, base URL) are **stored in the database** and configured using the `/set-llm` slash command, not environment variables.

## Deployment

Deploy to any platform supporting Python + PostgreSQL:

- **Fly.io** (recommended): See [Deployment Guide](docs/Deployment%20Guide.md)
- **Heroku**: Works with Heroku Postgres
- **Railway**: One-click PostgreSQL integration
- **Docker**: `docker-compose.yml` included
- **VPS**: Systemd service file example in docs

**Health Check Endpoint:** `http://your-host:8080/health`

## Cost Estimates

**Typical usage with GPT-4o-mini:**

- Small server (10,000 messages/month): ~$5-10/month
- Medium server (50,000 messages/month): ~$20-40/month
- Large server (200,000 messages/month): ~$80-150/month

**Cost optimization:**

- Heuristics reduce LLM calls by 50-80%
- Use `gpt-4o-mini` (10-20x cheaper than GPT-4)
- Disable proactive moderation for low-risk channels

## Architecture

```
┌─────────────────────────────────────────────┐
│          Discord Message Event              │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│        Check Heuristics (Fast Path)         │
│  • Regex patterns                           │
│  • Exact/fuzzy word matching                │
│  • Global fraud patterns                    │
└────────────────┬────────────────────────────┘
                 │
        ┌────────┴────────┐
        │ Match Found?    │
        └────────┬────────┘
                 │ Yes
                 ▼
┌─────────────────────────────────────────────┐
│       LLM Reasoning (Smart Path)            │
│  • Analyzes context                         │
│  • Reviews server rules                     │
│  • Decides proportional action              │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│          Execute Action & Learn             │
│  • Delete/warn/timeout/kick/ban             │
│  • Log to database                          │
│  • Generate new heuristics                  │
└─────────────────────────────────────────────┘
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE)

## Support

- **Issues**: [GitHub Issues](https://github.com/your-username/mod-gpt/issues)
- **Documentation**: See `docs/` directory
- **Security**: Report vulnerabilities privately to maintainers

---

**Need help getting started?** Check out the [Configuration Guide](docs/Configuration%20Guide.md) for detailed setup instructions.
