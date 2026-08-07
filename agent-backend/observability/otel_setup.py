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
    """
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:4317")
    return register(
        project_name=service_name,
        endpoint=endpoint,
        protocol="grpc",
        auto_instrument=True,
        set_global_tracer_provider=True,
    )
