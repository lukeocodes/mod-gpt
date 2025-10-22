# ModGPT – LLM-Aware Discord Moderator

ModGPT is an experimental Discord moderation bot that blends traditional admin tooling with large language model reasoning, tool-calling, and agent routing. The goal is to explore how far a language model can autonomously steer community safety, accountability, and engagement using server-provided context instead of hard-coded rules.

## Features
- **Context-driven moderation** – Reference any channel that contains static guidance (rules, code of conduct, announcements, honey pots, etc.) and the bot will pull those messages into its reasoning.
- **LLM function-calling** – Every event analysis yields structured tool calls (`take_moderation_action`, `send_message`, `escalate_to_human`). When the model recommends an action the bot executes it immediately.
- **Dynamic automations** – Configure high-certainty guardrails such as instant-kick honey pots or auto-delete channels, all logged with justifications.
- **Persona & engagement** – Give ModGPT a persona, configure interests, and ask it to spark new conversations aligned with that identity.
- **Comprehensive event coverage** – Messages, edits, member joins/removals, and manual engagement triggers flow through a routing layer to specialised agents.
- **Transparent logging** – Every action is mirrored to a configurable logs channel with a concise rationale.
- **Persistent audit trail** – Key decisions (warnings, kicks, bans, escalations, automations) are written to Supabase Postgres so history survives restarts.
- **Database-backed configuration** – Persona, context channels, automations, and log-channel settings live in Supabase too, keeping the bot’s brain consistent across deployments.
- **Custom branding** – Change the command prefix or the bot’s nickname so ModGPT blends into your community’s voice.
- **Thread-smart moderation** – Each event prompt includes timestamps, reply targets, server context, and recent channel history so the bot can decide between inline replies, mentions, or spawning a dedicated thread.
- **Autonomous caretaking** – A built-in scheduler reviews channel health, welcomes overlooked newcomers, and suggests structural improvements; you can also trigger the same sweep on demand.
- **Persistent memories** – Use the `remember` command to add long-lived instructions (e.g. “Don’t @here unless it’s urgent”) that stay in every prompt.
- **Dry-run onboarding** – Flip on dry-run mode to see what actions ModGPT would take before letting it enforce them.
- **Keyword automations** – Layer simple keyword filters on top of channel automations without hard-coding rules in the source.
- **Deployment guardrails** – Ship a `BUILT_IN_PROMPT` so each deployment adds non-editable base instructions, wrapped in runtime UUID tags to blunt prompt-injection attempts.

## Requirements
- Python 3.10+
- A Discord bot application with the following privileged intent toggles enabled:
  - Guild Members
  - Message Content
- An OpenAI-compatible API key (optional but required for reasoning). Any endpoint that follows the Responses/Chat Completions schema should work by setting `OPENAI_BASE_URL`.

## Installation
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # or follow official instructions
uv sync
```

### Environment variables
Create a `.env` file alongside `main.py`:
```
DISCORD_TOKEN=your_discord_bot_token
OPENAI_API_KEY=optional_if_using_reasoning
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=optional_custom_endpoint
SUPABASE_DB_URL=postgresql://user:password@host:5432/postgres
BUILT_IN_PROMPT=
```

If no OpenAI (or compatible) key is configured the bot will connect but skip autonomous reasoning; automations and manual commands will continue to work.

## Running the bot
```bash
uv run bot
```

The bot bootstraps Supabase tables on startup, persists all configuration (persona, context channels, automations, log channel) in Postgres, and records an audit row for each moderation decision. Any Postgres-compatible database will work if you prefer to self-host.

## Commands (mention the bot or use your configured prefix)
```
@ModGPT help
@ModGPT add-channel #rules Channel with our rules and moderation policy
@ModGPT remove-channel #old-guidelines
@ModGPT list-channels
@ModGPT set-logs #mod-logs
@ModGPT remember Avoid pinging @everyone outside announcements
@ModGPT list-memories
@ModGPT forget-memory 12
@ModGPT set-prefix !sentinel
@ModGPT set-nickname Sentinel Mod
@ModGPT set-persona Guardian | Calm and fair guardian of the server | Direct but empathetic responses
@ModGPT set-interests community safety, programming, tabletop RPGs
@ModGPT set-automation #honey-pot kick anyone posting here is immediately removed | Honeypot trap
@ModGPT disable-automation #honey-pot
@ModGPT spark Share your latest project win
@ModGPT set-dry-run on
@ModGPT run-cron
```

### Background caretaking & cron support
ModGPT runs a periodic maintenance loop (default: every 30 minutes) that inspects channel activity, outstanding questions, and newcomer status. It uses the same reasoning stack as real-time moderation, so scheduled actions carry the full server context.

Need an immediate sweep after a big announcement? Trigger `@ModGPT run-cron` in your moderator channel. Want to delegate it to system cron? Schedule a Discord reminder that pings the bot with that command, or call into the bot from an external script over the Discord API—no additional code changes required.

### Honey pot example
1. Create a channel `#honey-pot` with a topic like “Posting here means you get kicked.”
2. Add that channel as context: `@ModGPT add-channel #honey-pot Honeypot for ban evaders`
3. (Optional) Add an explicit automation: `@ModGPT set-automation #honey-pot kick Honey pot trigger | Messaging here violates the honey pot rule`

When anyone sends a message in `#honey-pot` the LLM sees the context and the automation, kicks the user, and logs the justification.

Need lighter-touch filters? Use keyword automations, e.g. `@ModGPT set-automation #marketplace delete_message Remove crypto spam | Remove spam pitches | keywords=buy now,click here`.

### Persistent memories
Memories are lightweight reminders the bot keeps in every prompt. Store one with `@ModGPT remember Please uphold the code of conduct section 3`, review them via `@ModGPT list-memories`, and prune outdated entries using `@ModGPT forget-memory <id>`.

### Dry-run mode
Enable dry-run mode (`@ModGPT set-dry-run on`) to preview actions in the logs channel without executing them. Disable it (`@ModGPT set-dry-run off`) once you’re confident ModGPT is behaving as expected.

## Architectural overview
```
main.py
 └── modgpt/
     ├── discord_bot.py      # Bot wiring, commands, and event registration
     ├── state.py            # Database-backed persistent configuration façade
     ├── llm.py              # Async OpenAI client wrapper & tool-call parsing
      ├── prompts.py          # Prompt templates for persona/context injection
      └── agents/
           ├── router.py      # Delegates events to specialised agents
           ├── moderation.py  # LLM-guided moderation + tool execution
           └── engagement.py  # Persona-driven conversation starters
```

The moderation agent constructs a system prompt using the configured persona and all context channels (channel name + notes). Each Discord event is summarised into a user message that includes channel topics, automations, and message content. The OpenAI response determines which function to call; ModGPT executes it and emits a log entry.

## Extending
- Implement additional tools, e.g. `schedule_follow_up`, `summarise_thread`, or `tag_content_warning`.
- Add richer automations such as keyword filters or role-based policies stored alongside `AutomationRule`.
- Expand the engagement agent with timers that periodically seed conversations without manual prompting.
- Wire in audio moderation later by adding a dedicated agent and command to opt channels into audio analysis.

## Safety considerations
- Ensure the bot role outranks moderators it needs to moderate.
- Double-check automations, especially kicks/bans, before enabling them.
- Keep the logs channel private so ModGPT’s justifications stay confidential.

Happy experimenting!
