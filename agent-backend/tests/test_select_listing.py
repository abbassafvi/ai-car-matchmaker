"""T028(b) — listing selection: the transition M4a is gated on.

Constitution Principle II's own worked example is `open_booking_form` being
unavailable until a listing is selected, so until Phase E there was nothing
in the system that could satisfy that precondition: `TOOLS_BY_PHASE` had
named `select_listing` since M2.5, and no module implemented it.

Two entry points reach the same state method deliberately -- a catalogue
Button click (applied in code by `api/main._handle_action`) and the model
calling the `select_listing` tool -- so the tests below pin that they cannot
diverge, and that neither can select a listing the marketplace never
returned (Principle I).
"""
import pytest

from agent.ranking import rank
from agent.state import Phase, SessionState
from agent.tools import select_listing


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


INTERVIEW = {"category": "SUV", "budget_max": 25000.0, "transaction_type": "buy"}


def results_ready_session() -> SessionState:
    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    slate = [listing("LST-0001"), listing("LST-0002", price=21000)]
    session.record_research(slate, rank(slate, INTERVIEW))
    assert session.phase == Phase.RESULTS_READY
    return session


# --- the state transition -------------------------------------------------


def test_selecting_advances_the_phase_in_code():
    session = results_ready_session()
    session.select_listing("LST-0002")

    assert session.selected_listing_id == "LST-0002"
    assert session.phase == Phase.FORM_FILLING


def test_selection_unlocks_exactly_the_booking_tools():
    """Principle II end to end: the gate opens on the transition, and only
    to the booking phase's tools.

    Two changes here in M4a Phase C, both deliberate and both the contract
    rather than merely an updated expectation:

    - `submit_booking` is **gone** from the model's tool set. Its `fields`
      argument is free-form, so a model-callable version could invent the
      user's name and email into a booking they never made. It is reachable
      only through the MCP App bridge, carrying values the user typed. A
      name left in the gate table that nothing binds is the hole M2.5 left
      with `select_listing`, so it was removed rather than merely unbound.
    - `select_listing` and `refine_search` are **added**, so FORM_FILLING
      stops being a one-way door: before this, a user who typed "actually,
      the Kia" had no tool that could help them, while a user who *clicked*
      another card sailed through, because `_handle_action` runs ahead of
      the gate.
    """
    session = results_ready_session()
    assert "open_booking_form" not in session.available_tools()

    session.select_listing("LST-0001")
    assert session.available_tools() == [
        "open_booking_form", "select_listing", "refine_search",
    ]
    assert "submit_booking" not in session.available_tools()


def test_cannot_select_a_listing_that_was_never_recommended():
    """Principle I: the slate is what a tool actually returned, so a
    hallucinated or stale id must not become a selection.
    """
    session = results_ready_session()
    with pytest.raises(ValueError, match="LST-9999"):
        session.select_listing("LST-9999")

    assert session.selected_listing_id is None
    assert session.phase == Phase.RESULTS_READY


def test_rejected_selection_leaves_the_session_untouched():
    session = results_ready_session()
    before = session.model_dump(mode="json")
    with pytest.raises(ValueError):
        session.select_listing("nope")
    assert session.model_dump(mode="json") == before


def test_cannot_select_from_an_empty_slate():
    session = SessionState(session_id="s1", phase=Phase.RESULTS_READY)
    with pytest.raises(ValueError, match="empty"):
        session.select_listing("LST-0001")


def test_selected_listing_returns_the_verbatim_record():
    """M4a pre-fills the booking form from this, so it must be the tool's
    own record rather than anything re-derived.
    """
    session = results_ready_session()
    session.select_listing("LST-0002")
    record = session.selected_listing()

    assert record["id"] == "LST-0002"
    assert record["price"] == 21000 and isinstance(record["price"], int)
    assert record is session.candidate_listings[
        session.candidate_ids().index("LST-0002")
    ]


def test_selected_listing_is_none_before_a_selection():
    assert results_ready_session().selected_listing() is None


