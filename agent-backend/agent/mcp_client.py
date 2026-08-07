"""T024 — marketplace tool discovery over MCP (Streamable HTTP).

Discovery is deliberately a startup-time concern rather than a per-turn one:
`create_deep_agent` fixes an agent's tool set at construction, so the tools
have to exist before `PhaseAgentRegistry` builds anything. `api/main.py`
calls `discover_marketplace_tools()` once in the FastAPI lifespan and hands
the result to the registry.

Two properties this module is responsible for:

1. **Fail-soft.** mcp-services being unreachable must degrade research, not
   kill the backend -- the same rule tracing follows. A failure here returns
   an empty tool list and logs; the agent then runs with no domain tools and
   `/health` reports `mcp_connected: false`.

2. **No global mutation.** It returns tools; it does not reach into
   `agent.graph.TOOL_REGISTRY`. That registry is the static, import-time
   mapping the phase-gate tests assert against, and a lifespan that mutated
   it would make `test_phase_gate.py` mean one thing under pytest and
   another under the running app.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DEFAULT_MARKETPLACE_URL = "http://localhost:8100/mcp"

# The tools we expect the marketplace server to expose. Discovery returning
# something *other* than this is worth a warning rather than a silent pass:
# the phase gate names these tools, so a rename on the server side would
# otherwise show up only as research quietly never happening.
EXPECTED_MARKETPLACE_TOOLS = {"search_listings", "get_listing_details"}


async def discover_marketplace_tools(url: str | None = None) -> list:
    """Adapted LangChain tools for the marketplace MCP server, or `[]`.

    Never raises. The caller cannot meaningfully recover from a discovery
    failure mid-startup, and taking the whole backend down over an optional
    downstream is a worse outcome than a degraded one that says so.
    """
    endpoint = url or os.environ.get("MCP_MARKETPLACE_URL", DEFAULT_MARKETPLACE_URL)

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({
            "marketplace": {"transport": "streamable_http", "url": endpoint},
        })
        tools = await client.get_tools()
    except Exception as exc:  # pragma: no cover - depends on mcp-services availability
        log.warning(
            "Marketplace tools unavailable at %s -- research will be degraded: %s",
            endpoint, exc,
        )
        return []

    discovered = {tool.name for tool in tools}
    missing = EXPECTED_MARKETPLACE_TOOLS - discovered
    if missing:
        log.warning(
            "Marketplace server at %s did not expose expected tool(s): %s",
            endpoint, ", ".join(sorted(missing)),
        )

    log.info("Discovered %d marketplace tool(s) at %s: %s",
             len(tools), endpoint, ", ".join(sorted(discovered)))
    return tools
