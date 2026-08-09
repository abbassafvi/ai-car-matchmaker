"""Live integration test for the WebSocket chat endpoint -- the actual
frontend-facing contract (connect, get initial A2UI surface, send a chat
message, get a chat reply plus an A2UI update). Needs a real LLM call, so
it's skipped cleanly without LLM_API_KEY, matching the pattern in
test_otel_setup.py / test_interview_agent.py.
"""
import os
import uuid

import pytest

from conftest import LLM_CREDENTIALS_PRESENT
from fastapi.testclient import TestClient


@pytest.mark.skipif(not LLM_CREDENTIALS_PRESENT, reason="LLM_API_KEY not set")
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


def test_health_reports_each_mcp_server_separately(tmp_path, monkeypatch):
    """Three independent signals, not one composite.

    `mcp_connected` has meant "the marketplace is reachable" to every
    M0-M3 reader, so booking (M4a) and payment (M4b) each got their own
    field rather than being folded in -- otherwise a checkout outage
    would present as "booking is broken", and one green flag would be
    covering three different failures.

    Written in M4b after mutation testing found that **neither**
    `booking_connected` nor `payment_connected` had any regression test:
    deleting `payment_connected` from the `status` calculation left the
    whole suite green. M4a's §14 finding 10 was verified live, both up
    and both down, and that verification was never turned into a test --
    §3's recurring shape, one level down.

    Nothing listens on port 9 (the discard protocol), so all three
    discoveries genuinely fail here rather than being mocked.
    """
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))
    monkeypatch.setenv("MCP_MARKETPLACE_URL", "http://127.0.0.1:9/mcp")
    monkeypatch.setenv("MCP_BOOKING_URL", "http://127.0.0.1:9/booking/mcp")
    monkeypatch.setenv("MCP_PAYMENT_URL", "http://127.0.0.1:9/payment/mcp")
    from api.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()

    # Each is reported, and each is its own field.
    for field in ("mcp_connected", "booking_connected", "payment_connected"):
        assert body[field] is False, f"{field} missing or wrongly true"
    assert body["booking_tools"] == []
    assert body["payment_tools"] == []
    assert body["status"] == "degraded"


def test_health_status_degrades_on_any_single_outage():
    """The truth table, tested directly.

    Mutation testing in M4b showed why this cannot be tested through the
    endpoint: every unit test that calls /health has all downstreams
    unreachable, so `status` is "degraded" regardless of the expression,
    and deleting `payment_connected` from it changed nothing. The
    one-server-down case is the one that matters, and it is a property of
    a pure function -- so assert it there rather than standing up two
    real MCP servers to check a boolean.
    """
    from api.main import HEALTH_SIGNALS, health_status

    # Spelled out, NOT derived from HEALTH_SIGNALS.
    #
    # The first version of this test built its cases by iterating the
    # constant, which made it circular: deleting `booking_connected` from
    # HEALTH_SIGNALS deleted the assertion about it too, and the mutation
    # stayed green. A test that reads its expectations from the thing
    # under test cannot detect that thing shrinking (§3 lesson 2).
    expected = {
        "llm_configured", "mcp_connected", "booking_connected", "payment_connected",
    }
    assert set(HEALTH_SIGNALS) == expected, (
        f"a downstream was added to or removed from the health composite: "
        f"{set(HEALTH_SIGNALS) ^ expected}. If that is intended, update this "
        f"literal deliberately -- it is the thing stopping a server from "
        f"quietly dropping out of /health."
    )

    all_up = {name: True for name in expected}
    assert health_status(**all_up) == "ok"

    # Each signal on its own must be able to degrade the composite.
    for name in sorted(expected):
        assert health_status(**{**all_up, name: False}) == "degraded", (
            f"{name} going down does not degrade /health -- a real outage "
            f"would report ok"
        )


def test_health_status_refuses_to_report_on_a_signal_it_was_not_given():
    """A silently-defaulted signal would report "ok" for a downstream
    nobody checked, which is worse than a crash: it is a green light with
    no evidence behind it.
    """
    from api.main import health_status

    with pytest.raises(ValueError, match="payment_connected"):
        health_status(llm_configured=True, mcp_connected=True, booking_connected=True)