def test_selection_survives_the_json_round_trip():
    session = results_ready_session()
    session.select_listing("LST-0001")
    restored = SessionState.model_validate(session.model_dump(mode="json"))

    assert restored.selected_listing_id == "LST-0001"
    assert restored.phase == Phase.FORM_FILLING
    assert restored.selected_listing()["id"] == "LST-0001"


def test_reselecting_replaces_rather_than_accumulates():
    """spec.md Edge Cases: picking a different listing discards the first
    choice rather than silently merging the two.
    """
    session = results_ready_session()
    session.select_listing("LST-0001")
    session.select_listing("LST-0002")
    assert session.selected_listing_id == "LST-0002"


# --- the model-facing tool ------------------------------------------------


def _call_tool(session: SessionState, listing_id: str):
    """`.func` bypasses InjectedState, which only resolves inside a real
    compiled graph (HANDOFF §8.14) -- same pattern as test_tools.py.
    """
    return select_listing.func(
        listing_id=listing_id,
        state={"session": session.model_dump(mode="json")},
        tool_call_id="call-1",
    )


def test_tool_records_the_selection_and_advances_the_phase():
    result = _call_tool(results_ready_session(), "LST-0001")
    updated = result.update["session"]

    assert updated["selected_listing_id"] == "LST-0001"
    assert updated["phase"] == "FORM_FILLING"


def test_tool_confirmation_names_the_car_from_the_record():
    result = _call_tool(results_ready_session(), "LST-0001")
    text = result.update["messages"][0].content
    assert "LST-0001" in text and "2022" in text and "Jeep" in text


def test_tool_rejects_an_unknown_id_without_raising_or_mutating():
    """A tool that raised would abort the turn; the model needs to be able
    to recover by asking which listing the user meant.
    """
    result = _call_tool(results_ready_session(), "LST-9999")

    assert "session" not in result.update, "a rejected selection must not write state"
    message = result.update["messages"][0].content
    assert "Could not select" in message and "LST-9999" in message


def test_tool_and_direct_call_produce_the_same_state():
    """The Button path and the model path must not diverge -- they are the
    same method, and this pins it.
    """
    via_tool = _call_tool(results_ready_session(), "LST-0002").update["session"]

    direct = results_ready_session()
    direct.select_listing("LST-0002")

    assert via_tool == direct.model_dump(mode="json")


# --- the UI action path (catalogue Button -> WebSocket) -------------------


class FakeSocket:
    """Records what the handler would have sent to the browser."""

    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)

    def of_type(self, type_):
        return [m for m in self.sent if m["type"] == type_]


async def _dispatch(session: SessionState, name: str, context: dict):
    from api.main import _SurfaceStream, _handle_action

    socket = FakeSocket()
    surfaces = _SurfaceStream(socket)
    updated = await _handle_action(
        socket, {"type": "action", "name": name, "context": context},
        session.model_dump(mode="json"), surfaces,
    )
    return socket, updated


@pytest.mark.asyncio
async def test_button_click_selects_and_confirms_without_an_llm():
    socket, session = await _dispatch(
        results_ready_session(), "select_listing", {"listing_id": "LST-0002"}
    )

    assert session["selected_listing_id"] == "LST-0002"
    assert session["phase"] == "FORM_FILLING"

    chat = socket.of_type("chat")
    assert len(chat) == 1 and "LST-0002" in chat[0]["content"]
    assert socket.of_type("a2ui"), "the catalogue must re-render as selected"


@pytest.mark.asyncio
async def test_click_marks_that_card_selected_and_leaves_the_others():
    socket, _ = await _dispatch(
        results_ready_session(), "select_listing", {"listing_id": "LST-0002"}
    )
    messages = socket.of_type("a2ui")[0]["messages"]
    rows = messages[-1]["updateDataModel"]["value"]["listings"]
    labels = {row["id"]: row["select_label"] for row in rows}

    assert labels["LST-0002"] == "✓ Selected"
    assert labels["LST-0001"] == "Choose this one"


