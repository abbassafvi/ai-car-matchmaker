"""Unit tests for save_interview_state -- exercised directly as a tool
call (no LLM involved), which is enough to verify its logic since the
overwrite/phase-transition behavior lives in SessionState (already covered
by test_state.py) and this file's job is only to confirm the tool wraps
that behavior correctly through the Command/InjectedState mechanism.
"""
from agent.state import SessionState
from agent.tools import save_interview_state


def _call(session_dict: dict, **args):
    """Call the tool's underlying function directly via `.func`, bypassing
    BaseTool's schema/injection layer.

    InjectedState is resolved by LangGraph's ToolNode when a tool runs
    inside a real graph; calling `.invoke()` directly does NOT perform that
    injection (verified empirically -- `state["session"]` came back None
    even when `state=...` was passed as a kwarg to `.invoke()`, because the
    injection annotation is metadata for the graph runtime, not the
    BaseTool call path). `.func` sidesteps that entirely, which is exactly
    what a fast, LLM-free unit test of the tool's own logic needs.
    """
    return save_interview_state.func(**args, state={"session": session_dict}, tool_call_id="call-1")


def _fresh_session() -> dict:
    return SessionState(session_id="s1").model_dump(mode="json")


def test_fills_slots_and_returns_command_update():
    result = _call(_fresh_session(), use_case="road trip", transaction_type="rent")
    updated = result.update["session"]
    assert updated["interview"]["use_case"] == "road trip"
    assert updated["interview"]["transaction_type"] == "rent"
    assert updated["phase"] == "INTERVIEWING"  # still incomplete


def test_includes_a_tool_message_with_the_right_call_id():
    result = _call(_fresh_session(), use_case="commute")
    messages = result.update["messages"]
    assert len(messages) == 1
    assert messages[0].tool_call_id == "call-1"


def test_all_five_slots_in_one_call_transitions_phase():
    result = _call(
        _fresh_session(),
        use_case="commute", category="Sedan", budget_max=25000,
        transaction_type="buy", target_date="2026-09-01",
    )
    assert result.update["session"]["phase"] == "RESEARCHING"


def test_second_call_overwrites_not_appends():
    r1 = _call(_fresh_session(), budget_max=25000)
    r2 = _call(r1.update["session"], budget_max=30000)
    assert r2.update["session"]["interview"]["budget_max"] == 30000


def test_partial_update_leaves_other_slots_untouched():
    r1 = _call(_fresh_session(), use_case="commute")
    r2 = _call(r1.update["session"], category="SUV")
    interview = r2.update["session"]["interview"]
    assert interview["use_case"] == "commute"
    assert interview["category"] == "SUV"
