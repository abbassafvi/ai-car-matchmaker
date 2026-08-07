"""T025 — the RESEARCHING phase behaviour, without an LLM.

Everything here is deterministic on purpose. The search is code-driven, the
ranking is code-driven and the relaxation ladder is code-driven, so the
whole of US2's core logic is testable with no key and no network -- which is
what lets CI cover it and leaves the live-gated tests (T021/T029) to prove
only the things that genuinely need a model.

The fake tool below mirrors the real adapter contract exactly as verified
against the running server (HANDOFF §8.5/§8.7a): results arrive in
`ToolMessage.artifact["structured_content"]`, and a failure arrives as a
ToolMessage with `status="error"` rather than as a raised exception.
"""
import pytest
from langchain_core.messages import ToolMessage

from agent.research import (
    RELAXATION_LADDER,
    ResearchOutcome,
    narration_brief,
    query_from_interview,
    run_research,
)
from agent.state import Phase, SessionState

INTERVIEW = {
    "use_case": "family road trips", "category": "SUV", "budget_max": 25000.0,
    "budget_min": None, "transaction_type": "buy", "target_date": "2026-09-01",
}


def listing(id_, **kw):
    base = {
        "id": id_, "brand": "Jeep", "model": "SUV Sport", "category": "SUV",
        "year": 2022, "price": 17391, "transaction_type": "buy",
        "rent_price_per_day": 90, "mileage": 34000, "fuel_type": "Petrol",
        "seats": 5, "location": "Austin, TX",
        "description": "<untrusted_listing_data>a car</untrusted_listing_data>",
        "listing_source": "AutoNation — Dealership",
        "availability_date": "2026-08-20",
    }
    base.update(kw)
    return base


class FakeSearchTool:
    """Records the queries it was called with and replays scripted results."""

    name = "search_listings"

    def __init__(self, responses, *, fail=False):
        self.responses = list(responses)
        self.calls = []
        self.fail = fail

    async def ainvoke(self, tool_call):
        args = tool_call["args"]
        self.calls.append(args)
        if self.fail:
            return ToolMessage(
                content="Error executing tool search_listings: boom",
                tool_call_id=tool_call["id"], name=self.name, status="error",
            )
        listings = self.responses.pop(0) if self.responses else []
        return ToolMessage(
            content=[{"type": "text", "text": "..."}],
            tool_call_id=tool_call["id"], name=self.name,
            artifact={"structured_content": {
                "listings": listings, "count": len(listings),
                "query": {k: v for k, v in args.items() if v is not None and k != "limit"},
            }},
        )


# --- query construction ---------------------------------------------------

def test_query_is_built_from_state_not_from_the_model():
    q = query_from_interview(INTERVIEW)
    assert q["category"] == "SUV"
    assert q["budget_max"] == 25000.0
    assert q["transaction_type"] == "buy"
    assert q["available_by"] == "2026-09-01"


def test_transaction_type_enum_is_unwrapped():
    """(str, Enum) stringifies as 'TransactionType.BUY'; the server expects
    'buy'. Same trap render_a2ui._display exists for.
    """
    from agent.state import TransactionType

    q = query_from_interview({**INTERVIEW, "transaction_type": TransactionType.BUY})
    assert q["transaction_type"] == "buy"


# --- the happy path -------------------------------------------------------

@pytest.mark.asyncio
async def test_first_search_uses_the_interview_constraints_verbatim():
    tool = FakeSearchTool([[listing("LST-0001")]])
    await run_research(INTERVIEW, [tool])

    assert len(tool.calls) == 1, "a matching first search must not be retried"
    call = tool.calls[0]
    assert call["category"] == "SUV"
    assert call["budget_max"] == 25000.0
    assert call["transaction_type"] == "buy"
    assert call["available_by"] == "2026-09-01"


@pytest.mark.asyncio
async def test_results_are_ranked_and_records_aligned_to_the_ranking():
    tool = FakeSearchTool([[
        listing("EXPENSIVE", price=24500, year=2019, mileage=90000),
        listing("BARGAIN", price=12000, year=2024, mileage=8000),
    ]])
    outcome = await run_research(INTERVIEW, [tool])

    assert outcome.found
    assert [r.listing_id for r in outcome.recommendations] == ["BARGAIN", "EXPENSIVE"]
    assert [l["id"] for l in outcome.listings] == ["BARGAIN", "EXPENSIVE"]


@pytest.mark.asyncio
async def test_listings_are_the_verbatim_tool_records():
    """Principle I: what gets persisted and rendered is the tool's own
    record, not a projection this module re-typed along the way.
    """
    source = listing("LST-0035", price=17391, year=2022)
    outcome = await run_research(INTERVIEW, [FakeSearchTool([[source]])])
    assert outcome.listings[0] == source
    assert isinstance(outcome.listings[0]["price"], int)


# --- zero results and the relaxation ladder (spec.md US2 AS2) -------------

