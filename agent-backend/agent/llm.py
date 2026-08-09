"""LLM client factory with automatic provider fallback.

Provider is selected by env var, so switching provider *or* model stays a
config change rather than a code change (README and plan.md both make that
claim -- this module is what makes it true):

  LLM_PROVIDER  "google" (default) | "openai_compatible"
  LLM_MODEL     model id as that provider names it
  LLM_API_KEY   credential -- environment only, never hardcoded, never logged
  LLM_BASE_URL  openai_compatible only: the /chat/completions base URL
  LLM_MAX_TOKENS   output cap override (DEFAULT_MAX_TOKENS_BY_PROVIDER)
  LLM_MAX_RETRIES  retry budget override (DEFAULT_MAX_RETRIES_BY_PROVIDER)

Fallback provider (activates on rate limit / quota exhaustion):

  LLM_FALLBACK_PROVIDER  "google" | "openai_compatible"
  LLM_FALLBACK_MODEL     model id for the fallback provider
  LLM_FALLBACK_API_KEY   credential for the fallback provider
  LLM_FALLBACK_BASE_URL  openai_compatible only: fallback base URL

When the primary provider returns 429 (rate limit) or 403 (quota
exceeded), the FallbackModel transparently retries on the secondary
provider. This is critical for demos: Groq's 8000 TPM limit is hit
quickly with 10 tool schemas per request, and Vertex AI has its own
quotas. Dual-provider ensures at least one path is always available.

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

import logging
import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import ConfigDict

log = logging.getLogger(__name__)


class FallbackModel(BaseChatModel):
    """Wraps a primary and fallback model, switching on rate-limit errors.

    When the primary provider returns 429 (rate limit) or 403 (quota
    exceeded), the request is transparently retried on the fallback provider.
    This is the cheapest way to survive a quota exhaustion during a demo
    without manual intervention.

    The fallback is only attempted once per request -- if both providers
    fail, the fallback's error is raised. This prevents infinite loops
    where both providers are down.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    primary: BaseChatModel
    fallback: BaseChatModel
    _fallback_used: bool = False

    @property
    def _llm_type(self) -> str:
        return f"fallback({self.primary._llm_type}/{self.fallback._llm_type})"

    @property
    def _identifying_params(self) -> dict:
        return {
            "primary": self.primary._identifying_params,
            "fallback": self.fallback._identifying_params,
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ):
        try:
            return self.primary._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as e:
            if self._is_rate_limit_error(e):
                log.warning(
                    "Primary provider rate-limited (%s), falling back to secondary",
                    type(e).__name__,
                )
                self._fallback_used = True
                return self.fallback._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            raise

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ):
        try:
            return await self.primary._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception as e:
            if self._is_rate_limit_error(e):
                log.warning(
                    "Primary provider rate-limited (%s), falling back to secondary",
                    type(e).__name__,
                )
                self._fallback_used = True
                return await self.fallback._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )
            raise

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        """Check if the exception is a rate limit or quota error."""
        exc_str = str(exc).lower()
        exc_type = type(exc).__name__

        # OpenAI/Groq rate limits
        if "ratelimiterror" in exc_type.lower() or "rate limit" in exc_str:
            return True
        if "429" in exc_str:
            return True
        if "quota" in exc_str:
            return True
        if "tokens per minute" in exc_str:
            return True

        # Google/Vertex quota errors
        if "resourceexhausted" in exc_type.lower():
            return True
        if "403" in exc_str and "quota" in exc_str:
            return True
        if "requests per day" in exc_str:
            return True

        return False

DEFAULT_PROVIDER = "google"
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"

# Output cap, per provider. This is not a cosmetic default -- it is a
# latency control, and the right value differs by provider for opposite
# reasons:
#
#   google: Gemini 3.x flash models spend part of the output budget on
#     internal reasoning before emitting a tool call, so too small a cap is
#     consumed before any visible output appears. 4096 is headroom.
#
#   openai_compatible: Groq rate-limits on TOKENS PER MINUTE (8000/min on
#     openai/gpt-oss-120b), and the reservation counts prompt + max_tokens.
#     DeepAgents binds 10 tool schemas into every request, so at 4096 a
#     single interview turn reserves most of a minute's allowance and the
#     next one 429s into retry backoff. Measured on the real agent path:
#     4096 -> 39s and 68s per turn; 1024 -> 2.2s and 1.7s. Same model, same
#     conversation, same day. Do not raise this without re-measuring.
#
# Both are floors, not ceilings: too low starves reasoning models of output
# entirely (gpt-oss-120b at max_tokens=16 returns empty content, having
# spent the whole budget on reasoning tokens).
DEFAULT_MAX_TOKENS_BY_PROVIDER = {
    "google": 4096,
    "openai_compatible": 1024,
}
DEFAULT_MAX_TOKENS = DEFAULT_MAX_TOKENS_BY_PROVIDER["google"]


