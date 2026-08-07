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
from agent.render_a2ui import build_interview_surface_init, build_interview_surface_update  # noqa: E402
from agent.state import InterviewState, Phase, SessionState  # noqa: E402
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

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        # Boot even without credentials so a misconfigured deployment shows
        # a readable error in the UI and a degraded /health, rather than the
        # container dying at startup with a stack trace.
        if is_configured():
            app.state.agents = PhaseAgentRegistry(checkpointer)
        else:
            app.state.agents = None
            log.warning("LLM_API_KEY not set -- starting in degraded mode, chat will not work.")
        app.state.checkpointer = checkpointer
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    """Reports degraded (not failed) without an LLM key, so the container
    stays up and the cause is visible.
    """
    configured = app.state.agents is not None
    return {
        "status": "ok" if configured else "degraded",
        "service": "agent-backend",
        "llm_configured": configured,
        "tracing_enabled": getattr(app.state, "tracing_enabled", False),
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

    # Full component tree on every connect -- a freshly loaded frontend has
    # no prior tree to apply incremental updates to, whether this is a
    # brand-new session or a resumed one (US5).
    await websocket.send_json({
        "type": "a2ui",
        "messages": build_interview_surface_init(InterviewState(**session["interview"])),
    })

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
            await websocket.send_json({
                "type": "a2ui",
                "messages": [build_interview_surface_update(InterviewState(**session["interview"]))],
            })
    except WebSocketDisconnect:
        pass
