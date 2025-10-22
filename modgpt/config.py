"""Configuration helpers for the mod-gpt bot."""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from pathlib import Path

_DEFAULT_MODEL = "gpt-4o-mini"


class BotSettings(BaseModel):
    """Runtime configuration parsed from environment variables."""

    discord_token: str = Field(..., alias="DISCORD_TOKEN")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default=_DEFAULT_MODEL, alias="OPENAI_MODEL")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    database_url: Optional[str] = Field(default=None, alias="SUPABASE_DB_URL")
    built_in_prompt: Optional[str] = Field(default=None, alias="BUILT_IN_PROMPT")

    class Config:
        populate_by_name = True


def load_settings(env_file: str | None = ".env") -> BotSettings:
    """Load and validate configuration, raising a helpful error if missing."""

    if env_file and Path(env_file).exists():
        load_dotenv(env_file)

    try:
        settings = BotSettings.model_validate(os.environ)
    except ValidationError as exc:
        missing = [err["loc"][0] for err in exc.errors() if err["type"] == "missing"]
        raise RuntimeError(
            (
                "Missing required configuration values: "
                f"{', '.join(missing)}. "
                "Create a .env file with DISCORD_TOKEN and optionally OPENAI_API_KEY."
            )
        ) from exc

    return settings
