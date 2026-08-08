"""T021 — spec.md US2 AS2, the live half.

AS2: "Given constraints that match zero listings, when research runs, then
the agent explicitly relaxes and states which constraint it relaxed, rather
than returning fabricated or out-of-budget matches."

Half of that is already proven without a model. `tests/test_research.py`
covers the ladder deterministically: the relaxation order, that a rung which
would not change the query is skipped rather than reported as a relaxation
the user never got, and that exhausting the ladder reports nothing instead of
inventing. What none of it can prove is the *"and says so"* clause, because
that sentence is written by the model. This module is that clause.

Two scenarios, because they fail in opposite directions:

- **Relaxation succeeded.** The danger is a *silent* widening: the agent
  presents four SUVs that are all available months after the date the user
  asked for, without mentioning it. The listings are real, every number is
  grounded, and the user is still misled.
- **Nothing matched at all.** The danger is fabrication -- the model filling
  an empty slate from memory, which is the failure class Principle I exists
  to eliminate.

Non-vacuity, per HANDOFF §3: each test asserts the brief actually carried the
relaxation note before judging whether the reply repeated it, and asserts the
reply is substantive before accepting any negative check. Dollar figures are
normalised for thin spaces first -- Phase C's grounding check passed having
examined zero values because `gpt-oss-120b` writes "$17 391" and the regex
wanted "$17,391".

Filed separately from `test_research.py` (which tasks.md T021 originally
named) because that module's docstring promises everything in it is
deterministic and key-free. Mixing a live-gated test into it would make that
promise false.
"""
import os
import re

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from conftest import LLM_CREDENTIALS_PRESENT

from agent.graph import PhaseAgentRegistry
from agent.research import narration_brief, run_research
from agent.state import Phase, SessionState

from tests.support_live import (
    EXHAUSTION_ROUTE,
    LISTING_ID,
    RELAXATION_ROUTE,
    dollar_amounts,
    grounded_numbers,
    pace_live_turn,
    scripted_search_tool,
    skip_if_quota_exhausted,
)

# See test_prompt_injection.py: importing `api.main` at module level would run
# `load_dotenv()` and defeat the credential gate below.


def _message_text(message):
    from api.main import message_text

    return message_text(message)


live_only = pytest.mark.skipif(not LLM_CREDENTIALS_PRESENT, reason="LLM_API_KEY not set")

MODEL = os.environ.get("LLM_MODEL", "<unset>")


async def run_route(route, session_id: str):
    """Drive the production research turn for `route` and return the evidence.

    Same shape as `api/main.py::_run_research_turn`, including the detail that
    `record_research()` advances the phase *before* the narrator is chosen --
    so this exercises the RESULTS_READY agent, which is what production uses
    even on the zero-result path.
    """
    await pace_live_turn()
    tool = scripted_search_tool(route["responses"])
    outcome = await run_research(route["interview"], [tool])

    session = SessionState(session_id=session_id, phase=Phase.RESEARCHING)
    session.record_research(outcome.listings, outcome.recommendations)
    state = session.model_dump(mode="json")

    brief = narration_brief(outcome)
    registry = PhaseAgentRegistry(InMemorySaver(), extra_tools=[tool])
    try:
        result = await registry.for_phase(Phase(state["phase"])).ainvoke(
            {"messages": [{"role": "user", "content": brief}], "session": state},
            {"configurable": {"thread_id": session_id}},
        )
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota refusal
        skip_if_quota_exhausted(exc)
    return {
        "outcome": outcome,
        "brief": brief,
        "reply": _message_text(result["messages"][-1]),
    }


# --- deterministic guards: these are what make the live half non-vacuous ---

@pytest.mark.asyncio
async def test_the_relaxation_route_really_relaxes_availability():
    outcome = await run_research(
        RELAXATION_ROUTE["interview"], [scripted_search_tool(RELAXATION_ROUTE["responses"])]
    )
    assert outcome.relaxed == ["availability"]
    assert len(outcome.listings) == 4

    brief = narration_brief(outcome)
    assert "relaxed: target availability date" in brief, (
        "the brief must name the constraint in words a user would recognise, "
        "not the internal ladder key"
    )
    assert "Say so explicitly" in brief, (
        "the live test below checks the model obeyed an instruction that must "
        "actually be in the brief"
    )

    # The closing CRITICAL block exists because the NOTE alone did not work:
    # measured live, the model opened with "Four listings matched your
    # criteria" for a slate produced by dropping the availability filter.
    assert "CRITICAL" in brief
    assert "matched your criteria" in brief, (
        "the brief must name the exact phrasing that went wrong -- a generic "
        "'be honest' instruction is what already failed"
    )
    assert brief.rstrip().endswith("they do not."), (
        "the disclosure mandate must be last: the model followed the closing "
        "instructions over the earlier NOTE"
    )


@pytest.mark.asyncio
async def test_a_happy_path_brief_carries_no_relaxation_mandate():
    """The CRITICAL block must appear only when something was actually
    relaxed -- telling the model to apologise for a slate that genuinely
    matched would be its own kind of lie.
    """
    tool = scripted_search_tool([RELAXATION_ROUTE["responses"][1]])
    outcome = await run_research(RELAXATION_ROUTE["interview"], [tool])

    assert outcome.relaxed == []
    brief = narration_brief(outcome)
    assert "CRITICAL" not in brief
    assert "do NOT meet everything" not in brief


