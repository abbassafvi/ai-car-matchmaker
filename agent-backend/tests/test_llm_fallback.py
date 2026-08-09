"""Tests for the LLM fallback mechanism.

Verifies that:
1. FallbackModel tries primary first, falls back on rate-limit errors
2. FallbackModel does NOT fall back on non-rate-limit errors
3. _is_rate_limit_error correctly identifies various error types
4. build_model returns FallbackModel when LLM_FALLBACK_PROVIDER is set
5. build_model returns primary only when no fallback is configured
"""
import os
from unittest.mock import patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult

from agent.llm import FallbackModel, build_model


class FakeModel(BaseChatModel):
    """A fake chat model for testing."""

    model_config = {"arbitrary_types_allowed": True}

    response: str = "fake response"
    should_fail: bool = False
    error_message: str = "rate limit exceeded"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.should_fail:
            raise Exception(self.error_message)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.should_fail:
            raise Exception(self.error_message)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )


# --- _is_rate_limit_error tests -------------------------------------------


def test_is_rate_limit_error_identifies_429():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("Error code: 429")) is True


def test_is_rate_limit_error_identifies_rate_limit_string():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("Rate limit exceeded")) is True


def test_is_rate_limit_error_identifies_quota():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("Quota exceeded for this API key")) is True


def test_is_rate_limit_error_identifies_tokens_per_minute():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("Tokens per minute limit reached")) is True


def test_is_rate_limit_error_identifies_resource_exhausted():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("ResourceExhausted: quota exhausted")) is True


def test_is_rate_limit_error_identifies_403_with_quota():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("403 Forbidden: quota exceeded")) is True


def test_is_rate_limit_error_rejects_non_rate_limit():
    model = FallbackModel(primary=FakeModel(), fallback=FakeModel())
    assert model._is_rate_limit_error(Exception("Invalid API key")) is False
    assert model._is_rate_limit_error(Exception("Connection timeout")) is False
    assert model._is_rate_limit_error(Exception("500 Internal Server Error")) is False


# --- FallbackModel behavior tests -----------------------------------------


def test_fallback_model_tries_primary_first():
    primary = FakeModel(response="primary response")
    fallback = FakeModel(response="fallback response")
    model = FallbackModel(primary=primary, fallback=fallback)

    result = model.invoke([HumanMessage(content="hello")])
    assert result.content == "primary response"


def test_fallback_model_falls_back_on_rate_limit():
    primary = FakeModel(should_fail=True, error_message="Error code: 429")
    fallback = FakeModel(response="fallback response")
    model = FallbackModel(primary=primary, fallback=fallback)

    result = model.invoke([HumanMessage(content="hello")])
    assert result.content == "fallback response"
    assert model._fallback_used is True


def test_fallback_model_does_not_fall_back_on_other_errors():
    primary = FakeModel(should_fail=True, error_message="Invalid API key")
    fallback = FakeModel(response="fallback response")
    model = FallbackModel(primary=primary, fallback=fallback)

    with pytest.raises(Exception, match="Invalid API key"):
        model.invoke([HumanMessage(content="hello")])
    assert model._fallback_used is False


def test_fallback_model_raises_if_both_fail():
    primary = FakeModel(should_fail=True, error_message="Error code: 429")
    fallback = FakeModel(should_fail=True, error_message="Fallback also failed")
    model = FallbackModel(primary=primary, fallback=fallback)

    with pytest.raises(Exception, match="Fallback also failed"):
        model.invoke([HumanMessage(content="hello")])


# --- build_model fallback integration tests -------------------------------


@patch.dict(os.environ, {
    "LLM_API_KEY": "test-key",
    "LLM_PROVIDER": "openai_compatible",
    "LLM_MODEL": "test-model",
    "LLM_FALLBACK_PROVIDER": "google",
    "LLM_FALLBACK_API_KEY": "fallback-key",
    "LLM_FALLBACK_MODEL": "gemini-3.6-flash",
})
def test_build_model_returns_fallback_model_when_configured():
    with patch("agent.llm._build_single_model") as mock_build:
        mock_primary = FakeModel(response="primary")
        mock_fallback = FakeModel(response="fallback")
        mock_build.side_effect = [mock_primary, mock_fallback]

        model = build_model()
        assert isinstance(model, FallbackModel)
        assert model.primary is mock_primary
        assert model.fallback is mock_fallback


@patch.dict(os.environ, {
    "LLM_API_KEY": "test-key",
    "LLM_PROVIDER": "openai_compatible",
    "LLM_MODEL": "test-model",
}, clear=True)
def test_build_model_returns_primary_only_when_no_fallback():
    with patch("agent.llm._build_single_model") as mock_build:
        mock_primary = FakeModel(response="primary")
        mock_build.return_value = mock_primary

        model = build_model()
        assert model is mock_primary


@patch.dict(os.environ, {
    "LLM_API_KEY": "test-key",
    "LLM_PROVIDER": "openai_compatible",
    "LLM_MODEL": "test-model",
    "LLM_FALLBACK_PROVIDER": "google",
    "LLM_FALLBACK_API_KEY": "",  # empty key
})
def test_build_model_warns_when_fallback_key_missing():
    with patch("agent.llm._build_single_model") as mock_build:
        mock_primary = FakeModel(response="primary")
        mock_build.return_value = mock_primary

        model = build_model()
        assert model is mock_primary  # no fallback