@pytest.mark.asyncio
async def test_a_tampered_listing_id_is_refused():
    """The id arrives from the browser, so it is untrusted input: a client
    that sends an id outside the persisted slate must not be able to select
    a listing the marketplace never returned.
    """
    socket, session = await _dispatch(
        results_ready_session(), "select_listing", {"listing_id": "LST-9999"}
    )

    assert session["selected_listing_id"] is None
    assert session["phase"] == "RESULTS_READY"
    assert socket.of_type("error")
    assert not socket.of_type("chat")


@pytest.mark.asyncio
async def test_a_missing_listing_id_is_refused_rather_than_crashing():
    socket, session = await _dispatch(results_ready_session(), "select_listing", {})
    assert session["selected_listing_id"] is None
    assert socket.of_type("error")


@pytest.mark.asyncio
async def test_a_click_is_written_to_the_checkpointer_not_just_returned():
    """The bug this test exists for: `_handle_action` updated the handler's
    local session and re-rendered the catalogue, but nothing wrote it to the
    checkpointer -- a button click runs no graph, and LangGraph only
    persists as a side effect of running. The selection looked applied and
    vanished on reload.

    Every other test in this file asserts on the value `_handle_action`
    *returns*, which is exactly why none of them caught it. This one asserts
    on what a subsequent load reads back.
    """
    from api.main import _SurfaceStream, _handle_action, _load_session

    recorded = {}

    class FakeAgent:
        async def aupdate_state(self, config, values):
            recorded["config"] = config
            recorded["session"] = values["session"]

        async def aget_state(self, config):
            class Snapshot:
                values = {"session": recorded.get("session")}
            return Snapshot()

    class FakeAgents:
        def for_phase(self, phase):
            return FakeAgent()

    agents, config = FakeAgents(), {"configurable": {"thread_id": "t1"}}
    socket = FakeSocket()
    await _handle_action(
        socket, {"type": "action", "name": "select_listing",
                 "context": {"listing_id": "LST-0002"}},
        results_ready_session().model_dump(mode="json"),
        _SurfaceStream(socket), agents, config,
    )

    assert recorded, "the selection was never persisted"
    assert recorded["session"]["selected_listing_id"] == "LST-0002"
    assert recorded["session"]["phase"] == "FORM_FILLING"
    assert recorded["config"] is config

    # And a fresh load sees it, which is what a reconnect does.
    reloaded = await _load_session(agents, config, "t1")
    assert reloaded["selected_listing_id"] == "LST-0002"


@pytest.mark.asyncio
async def test_a_rejected_click_is_not_persisted():
    persisted = []

    class FakeAgent:
        async def aupdate_state(self, config, values):
            persisted.append(values)

    class FakeAgents:
        def for_phase(self, phase):
            return FakeAgent()

    from api.main import _SurfaceStream, _handle_action

    socket = FakeSocket()
    await _handle_action(
        socket, {"type": "action", "name": "select_listing",
                 "context": {"listing_id": "LST-9999"}},
        results_ready_session().model_dump(mode="json"),
        _SurfaceStream(socket), FakeAgents(), {"configurable": {"thread_id": "t1"}},
    )
    assert persisted == []


@pytest.mark.asyncio
async def test_selection_still_works_without_an_llm_configured():
    """`agents is None` (no key) must not crash the click path -- the
    catalogue of a resumed session is still usable.
    """
    socket, session = await _dispatch(
        results_ready_session(), "select_listing", {"listing_id": "LST-0001"}
    )
    assert session["selected_listing_id"] == "LST-0001"


@pytest.mark.asyncio
async def test_an_unknown_action_name_is_ignored_not_obeyed():
    socket, session = await _dispatch(
        results_ready_session(), "drop_everything", {"listing_id": "LST-0001"}
    )
    assert session["selected_listing_id"] is None
    assert socket.sent == []
