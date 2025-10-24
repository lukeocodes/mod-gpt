# Sentinel AI Tests

This directory contains automated tests for the Sentinel AI Discord moderation bot.

## Running Tests

### Using uv (recommended)

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_message_splitting.py

# Run with verbose output
uv run pytest -v

# Run with coverage
uv run pytest --cov=sentinel
```

### Using pytest directly

```bash
# Activate virtual environment first
source .venv/bin/activate

# Run tests
pytest
pytest tests/test_message_splitting.py -v
```

## Test Structure

- `test_message_splitting.py` - Tests for Discord message splitting functionality that handles the 2000 character limit
- `test_prompt_injection.py` - Tests for prompt injection detection heuristics and security patterns

## Adding New Tests

1. Create a new test file with the prefix `test_` (e.g., `test_feature.py`)
2. Import pytest and the modules you want to test
3. Create test classes or functions with descriptive names
4. Run tests to verify they work

Example:

```python
import pytest
from sentinel.module import function_to_test

def test_feature():
    """Test description."""
    result = function_to_test()
    assert result == expected_value
```

## Test Coverage

Run tests with coverage to see which parts of the codebase are tested:

```bash
uv run pytest --cov=sentinel --cov-report=html
open htmlcov/index.html
```

## Continuous Integration

Tests are automatically run in CI/CD pipelines on pull requests and commits to main.
