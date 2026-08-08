"""The mcp-services process: two MCP servers, one port.

plan.md always described mcp-services as "3 MCP servers, one process", but
until M4a exactly one existed and the container ran it directly
(`marketplace.server:app`). This module is that description made real.

Routing is chosen so that **nothing M0-M3 shipped has to change**:

    /mcp           marketplace  (unchanged -- MCP_MARKETPLACE_URL, the
                                compose healthcheck and all 39 existing
                                tests keep working untouched)
    /health        marketplace's health route, also unchanged
    /booking/mcp   booking (M4a)
    /booking/health

Each `streamable_http_app()` carries its own session-manager lifespan that
*must* run, and Starlette does not run the lifespan of a mounted app -- a
sub-app's lifespan is silently skipped. Mounting both and forgetting this
yields a server that accepts connections and then hangs on the first real
request, so the two lifespans are entered explicitly below.

Verified before this file was written, by running a real client against
both mounts: marketplace lists its 2 tools at /mcp, booking lists its tools
and serves the ui:// resource at /booking/mcp, and GET /health still
answers 200 with the 203-listing payload.
"""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from booking.server import app as booking_asgi
from marketplace.server import app as marketplace_asgi

BOOKING_PREFIX = "/booking"


def compose(marketplace_app: Starlette, booking_app: Starlette) -> Starlette:
    """Mount two streamable-HTTP MCP apps into one ASGI app.

    A function rather than module-level statements because a FastMCP
    instance's `StreamableHTTPSessionManager` is **single-use**: it is
    cached on the instance at first `streamable_http_app()` call, and its
    `.run()` raises "can only be called once per instance" on a second
    entry. So a test cannot enter the production apps' lifespans without
    burning the one run the process gets -- doing so broke an unrelated,
    previously-passing marketplace test. Tests build their own composition
    from throwaway servers through this same function, which keeps the
    mechanism under test without touching the singletons.
    """

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        # Starlette does **not** run a mounted app's lifespan -- it is
        # silently skipped. Both session managers start here or the server
        # accepts connections and then hangs on the first MCP request.
        # AsyncExitStack unwinds in reverse even if the second fails to start.
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(
                marketplace_app.router.lifespan_context(marketplace_app)
            )
            await stack.enter_async_context(
                booking_app.router.lifespan_context(booking_app)
            )
            yield

    # Order matters: Mount("") matches everything, so it must come last or
    # it would swallow /booking/* before the booking mount is consulted.
    return Starlette(
        routes=[
            Mount(BOOKING_PREFIX, booking_app),
            Mount("", marketplace_app),
        ],
        lifespan=lifespan,
    )


app = compose(marketplace_asgi, booking_asgi)
