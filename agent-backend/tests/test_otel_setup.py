"""Constitution Principle V: prove a span emitted through our tracer setup
actually lands in Phoenix, not just that the SDK call didn't raise. This is
an integration test — it needs a live Phoenix instance (`docker compose up
phoenix`) and is skipped automatically if one isn't reachable, so the plain
unit suite doesn't hard-depend on Docker.
"""
import os
import socket
import time
import uuid

import pytest

PHOENIX_HOST, PHOENIX_GRPC_PORT, PHOENIX_HTTP_PORT = "localhost", 14317, 16006


def _phoenix_reachable() -> bool:
    try:
        with socket.create_connection((PHOENIX_HOST, PHOENIX_GRPC_PORT), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _phoenix_reachable(), reason="Phoenix not running (docker compose up phoenix)")
def test_span_lands_in_phoenix():
    import httpx

    from observability.otel_setup import setup_observability

    project_name = f"test-{uuid.uuid4().hex[:8]}"
    os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = f"http://{PHOENIX_HOST}:{PHOENIX_GRPC_PORT}"

    tracer_provider = setup_observability(service_name=project_name)
    tracer = tracer_provider.get_tracer(project_name)
    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("probe", "test_otel_setup")
    tracer_provider.force_flush()

    # Phoenix ingests asynchronously even after flush; poll briefly.
    # Reading spans requires the project's opaque id (there is no
    # query-by-name span endpoint), so resolve it from /v1/projects first.
    base = f"http://{PHOENIX_HOST}:{PHOENIX_HTTP_PORT}"
    deadline = time.time() + 10
    spans = []
    while time.time() < deadline:
        projects = httpx.get(f"{base}/v1/projects").json().get("data", [])
        match = next((p for p in projects if p["name"] == project_name), None)
        if match:
            resp = httpx.get(f"{base}/v1/projects/{match['id']}/spans")
            if resp.status_code == 200 and resp.json().get("data"):
                spans = resp.json()["data"]
                break
        time.sleep(1)

    assert any(s["name"] == "test-span" for s in spans), "span never appeared in Phoenix"
