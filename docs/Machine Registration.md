# Machine Registration

Sentinel AI automatically registers each running instance to track multi-machine deployments.

## Overview

The bot registers itself on startup and sends periodic heartbeats every 5 minutes. Machines inactive for more than 5 minutes are considered offline.

## Database Schema

```sql
CREATE TABLE machines (
    machine_id TEXT PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_version TEXT,
    hostname TEXT,
    metadata JSONB
);

CREATE INDEX idx_machines_last_active ON machines(last_active DESC);
```

## Configuration

### Fly.io Deployment

Fly.io provides `FLY_MACHINE_ID` automatically. Configure it in `fly.toml`:

```toml
[env]
  # Machine ID will be set automatically by Fly.io
  # No need to hardcode - it's read from FLY_MACHINE_ID

[experimental]
  # Enable auto-instrumentation to get FLY_MACHINE_ID
  auto_rollback = true
```

The bot automatically reads from these environment variables (in order of precedence):

1. `MACHINE_ID` - Explicit machine ID (use for testing)
2. `FLY_MACHINE_ID` - Fly.io's automatic machine ID
3. `HOSTNAME` - Fallback to system hostname

### GitHub Actions

No special configuration needed! Fly.io sets `FLY_MACHINE_ID` automatically when the machine starts.

Your existing `.github/workflows/fly-deploy.yml` should work as-is:

```yaml
- name: Deploy to Fly.io
  run: fly deploy --remote-only
  env:
    FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

### Local Development

For local testing, set `MACHINE_ID` manually:

```bash
# .env file
MACHINE_ID=local-dev-machine
```

Or let it use your hostname:

```bash
# No MACHINE_ID set - will use socket.gethostname()
```

## Implementation

### Registration Service

The bot uses a dedicated `RegistrationService` to manage machine registration and heartbeats:

```python
from sentinel.services.registration import RegistrationService

# Initialize service
registration_service = RegistrationService(
    database=database,
    machine_id=settings.machine_id,
    version=settings.version,
    heartbeat_interval=300,  # 5 minutes (optional, default is 300)
)

# Register on startup
await registration_service.register()

# Start periodic heartbeat
await registration_service.start_heartbeat()
```

### Startup Registration

On bot startup (`main.py`):

```python
# Initialize machine registration service
registration_service = None
if settings.machine_id:
    registration_service = RegistrationService(
        database=database,
        machine_id=settings.machine_id,
        version=settings.version,
    )
    await registration_service.register()
    await registration_service.start_heartbeat()
else:
    logger.warning("No MACHINE_ID set - machine registration disabled")
```

### Periodic Heartbeat

The service automatically updates the `last_active` timestamp every 5 minutes. The heartbeat runs in a background task and is automatically cleaned up on shutdown.

### Service Methods

```python
# Check if heartbeat is running
is_running = registration_service.is_running

# Get the machine ID
machine_id = registration_service.machine_id

# Manually trigger registration (updates last_active)
await registration_service.register()

# Stop heartbeat
await registration_service.stop_heartbeat()

# Clean shutdown (stops heartbeat gracefully)
await registration_service.shutdown()
```

### Querying Machines

The registration service provides convenient methods to query machine status:

```python
# Get list of active machines (last 5 minutes by default)
active_machines = await registration_service.get_active_machines(max_age_minutes=5)

# Get list of all registered machines
all_machines = await registration_service.get_all_machines()

# Get counts of active and total machines
counts = await registration_service.get_machine_counts(max_age_minutes=5)
# Returns: {"active": 2, "total": 3}
```

These methods handle database connectivity checks and exceptions gracefully, returning empty lists or zero counts if the database is unavailable.

## Metadata Captured

Each machine registration includes:

| Field         | Description                  | Source                           |
| ------------- | ---------------------------- | -------------------------------- |
| `machine_id`  | Unique machine identifier    | `MACHINE_ID` or `FLY_MACHINE_ID` |
| `hostname`    | Machine hostname             | `socket.gethostname()`           |
| `bot_version` | Bot version                  | `VERSION` env var                |
| `first_seen`  | First registration timestamp | Auto-set on insert               |
| `last_active` | Last heartbeat timestamp     | Updated every 5 min              |
| `metadata`    | Custom metadata (JSON)       | Optional, currently unused       |

## Use Cases

### Monitoring

Check which machines are currently active:

```sql
SELECT machine_id, hostname, last_active, bot_version
FROM machines
WHERE last_active > NOW() - INTERVAL '5 minutes'
ORDER BY last_active DESC;
```

### Debugging

Identify which machine handled a specific event:

```sql
-- Find machine active at time of incident
SELECT m.machine_id, m.hostname, m.metadata
FROM machines m
WHERE m.last_active >= '2025-10-24 12:00:00'
  AND m.last_active <= '2025-10-24 12:30:00'