@pytest.mark.asyncio
async def test_zero_matches_relaxes_availability_first():
    tool = FakeSearchTool([[], [listing("LST-0002")]])
    outcome = await run_research(INTERVIEW, [tool])

    assert outcome.relaxed == ["availability"]
    assert outcome.found
    assert tool.calls[0]["available_by"] == "2026-09-01"
    assert "available_by" not in tool.calls[1]


@pytest.mark.asyncio
async def test_ladder_widens_budget_before_abandoning_category():
    tool = FakeSearchTool([[], [], [listing("LST-0003")]])
    outcome = await run_research(INTERVIEW, [tool])

    assert outcome.relaxed == ["availability", "budget"]
    assert tool.calls[2]["budget_max"] == pytest.approx(30000.0)
    assert tool.calls[2]["category"] == "SUV", "category must survive a budget relaxation"


@pytest.mark.asyncio
async def test_exhausting_the_ladder_reports_nothing_rather_than_inventing():
    tool = FakeSearchTool([[], [], [], []])
    outcome = await run_research(INTERVIEW, [tool])

    assert not outcome.found
    assert outcome.recommendations == []
    assert outcome.relaxed == [step for step, _ in RELAXATION_LADDER]


@pytest.mark.asyncio
async def test_relaxation_steps_that_would_not_change_the_query_are_skipped():
    """An unconstrained search must not claim to have "relaxed" a filter it
    never applied -- the user would be told something untrue.
    """
    bare = {**INTERVIEW, "target_date": None, "budget_max": None, "category": None}
    tool = FakeSearchTool([[], []])
    outcome = await run_research(bare, [tool])

    assert outcome.relaxed == []
    assert len(tool.calls) == 1


@pytest.mark.asyncio
async def test_relaxation_is_named_in_the_reasoning_steps():
    outcome = await run_research(INTERVIEW, [FakeSearchTool([[], [listing("X")]])])
    assert any("relaxing the target availability date" in s for s in outcome.steps)


# --- failure paths --------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_error_status_is_detected_even_though_it_does_not_raise():
    """HANDOFF §8.7a: the adapter returns ToolMessage(status="error"), so
    code that only guards with try/except would treat a failed search as an
    empty result set and go on to "relax constraints" against nothing.
    """
    outcome = await run_research(INTERVIEW, [FakeSearchTool([], fail=True)])
    assert outcome.error is not None
    assert not outcome.found
    assert outcome.relaxed == []


@pytest.mark.asyncio
async def test_missing_search_tool_degrades_instead_of_raising():
    outcome = await run_research(INTERVIEW, [])
    assert outcome.error is not None
    assert not outcome.found


@pytest.mark.asyncio
async def test_missing_structured_content_refuses_to_fall_back_to_prose():
    """If the grounding channel is broken, failing loudly is correct --
    reading the stringified JSON in .content instead would silently
    downgrade Principle I's guarantee.
    """
    class NoArtifact(FakeSearchTool):
        async def ainvoke(self, tool_call):
            self.calls.append(tool_call["args"])
            return ToolMessage(content="{}", tool_call_id=tool_call["id"], name=self.name)

    outcome = await run_research(INTERVIEW, [NoArtifact([])])
    assert outcome.error is not None and "structured_content" in outcome.error


# --- narration brief ------------------------------------------------------

def test_narration_brief_carries_the_untrusted_delimiters_through():
    """Principle IV is only meaningful if untrusted text actually reaches
    the model -- T029 needs a path for the ADV-* probes to travel.
    """
    outcome = ResearchOutcome(listings=[listing("ADV-0001")], query={})
    from agent.ranking import rank
    outcome.recommendations = rank(outcome.listings, INTERVIEW)

    brief = narration_brief(outcome)
    assert "<untrusted_listing_data>" in brief
    assert "</untrusted_listing_data>" in brief


def test_narration_brief_on_zero_results_forbids_inventing_listings():
    brief = narration_brief(ResearchOutcome(relaxed=["availability"]))
    assert "NO listings" in brief
    assert "Do not invent listings" in brief


# --- state transition -----------------------------------------------------

def test_record_research_advances_the_phase_in_code():
    """Principle II: the RESEARCHING -> RESULTS_READY transition is a code
    path, not something the model announces it has done.
    """
    from agent.ranking import rank

    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    listings = [listing("LST-0001")]
    session.record_research(listings, rank(listings, INTERVIEW))

    assert session.phase == Phase.RESULTS_READY
    assert session.candidate_ids() == ["LST-0001"]
    assert session.candidate_listings[0]["price"] == 17391


def test_record_research_survives_the_json_round_trip():
    """Everything persisted must go through the checkpointer as plain JSON."""
    from agent.ranking import rank

    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    listings = [listing("LST-0001")]
    session.record_research(listings, rank(listings, INTERVIEW))

    restored = SessionState.model_validate(session.model_dump(mode="json"))
    assert restored == session
    assert restored.recommendations[0].reasoning == session.recommendations[0].reasoning
