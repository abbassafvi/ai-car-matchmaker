"""Regression test for a real bug caught during live browser verification:
the WebSocket handler had no error handling around agent.invoke(), so any
failure (observed live: OpenRouter returning 402 on exhausted credits, but
equally applicable to rate limits or transient provider errors) killed the
connection silently instead of degrading gracefully.

Does NOT need real LLM credentials or a live LLM call -- constructing the
ChatOpenAI client only needs an API-key-shaped string (never validated at
construction time), and the actual failure is injected via monkeypatch
directly on the compiled agent, so this runs in the default test suite
rather than being gated like test_interview_agent.py / test_chat_endpoint.py.

The dummy key is set via monkeypatch.setenv (function-scoped, auto-reverted)
rather than os.environ.setdefault() at module level -- an earlier version of
this test used setdefault() and it leaked into every other test module
collected afterward in the same pytest session, making
test_interview_agent.py's "skip without real credentials" check see this
module's fake key and attempt a real (and real-failing) API call instead of
skipping. Caught by running the full suite together, not just this file in
isolation.
"""
import uuid

from fastapi.testclient import TestClient

from agent.state import Phase


def test_agent_failure_sends_graceful_error_and_keeps_connection_open(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))
    from api.main import app

    session_id = f"test-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated provider failure")

        # Patch the agent the registry returns for this phase, rather than a
        # single app-level agent -- the handler now selects its agent per
        # turn from the phase gate.
        monkeypatch.setattr(app.state.agents.for_phase(Phase.INTERVIEWING), "invoke", _boom)

        with client.websocket_connect(f"/ws/{session_id}") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "a2ui"

            ws.send_json({"type": "chat", "content": "hello"})

            # Skip typing events and find the error message.
            error_msg = None
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "error":
                    error_msg = msg
                    break
            assert error_msg is not None, "never received an error message"
            assert "message" in error_msg

            # Connection must still be usable after a failed turn -- send
            # again (still failing, same monkeypatch) and confirm we get
            # another graceful error rather than a dropped connection.
            ws.send_json({"type": "chat", "content": "still there?"})
            second_error = None
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "error":
                    second_error = msg
                    break
            assert second_error is not None, "never received a second error message"
