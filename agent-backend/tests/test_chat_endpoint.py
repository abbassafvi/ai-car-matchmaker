"""Live integration test for the WebSocket chat endpoint -- the actual
frontend-facing contract (connect, get initial A2UI surface, send a chat
message, get a chat reply plus an A2UI update). Needs a real LLM call, so
it's skipped cleanly without OPENROUTER_API_KEY, matching the pattern in
test_otel_setup.py / test_interview_agent.py.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient


def _has_llm_credentials() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


@pytest.mark.skipif(not _has_llm_credentials(), reason="OPENROUTER_API_KEY not set")
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


@pytest.mark.skipif(not _has_llm_credentials(), reason="OPENROUTER_API_KEY not set")
def test_health_endpoint(tmp_path):
    os.environ["SESSIONS_DB_PATH"] = str(tmp_path / "sessions.sqlite")
    from api.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
