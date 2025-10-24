# Architecture Overview

## System Design

**Sentinel AI** is an LLM-powered Discord moderation bot that uses OpenAI's GPT models to provide intelligent, context-aware moderation. The architecture is built around an event-driven design with function-calling capabilities, allowing the LLM to take autonomous moderation actions.

## Core Components

### 1. **Bot Layer** (`sentinel/bot.py`)

The Discord client initialization and event handling orchestration. This is the main entry point that:

- Initializes the Discord bot with appropriate intents (members, message content)
- Registers slash commands and context menu commands
- Sets up event handlers for messages, edits, deletions, and member joins
- Manages the scheduled tick loop for periodic maintenance
- Coordinates between Discord events and the moderation agent

### 2. **Moderation Agent** (`sentinel/services/moderation.py`)

The core reasoning engine that processes Discord events and decides on actions:

- **Event Processing**: Handles all Discord events (messages, edits, joins, etc.)
- **Heuristic Matching**: Fast-path rule checking using regex, exact match, fuzzy, and contains patterns
- **LLM Reasoning**: When heuristics match or manual review is needed, consults the LLM with full context
- **Function Calling**: Uses OpenAI's function calling API to execute moderation actions
- **Learning**: Generates new heuristics from context channels, memories, and user feedback
- **Conversation Threading**: Creates threads for lengthy discussions in busy channels

### 3. **State Management** (`sentinel/services/state.py`)

Manages bot configuration and dynamic state:

- **Context Channels**: Channels containing server rules, guidelines, and important information
- **Persona Configuration**: Bot personality, interests, and conversation style
- **Automation Rules**: Server-specific policies (currently placeholder for future use)
- **Memories**: Persistent admin notes and instructions
- **LLM Settings**: API key, model, and base URL configuration
- **Database Persistence**: Loads and saves state to PostgreSQL

### 4. **Database Layer** (`sentinel/db.py`)

PostgreSQL integration for persistent storage:

- **Moderation Records**: Audit log of all actions taken
- **Heuristic Rules**: Pattern-based detection rules (global and guild-specific)
- **Conversations**: Multi-turn conversation tracking with threading support
- **State Storage**: Persistent configuration and memories
- **Analytics**: Count queries for actions, heuristics, and patterns

### 5. **LLM Client** (`sentinel/services/llm.py`)

Wrapper around OpenAI's async client:

- **Configuration**: Supports custom base URLs for OpenAI-compatible APIs
- **Function Calling**: Structured tool execution with JSON schema validation
- **Error Handling**: Graceful degradation when LLM is unavailable
- **Dynamic Configuration**: Runtime updates to API keys and models

### 6. **Conversation Manager** (`sentinel/services/conversations.py`)

Manages natural multi-turn conversations:

- **Context Tracking**: Maintains conversation history per user/channel
- **Threading Logic**: Creates threads in busy channels (3+ active users)
- **Exit Detection**: Recognizes when users want to end conversations
- **Timeout Management**: Conversations expire after 60 seconds of inactivity
- **Participant Tracking**: Links multiple users in group conversations

### 7. **Commands** (`sentinel/commands/`)

User-facing command interfaces:

- **Slash Commands** (`slash.py`): Admin configuration commands for context channels, personas, heuristics, etc.
- **Context Menu Commands** (`context_menu.py`): Right-click actions on messages (e.g., "Flag for Moderation")

### 8. **Health Server** (`sentinel/health.py`)

Lightweight HTTP endpoint for deployment health checks:

- Provides JSON status including dry-run mode, database connection, and LLM configuration
- Used by platforms like Fly.io to monitor bot health

## Data Flow

### Message Moderation Flow