ORDER BY m.last_active DESC;
```

### Version Distribution

See which versions are running across machines:

```sql
SELECT
    bot_version,
    COUNT(*) as machine_count,
    MAX(last_active) as most_recent_heartbeat
FROM machines
WHERE last_active > NOW() - INTERVAL '5 minutes'
GROUP BY bot_version
ORDER BY machine_count DESC;
```

### Cleanup

Remove machines that haven't been active in over 24 hours:

```sql
DELETE FROM machines
WHERE last_active < NOW() - INTERVAL '24 hours';
```

## Health Check Integration

The health endpoint (`/health`) automatically reports active machines:

```bash
curl http://localhost:8080/health
```

**Response:**

```json
{
  "status": "ok",
  "dry_run": false,
  "persona": "Deepy",
  "llm_configured": true,
  "database_connected": true,
  "machines": {
    "active": 2,
    "total": 3,
    "instances": [
      {
        "machine_id": "e286de4f711e86",
        "hostname": "e286de4f711e86",
        "version": "1.2.3",
        "last_active": "2025-10-24T13:45:00Z"
      },
      {
        "machine_id": "9080ee20d21189",
        "hostname": "9080ee20d21189",
        "version": "1.2.3",
        "last_active": "2025-10-24T13:44:30Z"
      }
    ]
  }
}
```

This allows you to:

- Monitor how many machines are currently running
- Verify all machines are on the same version
- Identify stale machines that haven't sent heartbeats

## Slash Command (Future)

Consider adding a `/machines` admin command to show active instances:

```python
@tree.command(name="machines", description="Show active bot machines")
@app_commands.checks.has_permissions(administrator=True)
async def machines(
    interaction: discord.Interaction,
    registration_service: RegistrationService,
) -> None:
    active = await registration_service.get_active_machines(max_age_minutes=5)
    counts = await registration_service.get_machine_counts(max_age_minutes=5)

    if not active:
        await interaction.response.send_message(
            "❌ No active machines found", ephemeral=True
        )
        return

    lines = [f"**Active Machines ({counts['active']}/{counts['total']}):**"]
    for machine in active:
        version = machine.get("bot_version", "unknown")
        lines.append(
            f"• `{machine['machine_id']}` ({machine['hostname']}) "
            f"- Version: {version} - Last active: {machine['last_active']}"
        )

    await interaction.response.send_message("\n".join(lines), ephemeral=True)
```

## Troubleshooting

### Machine not registering

**Problem:** Bot starts but no machine record in database  
**Cause:** `MACHINE_ID` not set and `FLY_MACHINE_ID` not available  
**Solution:** Check logs for "No MACHINE_ID set - machine registration disabled"

### Duplicate machine IDs

**Problem:** Multiple machines with same ID  
**Cause:** `MACHINE_ID` hardcoded instead of using Fly.io's automatic ID  
**Solution:** Remove hardcoded `MACHINE_ID` from `fly.toml` - let Fly.io set `FLY_MACHINE_ID`

### Heartbeat not updating

**Problem:** `last_active` timestamp not updating  
**Cause:** Heartbeat task crashed or database connection lost  
**Solution:** Check logs for "Failed to send machine heartbeat" errors

### Old machines showing as active

**Problem:** Machines stopped weeks ago still in table  
**Cause:** No cleanup process  
**Solution:** Run manual cleanup query or add periodic cleanup task

## Benefits

1. **Visibility** - Know exactly which machines are running
2. **Debugging** - Identify which machine handled a problematic event
3. **Monitoring** - Track machine health and uptime
4. **Capacity Planning** - See distribution across regions
5. **Incident Response** - Quickly identify and restart failing machines

## Future Enhancements

1. **Health Metrics** - Track CPU, memory, event throughput per machine
2. **Auto-scaling Triggers** - Scale based on active machine count
3. **Machine Affinity** - Route certain guilds to specific machines
4. **Graceful Shutdown** - Mark machine as inactive on shutdown
5. **Machine Dashboard** - Web UI showing real-time machine status
