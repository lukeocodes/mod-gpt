"""Configuration helpers for the Sentinel AI bot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, Field, ValidationError


class BotSettings(BaseModel):
    """Runtime configuration parsed from environment variables."""

    version: Optional[str] = Field(
        default=None,
        alias="VERSION",
        validation_alias=AliasChoices("VERSION", "APP_VERSION", "BOT_VERSION"),
    )
    discord_token: str = Field(..., alias="DISCORD_TOKEN")
    database_url: Optional[str] = Field(
        default=None,
        alias="SUPABASE_DB_URL",
        validation_alias=AliasChoices("SUPABASE_DB_URL", "DATABASE_URL", "database_url"),
    )
    health_host: str = Field(default="0.0.0.0", alias="HEALTH_HOST")
    health_port: int = Field(default=8080, alias="HEALTH_PORT")
    machine_id: Optional[str] = Field(
        default=None,
        alias="MACHINE_ID",
        validation_alias=AliasChoices("MACHINE_ID", "FLY_MACHINE_ID", "HOSTNAME"),
    )

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
                "Ensure DISCORD_TOKEN is set before running the bot."
            )
        ) from exc

    return settings
