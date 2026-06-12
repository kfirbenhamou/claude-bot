from __future__ import annotations
"""
services/llm.py
Shared Anthropic client for text generation across the family bot.
"""

import logging
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_client: Anthropic | None = None

DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
DEFAULT_SONNET = "claude-sonnet-4-6"


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        _client = Anthropic(api_key=api_key)
    return _client


def complete(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0,
    fallback_model: str | None = DEFAULT_HAIKU,
) -> str:
    """Single-turn completion: system prompt + one user message."""
    return complete_messages(
        system,
        [{"role": "user", "content": user}],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        fallback_model=fallback_model,
    )


def complete_messages(
    system: str,
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0,
    fallback_model: str | None = DEFAULT_HAIKU,
) -> str:
    """Multi-turn completion with Anthropic messages API."""
    model = model or os.getenv("ANTHROPIC_QA_MODEL", DEFAULT_HAIKU)
    client = _get_client()

    logger.info(f"[anthropic] model={model} messages={len(messages)}")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            temperature=temperature,
        )
    except Exception as e:
        msg = str(e)
        if fallback_model and fallback_model != model and (
            "404" in msg or "not_found" in msg.lower() or "model" in msg.lower()
        ):
            logger.warning(
                f"[anthropic] model failed ({model}); retrying with {fallback_model}. error={msg}"
            )
            response = client.messages.create(
                model=fallback_model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                temperature=temperature,
            )
        else:
            raise

    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts).strip()
