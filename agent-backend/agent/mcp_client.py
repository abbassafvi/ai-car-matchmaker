"""T024/T033 — MCP tool discovery over Streamable HTTP.

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
import uuid
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MARKETPLACE_URL = "http://localhost:8100/mcp"
DEFAULT_BOOKING_URL = "http://localhost:8100/booking/mcp"
DEFAULT_PAYMENT_URL = "http://localhost:8100/payment/mcp"

# The tools we expect the marketplace server to expose. Discovery returning
# something *other* than this is worth a warning rather than a silent pass:
# the phase gate names these tools, so a rename on the server side would
# otherwise show up only as research quietly never happening.
EXPECTED_MARKETPLACE_TOOLS = {"search_listings", "get_listing_details"}

# The booking server's tools (M4a). ⚠️ These must **never** be handed to
# `PhaseAgentRegistry(extra_tools=...)`. `graph.resolve_registry()` resolves
# extras *over* the local registry (`registry[tool.name] = tool`, extras
# win), and `TOOLS_BY_PHASE[FORM_FILLING]` names `open_booking_form` -- so
# injecting the raw MCP tool would silently replace the local wrapper with
# the one whose schema demands the whole listing record, reinstating the
# Principle I violation the wrapper exists to prevent, with every test
# still green. They are discovered separately, kept out of `extra_tools`,
# and reached only by backend code: `agent/tools.py::build_booking_tools`
# closes over them, and the MCP App bridge calls `submit_booking` directly.
EXPECTED_BOOKING_TOOLS = {"open_booking_form", "submit_booking"}

# The payment server's tools (M4b). ⚠️ Same rule as the booking tools, and
# the stakes are higher: `TOOLS_BY_PHASE[AWAITING_PAYMENT]` names
# `open_mock_checkout`, so injecting the raw MCP tools would replace the
# local wrapper with one whose schema is `{booking, listing}` **required**
# -- the model retyping the price it is about to charge, which is
# Principle I inverted in the one place it matters most. And
# `confirm_mock_payment` would arrive bound to nothing but present in the
# registry, one gate-table edit away from being callable with card-like
# arguments (Principle III). Discovered separately, kept out of
# `extra_tools`, reached only by backend code.
EXPECTED_PAYMENT_TOOLS = {"open_mock_checkout", "confirm_mock_payment"}


async def _discover(label: str, endpoint: str, expected: set[str]) -> list:
    """Adapted LangChain tools for one MCP server, or `[]`.

    Never raises, for either server: the caller cannot meaningfully recover
    from a discovery failure mid-startup, and taking the whole backend down
    over an optional downstream is a worse outcome than a degraded one that
    says so.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({
            label: {"transport": "streamable_http", "url": endpoint},
        })
        tools = await client.get_tools()
    except Exception as exc:  # pragma: no cover - depends on mcp-services availability
        log.warning(
            "%s tools unavailable at %s -- that capability will be degraded: %s",
            label, endpoint, exc,
        )
        return []

    discovered = {tool.name for tool in tools}
    missing = expected - discovered
    if missing:
        log.warning(
            "%s server at %s did not expose expected tool(s): %s",
            label, endpoint, ", ".join(sorted(missing)),
        )

    log.info("Discovered %d %s tool(s) at %s: %s",
             len(tools), label, endpoint, ", ".join(sorted(discovered)))
    return tools


async def discover_booking_tools(url: str | None = None) -> list:
    """Adapted LangChain tools for the booking MCP server, or `[]`.

    Kept deliberately separate from the marketplace's list rather than
    merged into one `MultiServerMCPClient` call: the two sets have different
    privileges. Marketplace tools are model-facing and are injected into the
    agent registry; booking tools are **not**, for the reason recorded on
    `EXPECTED_BOOKING_TOOLS` above. Two lists make that difference
    structural instead of a comment someone has to notice.
    """
    endpoint = url or os.environ.get("MCP_BOOKING_URL", DEFAULT_BOOKING_URL)
    return await _discover("booking", endpoint, EXPECTED_BOOKING_TOOLS)


async def discover_payment_tools(url: str | None = None) -> list:
    """Adapted LangChain tools for the payment MCP server, or `[]`.

    A third list rather than a merge, for the reason recorded on
    `EXPECTED_PAYMENT_TOOLS`: three servers with three different
    privileges. Marketplace tools are model-facing and injected; booking
    and payment tools are not, and are reached only through local
    wrappers or the App bridge.
    """
    endpoint = url or os.environ.get("MCP_PAYMENT_URL", DEFAULT_PAYMENT_URL)
    return await _discover("payment", endpoint, EXPECTED_PAYMENT_TOOLS)


FORM_RESOURCE_URI = "ui://booking/form.html"
CHECKOUT_RESOURCE_URI = "ui://payment/checkout.html"

