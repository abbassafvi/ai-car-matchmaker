"""`refine_search` — the tool that closes the "found it, can't pick it" trap.

The M4a Phase C audit reproduced this end to end: in RESULTS_READY the
model could call `search_listings`, but **nothing writes
`candidate_listings` outside a research pass**. So the model found a car,
described it, the user said "that one", and `select_listing` refused it:

    'LST-0099' is not in the current candidate slate (LST-0001, LST-0002)

Two search paths with unequal privileges, only one of which updated state.
The fix removes the raw `search_listings` from RESULTS_READY and replaces
it with this, which re-runs the same code-driven pass the first search used
-- relaxation ladder, deterministic ranking and all -- and commits the
result through `SessionState.refine_results`.

The same tool also closes the related gap that a budget change after
results could not update interview state, so the interview A2UI surface
went stale the moment the user said "actually, make that $30,000".
"""
import pytest
from langchain_core.tools import StructuredTool

from agent.state import Booking, Phase, SessionState
from agent.tools import build_research_tools
from tests.support_live import scripted_search_tool, search_calls

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def listing(id_, **kw):
    base = {
        "id": id_, "brand": "Kia", "model": "Sportage", "category": "SUV",
        "year": 2022, "price": 19000, "transaction_type": "buy",
        "rent_price_per_day": None, "mileage": 30000, "fuel_type": "Petrol",
        "seats": 5, "location": "Austin, TX",
        "description": "<untrusted_listing_data>a car</untrusted_listing_data>",
        "listing_source": "AutoNation — Dealership",
        "availability_date": "2026-08-20",
    }
    base.update(kw)
    return base


ORIGINAL = [listing("LST-0001", price=24000), listing("LST-0002", price=21000)]
CHEAPER = [listing("LST-0009", price=12000), listing("LST-0010", price=13500)]


def results_ready(slate=ORIGINAL) -> SessionState:
    session = SessionState(session_id="s1", phase=Phase.INTERVIEWING)
    session.save_interview_slots(
        use_case="commute", category="SUV", budget_max=25000.0,
        transaction_type="buy", target_date="2026-12-31",
    )
    session.record_research(slate, [])
    assert session.phase == Phase.RESULTS_READY
    return session


async def refine(session: SessionState, slates, **changes):
    """Run the tool against a scripted search, outside a compiled graph.

    `InjectedState` only resolves inside a real graph (§8.14), so the
    underlying coroutine is called directly -- and `scripted_search_tool`
    is the same `StructuredTool`-shaped stand-in the live tests use, so the
    tool under test sees the artifact channel it will see in production.
    """
    search = scripted_search_tool(slates)
    (tool,) = build_research_tools([search])
    command = await tool.coroutine(
        state={"session": session.model_dump(mode="json")},
        tool_call_id="c1",
        **changes,
    )
    return command, search


async def test_refining_replaces_the_slate_so_the_new_cars_are_selectable():
    """The whole point. Before this the model could describe LST-0009 and
    then `select_listing` would refuse it, because the slate still held
    LST-0001/0002.
    """
    session = results_ready()
    command, _ = await refine(session, [CHEAPER], budget_max=15000.0)

    updated = SessionState.model_validate(command.update["session"])
    assert updated.candidate_ids() == ["LST-0009", "LST-0010"]

    # Non-vacuous: prove the id that used to be rejected is now accepted.
    updated.select_listing("LST-0009")
    assert updated.selected_listing_id == "LST-0009"
    assert updated.phase == Phase.FORM_FILLING


async def test_refining_updates_the_interview_state_the_surface_renders():
    """The budget the user just changed has to reach `InterviewState`, or
    the interview A2UI surface keeps showing the old one -- which is the
    stale-UI half of the same finding.
    """
    session = results_ready()
    command, _ = await refine(session, [CHEAPER], budget_max=15000.0)

    updated = SessionState.model_validate(command.update["session"])
    assert updated.interview.budget_max == 15000.0
    assert updated.interview.category == "SUV", "unchanged slots must be kept"


async def test_the_search_is_run_on_the_changed_constraints():
    """Non-vacuous in the direction that matters: assert what the tool
    actually sent, not merely that a slate came back. A refinement that
    quietly re-ran the *old* query would return plausible results and pass
    every assertion about the shape of its output.
    """
    session = results_ready()
    _, search = await refine(session, [CHEAPER], budget_max=15000.0)

    calls = search_calls(search)
    assert calls, "the search tool was never called"
    assert calls[0]["budget_max"] == 15000.0
    assert calls[0]["category"] == "SUV"


async def test_refining_from_form_filling_discards_the_booking():
    """A refinement is a retreat, and it must not leave a booking pointing
    at a car that is no longer on the slate.
    """
    session = results_ready()
    session.select_listing("LST-0001")
    session.booking = Booking(
        id="BKG-OLD", listing_id="LST-0001", session_id="s1", status="DRAFT",
    )
    command, _ = await refine(session, [CHEAPER], budget_max=15000.0)

    updated = SessionState.model_validate(command.update["session"])
    assert updated.phase == Phase.RESULTS_READY
    assert updated.selected_listing_id is None
    assert updated.booking is None


async def test_a_failed_refinement_keeps_the_results_the_user_has():
    """Degrade, do not destroy. Throwing away a usable slate because a
    retry failed would be a worse outcome than the failure itself.
    """
    session = results_ready()

    async def _explode(**_):
        raise RuntimeError("mcp-services is down")

    broken = StructuredTool.from_function(
        coroutine=_explode, name="search_listings", description="fails",
        response_format="content_and_artifact",
    )
    (tool,) = build_research_tools([broken])
    command = await tool.coroutine(
        state={"session": session.model_dump(mode="json")},
        tool_call_id="c1",
        budget_max=15000.0,
    )

    assert "session" not in command.update, "a failed search must not mutate state"
    assert "could not be run" in command.update["messages"][0].content


async def test_the_brief_handed_back_is_the_one_that_discloses_relaxation():
    """spec.md US2 AS2 has to hold for a *re*-search too.

    `narration_brief` is reused rather than reimplemented here precisely so
    that the two live defects Phase F found -- a silently widened search
    described as a match, and markdown in the chat bubble -- cannot come
    back through a second, hand-written brief.
    """
    session = results_ready()
    # Nothing at the asked-for price; the ladder relaxes and then finds.
    command, _ = await refine(session, [[], CHEAPER], budget_max=9000.0)

    brief = command.update["messages"][0].content
    assert "CRITICAL" in brief
    assert "do NOT meet everything the user asked for" in brief
    assert "no markdown" in brief


async def test_the_reasoning_trace_travels_on_the_artifact():
    """The steps reach the A2UI surface through the typed channel (§8.5),
    not by parsing them back out of the model's prose.
    """
    session = results_ready()
    command, _ = await refine(session, [CHEAPER], budget_max=15000.0)

    refined = command.update["messages"][0].artifact["refine_search"]
    assert refined["steps"], "no reasoning steps were carried"
    assert len(refined["steps"]) == len(refined["step_kinds"])
    assert [l["id"] for l in refined["listings"]] == ["LST-0009", "LST-0010"]


def test_no_marketplace_means_no_refine_tool():
    """Fail-soft: an unreachable marketplace leaves the name unresolved and
    therefore unbound, rather than binding a tool that cannot work.
    """
    assert build_research_tools([]) == []