def default_max_tokens(provider: str) -> int:
    return DEFAULT_MAX_TOKENS_BY_PROVIDER.get(provider, DEFAULT_MAX_TOKENS)


# Retry budget, per provider. The client default is 2, which is too few for
# Groq and it matters more than it looks.
#
# Groq's limit is TOKENS per minute, not requests, so the ceiling is reached
# by a *burst* rather than by sustained load, and it clears in about a
# second: the 429 body literally says "Please try again in 1.005s". Two
# retries is enough for one throttled turn and not enough for several in
# succession -- which is exactly the shape of both a judge clicking through
# a demo and Phase F's live test run. Measured: six live agent turns
# back to back exhausted the default budget and raised
# `openai.RateLimitError: ... Limit 8000, Used 5609, Requested 2525`.
#
# HANDOFF §11 lists the TPM ceiling as the main demo risk; this is the
# cheapest mitigation for it, and it costs nothing when nothing is throttled.
# Trading a slower turn for a completed one is the right way round here --
# the alternative is the agent visibly dying mid-sentence.
DEFAULT_MAX_RETRIES_BY_PROVIDER = {
    "google": 2,
    "openai_compatible": 6,
}
DEFAULT_MAX_RETRIES = 2


def default_max_retries(provider: str) -> int:
    return DEFAULT_MAX_RETRIES_BY_PROVIDER.get(provider, DEFAULT_MAX_RETRIES)


class LLMNotConfiguredError(RuntimeError):
    """Raised when no API key is available.

    Distinct from a generic RuntimeError so callers can tell "operator
    hasn't configured this yet" apart from "the provider call failed", and
    degrade differently for each.
    """


def is_configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def build_model(max_tokens: int | None = None) -> BaseChatModel:
    """Build the chat model for the configured provider.

    If LLM_FALLBACK_PROVIDER is set, returns a FallbackModel that
    automatically retries on the fallback provider when the primary
    hits a rate limit or quota error.

    `max_tokens=None` means "use the right default for this provider" (see
    DEFAULT_MAX_TOKENS_BY_PROVIDER). `LLM_MAX_TOKENS` overrides it from the
    environment so a rate-limit ceiling can be tuned without a code change,
    matching how provider and model are already configured.
    """
    primary = _build_single_model(max_tokens)

    fallback_provider = os.environ.get("LLM_FALLBACK_PROVIDER")
    if not fallback_provider:
        return primary

    fallback_api_key = os.environ.get("LLM_FALLBACK_API_KEY")
    if not fallback_api_key:
        log.warning(
            "LLM_FALLBACK_PROVIDER set but LLM_FALLBACK_API_KEY missing; "
            "fallback disabled"
        )
        return primary

    try:
        fallback = _build_single_model(
            max_tokens=None,
            provider=fallback_provider,
            model=os.environ.get("LLM_FALLBACK_MODEL"),
            api_key=fallback_api_key,
            base_url=os.environ.get("LLM_FALLBACK_BASE_URL"),
        )
        log.info(
            "LLM fallback configured: %s -> %s",
            os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER),
            fallback_provider,
        )
        return FallbackModel(primary=primary, fallback=fallback)
    except Exception:
        log.exception("Failed to build fallback model; primary only")
        return primary


def _build_single_model(
    max_tokens: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Build a single provider model (no fallback)."""
    api_key = api_key or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMNotConfiguredError(
            "LLM_API_KEY is not set. Copy agent-backend/.env.example to "
            "agent-backend/.env and fill it in, or export it in your shell."
        )

    provider = (provider or os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)).lower()
    model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    if max_tokens is None:
        env_override = os.environ.get("LLM_MAX_TOKENS")
        max_tokens = int(env_override) if env_override else default_max_tokens(provider)

    retries_override = os.environ.get("LLM_MAX_RETRIES")
    max_retries = int(retries_override) if retries_override else default_max_retries(provider)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )

    if provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=base_url or os.environ.get("LLM_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER {provider!r}. Expected 'google' or 'openai_compatible'."
    )
