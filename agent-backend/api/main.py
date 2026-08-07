"""WebSocket bridge between the frontend and the interview agent.

One long-lived SqliteSaver checkpointer backs all sessions -- opened once
at startup via FastAPI's lifespan and closed at shutdown -- the same
persistence layer already proven in tests/test_graph_persistence.py.

Message envelope (both directions):
  {"type": "chat", "content": "..."}                 -- chat text
  {"type": "a2ui", "messages": [...]}                 -- A2UI protocol messages (agent -> client only)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langgraph.checkpoint.sqlite import SqliteSaver

# Local/native dev convenience only -- in Docker, real env vars are passed
# via compose, and this is a no-op if agent-backend/.env doesn't exist. Must
# run before importing agent.* so OPENROUTER_API_KEY is set by the time
# build_interview_agent()/build_model() are called from lifespan below.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from agent.graph import build_interview_agent  # noqa: E402
from agent.render_a2ui import build_interview_surface_init, build_interview_surface_update  # noqa: E402
from agent.state import InterviewState, SessionState  # noqa: E402

DB_PATH = os.environ.get(
    "SESSIONS_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "sessions.sqlite")
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app.state.agent = build_interview_agent(checkpointer)
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-backend"}


@app.websocket("/ws/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    agent = websocket.app.state.agent
    config = {"configurable": {"thread_id": session_id}}

    snapshot = agent.get_state(config)
    session = snapshot.values.get("session") or SessionState(session_id=session_id).model_dump(mode="json")

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

            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": incoming["content"]}], "session": session},
                    config=config,
                )
            except Exception:
                # Tool/API failures degrade gracefully (rate limits, transient
                # provider errors, etc.) -- the connection and session state
                # stay intact so the user can just retry, instead of the
                # WebSocket silently dying with no explanation. `session` is
                # deliberately left untouched: a failed turn must not corrupt
                # or partially apply state.
                await websocket.send_json({
                    "type": "error",
                    "message": "Something went wrong processing that message. Please try again.",
                })
                continue

            session = result["session"]

            await websocket.send_json({
                "type": "chat", "role": "assistant", "content": result["messages"][-1].content,
            })
            await websocket.send_json({
                "type": "a2ui",
                "messages": [build_interview_surface_update(InterviewState(**session["interview"]))],
            })
    except WebSocketDisconnect:
        pass
