"""The mcp-services process: three MCP servers, one port.

plan.md always described mcp-services as "3 MCP servers, one process".
M4a made two of them real; M4b completes the description.

Routing is chosen so that **nothing already shipped has to change**:

    /mcp            marketplace  (unchanged -- MCP_MARKETPLACE_URL, the
                                 compose healthcheck and every M0-M3 test
                                 keep working untouched)
    /health         marketplace's health route, also unchanged
    /booking/mcp    booking (M4a)
    /booking/health
    /payment/mcp    payment (M4b)
    /payment/health

Each `streamable_http_app()` carries its own session-manager lifespan that
*must* run, and Starlette does not run the lifespan of a mounted app -- a
sub-app's lifespan is silently skipped. Mounting one and forgetting this
yields a server that accepts connections and then hangs on the first real
request, so every mounted lifespan is entered explicitly below.
"""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from booking.server import app as booking_asgi
from marketplace.server import app as marketplace_asgi
from payment.server import app as payment_asgi

BOOKING_PREFIX = "/booking"
PAYMENT_PREFIX = "/payment"
ROOT_PREFIX = ""


def compose(*mounts: tuple[str, Starlette]) -> Starlette:
    """Mount any number of streamable-HTTP MCP apps into one ASGI app.

    Takes `(prefix, app)` pairs rather than positional apps with prefixes
    baked in. M4a's version was `compose(marketplace_app, booking_app)`,
    which read fine with two servers and does not extend: a third would
    have meant a third parameter and a third hardcoded prefix, and the
    prefix a given app ends up on would stay invisible at the call site.

    A function rather than module-level statements because a FastMCP
    instance's `StreamableHTTPSessionManager` is **single-use**: it is
    cached on the instance at the first `streamable_http_app()` call, and
    its `.run()` raises "can only be called once per instance" on a second
    entry. So a test cannot enter the production apps' lifespans without
    burning the one run the process gets -- doing so broke an unrelated,
    previously-passing marketplace test when this file was first written.
    Tests build their own composition from throwaway servers through this
    same function, which keeps the mechanism under test without touching
    the singletons.

    **Ordering is enforced, not merely documented.** `Mount("")` matches
    every path, so a root mount listed before a prefixed one silently
    swallows it: the prefixed server becomes unreachable while every
    import-level test still passes and its own health route still answers
    from a direct client. That was a comment in the M4a version and the
    kind of comment a third mount is exactly likely to be added above.
    Now it raises.
    """
    prefixes = [prefix for prefix, _ in mounts]

    if len(set(prefixes)) != len(prefixes):
        raise ValueError(f"duplicate mount prefix in {prefixes!r}")

    if ROOT_PREFIX in prefixes and prefixes[-1] != ROOT_PREFIX:
        raise ValueError(
            f"the root mount must be last or it swallows every prefixed "
            f"mount after it -- got {prefixes!r}"
        )

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        # Starlette does **not** run a mounted app's lifespan -- it is
        # silently skipped. Every session manager starts here or the
        # server accepts connections and then hangs on the first MCP
        # request. AsyncExitStack unwinds in reverse even if a later one
        # fails to start.
        async with AsyncExitStack() as stack:
            for _prefix, mounted in mounts:
                await stack.enter_async_context(
                    mounted.router.lifespan_context(mounted)
                )
            yield

    return Starlette(
        routes=[Mount(prefix, mounted) for prefix, mounted in mounts],
        lifespan=lifespan,
    )


app = compose(
    (BOOKING_PREFIX, booking_asgi),
    (PAYMENT_PREFIX, payment_asgi),
    # Last, always: Mount("") matches everything above it. `compose`
    # enforces this, so a mount added below here fails loudly at import
    # rather than going quietly unreachable.
    (ROOT_PREFIX, marketplace_asgi),
)
