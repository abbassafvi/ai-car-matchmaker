"""Live integration test for the WebSocket chat endpoint -- the actual
frontend-facing contract (connect, get initial A2UI surface, send a chat
message, get a chat reply plus an A2UI update). Needs a real LLM call, so
it's skipped cleanly without LLM_API_KEY, matching the pattern in
test_otel_setup.py / test_interview_agent.py.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient


def _has_llm_credentials() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


@pytest.mark.skipif(not _has_llm_credentials(), reason="LLM_API_KEY not set")
def test_full_round_trip_over_websocket(tmp_path):
    os.environ["SESSIONS_DB_PATH"] = str(tmp_path / "sessions.sqlite")
    from api.main import app  # imported here so SESSIONS_DB_PATH is set first

    session_id = f"test-{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{session_id}") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "a2ui"
            assert any("createSurface" in m for m in init_msg["messages"])

            ws.send_json({
                "type": "chat",
                "content": (
                    "I need a Sedan to buy, budget up to $25000, for my "
                    "daily commute, by September 2026."
                ),
            })

            chat_reply = ws.receive_json()
            assert chat_reply["type"] == "chat"
            assert chat_reply["role"] == "assistant"
            assert len(chat_reply["content"]) > 0

            a2ui_update = ws.receive_json()
            assert a2ui_update["type"] == "a2ui"
            update_msg = a2ui_update["messages"][0]
            slots = {s["key"]: s for s in update_msg["updateDataModel"]["value"]}
            assert slots["category"]["filled"] is True
            assert slots["category"]["value"] == "Sedan"


def test_health_reports_llm_configured_and_marketplace_missing(tmp_path, monkeypatch):
    """M3: `status` now covers the marketplace too, not just the LLM key.

    With a key but no reachable mcp-services (the situation in CI), the
    backend is genuinely only half-usable -- it can interview but cannot
    research. Reporting `ok` there would have made a failed tool discovery
    look identical to a logic bug at exactly the moment research silently
    stopped happening.
    """
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))
    monkeypatch.setenv("MCP_MARKETPLACE_URL", "http://127.0.0.1:9/mcp")  # nothing listens
    from api.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["llm_configured"] is True
        assert body["mcp_connected"] is False
        assert body["marketplace_tools"] == []
        assert body["status"] == "degraded"


def test_backend_boots_and_reports_degraded_without_an_llm_key(tmp_path, monkeypatch):
    """F7: a missing key must not kill the container at startup.

    Previously build_model() raised inside lifespan, so `docker compose up`
    without a configured .env exited the agent-backend service instead of
    surfacing a readable cause. The app now boots degraded and says so.
    """
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))
    from api.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"
        assert resp.json()["llm_configured"] is False

        # And a chat turn explains itself rather than dropping the socket.
        with client.websocket_connect(f"/ws/degraded-{uuid.uuid4().hex[:8]}") as ws:
            assert ws.receive_json()["type"] == "a2ui"
            ws.send_json({"type": "chat", "content": "hello"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert "LLM_API_KEY" in err["message"]
