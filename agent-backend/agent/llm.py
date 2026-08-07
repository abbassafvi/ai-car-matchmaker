"""LLM client factory. Provider: OpenRouter (OpenAI-compatible API), so
swapping the underlying model is an env-var change, not a code change.
Credentials come only from the environment -- never hardcoded, never
logged.
"""
from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_MAX_TOKENS = 1024


def build_model(max_tokens: int = DEFAULT_MAX_TOKENS) -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy agent-backend/.env.example "
            "to .env and fill it in, or export it in your shell."
        )
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        max_tokens=max_tokens,
    )
