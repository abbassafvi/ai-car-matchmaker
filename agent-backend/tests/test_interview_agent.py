"""Live integration test for the real interview agent (US1 Acceptance
Scenario 3: all slots filled -> phase auto-transitions to RESEARCHING with
no further prompt needed). Needs a real LLM call, so it's skipped cleanly
when LLM_API_KEY isn't set -- same pattern as test_otel_setup.py.

Deliberately just one live-LLM test here: each call costs real tokens
against a real account, and the tool-level logic (overwrite semantics,
partial updates, phase gating) is already covered without any LLM calls in
test_tools.py and test_state.py. This test's only job is to prove the
LLM + InjectedState + Command plumbing genuinely works end-to-end inside a
real compiled graph -- something a mocked test can't demonstrate.
"""
import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_interview_agent, new_session_state


def _has_llm_credentials() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


@pytest.mark.skipif(not _has_llm_credentials(), reason="LLM_API_KEY not set")
def test_all_slots_in_one_message_transitions_to_researching():
    agent = build_interview_agent(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-thread-1"}}

    result = agent.invoke(
        {
            "messages": [{
                "role": "user",
                "content": (
                    "I need a Sedan to buy, budget up to $25000, for my daily "
                    "commute, and I want it by September 2026."
                ),
            }],
            "session": new_session_state("test-thread-1"),
        },
        config=config,
    )

    session = result["session"]
    assert session["phase"] == "RESEARCHING"
    assert session["interview"]["category"] == "Sedan"
    assert session["interview"]["transaction_type"] == "buy"
    assert session["interview"]["budget_max"] == 25000
