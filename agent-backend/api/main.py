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
from agent.mcp_client import discover_marketplace_tools  # noqa: E402
from agent.render_a2ui import (  # noqa: E402
    CATALOGUE_SURFACE_ID,
    INTERVIEW_SURFACE_ID,
    REASONING_SURFACE_ID,
    build_catalogue_surface_init,
    build_catalogue_surface_update,
    build_interview_surface_init,
    build_interview_surface_update,
    build_reasoning_surface_init,
    build_reasoning_surface_update,
)
from agent.research import SEARCH_TOOL, narration_brief, run_research  # noqa: E402
from agent.state import InterviewState, Phase, RankedRecommendation, SessionState  # noqa: E402
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

    # T024: discover the marketplace tools once, here, because DeepAgents
    # fixes an agent's tool set at construction -- the registry below cannot
    # acquire them later. Fail-soft like tracing: an unreachable mcp-services
    # degrades research rather than taking the backend down.
    marketplace_tools = await discover_marketplace_tools()
    app.state.marketplace_tools = marketplace_tools

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        # Boot even without credentials so a misconfigured deployment shows
        # a readable error in the UI and a degraded /health, rather than the
        # container dying at startup with a stack trace.
        if is_configured():
            app.state.agents = PhaseAgentRegistry(checkpointer, extra_tools=marketplace_tools)
        else:
            app.state.agents = None
            log.warning("LLM_API_KEY not set -- starting in degraded mode, chat will not work.")
        app.state.checkpointer = checkpointer
        yield


app = FastAPI(lifespan=lifespan)


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
    mcp_connected = any(tool.name == SEARCH_TOOL for tool in tools)
    return {
        "status": "ok" if (configured and mcp_connected) else "degraded",
        "service": "agent-backend",
        "llm_configured": configured,
        "tracing_enabled": getattr(app.state, "tracing_enabled", False),
        "mcp_connected": mcp_connected,
        "marketplace_tools": sorted(tool.name for tool in tools),
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
    await surfaces.send(
        CATALOGUE_SURFACE_ID,
        lambda: build_catalogue_surface_init(listings, recommendations, interview),
        lambda: build_catalogue_surface_update(listings, recommendations, interview),
    )


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

    # Full component tree on every connect -- a freshly loaded frontend has
    # no prior tree to apply incremental updates to, whether this is a
    # brand-new session or a resumed one (US5).
    await surfaces.send(
        INTERVIEW_SURFACE_ID,
        lambda: build_interview_surface_init(InterviewState(**session["interview"])),
        lambda: build_interview_surface_update(InterviewState(**session["interview"])),
    )

    # A resumed session that already has a ranked slate gets its catalogue
    # back immediately, rebuilt from `SessionState.candidate_listings`.
    # Without this, reconnecting to a RESULTS_READY session would show an
    # empty panel despite the records being persisted -- which is the exact
    # symptom tasks.md T025(iii) persisted them to prevent, and which no
    # doc had assigned to a task. The reasoning trace is deliberately not
    # replayed: steps describe one search as it happened and are not
    # persisted, whereas the slate is durable state.
    if session.get("recommendations"):
        await _send_catalogue(surfaces, session)

    try:
        while True:
            incoming = await websocket.receive_json()
            if incoming.get("type") != "chat" or not incoming.get("content"):
                continue

            if agents is None:
                await websocket.send_json({"type": "error", "message": LLM_UNCONFIGURED_MESSAGE})
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
                    {"messages": [{"role": "user", "content": incoming["content"]}], "session": session},
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
    except WebSocketDisconnect:
        pass
