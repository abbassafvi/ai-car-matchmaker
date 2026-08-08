"""Constitution Principle V (Full Observability): process-level tracer
registration, called once at application startup — not opt-in per call
site. Every LLM call and tool call gets traced automatically via
auto_instrument once the LangChain/LangGraph instrumentor is installed.
"""
from __future__ import annotations

import os

from phoenix.otel import register


def setup_observability(service_name: str = "ai-car-matchmaker-agent-backend"):
    """Registers an OTel tracer provider pointed at the Phoenix collector.

    PHOENIX_COLLECTOR_ENDPOINT defaults to the docker-compose service name
    so this works unmodified inside the compose network; override it for
    local (non-docker) runs, e.g. http://localhost:14317.

    `batch=True` is load-bearing, not a tuning preference. `register`
    defaults to `batch=False`, which installs a **SimpleSpanProcessor** that
    exports every span *synchronously* on the thread that ended it. That put
    Phoenix on the request critical path: each LLM and tool span blocked an
    agent turn until the collector acknowledged it, and an unreachable
    collector blocked on connect instead of failing fast. Two consequences,
    both measured rather than reasoned about:

    - Natively, with no Phoenix and no .env, the endpoint below resolves to
      the docker-internal hostname `phoenix`, so every span blocked on a DNS
      lookup that cannot succeed. A stranger's `pytest` run took **105s**
      where it takes ~10s with Phoenix up -- almost all of it idle I/O wait
      (`user 5s` of `real 106s`), which reads as a hung suite.
    - In the demo, a slow or dying Phoenix would stall every agent turn.
      §8.28 says tracing must be fail-soft; it was fail-soft at
      *registration* but not at *export*, which is where it matters.

    Phoenix's own startup banner warns to use a BatchSpanProcessor in
    production. With batching, export moves to a background thread and the
    request path no longer waits on it. `force_flush()` still drains the
    queue, so test_otel_setup's poll-for-the-span assertion is unaffected.
    """
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:4317")
    return register(
        project_name=service_name,
        endpoint=endpoint,
        protocol="grpc",
        auto_instrument=True,
        set_global_tracer_provider=True,
        batch=True,
    )
