"""WebSocket bridge between the frontend and the phase-gated agent.

One long-lived AsyncSqliteSaver checkpointer backs all sessions -- opened
once at startup via FastAPI's lifespan and closed at shutdown -- against
the same SQLite file and schema proven in tests/test_graph_persistence.py
(which keeps using the sync SqliteSaver to test persistence in isolation).

Why *Async*SqliteSaver, and why this whole module is async-all-the-way:
M3's marketplace tools arrive via langchain-mcp-adapters, which produces
`StructuredTool(coroutine=...)` with `func=None` -- i.e. async-only tools.
Calling one synchronously raises "StructuredTool does not support sync
invocation", and that holds inside an `asyncio.to_thread` worker too, so
the previous `await asyncio.to_thread(agent.invoke, ...)` could not
survive M3. Switching to `agent.ainvoke` in turn rules out the sync
SqliteSaver, whose `aget_tuple`/`aput`/`alist` all raise
NotImplementedError. Verified empirically before making this change.

Message envelope (both directions):
  {"type": "chat", "content": "..."}                 -- chat text
  {"type": "action", "name": ..., "context": {...}}   -- A2UI surface action (client -> agent only)
  {"type": "a2ui", "messages": [...]}                 -- A2UI protocol messages (agent -> client only)
  {"type": "error", "message": "..."}                 -- graceful failure (agent -> client only)

Phase C's `{"type": "progress", "steps": [...]}` placeholder is **gone** as
of T026: hackathon requirement #5 and FR-005 both say reasoning steps must
render via A2UI, and they now do, as the `research-reasoning` surface.
Removing it cost no frontend change, because nothing ever consumed it --
App.tsx handled chat/a2ui/error only, so Phase C's steps were generated,
streamed and dropped on the floor.

Three A2UI surfaces are emitted, all through the one `a2ui` envelope:
`interview-progress` (M2), `research-reasoning` and `catalogue` (T026).
Each is created once per connection and updated incrementally thereafter --
`_SurfaceStream` below owns that bookkeeping, because a second
`createSurface` for a live surface is not an update, it is a reset.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Local/native dev convenience only -- in Docker, real env vars are passed
# via compose, and this is a no-op if agent-backend/.env doesn't exist. Must
# run before importing agent.* so LLM_API_KEY is set by the time
# build_model() is called from lifespan below.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agent.graph import PhaseAgentRegistry  # noqa: E402
from agent.llm import is_configured  # noqa: E402
from agent.mcp_client import (  # noqa: E402
    call_structured,
    discover_booking_tools,
    discover_marketplace_tools,
    discover_payment_tools,
    read_app_resource,
)
from agent.render_a2ui import (  # noqa: E402
    CATALOGUE_SURFACE_ID,
    INTERVIEW_SURFACE_ID,
    REASONING_SURFACE_ID,
    SELECT_LISTING_ACTION,
    build_catalogue_surface_init,
    build_catalogue_surface_update,
    build_interview_surface_init,
    build_interview_surface_update,
    build_reasoning_surface_init,
    build_reasoning_surface_update,
)
from agent.prompts import phase_context_line  # noqa: E402
from agent.research import SEARCH_TOOL, narration_brief, run_research  # noqa: E402
from agent.state import (  # noqa: E402
    Booking,
    InterviewState,
    Phase,
    RankedRecommendation,
    SessionState,
)
from agent.tools import (  # noqa: E402
    CONFIRM_MOCK_PAYMENT_TOOL,
    OPEN_BOOKING_FORM_TOOL,
    OPEN_MOCK_CHECKOUT_TOOL,
    SUBMIT_BOOKING_TOOL,
    build_runtime_tools,
)
from observability.otel_setup import setup_observability  # noqa: E402

log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "SESSIONS_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "sessions.sqlite")
)

LLM_UNCONFIGURED_MESSAGE = (
    "The agent has no LLM configured. Set LLM_API_KEY in agent-backend/.env "
    "(see .env.example) and restart the backend."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Constitution Principle V: registration happens once, here, at process
    # startup -- not opt-in per call site. auto_instrument patches LangChain
    # globally, so this must run *before* any agent is constructed.
    # Failure to reach Phoenix must not take the app down: tracing is an
    # observability aid, not a request-path dependency.
    app.state.tracing_enabled = False
    try:
        setup_observability()
        app.state.tracing_enabled = True
    except Exception as exc:  # pragma: no cover - depends on Phoenix availability
        log.warning("Tracing disabled -- could not register with Phoenix: %s", exc)

    # T024/T033: discover both MCP servers' tools once, here, because
    # DeepAgents fixes an agent's tool set at construction -- the registry
    # below cannot acquire them later. Fail-soft like tracing: an
    # unreachable mcp-services degrades research or booking rather than
    # taking the backend down.
    #
    # ⚠️ The two lists are kept apart on purpose. Only `runtime_tools` goes
    # to the registry: it carries the marketplace tools as-is plus *local
    # wrappers* built over the booking ones. The raw booking tools must
    # never be injected, because extras resolve over the local registry and
    # the raw `open_booking_form` demands the whole listing record as model
    # arguments -- see agent/tools.py::build_booking_tools.
    marketplace_tools = await discover_marketplace_tools()
    booking_tools = await discover_booking_tools()
    payment_tools = await discover_payment_tools()
    app.state.marketplace_tools = marketplace_tools
    app.state.booking_tools = booking_tools
    app.state.payment_tools = payment_tools
    runtime_tools = build_runtime_tools(marketplace_tools, booking_tools, payment_tools)

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        # Boot even without credentials so a misconfigured deployment shows
        # a readable error in the UI and a degraded /health, rather than the
        # container dying at startup with a stack trace.
        if is_configured():
            app.state.agents = PhaseAgentRegistry(checkpointer, extra_tools=runtime_tools)
        else:
            app.state.agents = None
            log.warning("LLM_API_KEY not set -- starting in degraded mode, chat will not work.")
        app.state.checkpointer = checkpointer
        yield


app = FastAPI(lifespan=lifespan)

# The four things that must all be true for the stack to be "ok".
#
# A named function rather than an inline expression, and that is not
# tidying. Mutation testing in M4b found that deleting `payment_connected`
# from the composite left the entire suite green: every unit test that
# reaches /health has *all* the downstreams unreachable, so `status` is
# "degraded" whatever the expression says, and the contribution of any
# single flag is invisible. One-server-down is the case that matters --
# and standing up two real MCP servers to assert a boolean is the wrong
# trade. Extracted, the truth table is testable directly, which is what
# `test_health_status_degrades_on_any_single_outage` does.
HEALTH_SIGNALS = ("llm_configured", "mcp_connected", "booking_connected", "payment_connected")


def health_status(**signals: bool) -> str:
    """"ok" only when every signal in HEALTH_SIGNALS is true.

    Keyword-only and explicit about its inputs so that adding a fourth
    downstream (T027's listing-detail server, if it ever lands) is a
    change to `HEALTH_SIGNALS` rather than to an `and` chain someone has
    to read carefully.
    """
    missing = set(HEALTH_SIGNALS) - set(signals)
    if missing:
        raise ValueError(f"health_status is missing signal(s): {sorted(missing)}")
    return "ok" if all(signals[name] for name in HEALTH_SIGNALS) else "degraded"


@app.get("/health")
async def health():
    """Reports degraded (not failed) on a missing LLM key or an unreachable
    marketplace, so the container stays up and the cause is visible.

    `mcp_connected` is reported for the same reason `tracing_enabled` is:
    without it, a failed tool discovery presents to a user as "the agent
    just never searches", which is indistinguishable from a logic bug. Note
    that tool discovery happens once at startup and the per-phase agents
    cache their tools, so a false here is not self-healing -- mcp-services
    coming back up needs a backend restart to take effect.
    """
    configured = app.state.agents is not None
    tools = getattr(app.state, "marketplace_tools", []) or []
    booking = getattr(app.state, "booking_tools", []) or []
    payment = getattr(app.state, "payment_tools", []) or []
    mcp_connected = any(tool.name == SEARCH_TOOL for tool in tools)
    # Reported separately rather than folded into `mcp_connected`, which
    # every M0-M3 caller and test reads as "the marketplace is reachable".
    # Redefining it would have made an existing green signal quietly mean
    # something else; a second field makes a booking outage its own,
    # nameable cause. `status` degrades on either, so the composite still
    # tells the truth (§14 finding 10).
    booking_connected = any(tool.name == OPEN_BOOKING_FORM_TOOL for tool in booking)
    # A third field for the same reason there is a second: folding payment
    # into `booking_connected` would make one green signal mean two things,
    # and a checkout outage would present as "booking is broken".
    payment_connected = any(tool.name == OPEN_MOCK_CHECKOUT_TOOL for tool in payment)
    return {
        "status": health_status(
            llm_configured=configured,
            mcp_connected=mcp_connected,
            booking_connected=booking_connected,
            payment_connected=payment_connected,
        ),
        "service": "agent-backend",
        "llm_configured": configured,
        "tracing_enabled": getattr(app.state, "tracing_enabled", False),
        "mcp_connected": mcp_connected,
        "booking_connected": booking_connected,
        "payment_connected": payment_connected,
        "marketplace_tools": sorted(tool.name for tool in tools),
        "booking_tools": sorted(tool.name for tool in booking),
        "payment_tools": sorted(tool.name for tool in payment),
    }


def message_text(message) -> str:
    """Flatten a LangChain message's content to plain display text.

    `.content` is not always a string. Gemini (and any multimodal or
    thinking model) returns a list of content blocks, e.g.
    `[{"type": "text", "text": "..."}, {"type": "thinking", ...}]`.
    Passing that straight to the client put a JSON array where the chat
    bubble expected a string, so normalize here -- at the one point where
    model output crosses into the wire protocol.

    Non-text blocks (reasoning/thinking in particular) are dropped rather
    than rendered: they are the model's internal scratchpad, and the
    user-facing reasoning trace is the A2UI reasoning-steps surface built
    from structured tool output, not from prose the model emitted.
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


class _SurfaceStream:
    """Per-connection A2UI surface bookkeeping.

    A2UI's incremental model splits every surface into a one-time
    `createSurface` + component tree and cheap `updateDataModel` messages
    thereafter. Which of the two to send depends on whether *this* client
    has seen the tree yet, so the state belongs to the connection, not to
    the session: a reconnecting browser has no prior tree to patch, even
    when the session it is resuming is old (US5).

    Re-sending `createSurface` for a live surface would be a reset, not an
    update, so the decision is made here once rather than at each call site.
    """

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._live: set[str] = set()

    async def send(self, surface_id: str, build_init, build_update) -> None:
        """Emit `surface_id`, initialising it on first use.

        Both arguments are callables so only the branch actually taken is
        built -- the init path serialises a full component tree.
        """
        if surface_id in self._live:
            messages = [build_update()]
        else:
            messages = build_init()
            self._live.add(surface_id)
        await self._websocket.send_json({"type": "a2ui", "messages": messages})


def _catalogue_inputs(session: dict) -> tuple[list[dict], list[RankedRecommendation], dict]:
    """The catalogue's three inputs, read from persisted session state.

    Principle I's grounding channel in its persisted form: the listings are
    the verbatim tool records `record_research` stored, and the
    recommendations are the deterministic ranker's own output. Neither is
    re-derived here and neither comes from the model.
    """
    return (
        session.get("candidate_listings") or [],
        [RankedRecommendation.model_validate(rec) for rec in session.get("recommendations") or []],
        session.get("interview") or {},
    )


async def _send_catalogue(surfaces: _SurfaceStream, session: dict) -> None:
    listings, recommendations, interview = _catalogue_inputs(session)
    selected = session.get("selected_listing_id")
    await surfaces.send(
        CATALOGUE_SURFACE_ID,
        lambda: build_catalogue_surface_init(listings, recommendations, interview, selected),
        lambda: build_catalogue_surface_update(listings, recommendations, interview, selected),
    )


def _refine_artifact(messages) -> dict | None:
    """The `refine_search` artifact from this turn, if the tool ran.

    Read off `ToolMessage.artifact` -- the typed channel (§8.5) -- rather
    than by re-deriving the reasoning steps here or, worse, parsing them out
    of the model's reply. Scans backwards because only the most recent
    refinement in a turn is current.
    """
    for message in reversed(messages):
        artifact = getattr(message, "artifact", None)
        if isinstance(artifact, dict) and "refine_search" in artifact:
            return artifact["refine_search"]
    return None


async def _refresh_refined_surfaces(
    surfaces: _SurfaceStream, session: dict, before: tuple[list[str], str | None], messages
) -> None:
    """Re-render the catalogue (and reasoning trace) after a model turn.

    Two different things a model turn can change need this, and only the
    first was handled originally:

    - **`refine_search` replaced the slate.** The old cards are for cars
      that are no longer selectable, so clicking one would be rejected --
      the "agent looks broken" path.
    - **`select_listing` chose a car.** Found by running a real
      conversation: saying "I'll take the Jeep" recorded the selection and
      opened the booking form, but every card still read "Choose this one",
      because `_handle_action` re-renders after a *click* and nothing did
      after the tool. The two paths converged on state and diverged on
      screen -- §14 finding 5's shape, one layer up, and invisible to every
      test because they all assert on state.

    Compared rather than always re-sent, so an ordinary question turn does
    not re-serialise the catalogue.
    """
    previous_slate, previous_selection = before
    slate = [listing["id"] for listing in session.get("candidate_listings") or []]
    if slate == previous_slate and session.get("selected_listing_id") == previous_selection:
        return

    refined = _refine_artifact(messages)
    if refined:
        steps, kinds = refined.get("steps") or [], refined.get("step_kinds") or []
        await surfaces.send(
            REASONING_SURFACE_ID,
            lambda: build_reasoning_surface_init(steps, kinds),
            lambda: build_reasoning_surface_update(steps, kinds),
        )
    await _send_catalogue(surfaces, session)


class _BookingFormStream:
    """Per-connection bookkeeping for the booking MCP App, mirroring
    `_SurfaceStream`'s role and existing for the same reason: what the
    browser has already been shown is a property of the *connection*, not
    of the session. A reconnecting browser has no iframe, however old the
    session it is resuming (US5).

    Deciding when to push is not "has the phase changed". Three different
    things must open the form, and one must not:

    - the user **clicks** a card, so `_handle_action` advances the phase;
    - the model calls `open_booking_form` ("show me the form again"),
      which cannot push anything itself -- it runs inside a graph and knows
      nothing about this socket, so it bumps
      `SessionState.booking_form_requests` and this notices;
    - the browser **reconnects** mid-booking and needs the iframe back;
    - but a submitted booking must **not** reopen the form, or a resumed
      AWAITING_PAYMENT session would land back on a form it has finished.

    Tracking the selected listing id as well as the counter is what makes
    re-selection work: picking a different car has to re-open the form on
    the new one, and that changes no counter.
    """

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._shown_for: str | None = None
        self._requests_seen = 0

    def _should_send(self, session: dict) -> bool:
        if Phase(session["phase"]) != Phase.FORM_FILLING:
            return False
        if not session.get("selected_listing_id"):
            return False
        booking = session.get("booking") or {}
        if booking.get("status") == "SUBMITTED":
            return False
        return (
            session["selected_listing_id"] != self._shown_for
            or (session.get("booking_form_requests") or 0) > self._requests_seen
        )

    async def maybe_open(self, booking_tools: list, session: dict) -> None:
        """Push the MCP App envelope if this connection still owes one.

        Fail-soft, like every other downstream call: mcp-services being
        unreachable must leave the chat usable and the session intact, not
        take the turn down. The user is told, because an iframe that
        silently never appears is the worst version of this.
        """
        if not self._should_send(session):
            return
        try:
            envelope = await build_booking_app_envelope(booking_tools, session)
        except Exception:
            log.exception("Could not open the booking form for %s", session["session_id"])
            await self._websocket.send_json({
                "type": "error",
                "message": "I couldn't open the booking form. Please try again.",
            })
            return

        await self._websocket.send_json(envelope)
        self._shown_for = session["selected_listing_id"]
        self._requests_seen = session.get("booking_form_requests") or 0


class _CheckoutStream:
    """Per-connection bookkeeping for the checkout MCP App.

    Same rationale as `_BookingFormStream`: the browser has already been
    shown the checkout App is a property of the *connection*, not of the
    session.  A reconnecting browser needs the checkout iframe back, but a
    confirmed session must not re-open it.

    Three things open checkout, one must not:

    - the model calls `open_mock_checkout` ("show me the checkout");
    - the browser reconnects mid-checkout;
    - but a confirmed session must **not** reopen checkout.
    """

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._shown_booking: str | None = None
        self._requests_seen = 0

    def _should_send(self, session: dict) -> bool:
        if Phase(session["phase"]) != Phase.AWAITING_PAYMENT:
            return False
        booking = session.get("booking") or {}
        if booking.get("status") != "SUBMITTED":
            return False
        # Already confirmed — do not re-open.
        if session.get("payment_confirmation"):
            return False
        # A new booking or a new request counter bump.
        booking_id = booking.get("id")
        return (
            booking_id != self._shown_booking
            or (session.get("checkout_requests") or 0) > self._requests_seen
        )

    async def maybe_open(self, payment_tools: list, session: dict) -> None:
        if not self._should_send(session):
            return
        try:
            envelope = await build_checkout_app_envelope(payment_tools, session)
        except Exception:
            log.exception("Could not open checkout for %s", session["session_id"])
            await self._websocket.send_json({
                "type": "error",
                "message": "I couldn't open the checkout. Please try again.",
            })
            return

        await self._websocket.send_json(envelope)
        self._shown_booking = (session.get("booking") or {}).get("id")
        self._requests_seen = session.get("checkout_requests") or 0


def _booking_tool(booking_tools: list, name: str):
    tool = next((t for t in booking_tools or [] if t.name == name), None)
    if tool is None:
        raise RuntimeError(
            f"the booking MCP server did not provide {name!r} -- check "
            f"/health's booking_connected and MCP_BOOKING_URL"
        )
    return tool


def _payment_tool(payment_tools: list, name: str):
    tool = next((t for t in payment_tools or [] if t.name == name), None)
    if tool is None:
        raise RuntimeError(
            f"the payment MCP server did not provide {name!r} -- check "
            f"/health's payment_connected and MCP_PAYMENT_URL"
        )
    return tool


async def build_booking_app_envelope(booking_tools: list, session: dict) -> dict:
    """The `mcp_app` message: everything the host needs to render the App.

    Three parts, and all three are required by the MCP Apps protocol rather
    than by us:

    - **`resource`** — the `ui://` document *and its `_meta`*, which is
      where the deny-by-default CSP lives (spec.md US3 AS1). Read through
      `read_app_resource`, not the LangChain adapter, which drops `_meta`.
    - **`toolInput`** — ext-apps 1.7.5 states `sendToolInput` "is sent
      exactly once and is **required before** `sendToolResult`", so a host
      that only forwards the result leaves the View waiting forever.
    - **`toolResult`** — what `ontoolresult` in the App actually renders.

    ⚠️ **`toolInput.arguments` carries the server's projection, not the
    record we called with.** The real argument to `open_booking_form` is
    the verbatim listing, and that includes `description` -- the one
    attacker-controlled field, delimited with `<untrusted_listing_data>`.
    `LISTING_DISPLAY_FIELDS` strips it from the tool's *result*; nothing
    strips it from its *arguments*. Echoing the real arguments would carry
    third-party prose into the App document and defeat the server-side
    allowlist entirely (Principle IV). So the input we report is the
    projection the result already contains: still honest about what the
    tool was asked to do, minus the field the form must never see.
    """
    listing = SessionState.model_validate(session).selected_listing()
    if listing is None:
        raise RuntimeError("no listing is selected, so there is no form to open")

    payload = await call_structured(
        _booking_tool(booking_tools, OPEN_BOOKING_FORM_TOOL), {"listing": listing},
    )
    resource = await read_app_resource(payload["resourceUri"])

    return {
        "type": "mcp_app",
        "app": "booking",
        "toolName": OPEN_BOOKING_FORM_TOOL,
        "resource": resource,
        "toolInput": {"arguments": {"listing": payload["listing"]}},
        "toolResult": {"structuredContent": payload},
    }


async def build_checkout_app_envelope(payment_tools: list, session: dict) -> dict:
    """The `mcp_app` message for the checkout App.

    Same shape as `build_booking_app_envelope`: resource, toolInput,
    toolResult.  Both verbatim records go to the server, not through the
    model, and the server echoes back only display-safe projections.
    """
    state = SessionState.model_validate(session)
    listing = state.selected_listing()
    booking = state.booking

    if booking is None or booking.status != "SUBMITTED" or listing is None:
        raise RuntimeError("no submitted booking to check out")

    payload = await call_structured(
        _payment_tool(payment_tools, OPEN_MOCK_CHECKOUT_TOOL),
        {"booking": booking.model_dump(mode="json"), "listing": listing},
    )
    resource = await read_app_resource(payload["resourceUri"])

    return {
        "type": "mcp_app",
        "app": "checkout",
        "toolName": OPEN_MOCK_CHECKOUT_TOOL,
        "resource": resource,
        "toolInput": {"arguments": {"booking": payload.get("booking"), "listing": payload.get("listing")}},
        "toolResult": {"structuredContent": payload},
    }


async def _persist_session(agents, config, session: dict) -> None:
    """Write `session` into the checkpointer without running the agent.

    Needed because a UI action mutates state outside any graph execution,
    and LangGraph only checkpoints as a side effect of running. Without
    this, a selection lived only in the WebSocket handler's local variable:
    the catalogue showed it, and a reconnect silently lost it -- which the
    unit tests could not catch, because they assert on the value
    `_handle_action` returns rather than on what a later `_load_session`
    reads back. Found by clicking the button and reloading the page.

    `aupdate_state` is LangGraph's supported way to write state outside a
    run. It is a no-op when no agent exists (no LLM key), which leaves the
    selection in-memory for that session only -- acceptable, since a
    keyless deployment cannot progress to booking anyway.

    **`as_node` is required, and omitting it was a live bug.** LangGraph
    infers which node an external update should be attributed to from the
    last thing that wrote to the thread. After a graph run that is
    unambiguous, so the first click after a model turn worked -- which is
    why Phase E's manual verification passed and why every unit test here
    passed against a `FakeAgent` that never ran LangGraph at all. But two
    updates in a row with no run between them leave nothing to infer from,
    and the second raises `InvalidUpdateError: Ambiguous update, specify
    as_node`. That is a **second consecutive catalogue click** -- exactly
    the re-selection path M4a Phase C1 turned into a supported route --
    and it killed the WebSocket, because `chat_ws` had no handler around
    the action branch. Found by clicking two cards in a browser.

    `__start__` rather than `model` or `tools`: this is an external input
    to the thread, not something the model or a tool produced. Both of
    those also happen to work, and both would make the trace assert
    something untrue about where the value came from (Principle V -- the
    trace is the audit log).
    """
    if agents is None:
        return
    phase = Phase(session["phase"])
    await agents.for_phase(phase).aupdate_state(
        config, {"session": session}, as_node="__start__",
    )


async def _handle_action(
    websocket: WebSocket, incoming: dict, session: dict, surfaces: _SurfaceStream,
    agents=None, config=None,
) -> dict:
    """Apply a UI action from an A2UI surface (T028).

    A button click is a *direct user instruction*, so it is applied in code
    rather than described to the model and hoped for -- the same reason the
    phase transitions live in `SessionState` (Principle II). It reaches
    `SessionState.select_listing`, which is the identical code path the
    `select_listing` tool uses, so clicking a card and saying "I'll take the
    Jeep" cannot diverge.

    The listing id arriving from the client is untrusted input like any
    other: `select_listing` rejects anything outside the persisted candidate
    slate, so a tampered or stale id cannot select a listing that was never
    recommended.
    """
    if incoming.get("name") != SELECT_LISTING_ACTION:
        log.warning("Ignoring unknown UI action %r", incoming.get("name"))
        return session

    listing_id = (incoming.get("context") or {}).get("listing_id")
    state = SessionState.model_validate(session)
    try:
        state.select_listing(listing_id)
    except ValueError as exc:
        log.warning("Rejected listing selection %r: %s", listing_id, exc)
        await websocket.send_json({
            "type": "error",
            "message": "That listing is no longer available to select. Try searching again.",
        })
        return session

    session = state.model_dump(mode="json")
    listing = state.selected_listing() or {}
    await _persist_session(agents, config, session)

    # Re-render so the chosen card shows as selected, then confirm in chat.
    # Deterministic text, not a model turn: the confirmation restates values
    # from the tool record, and spending an LLM round trip to say "got it"
    # would add latency and a hallucination surface for no benefit.
    await _send_catalogue(surfaces, session)
    await websocket.send_json({
        "type": "chat",
        "role": "assistant",
        "content": (
            f"Got it — you've chosen the {listing.get('year')} "
            f"{listing.get('brand')} {listing.get('model')} ({listing_id}). "
            "Booking comes next."
        ),
    })
    return session


async def _handle_app_tool_call(
    websocket: WebSocket, incoming: dict, session: dict,
    booking_tools: list, payment_tools: list,
    agents=None, config=None,
) -> dict:
    """The MCP App bridge: both the booking and checkout iframe's
    `tools/call`, tunnelled over our WS.

    Two tools are reachable through this route — one per MCP App — and
    neither is bound to a model phase (Principle II + III):

    - **`submit_booking`** (FORM_FILLING): its `fields` argument is
      free-form, so a model-callable version could fabricate the user's
      contact details.  Values arrive from the form the user typed into.
    - **`confirm_mock_payment`** (AWAITING_PAYMENT): its `fields` argument
      would be card-like, and a model tool's arguments are written into
      the message history, checkpointed, and traced — all three of
      spec.md US4 AS2's prohibitions.  The values arrive from the iframe,
      but the backend forwards *nothing* the browser sent: `booking_id`
      comes from persisted state.

    This is a *second gate*, with a different subject from
    `TOOLS_BY_PHASE`.  That one decides what the *model* may call; this
    decides what each *iframe* may call, and an iframe is untrusted input.
    Three things are therefore never taken from the message for either App:

    - **which tool.** An allowlist of one per App.
    - **which phase.** Principle II applies here too.
    - **which listing / booking.** Both are read from persisted state.
    """
    call_id = incoming.get("call_id")

    async def reply(result: dict) -> None:
        await websocket.send_json({
            "type": "app_tool_result", "call_id": call_id, "result": result,
        })

    tool_name = incoming.get("name")
    state = SessionState.model_validate(session)

    # --- checkout: confirm_mock_payment (AWAITING_PAYMENT) -----------------
    if tool_name == CONFIRM_MOCK_PAYMENT_TOOL:
        if state.phase != Phase.AWAITING_PAYMENT:
            log.warning("Refused checkout confirm in phase %s", state.phase)
            await reply({"structuredContent": {
                "ok": False,
                "errors": {"_": "Payment is not available yet. "
                                "Complete the booking form first."},
            }})
            return session

        if state.booking is None or state.booking.status != "SUBMITTED":
            await reply({"structuredContent": {
                "ok": False,
                "errors": {"_": "There is no submitted booking to pay for."},
            }})
            return session

        # `booking_id` from persisted state, never from the browser.
        # `fields` from the iframe are accepted so the allowlist has
        # something to drop — nothing is forwarded.
        try:
            result = await call_structured(
                _payment_tool(payment_tools, CONFIRM_MOCK_PAYMENT_TOOL),
                {"booking_id": state.booking.id, "fields": (incoming.get("arguments") or {}).get("fields")},
            )
        except Exception:
            log.exception("confirm_mock_payment failed for session %s", session["session_id"])
            await reply({"structuredContent": {
                "ok": False,
                "errors": {"_": "The payment service is unavailable. Please try again."},
            }})
            return session

        if not result.get("ok"):
            await reply({"structuredContent": result})
            return session

        confirmation = result["confirmation"]
        try:
            state.confirm_payment(PaymentConfirmation(
                id=confirmation["id"],
                booking_id=state.booking.id,
                confirmation_code=confirmation["confirmation_code"],
                status=confirmation["status"],
                created_at=confirmation["created_at"],
            ))
        except ValueError as exc:
            log.warning("Refused to record confirmation %s: %s", confirmation["id"], exc)
            await reply({"structuredContent": {
                "ok": False, "errors": {"_": "This payment has already been confirmed."},
            }})
            return session

        session = state.model_dump(mode="json")
        await _persist_session(agents, config, session)
        await reply({"structuredContent": result})

        listing = state.selected_listing() or {}
        await websocket.send_json({
            "type": "chat", "role": "assistant",
            "content": (
                f"Payment confirmed for the {listing.get('year')} "
                f"{listing.get('brand')} {listing.get('model')}. "
                f"Confirmation code: {confirmation['confirmation_code']}. "
                f"Thank you!"
            ),
        })
        return session

    # --- booking: submit_booking (FORM_FILLING) ----------------------------
    if tool_name == SUBMIT_BOOKING_TOOL:
        listing = state.selected_listing()
        if state.phase != Phase.FORM_FILLING or listing is None:
            log.warning("Refused a booking submit in phase %s", state.phase)
            await reply({"structuredContent": {
                "ok": False,
                "errors": {"_": "This booking can no longer be submitted. "
                                "Pick a car again to start over."},
            }})
            return session

        fields = (incoming.get("arguments") or {}).get("fields") or {}
        try:
            result = await call_structured(
                _booking_tool(booking_tools, SUBMIT_BOOKING_TOOL),
                {
                    "listing_id": state.selected_listing_id,
                    "fields": fields,
                    "available_from": listing.get("availability_date"),
                },
            )
        except Exception:
            log.exception("submit_booking failed for session %s", session["session_id"])
            await reply({"structuredContent": {
                "ok": False,
                "errors": {"_": "The booking service is unavailable. Please try again."},
            }})
            return session

        if not result.get("ok"):
            await reply({"structuredContent": result})
            return session

        record = result["booking"]
        try:
            state.submit_booking(Booking(
                id=record["id"],
                listing_id=state.selected_listing_id,
                session_id=state.session_id,
                submitted_form_fields=record["submitted_form_fields"],
                status="SUBMITTED",
            ))
        except ValueError as exc:
            log.warning("Refused to record booking %s: %s", record["id"], exc)
            await reply({"structuredContent": {
                "ok": False, "errors": {"_": "This booking has already been submitted."},
            }})
            return session

        session = state.model_dump(mode="json")
        await _persist_session(agents, config, session)
        await reply({"structuredContent": result})

        await websocket.send_json({
            "type": "chat", "role": "assistant",
            "content": (
                f"Your booking for the {listing.get('year')} {listing.get('brand')} "
                f"{listing.get('model')} is submitted — reference {record['id']}. "
                "Payment is the next step."
            ),
        })
        return session

    # --- unknown tool ------------------------------------------------------
    log.warning("Refused app tool call %r", tool_name)
    await reply({"structuredContent": {
        "ok": False,
        "errors": {"_": "That action is not available from this form."},
    }})
    return session


async def _run_research_turn(
    websocket: WebSocket, agents, session: dict, config, surfaces: _SurfaceStream
) -> dict:
    """T025: research runs in the same turn the interview completes.

    spec.md US1 AS3 requires the INTERVIEWING -> RESEARCHING transition to
    proceed "with no further user prompt required". Previously the phase
    flipped mid-turn but nothing ran until the user happened to send another
    message, so the agent looked like it had simply stopped.

    The search itself is code-driven (agent/research.py explains why): the
    constraints go from persisted state straight into the tool call, so no
    price or filter has to survive a round trip through the model's memory.
    The model is invoked afterwards, to narrate a slate it can read.
    """
    outcome = await run_research(session["interview"], agents.extra_tools)

    # T026: the reasoning trace goes out first and on its own, before the
    # slower narration round trip, so the user watches the search reason
    # rather than waiting at a blank panel (requirement #5 / FR-005).
    await surfaces.send(
        REASONING_SURFACE_ID,
        lambda: build_reasoning_surface_init(outcome.steps, outcome.step_kinds),
        lambda: build_reasoning_surface_update(outcome.steps, outcome.step_kinds),
    )

    if outcome.error:
        # A failed pass leaves the phase at RESEARCHING deliberately, so the
        # next message retries -- this is the recoverable case (mcp-services
        # restarting, a transient network fault) and silently advancing past
        # it would strand the session with an empty catalogue forever.
        log.warning("Research did not complete for session %s: %s",
                    session["session_id"], outcome.error)
    else:
        # A completed pass advances even when it found nothing: research
        # genuinely ran, and staying in RESEARCHING would re-run the same
        # fruitless search on every subsequent message. The user can adjust
        # constraints from RESULTS_READY, where the search tools are still
        # bound by the gate.
        state = SessionState.model_validate(session)
        state.record_research(outcome.listings, outcome.recommendations)
        session = state.model_dump(mode="json")

        # Render from what was just persisted, not from `outcome`, so the
        # catalogue on screen is provably the same slate a reconnect will
        # rebuild from -- one code path, one source of truth.
        await _send_catalogue(surfaces, session)

    narrator = agents.for_phase(Phase(session["phase"]))
    result = await narrator.ainvoke(
        {"messages": [{"role": "user", "content": narration_brief(outcome)}],
         "session": session},
        config,
    )
    session = result["session"]

    await websocket.send_json({
        "type": "chat", "role": "assistant",
        "content": message_text(result["messages"][-1]),
    })
    return session


async def _load_session(agents, config, session_id: str) -> dict:
    """Current persisted SessionState for this thread, or a fresh one.

    `aget_state`, not `get_state`: AsyncSqliteSaver's sync methods refuse to
    run on the same thread as their event loop, so the sync path would raise
    here rather than silently working.
    """
    if agents is None:
        return SessionState(session_id=session_id).model_dump(mode="json")
    agent = agents.for_phase(Phase.INTERVIEWING)
    snapshot = await agent.aget_state(config)
    return snapshot.values.get("session") or SessionState(session_id=session_id).model_dump(mode="json")


@app.websocket("/ws/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    agents = websocket.app.state.agents
    config = {"configurable": {"thread_id": session_id}}

    session = await _load_session(agents, config, session_id)
    surfaces = _SurfaceStream(websocket)
    booking_tools = websocket.app.state.booking_tools
    payment_tools = websocket.app.state.payment_tools
    booking_form = _BookingFormStream(websocket)
    checkout_stream = _CheckoutStream(websocket)

    # The initial push is inside the same `try` as the message loop, not
    # before it. A browser reload closes the old socket while the backend
    # is still writing these, and with the sends outside the handler that
    # raced into an unhandled `WebSocketDisconnect` -- a full traceback in
    # the log on every single refresh. Nothing was wrong, which is the
    # problem: a log that cries wolf on the most ordinary action in
    # development is a log nobody reads when something real happens (the
    # same argument as §8.32's quota-skip).
    try:
        # Full component tree on every connect -- a freshly loaded frontend
        # has no prior tree to apply incremental updates to, whether this is
        # a brand-new session or a resumed one (US5).
        await surfaces.send(
            INTERVIEW_SURFACE_ID,
            lambda: build_interview_surface_init(InterviewState(**session["interview"])),
            lambda: build_interview_surface_update(InterviewState(**session["interview"])),
        )

        # A resumed session that already has a ranked slate gets its
        # catalogue back immediately, rebuilt from
        # `SessionState.candidate_listings`. Without this, reconnecting to a
        # RESULTS_READY session would show an empty panel despite the
        # records being persisted -- the exact symptom tasks.md T025(iii)
        # persisted them to prevent, and which no doc had assigned to a
        # task. The reasoning trace is deliberately not replayed: steps
        # describe one search as it happened and are not persisted, whereas
        # the slate is durable state.
        if session.get("recommendations"):
            await _send_catalogue(surfaces, session)

        # And a session resumed mid-booking gets its form back, for the
        # same reason and from the same persisted record (US5). Without
        # this a reconnect in FORM_FILLING shows a catalogue with a card
        # marked selected and no way to proceed.
        await booking_form.maybe_open(booking_tools, session)

        # A session resumed in AWAITING_PAYMENT gets its checkout back.
        await checkout_stream.maybe_open(payment_tools, session)

        while True:
            incoming = await websocket.receive_json()

            # A2UI surface actions (button clicks) are applied in code and
            # need no LLM, so they are handled before the agent-required
            # guard below -- a user can still pick a listing from the
            # catalogue of a resumed session when no key is configured.
            # The MCP App bridge: the booking iframe's `tools/call`,
            # tunnelled by the host over this socket. Like an A2UI action
            # it needs no LLM, so it is handled before the agent guard.
            if incoming.get("type") == "app_tool_call":
                try:
                    session = await _handle_app_tool_call(
                        websocket, incoming, session,
                        booking_tools, payment_tools,
                        agents, config,
                    )
                except Exception:
                    log.exception("App tool call failed for session %s", session_id)
                    await websocket.send_json({
                        "type": "app_tool_result",
                        "call_id": incoming.get("call_id"),
                        "result": {"structuredContent": {
                            "ok": False,
                            "errors": {"_": "Something went wrong. Please try again."},
                        }},
                    })
                continue

            if incoming.get("type") == "action":
                try:
                    session = await _handle_action(
                        websocket, incoming, session, surfaces, agents, config
                    )
                except Exception:
                    # Same contract the chat and research turns already had,
                    # and the action branch did not: a failure explains
                    # itself and leaves the connection usable. It was the
                    # only inbound branch that could take the socket down,
                    # which is how a persistence bug presented as the whole
                    # UI going dead with nothing in the chat log -- no
                    # error, no reconnect, the page simply stopped
                    # responding to clicks. `session` keeps its previous
                    # value, so a failed action cannot half-apply.
                    log.exception("UI action failed for session %s", session_id)
                    await websocket.send_json({
                        "type": "error",
                        "message": "Something went wrong applying that. Please try again.",
                    })
                # A click is one of the three routes into FORM_FILLING, and
                # the form is opened in code rather than by asking the model
                # to decide -- the same shape as the research auto-kickoff,
                # and for the same reason (Principle II: the state machine
                # drives, not the LLM).
                await booking_form.maybe_open(booking_tools, session)
                await checkout_stream.maybe_open(payment_tools, session)
                continue

            if incoming.get("type") != "chat" or not incoming.get("content"):
                continue

            if agents is None:
                await websocket.send_json({"type": "error", "message": LLM_UNCONFIGURED_MESSAGE})
                continue

            # A session already sitting in RESEARCHING skips the model turn
            # entirely and goes straight to the code-driven search.
            #
            # Normally RESEARCHING is transient: `save_interview_slots`
            # flips the phase mid-turn and `_run_research_turn` runs
            # immediately below. But a session *resumed* in RESEARCHING (a
            # reconnect, or a previous pass that errored) took the ordinary
            # path here first -- and the RESEARCHING agent binds
            # `search_listings`, so the model ran its own search, whose
            # result nothing reads, before the real search ran underneath
            # it. Two searches, one discarded, ~3k wasted tokens against a
            # 200k/day budget, and a chat reply written about a slate the
            # user was never shown (§14 finding 12).
            if Phase(session["phase"]) == Phase.RESEARCHING:
                try:
                    session = await _run_research_turn(
                        websocket, agents, session, config, surfaces
                    )
                except Exception:
                    log.exception("Research turn failed for session %s", session_id)
                    await websocket.send_json({
                        "type": "error",
                        "message": "I couldn't finish researching listings. Please try again.",
                    })
                continue

            # Phase gate (Constitution Principle II): the agent used for
            # this turn is the one built with only this phase's tools, so
            # out-of-phase tools are not merely discouraged -- they were
            # never bound to the model in the first place.
            agent = agents.for_phase(Phase(session["phase"]))

            try:
                # Native async, so the event loop stays free during the LLM
                # round trip and concurrent sessions are not serialized
                # behind each other (spec.md US5 AS2 requires two sessions
                # usable at once -- the property T053 established with
                # asyncio.to_thread, preserved here by different means).
                result = await agent.ainvoke(
                    {
                        # The phase line rides *with* the user's message
                        # rather than as a separate message, so the history
                        # does not accumulate one system turn per exchange
                        # -- at ~20 tokens each that is small, but it also
                        # keeps the transcript readable and keeps the state
                        # attached to the turn it describes.
                        "messages": [{
                            "role": "user",
                            "content": f"{phase_context_line(session)}\n\n{incoming['content']}",
                        }],
                        "session": session,
                    },
                    config,
                )
            except Exception:
                # Tool/API failures degrade gracefully (rate limits, transient
                # provider errors, etc.) -- the connection and session state
                # stay intact so the user can just retry, instead of the
                # WebSocket silently dying with no explanation. `session` is
                # deliberately left untouched: a failed turn must not corrupt
                # or partially apply state.
                log.exception("Agent turn failed for session %s", session_id)
                await websocket.send_json({
                    "type": "error",
                    "message": "Something went wrong processing that message. Please try again.",
                })
                continue

            before = (
                [listing["id"] for listing in session.get("candidate_listings") or []],
                session.get("selected_listing_id"),
            )
            session = result["session"]

            await websocket.send_json({
                "type": "chat", "role": "assistant",
                "content": message_text(result["messages"][-1]),
            })
            await surfaces.send(
                INTERVIEW_SURFACE_ID,
                lambda: build_interview_surface_init(InterviewState(**session["interview"])),
                lambda: build_interview_surface_update(InterviewState(**session["interview"])),
            )

            # `refine_search` replaces the slate from inside the agent run,
            # so the surfaces have to catch up or the user is left looking
            # at cards for cars that are no longer selectable -- clicking
            # one would be rejected by `select_listing`, which is the
            # "agent looks broken" path this whole fix exists to remove.
            # Compared rather than always re-sent so an ordinary question
            # turn does not re-serialise the catalogue.
            await _refresh_refined_surfaces(surfaces, session, before, result["messages"])

            # One inbound message can now produce several outbound ones: the
            # interview reply above, then a reasoning trace, a catalogue and
            # a narration.
            if Phase(session["phase"]) == Phase.RESEARCHING:
                try:
                    session = await _run_research_turn(
                        websocket, agents, session, config, surfaces
                    )
                except Exception:
                    # Same contract as the interview turn: a failure explains
                    # itself and leaves the session usable. `session` keeps
                    # its pre-research value, so the next message retries.
                    log.exception("Research turn failed for session %s", session_id)
                    await websocket.send_json({
                        "type": "error",
                        "message": "I couldn't finish researching listings. Please try again.",
                    })

            # Last, after every model turn: the model may have called
            # `select_listing` ("I'll take the Jeep") or `open_booking_form`
            # ("show me the form again"), and neither can push to this
            # socket from inside a graph run.  Checked here rather than
            # branched on the tool actually called, so the prose path and
            # the click path converge on one piece of code -- which is the
            # guarantee §14 finding 5 showed had quietly stopped holding.
            await booking_form.maybe_open(booking_tools, session)
            await checkout_stream.maybe_open(payment_tools, session)
    except WebSocketDisconnect:
        pass
