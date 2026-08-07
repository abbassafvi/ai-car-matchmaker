"""F1 regression: observability must be wired into the *running app*.

The M2.5 audit found `setup_observability()` had zero production callers --
only its own test called it. The compose stack ran Phoenix, the OTLP
endpoint was plumbed through, and a full live session produced exactly zero
spans. Constitution Principle V and FR-012 were unmet while plan.md
recorded them as PASS.

These tests are deliberately Phoenix-free: they assert the *wiring*
(startup calls it, failure degrades instead of crashing). That a span
genuinely lands in Phoenix is covered by test_otel_setup.py, which needs a
live collector.
"""
import uuid

from fastapi.testclient import TestClient


def test_startup_registers_tracing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))

    called = {}

    import api.main as main

    def _fake_setup(*args, **kwargs):
        called["yes"] = True
        return object()

    monkeypatch.setattr(main, "setup_observability", _fake_setup)

    with TestClient(main.app) as client:
        assert called.get("yes"), "lifespan did not register the tracer provider"
        assert client.get("/health").json()["tracing_enabled"] is True


def test_unreachable_phoenix_does_not_take_the_app_down(tmp_path, monkeypatch):
    """Tracing is an observability aid, not a request-path dependency."""
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")
    monkeypatch.setenv("SESSIONS_DB_PATH", str(tmp_path / "sessions.sqlite"))

    import api.main as main

    def _explode(*args, **kwargs):
        raise RuntimeError("phoenix unreachable")

    monkeypatch.setattr(main, "setup_observability", _explode)

    with TestClient(main.app) as client:
        health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["tracing_enabled"] is False

        # And the app still serves a session.
        with client.websocket_connect(f"/ws/{uuid.uuid4().hex[:8]}") as ws:
            assert ws.receive_json()["type"] == "a2ui"
