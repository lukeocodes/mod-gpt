"""LLM interaction helpers for Sentinel AI."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

try:
    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionMessageToolCall
except ImportError:  # pragma: no cover - library not installed in test environment
    AsyncOpenAI = None  # type: ignore
    ChatCompletionMessageToolCall = Any  # type: ignore

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when an LLM request is made without configuration."""


class LLMClient:
    """Wrapper around OpenAI's async client with graceful fallbacks."""

    def __init__(self, api_key: Optional[str], model: str, base_url: Optional[str] = None):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._client = None
        if api_key and AsyncOpenAI is not None:
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def is_configured(self) -> bool:
        return self._client is not None

    def update_config(
        self, api_key: Optional[str], model: str, base_url: Optional[str] = None
    ) -> None:
        """Update LLM configuration and reinitialize the client."""
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._client = None
        if api_key and AsyncOpenAI is not None:
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            logger.info(
                "LLM client reconfigured with model=%s, base_url=%s", model, base_url or "default"
            )

    async def run(
        self,
        messages: Iterable[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 1500,
    ) -> Dict[str, Any]:
        """Execute a chat completion with optional tool-calling support."""

        if self._client is None:
            raise LLMUnavailable(
                "LLM credentials not configured. Use the `set-llm` command to provide an API key before enabling reasoning."
            )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=list(messages),
            tools=tools,
            max_tokens=max_tokens,
            temperature=0.4,
        )

        choice = response.choices[0]
        return choice.model_dump()

    @staticmethod
    def extract_tool_calls(choice: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize tool call payloads from OpenAI responses."""

        tool_calls = choice.get("message", {}).get("tool_calls") or []
        normalized: List[Dict[str, Any]] = []
        for call in tool_calls:
            if isinstance(call, ChatCompletionMessageToolCall):
                normalized.append(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    }
                )
            else:
                normalized.append(
                    {
                        "id": call.get("id"),
                        "name": call.get("function", {}).get("name"),
                        "arguments": call.get("function", {}).get("arguments"),
                    }
                )
        return normalized