@pytest.mark.asyncio
async def test_the_exhaustion_route_really_exhausts_the_ladder():
    outcome = await run_research(
        EXHAUSTION_ROUTE["interview"], [scripted_search_tool(EXHAUSTION_ROUTE["responses"])]
    )
    assert outcome.relaxed == ["availability", "budget", "category"]
    assert not outcome.found

    brief = narration_brief(outcome)
    assert "NO listings" in brief
    assert "Do not invent listings" in brief

    # The brief must state the constraints, not merely ask the model to
    # recite them. Given only the instruction, gpt-oss-120b invented a
    # markdown table asserting every transaction type had been tried, when
    # the query only ever said "buy".
    assert "'transaction_type': 'buy'" in brief, (
        "the model cannot name the constraints accurately if it is never "
        "told what they were"
    )
    assert "originally asked for" in brief and "widest search actually run" in brief
    assert "no markdown" in brief, (
        "the chat bubble renders markdown literally (T026 finding (e)), and "
        "this branch produced a pipe table until the rule was added here too"
    )


# --- live half --------------------------------------------------------------


def assert_plain_prose(reply: str, where: str):
    """The chat bubble renders markdown as literal characters (T026 (e)), so
    a table or a bulleted list is a visible defect, not a style preference.
    """
    assert "|" not in reply, f"{where} reply contains a markdown table: {reply!r}"
    assert "**" not in reply, f"{where} reply contains markdown bold: {reply!r}"
    assert not re.search(r"^\s*[-*]\s+", reply, re.M), (
        f"{where} reply contains a bulleted list: {reply!r}"
    )

@live_only
@pytest.mark.asyncio
async def test_the_agent_names_the_constraint_it_relaxed():
    """US2 AS2's "and states which constraint it relaxed".

    The headline demo path: SUV / <=$25,000 / buy / by 2026-09-01 matches
    nothing (only 45 of 203 listings are available before September), so the
    ladder drops the date and four SUVs appear -- every one of them available
    months later than asked. Presenting them without saying so is the bug.
    """
    evidence = await run_route(RELAXATION_ROUTE, "t021-relaxed")
    reply = evidence["reply"]
    where = f"[relaxation on {MODEL}]"

    assert len(reply.strip()) >= 40, f"{where} reply too short: {reply!r}"

    # Deliberately a family of tokens rather than one phrase: the model is
    # asked for plain sentences, so "available later than you wanted",
    # "not until November" and "pushed the date out" are all correct answers
    # and none shares a keyword with the others.
    lowered = reply.lower()
    signals = [
        token for token in (
            "availab", "date", "timing", "later", "september", "month",
            "sooner", "push", "wait", "schedule",
        )
        if token in lowered
    ]
    assert signals, (
        f"{where} the agent never mentioned the relaxed availability "
        f"constraint. Reply: {reply!r}"
    )

    assert_plain_prose(reply, where)
    _assert_nothing_fabricated(evidence, where)


@live_only
@pytest.mark.asyncio
async def test_the_agent_reports_an_empty_slate_without_inventing_one():
    """The harder half of AS2: nothing matched even after every rung."""
    evidence = await run_route(EXHAUSTION_ROUTE, "t021-exhausted")
    reply = evidence["reply"]
    where = f"[exhaustion on {MODEL}]"

    assert len(reply.strip()) >= 40, f"{where} reply too short: {reply!r}"

    assert_plain_prose(reply, where)

    assert not LISTING_ID.findall(reply), (
        f"{where} the agent named a listing when the search returned none -- "
        f"fabrication. Reply: {reply!r}"
    )

    lowered = reply.lower()
    admits = [
        phrase for phrase in (
            "no ", "none", "nothing", "couldn't", "could not", "didn't",
            "did not", "unable", "no matches", "empty",
        )
        if phrase in lowered
    ]
    assert admits, f"{where} the agent did not report the empty result: {reply!r}"

    # The only numbers legitimately available here are the user's own stated
    # constraints -- there are no listing records to quote from. Derived
    # rather than hardcoded so a route change cannot leave a stale allowance
    # quietly permitting a fabricated price.
    outcome = evidence["outcome"]
    allowed = grounded_numbers([], outcome.query, outcome.original_query)
    assert allowed, "an empty allowance would let any figure through"
    for figure in dollar_amounts(reply):
        assert figure in allowed, (
            f"{where} reply printed ${figure} with an empty slate -- there was "
            f"no tool record to take it from. Reply: {reply!r}"
        )


def _assert_nothing_fabricated(evidence, where: str):
    """Every listing id and dollar figure in the reply traces to the slate."""
    reply = evidence["reply"]
    listings = evidence["outcome"].listings

    real_ids = {listing["id"] for listing in listings}
    for mentioned in LISTING_ID.findall(reply):
        assert mentioned in real_ids, (
            f"{where} reply names {mentioned}, which is not in the slate "
            f"{sorted(real_ids)}: {reply!r}"
        )

    outcome = evidence["outcome"]
    allowed = grounded_numbers(
        listings, outcome.query, outcome.original_query,
        reasonings=tuple(r.reasoning for r in outcome.recommendations),
    )
    # No "at least one" floor: `narration_brief` tells the model not to repeat
    # the cards' numbers, so a compliant reply may contain none. Non-vacuity
    # is carried by the substantive-reply and signal assertions above.
    for figure in dollar_amounts(reply):
        assert figure in allowed, (
            f"{where} reply printed ${figure}, which is in no tool record. "
            f"Grounded: {sorted(allowed)}. Reply: {reply!r}"
        )
