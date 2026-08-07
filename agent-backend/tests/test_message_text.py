"""Regression test for a bug found while swapping the LLM provider.

`AIMessage.content` is a plain string for some providers and a list of
content blocks for others. Gemini returns blocks, so the WebSocket handler
was about to send a JSON array to the frontend where the chat bubble
expects a string -- it would have rendered as `[object Object]`-ish junk in
the browser rather than the assistant's reply.

Caught because a scratch script printing `.content[:120]` raised
AttributeError on a list; worth pinning, since the failure only appears
with a provider whose live tests are credential-gated and quota-limited.
"""
from langchain_core.messages import AIMessage

from api.main import message_text


def test_plain_string_content_passes_through():
    assert message_text(AIMessage(content="hello")) == "hello"


def test_gemini_style_content_blocks_are_flattened():
    msg = AIMessage(content=[
        {"type": "text", "text": "Got it — "},
        {"type": "text", "text": "what's your budget?"},
    ])
    assert message_text(msg) == "Got it — what's your budget?"


def test_reasoning_blocks_are_not_shown_to_the_user():
    """Thinking/reasoning blocks are the model's scratchpad. The user-facing
    reasoning trace is the A2UI surface built from tool output, not this.
    """
    msg = AIMessage(content=[
        {"type": "thinking", "thinking": "internal chain of thought"},
        {"type": "text", "text": "What's your budget?"},
    ])
    assert message_text(msg) == "What's your budget?"


def test_bare_string_items_in_a_list_are_kept():
    assert message_text(AIMessage(content=["a", "b"])) == "ab"


def test_empty_content_is_empty_string_not_a_crash():
    assert message_text(AIMessage(content=[])) == ""


def test_result_is_always_a_string():
    """The wire protocol declares `content` as a string; nothing that
    reaches send_json may be a list or dict.
    """
    for content in ("s", [], [{"type": "text", "text": "x"}], [{"type": "image", "url": "u"}]):
        assert isinstance(message_text(AIMessage(content=content)), str)