```
1. User posts message in Discord
   ↓
2. Bot receives `on_message` event
   ↓
3. Context channel auto-refresh (if applicable)
   ↓
4. ModerationAgent.handle_message()
   ↓
5. Check if bot should respond (ConversationManager)
   ↓
6. Fast-path: Check heuristics in database
   ↓
7. If heuristics match → LLM reasoning with matched patterns
   ↓
8. LLM uses function calling to:
   - Take moderation actions (delete, warn, timeout, kick, ban)
   - Send messages (with optional threading)
   - Suggest new heuristics for future detection
   ↓
9. Actions executed and logged to database
   ↓
10. Conversation context updated for follow-ups
```

### Heuristic Learning Flow

```
1. Admin flags a message (context menu) or adds context channel
   ↓
2. LLM analyzes message/channel content + server context
   ↓
3. LLM suggests patterns using `suggest_heuristic` function
   ↓
4. Patterns stored in heuristic_rules table
   ↓
5. Future messages checked against these patterns
   ↓
6. Matched patterns provided to LLM as pre-screening context
```

## Key Architectural Decisions

### 1. **Hybrid Approach: Heuristics + LLM**

- **Fast-path heuristics** for known patterns (spam, scams, profanity)
- **LLM reasoning** for context-dependent decisions
- **Continuous learning** from admin feedback and context channels

### 2. **Function-Calling Architecture**

- LLM has access to structured tools (delete_message, send_message, etc.)
- Enforces type safety and reduces hallucination
- Enables autonomous action while maintaining audit trails

### 3. **Context Channels**

- Admins designate channels containing rules/guidelines
- Bot periodically refreshes and summarizes content
- Summaries included in LLM system prompt for every decision
- Enables server-specific knowledge without hardcoding

### 4. **Conversation Tracking**

- 60-second conversation windows for natural follow-ups
- Automatic threading in busy channels (3+ active users)
- Exit keyword detection ("nevermind", "stop", etc.)
- Persistent storage for audit trails

### 5. **Database-First Design**

- PostgreSQL for all persistent state
- In-memory fallback if database unavailable
- Thread-safe async operations with locks
- Supports SSL for cloud providers (Supabase, etc.)

### 6. **Graceful Degradation**

- Bot functions without LLM (manual commands only)
- Continues without database (in-memory state)
- Dry-run mode for testing without real actions

### 7. **Global + Guild-Specific Heuristics**

- Global fraud patterns seeded on startup (Nitro scams, crypto scams, etc.)
- Guild-specific patterns learned from server context
- Combined for comprehensive coverage

## Technology Stack

- **Python 3.10+**: Modern async/await syntax
- **discord.py 2.3+**: Discord API wrapper with slash commands
- **OpenAI SDK**: GPT-4 function calling
- **PostgreSQL + psycopg2**: Persistent storage
- **Pydantic**: Type-safe configuration and state models
- **asyncio**: Async I/O for concurrent operations

## Deployment Considerations

- **Stateless**: State stored in database, not local files
- **Health Checks**: HTTP endpoint for container orchestration
- **Environment Variables**: 12-factor app configuration
- **Logging**: Structured logs with levels for debugging
- **Resource Usage**: Lightweight (suitable for free-tier hosting)

## Security & Safety

- **Dry-Run Mode**: Test configurations without real actions
- **Audit Logging**: All actions recorded with context
- **Permission Checks**: Slash commands require `manage_guild` or `manage_messages`
- **Rate Limiting**: Relies on Discord's built-in rate limits
- **Input Validation**: Pydantic models for all configuration
- **Prompt Injection Protection**:
  - UUID-tagged system prompts prevent role injection
  - 14 global heuristics detect common injection patterns
  - Automatic deletion, warning, and timeout for violators
  - LLM explicitly trained to recognize and reject manipulation attempts
  - See [Prompt Injection Protection](./Prompt%20Injection%20Protection.md) for details

## Future Extensibility

The architecture supports:

- Additional LLM providers (via base_url configuration)
- Custom automation rules per channel
- Multi-guild support (currently single-guild focused)
- Additional moderation tools (thread locking, role management, etc.)
- Webhook integration for external notifications
- Analytics dashboards (data already collected in database)
