"""LLM client factory.

Provider is selected by env var, so switching provider *or* model stays a
config change rather than a code change (README and plan.md both make that
claim -- this module is what makes it true):

  LLM_PROVIDER  "google" (default) | "openai_compatible"
  LLM_MODEL     model id as that provider names it
  LLM_API_KEY   credential -- environment only, never hardcoded, never logged
  LLM_BASE_URL  openai_compatible only: the /chat/completions base URL

Why "google" is the default rather than Gemini's OpenAI-compatibility
endpoint, which would have been the smaller change:

Gemini 3.x models are thinking models, and their function calls carry a
`thought_signature` that must be echoed back on the following turn. The
OpenAI compatibility layer drops it, so the *second* turn of any tool-using
conversation fails with:

    400 INVALID_ARGUMENT - Function call is missing a thought_signature in
    functionCall parts.

Verified directly: the failure reproduces through langchain_openai against
the compat endpoint and is not fixed by `reasoning_effort`, while the native
client round-trips the signature correctly and completes the same
interview turn. Since every phase of this agent is tool-driven, the compat
path is unusable for Gemini 3.x -- it is kept only for other providers.
"""
from __future__ import annotations

import os

DEFAULT_PROVIDER = "google"
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"

# Gemini 3.x flash models spend part of the output budget on internal
# reasoning before emitting a tool call, so a small cap can be consumed
# before any visible output appears.
DEFAULT_MAX_TOKENS = 4096


class LLMNotConfiguredError(RuntimeError):
    """Raised when no API key is available.

    Distinct from a generic RuntimeError so callers can tell "operator
    hasn't configured this yet" apart from "the provider call failed", and
    degrade differently for each.
    """


def is_configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def build_model(max_tokens: int = DEFAULT_MAX_TOKENS):
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError(
            "LLM_API_KEY is not set. Copy agent-backend/.env.example to "
            "agent-backend/.env and fill it in, or export it in your shell."
        )

    provider = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            max_tokens=max_tokens,
        )

    if provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER {provider!r}. Expected 'google' or 'openai_compatible'."
    )
