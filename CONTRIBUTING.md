# Contributing to mod-gpt

Thank you for considering contributing to mod-gpt! This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful, constructive, and professional in all interactions. We aim to maintain a welcoming and inclusive community.

## How to Contribute

### Reporting Bugs

Before creating a bug report:
1. Check the [issue tracker](https://github.com/your-username/mod-gpt/issues) for existing reports
2. Verify the bug exists in the latest version
3. Collect relevant information (logs, configuration, steps to reproduce)

**Bug Report Template:**
```
**Description:** Clear description of the bug

**Steps to Reproduce:**
1. Step one
2. Step two
3. Step three

**Expected Behavior:** What should happen

**Actual Behavior:** What actually happens

**Environment:**
- Python version: 
- Discord.py version:
- OpenAI SDK version:
- Database: (PostgreSQL version, provider)
- Deployment platform: (Fly.io, Heroku, self-hosted, etc.)

**Logs:**
```
Paste relevant logs here
```

**Additional Context:** Any other relevant information
```

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:
1. Check if the enhancement already exists in issues
2. Describe the use case and benefit
3. Provide examples of how it would work
4. Consider backward compatibility

### Pull Requests

1. **Fork the repository** and create a branch from `main`
2. **Follow the coding style** (see below)
3. **Write clear commit messages** using conventional commits
4. **Test your changes** thoroughly
5. **Update documentation** if you change behavior
6. **Submit the PR** with a clear description

**PR Template:**
```
**Description:** What does this PR do?

**Motivation:** Why is this change needed?

**Changes:**
- Change 1
- Change 2
- Change 3

**Testing:**
How did you test these changes?

**Documentation:**
Did you update relevant documentation?

**Breaking Changes:**
Does this introduce any breaking changes?
```

## Development Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 12+ (local or remote)
- Discord bot token (for testing)
- OpenAI API key (for testing)

### Installation

```bash
# Clone your fork
git clone https://github.com/your-username/mod-gpt.git
cd mod-gpt

# Install dependencies
pip install -e .

# Create .env file
cp .env.example .env
# Edit .env with your credentials

# Run the bot
python main.py
```

### Testing

Currently, testing is manual:

1. **Set up test Discord server**
   - Create a private server for testing
   - Invite your development bot
   - Create test channels

2. **Enable dry-run mode**
   ```
   /set-dry-run enabled
   ```

3. **Test scenarios**
   - Add context channels
   - Send test messages (spam, profanity, scams)
   - Use slash commands
   - Flag messages for learning
   - Test conversations

4. **Review logs**
   - Check console output
   - Review database entries
   - Verify actions logged correctly

**Future:** We plan to add automated tests using pytest and discord.py mocking.

## Coding Style

### Python Style

- **PEP 8** compliant (with some exceptions, see below)
- **Line length:** 100 characters (configured in pyproject.toml)
- **Formatter:** Black
- **Linter:** Ruff

**Run formatters:**
```bash
# Format code
black .

# Lint
ruff check .
```

### Naming Conventions

- **Functions/methods:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private methods:** `_leading_underscore`
- **Async functions:** Prefix with `async def` (obvious, but be consistent)

### Type Hints

Use type hints for all function signatures:

```python
def calculate_confidence(pattern: str, content: str) -> float:
    ...

async def fetch_messages(channel: discord.TextChannel, limit: int = 50) -> List[discord.Message]:
    ...
```

### Documentation

- **Docstrings:** Use for all public classes and complex functions
- **Comments:** Explain "why", not "what" (code should be self-explanatory)
- **Type hints:** Prefer type hints over docstring types

**Docstring Format:**
```python
def build_system_prompt(state: BotState, built_in_prompt: str | None = None) -> str:
    """Build the system prompt for LLM reasoning.
    
    Combines persona, context channels, memories, and built-in guidance
    into a comprehensive system prompt.
    
    Args:
        state: Current bot state including persona and context
        built_in_prompt: Optional deployment-specific guidance
        
    Returns:
        Complete system prompt with guardrails
    """
    ...
```

### Imports

Organize imports in three groups:
1. Standard library
2. Third-party packages
3. Local modules

```python
# Standard library
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

# Third-party
import discord
from discord.ext import commands

# Local
from ..db import Database
from ..services.llm import LLMClient
```

### Error Handling

- Use specific exceptions (not bare `except:`)
- Log errors with context
- Fail gracefully when possible

```python
try:
    await database.store_action(record)
except Exception:
    logger.exception("Failed to store moderation action - continuing anyway")
    # Don't let database errors stop moderation
```

### Async Best Practices

- Use `async def` for I/O-bound operations
- Use `await` for all async calls
- Use `asyncio.gather()` for parallel operations
- Use `asyncio.Lock` for shared state

## Commit Messages

We use **[Conventional Commits](https://www.conventionalcommits.org/)** for clear, structured commit history.

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring (no behavior change)
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks, dependency updates
- `ci`: CI/CD changes

### Scopes (optional)

- `bot`: Bot initialization and event handling
- `moderation`: Moderation agent and logic
- `state`: State management
- `db`: Database and queries
- `llm`: LLM client and prompts
- `commands`: Slash commands and context menus
- `conversations`: Conversation tracking
- `heuristics`: Heuristic system
- `docs`: Documentation

### Examples

```
feat(heuristics): add fuzzy matching for hate speech detection

Implements Levenshtein distance-based matching to catch common
evasion tactics like character substitution.

Closes #42

---

fix(moderation): prevent duplicate action logs

Fixed race condition where rapid events could cause duplicate
moderation records in database.

---

docs: add deployment guide for Railway

---

refactor(commands): extract command registration to separate module

Moved slash command definitions from bot.py to commands/slash.py
for better organization.

---

chore(deps): update discord.py to 2.3.2

Security update for CVE-2024-XXXXX
```

## Pull Request Process

1. **Branch naming:**
   - `feat/description` for features
   - `fix/description` for bug fixes
   - `docs/description` for documentation
   - `refactor/description` for refactoring

2. **Before submitting:**
   - Run formatters: `black . && ruff check --fix .`
   - Test thoroughly in your Discord server
   - Update documentation if behavior changed
   - Write clear commit messages

3. **PR description:**
   - Explain what and why
   - Reference related issues
   - Describe testing performed
   - Note any breaking changes

4. **Review process:**
   - Maintainers will review within 7 days
   - Address feedback promptly
   - Keep discussion constructive
   - Be patient and respectful

5. **After approval:**
   - Maintainer will merge (no need to squash yourself)
   - Delete your branch after merge

## Project Structure

```
mod-gpt/
├── main.py                 # Entry point
├── modgpt/
│   ├── __init__.py
│   ├── bot.py              # Bot initialization and events
│   ├── db.py               # Database layer
│   ├── health.py           # Health check server
│   ├── commands/
│   │   ├── slash.py        # Slash commands
│   │   └── context_menu.py # Context menu commands
│   ├── models/
│   │   └── config.py       # Configuration models
│   ├── services/
│   │   ├── llm.py          # LLM client
│   │   ├── state.py        # State management
│   │   ├── moderation.py   # Moderation agent
│   │   └── conversations.py # Conversation tracking
│   └── utils/
│       ├── prompts.py      # Prompt templates
│       └── seed_heuristics.py # Global heuristics
├── docs/                   # Documentation
├── pyproject.toml          # Dependencies
├── Dockerfile              # Container definition
├── fly.toml                # Fly.io config
└── README.md
```

## Areas for Contribution

We especially welcome contributions in these areas:

### High Priority
- [ ] Automated testing (pytest, discord.py mocking)
- [ ] Performance optimization (heuristic matching, database queries)
- [ ] Additional deployment guides (AWS, GCP, Azure)
- [ ] Metrics and analytics dashboard
- [ ] Internationalization (i18n) support

### Medium Priority
- [ ] Additional LLM providers (Anthropic, local models)
- [ ] Role-based permissions for commands
- [ ] Scheduled actions (auto-archive old messages, etc.)
- [ ] Voice channel moderation
- [ ] Content warning system

### Nice to Have
- [ ] Web dashboard for configuration
- [ ] Mobile app for moderation
- [ ] Machine learning model training from moderation history
- [ ] Multi-guild support (single bot, multiple servers)

## Questions?

- **General questions:** Open a [GitHub Discussion](https://github.com/your-username/mod-gpt/discussions)
- **Bug reports:** Create an [Issue](https://github.com/your-username/mod-gpt/issues)
- **Security issues:** Email maintainers privately (see SECURITY.md)

Thank you for contributing to mod-gpt! 🎉

