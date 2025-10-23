# Deployment Guide

This guide covers deploying **mod-gpt** to production environments.

## Prerequisites

Before deploying, you need:

1. **PostgreSQL Database**

   - Any PostgreSQL 12+ instance
   - Recommended: Supabase (free tier), Railway, or Heroku Postgres

2. **OpenAI API Key**

   - From [OpenAI Platform](https://platform.openai.com/)
   - Ensure you have credits/billing configured

3. **Discord Bot Token**

   - From [Discord Developer Portal](https://discord.com/developers/applications)
   - With required intents enabled (Members, Message Content)

4. **Deployment Platform**
   - Any platform supporting Python 3.10+ and Docker
   - Tested: Fly.io, Heroku, Railway, DigitalOcean

## Quick Start (Fly.io)

Fly.io offers free tier hosting suitable for small to medium Discord bots.

### 1. Install Fly CLI

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

### 2. Authenticate

```bash
fly auth login
```

### 3. Create App

```bash
# From project directory
fly launch --no-deploy
```

Follow prompts:

- App name: Choose unique name (e.g., `my-mod-gpt`)
- Region: Choose closest to your users
- Don't add databases yet (we'll use external PostgreSQL)

### 4. Set Secrets

```bash
fly secrets set DISCORD_TOKEN="YOUR_DISCORD_TOKEN"
fly secrets set DATABASE_URL="YOUR_POSTGRESQL_URL"
```

**Note:** OpenAI credentials are configured via `/set-llm` command after bot starts, not as secrets.

### 5. Deploy

```bash
fly deploy
```

### 6. Configure LLM

After bot starts, configure OpenAI credentials (stored in database):

```bash
# In Discord, use slash command:
/set-llm api_key:sk-proj-your-key model:gpt-4o-mini
```

### 7. Verify

```bash
# Check logs
fly logs

# Check health
curl https://your-app-name.fly.dev/health

# Should return:
# {"status": "ok", "dry_run": false, "persona": "ModGPT", "llm_configured": true, ...}
```

### 8. Monitor

```bash
# View logs in real-time
fly logs -f

# Check app status
fly status

# SSH into container (if needed)
fly ssh console
```

## Heroku Deployment

### 1. Create App

```bash
# Install Heroku CLI
brew install heroku/brew/heroku  # macOS
# Or download from https://devcenter.heroku.com/articles/heroku-cli

# Login
heroku login

# Create app
heroku create my-mod-gpt
```

### 2. Add PostgreSQL

```bash
# Free tier (10,000 rows)
heroku addons:create heroku-postgresql:mini

# Or use external provider
heroku config:set DATABASE_URL="your-postgresql-url"
```

### 3. Set Environment Variables

```bash
heroku config:set DISCORD_TOKEN="YOUR_DISCORD_TOKEN"
# DATABASE_URL is automatically set if you added Heroku Postgres
```

**Note:** Configure OpenAI credentials via `/set-llm` command after bot starts.

### 4. Deploy

```bash
# Using Git
git push heroku main

# Or using Docker
heroku container:push worker
heroku container:release worker
```

### 5. Scale

```bash
# Heroku doesn't run worker by default
heroku ps:scale worker=1
```

**Note:** Heroku requires a `Procfile` (already included):

```
worker: python main.py
```

## Railway Deployment

### 1. Create Project

1. Go to [Railway](https://railway.app/)
2. Click "New Project"
3. Select "Deploy from GitHub"
4. Connect your mod-gpt repository

### 2. Add PostgreSQL

1. Click "+ New"
2. Select "Database" → "PostgreSQL"
3. Copy the connection URL

### 3. Configure Environment

In Railway dashboard:

- `DISCORD_TOKEN`: Your Discord token
- `DATABASE_URL`: PostgreSQL connection URL from step 2

**Note:** Configure OpenAI credentials via `/set-llm` command after bot starts.

### 4. Deploy

Railway automatically deploys on git push.

**Health check:**

- Railway exposes port 8080 automatically
- Set health check endpoint: `/health`

## DigitalOcean App Platform

### 1. Create App

1. Go to [DigitalOcean App Platform](https://cloud.digitalocean.com/apps)
2. Click "Create App"
3. Select your GitHub repository
4. Choose "mod-gpt" directory

### 2. Configure Build

- **Build Command:** (leave empty, uses Dockerfile)
- **Run Command:** `python main.py`
- **HTTP Port:** `8080`
- **Health Check Path:** `/health`

### 3. Add Database

1. Go to "Resources"
2. Click "Add Resource"
3. Select "Database" → "PostgreSQL"
4. Choose plan (basic is fine)
5. Environment variable `DATABASE_URL` automatically set

### 4. Set Environment Variables

In "Settings" → "App-Level Environment Variables":

- `DISCORD_TOKEN`: Your Discord token
- `DATABASE_URL`: (automatically set if you added database resource)

**Note:** Configure OpenAI credentials via `/set-llm` command after bot starts.

### 5. Deploy

Click "Save" and app deploys automatically.

## Docker Compose (Self-Hosted)

Perfect for VPS or home server.

### 1. Create `docker-compose.yml`

```yaml
version: "3.8"

services:
  bot:
    build: .
    container_name: mod-gpt
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - DATABASE_URL=postgresql://postgres:password@postgres:5432/modgpt
    depends_on:
      - postgres
    ports:
      - "8080:8080"

  postgres:
    image: postgres:15-alpine
    container_name: mod-gpt-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_DB=modgpt
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

### 2. Create `.env` File

```bash
DISCORD_TOKEN=your-token-here
```

**Note:** Configure OpenAI credentials via `/set-llm` command after bot starts.

### 3. Run

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f bot

# Stop
docker-compose down

# Update
git pull
docker-compose up -d --build
```

## Systemd Service (Linux VPS)

For running directly on a Linux server without Docker.

### 1. Install Python

```bash
sudo apt update
sudo apt install python3.10 python3-pip git postgresql-client
```

### 2. Clone Repository

```bash
cd /opt
sudo git clone https://github.com/your-username/mod-gpt.git
cd mod-gpt
```

### 3. Install Dependencies

```bash
sudo pip3 install -e .
```

### 4. Create Service File

`/etc/systemd/system/mod-gpt.service`:

```ini
[Unit]
Description=ModGPT Discord Bot
After=network.target

[Service]
Type=simple
User=mod-gpt
WorkingDirectory=/opt/mod-gpt
Environment="DISCORD_TOKEN=your-token"
Environment="DATABASE_URL=postgresql://user:pass@localhost:5432/modgpt"
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Create User

```bash
sudo useradd -r -s /bin/false mod-gpt
sudo chown -R mod-gpt:mod-gpt /opt/mod-gpt
```

### 6. Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable mod-gpt
sudo systemctl start mod-gpt

# Check status
sudo systemctl status mod-gpt

# View logs
sudo journalctl -u mod-gpt -f
```

## Database Setup

### Supabase (Recommended)

Free tier: 500MB storage, unlimited API requests

1. Go to [Supabase](https://supabase.com/)
2. Create new project
3. Copy connection string from Settings → Database
4. Format: `postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres`

**Note:** SSL is automatically configured for Supabase URLs.

### Railway

1. Create PostgreSQL database in Railway
2. Copy `DATABASE_URL` from Variables tab
3. Use in your deployment

### Heroku Postgres

```bash
# Create database
heroku addons:create heroku-postgresql:mini

# Get URL
heroku config:get DATABASE_URL
```

### Self-Hosted PostgreSQL

```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
CREATE DATABASE modgpt;
CREATE USER modgpt WITH PASSWORD 'secure-password';
GRANT ALL PRIVILEGES ON DATABASE modgpt TO modgpt;
\q
```

**Connection URL:**

```
postgresql://modgpt:secure-password@localhost:5432/modgpt
```

## Monitoring & Logs

### Health Check Endpoint

The bot exposes a health endpoint on port 8080:

```bash
curl http://your-domain:8080/health
```

**Response:**

```json
{
  "status": "ok",
  "dry_run": false,
  "persona": "ModGPT",
  "llm_configured": true,
  "database_connected": true
}
```

**Use for:**

- Load balancer health checks
- Uptime monitoring (UptimeRobot, Better Uptime, etc.)
- Container orchestration (Kubernetes, Docker Swarm)

### Logging

The bot uses Python's `logging` module with INFO level by default.

**Log format:**

```
2025-10-23 12:00:00 | INFO | modgpt.bot | Logged in as ModGPT#1234
```

**Important log events:**

- Bot startup and shutdown
- Command sync to Discord
- LLM API calls and errors
- Moderation actions taken
- Database connection issues
- Heuristic generation

**View logs:**

- Fly.io: `fly logs -f`
- Heroku: `heroku logs --tail`
- Railway: Dashboard → Deployments → Logs
- Docker: `docker logs -f mod-gpt`
- Systemd: `journalctl -u mod-gpt -f`

### Error Alerting

**Recommended tools:**

- [Sentry](https://sentry.io/) - Python error tracking
- [Better Uptime](https://betteruptime.com/) - Health check monitoring
- [Discord Webhooks](https://support.discord.com/hc/en-us/articles/228383668) - Send errors to Discord channel

**Example: Send errors to Discord webhook**

Add to `main.py`:

```python
import logging
import httpx

class DiscordHandler(logging.Handler):
    def __init__(self, webhook_url):
        super().__init__()
        self.webhook_url = webhook_url

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            try:
                httpx.post(self.webhook_url, json={
                    "content": f"🚨 **{record.levelname}**: {record.getMessage()}"
                })
            except:
                pass

# Add handler
webhook_url = os.getenv("ERROR_WEBHOOK_URL")
if webhook_url:
    logging.getLogger().addHandler(DiscordHandler(webhook_url))
```

## Performance Tuning

### Resource Requirements

**Minimum:**

- CPU: 0.5 vCPU
- RAM: 512 MB
- Storage: 1 GB

**Recommended:**

- CPU: 1 vCPU
- RAM: 1 GB
- Storage: 10 GB (for database)

**Scaling factors:**

- Server size (1-10 servers: minimum; 10-100 servers: recommended)
- Message volume (higher = more LLM calls)
- Heuristics count (>1000 rules may need more CPU)

### Database Optimization

**Indexes:**
All critical indexes are created automatically on first run.

**Vacuum:**
Run weekly to reclaim space:

```sql
VACUUM ANALYZE moderation_actions;
VACUUM ANALYZE heuristic_rules;
VACUUM ANALYZE conversations;
```

**Connection pooling:**
For high-traffic bots, consider PgBouncer:

```bash
# Install
sudo apt install pgbouncer

# Configure /etc/pgbouncer/pgbouncer.ini
[databases]
modgpt = host=localhost port=5432 dbname=modgpt

[pgbouncer]
pool_mode = transaction
max_client_conn = 100
default_pool_size = 20
```

**Update DATABASE_URL:**

```
postgresql://user:pass@localhost:6432/modgpt
```

### LLM Cost Optimization

**Current costs (GPT-4o-mini):**

- Input: $0.15 per 1M tokens
- Output: $0.60 per 1M tokens

**Typical usage:**

- Per message: ~500-1000 tokens (~$0.0005-0.001)
- 10,000 messages/day: ~$5-10/month

**Optimization strategies:**

1. **Use heuristics** - Reduce LLM calls by 50-80%
2. **Lower temperature** - Already set to 0.4 (more deterministic, fewer tokens)
3. **Shorter context** - Limit context channel message fetches to 30-50
4. **Disable proactive moderation** - Only respond to mentions
5. **Use gpt-4o-mini** - 10-20x cheaper than GPT-4

### Discord API Rate Limits

**Limits:**

- 50 requests per second (global)
- 5 requests per second (per endpoint)

**The bot respects these automatically** via discord.py's rate limiter.

**Avoid:**

- Bulk message deletes (use targeted deletes)
- Rapid consecutive actions (space them out)
- Fetching large channel histories (limit to 50-100 messages)

## Security Best Practices

### 1. Environment Variables

**Never commit secrets to Git:**

```bash
# Add to .gitignore
.env
.env.local
.env.production
```

**Use secret management:**

- Fly.io: `fly secrets set`
- Heroku: `heroku config:set`
- Railway: Environment variables in dashboard
- Self-hosted: HashiCorp Vault, AWS Secrets Manager

### 2. Database Access

**Restrict access:**

- Use strong passwords (generated, not dictionary words)
- Firewall database to only allow bot IP
- Use SSL/TLS connections (enforced for Supabase)
- Create bot-specific database user (not `postgres` superuser)

**Example:**

```sql
CREATE USER modgpt_bot WITH PASSWORD 'strong-generated-password';
GRANT CONNECT ON DATABASE modgpt TO modgpt_bot;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO modgpt_bot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO modgpt_bot;
```

### 3. Discord Permissions

**Principle of least privilege:**

- Only grant required permissions (no Administrator)
- Use role-based access for commands (`manage_guild`, `manage_messages`)
- Separate logs channel from public channels
- Review permissions quarterly

### 4. API Key Rotation

**Rotate regularly:**

- OpenAI API keys: Every 90 days
- Discord bot token: Annually or if exposed
- Database passwords: Every 6 months

**Update via Discord:**

```bash
# Update in database (recommended)
/set-llm api_key:new-key
```

### 5. Audit Logging

**Enable comprehensive logging:**

- All moderation actions → `moderation_actions` table
- All LLM calls → application logs
- All command usage → logs channel
- All heuristic matches → logs channel

**Review regularly:**

```sql
-- Recent actions
SELECT * FROM moderation_actions ORDER BY created_at DESC LIMIT 100;

-- Actions by user
SELECT target_user_id, COUNT(*), array_agg(action_type)
FROM moderation_actions
GROUP BY target_user_id
ORDER BY count DESC;
```

## Backup & Disaster Recovery

### Database Backups

**Automated backups:**

- Supabase: Daily automatic backups (free tier: 7 days retention)
- Railway: Point-in-time recovery (paid plans)
- Heroku: Daily backups with PG Backups addon

**Manual backups:**

```bash
# Backup
pg_dump $DATABASE_URL > backup-$(date +%Y%m%d).sql

# Compress
gzip backup-$(date +%Y%m%d).sql

# Upload to S3 (example)
aws s3 cp backup-$(date +%Y%m%d).sql.gz s3://my-backups/
```

**Automated backup script:**

```bash
#!/bin/bash
# /opt/mod-gpt/backup.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR=/backups
DATABASE_URL="your-database-url"

pg_dump $DATABASE_URL | gzip > $BACKUP_DIR/modgpt-$DATE.sql.gz

# Keep only last 30 days
find $BACKUP_DIR -name "modgpt-*.sql.gz" -mtime +30 -delete
```

**Add to cron:**

```bash
0 2 * * * /opt/mod-gpt/backup.sh
```

### Restore from Backup

```bash
# Download backup
aws s3 cp s3://my-backups/backup-20251023.sql.gz .

# Decompress
gunzip backup-20251023.sql.gz

# Restore
psql $DATABASE_URL < backup-20251023.sql
```

### Configuration Backup

Bot state is stored in database, but also export for safety:

```sql
-- Export bot state
\copy (SELECT * FROM bot_state) TO 'bot-state-backup.csv' CSV HEADER;

-- Export heuristics
\copy (SELECT * FROM heuristic_rules WHERE active = true) TO 'heuristics-backup.csv' CSV HEADER;
```

## Troubleshooting

### Bot not starting

**Check logs first:**

```bash
fly logs  # or heroku logs, docker logs, etc.
```

**Common issues:**

- ❌ Invalid Discord token → Check token, regenerate if needed
- ❌ Database connection failed → Verify `DATABASE_URL`, check firewall
- ❌ Missing environment variables → Set all required vars
- ❌ Port already in use → Change `HEALTH_PORT`

### High memory usage

**Causes:**

- Too many heuristics loaded (>10,000)
- Large context channels (>500 messages)
- Memory leak (restart bot)

**Solutions:**

- Disable unused heuristics
- Reduce context channel fetch limits
- Restart bot weekly (automated)

### Slow responses

**Causes:**

- LLM API latency (500-2000ms)
- Database query slow (missing indexes)
- Rate limiting from Discord

**Solutions:**

- Switch to faster model (gpt-4o-mini vs gpt-4)
- Add database indexes (check slow query log)
- Reduce concurrent operations

### Database connection pool exhausted

**Error:**

```
psycopg2.pool.PoolError: connection pool exhausted
```

**Solution:**
Increase connection limit or add PgBouncer (see Performance Tuning).

## Next Steps

After deploying:

1. ✅ Invite bot to Discord server
2. ✅ Configure LLM: `/set-llm api_key:sk-... model:gpt-4o-mini`
3. ✅ Run `/add-channel` for rules channel
4. ✅ Wait for heuristic generation (check logs)
5. ✅ Test with sample messages
6. ✅ Enable dry-run mode initially
7. ✅ Monitor logs for 24-48 hours
8. ✅ Disable dry-run when confident
9. ✅ Set up monitoring/alerting
10. ✅ Configure automated backups
11. ✅ Document your specific server rules in context channels