# Which server serves which `ui://` resource. A resource read has to go to
# the server that declares it, and the two live behind different env vars
# -- so this is a lookup rather than a default argument, which is what
# `read_form_resource` used to have when booking was the only App.
APP_RESOURCE_ENDPOINTS = {
    FORM_RESOURCE_URI: ("MCP_BOOKING_URL", DEFAULT_BOOKING_URL),
    CHECKOUT_RESOURCE_URI: ("MCP_PAYMENT_URL", DEFAULT_PAYMENT_URL),
}


async def read_app_resource(uri: str, url: str | None = None) -> dict[str, Any]:
    """Fetch an MCP App's `ui://` resource, **keeping its `_meta`**.

    Deliberately not `MultiServerMCPClient.get_resources()`, which is the
    obvious call and the wrong one. Measured against the live server: the
    adapter converts each content part to a LangChain `Blob` carrying only
    `mimetype` and `metadata={"uri": ...}`, and **drops `_meta` entirely**.
    The resource's `_meta` is where the deny-by-default CSP lives --

        {"ui": {"csp": {"connectDomains": [], "resourceDomains": []},
                "permissions": {}}}

    -- which is spec.md US3 AS1's (and US4 AS1's) actual requirement and
    the whole reason both App servers declare it on the resource rather
    than the tool. It does survive the wire: `read_resource()`'s
    `contents[0].meta` has it. So this drops to a raw `ClientSession` for
    one call.

    `uri` is required and the endpoint is looked up from it. This was
    `read_form_resource(uri=FORM_RESOURCE_URI, url=None)` while booking
    was the only App, which read fine and hid a trap: the default
    endpoint was `MCP_BOOKING_URL`, so calling it for the checkout
    resource would have asked the *booking* server for a document it does
    not serve. A defaulted URI plus a defaulted endpoint that must agree
    is two defaults one edit apart from disagreeing silently.

    Nothing would have failed if we had used the adapter. The form carries
    its own `default-src 'none'` meta tag and Phase D sandboxes the iframe,
    so the document stays locked down either way -- US3 AS1 would just have
    quietly stopped being a property of the protocol and become two
    hardcodings that happen to agree, with the host inventing a policy the
    server had already stated. That is the failure this project keeps
    paying for, so: read the declaration, ship the declaration.

    Raises rather than returning a partial result. Unlike tool discovery
    there is no degraded mode worth having -- an MCP App with no document
    is not an MCP App, and the caller (the form-open path) can report it.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    if url is None:
        try:
            env_var, fallback = APP_RESOURCE_ENDPOINTS[uri]
        except KeyError:
            raise ValueError(
                f"no MCP server is registered for {uri!r} -- add it to "
                f"APP_RESOURCE_ENDPOINTS. Guessing an endpoint would ask one "
                f"App's server for another App's document."
            ) from None
        endpoint = os.environ.get(env_var, fallback)
    else:
        endpoint = url

    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)

    if not result.contents:
        raise RuntimeError(f"{uri} returned no contents")

    content = result.contents[0]
    html = getattr(content, "text", None)
    if not html:
        raise RuntimeError(
            f"{uri} returned no text -- an MCP App resource must be an HTML "
            f"document, got {type(content).__name__}"
        )

    return {
        "uri": uri,
        "mimeType": content.mimeType,
        "html": html,
        # The host needs this to build the iframe's sandbox/CSP. `meta` is
        # `_meta` on the wire; the SDK exposes it under this name.
        "meta": getattr(content, "meta", None) or {},
    }


async def call_structured(tool, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke an adapted MCP tool and return its `structured_content`.

    The typed grounding channel (HANDOFF §8.5): `ToolMessage.artifact
    ["structured_content"]` holds real dicts with real ints, while
    `.content` holds a stringified copy. Backend code reads the artifact.

    Note a failed MCP call arrives as a `ToolMessage` with `status ==
    "error"` rather than as an exception (§8.7a), so "no exception" does
    not mean "it worked" and the status is checked explicitly.
    """
    message = await tool.ainvoke({
        "args": args,
        "id": f"{tool.name}-{uuid.uuid4().hex[:8]}",
        "name": tool.name,
        "type": "tool_call",
    })

    if getattr(message, "status", None) == "error":
        raise RuntimeError(f"{tool.name} failed: {message.content}")

    artifact = getattr(message, "artifact", None) or {}
    structured = artifact.get("structured_content")
    if not isinstance(structured, dict):
        raise RuntimeError(
            f"{tool.name} returned no structured_content -- the grounding "
            f"channel is broken, refusing to fall back to prose. Got: {artifact!r}"
        )
    return structured


async def discover_marketplace_tools(url: str | None = None) -> list:
    """Adapted LangChain tools for the marketplace MCP server, or `[]`.

    Never raises. The caller cannot meaningfully recover from a discovery
    failure mid-startup, and taking the whole backend down over an optional
    downstream is a worse outcome than a degraded one that says so.
    """
    endpoint = url or os.environ.get("MCP_MARKETPLACE_URL", DEFAULT_MARKETPLACE_URL)
    return await _discover("marketplace", endpoint, EXPECTED_MARKETPLACE_TOOLS)
