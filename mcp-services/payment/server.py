"""Mock checkout MCP server (T039) — an MCP App, mounted at /payment/mcp.

Hackathon hard requirement #4: mock payment/checkout must be an **MCP App**
rendered inside the chat. Structurally identical to `booking/server.py`,
which is the point -- M4a established the shape and this is the second
instance of it, not a second design:

  - a resource whose URI is `ui://` and whose MIME type is
    `text/html;profile=mcp-app` (plain `text/html` is *not* an MCP App and
    hosts will not render it as one), and
  - a tool whose `_meta` carries `ui/resourceUri` pointing at it, written
    both flat and nested because ext-apps' own `registerAppTool` emits
    both spellings and hosts read either.

Three things differ from booking, all of them because of Principle III:

1. **`confirm_mock_payment` retains nothing the caller submits.** See
   `payment/store.py`'s module docstring for the full three-layer
   argument; the short version is that `PAYMENT_FIELDS` is empty by
   design and `normalise()` is still applied, so a direct MCP client
   posting a card number to this endpoint gets it dropped here.
2. **The tool takes no `fields` it acts on.** `fields` is accepted so the
   allowlist has something to drop and so the boundary is visible in the
   signature, and is otherwise unused.
3. **Nothing is priced here.** The App displays the listing's own `price`
   (or `rent_price_per_day`) verbatim. There is no total, no tax and no
   fee line, because every one of those would be a number on a user's
   screen that no tool call ever returned -- Principle I, in the surface
   where inventing a plausible number is most tempting.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from payment import store

# ⚠️ Stated explicitly, exactly as on the booking server, and for the
# reason that cost M4a a Docker debugging cycle (§14 finding 13).
#
# FastMCP turns DNS-rebinding protection **on by default** with an
# allowlist of `127.0.0.1:*` / `localhost:*`, and answers `421 Misdirected
# Request` to any other `Host` header. The backend calls
# `http://mcp-services:8100/payment/mcp`, so leaving this implicit means
# every containerised MCP request to checkout is rejected -- while
# `GET /payment/health` keeps answering `{"status":"ok"}`, because a
# `custom_route` never passes through that middleware. The symptom would
# be "the checkout App never opens" with a green health check pointing the
# other way.
#
# Off rather than allowlisting the compose service name: these servers sit
# on a private compose network and are called by the backend, never by a
# browser, so the attack this protection exists to stop (a page in the
# user's browser resolving a hostile name to 127.0.0.1) has no path here.
# An allowlist would also break silently the day the service is renamed.
PAYMENT_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)

CHECKOUT_RESOURCE_URI = "ui://payment/checkout.html"
CHECKOUT_MIME_TYPE = "text/html;profile=mcp-app"
CHECKOUT_HTML_PATH = Path(__file__).resolve().parent / "static" / "checkout.html"

# What the checkout App may show about the car. An allowlist, not a
# denylist: a field added to the dataset should have to be opted in to a
# payment screen rather than opted out of one.
#
# Deliberately *narrower* than booking's `LISTING_DISPLAY_FIELDS` -- no
# mileage, fuel type or seats. Checkout is confirming a price for a car
# the user has already chosen and already seen in full, so re-showing the
# spec sheet adds surface without adding information. `description` is
# absent here for the same reason it is absent there: it is the one
# attacker-controlled field and it arrives wrapped in
# `<untrusted_listing_data>` delimiters (HANDOFF §8.21b, Principle IV).
LISTING_DISPLAY_FIELDS = (
    "id", "brand", "model", "year", "category", "price",
    "transaction_type", "rent_price_per_day", "location",
)

# What the checkout App may show about the booking.
#
# `submitted_form_fields` is deliberately excluded. The user's name, email
# and phone are already recorded and already confirmed on screen; copying
# them into a second sandboxed document achieves nothing and widens the
# blast radius of anything that ever goes wrong with an App. Least data
# that makes the screen make sense.
BOOKING_DISPLAY_FIELDS = ("id", "listing_id", "status")

mcp = FastMCP(
    "car-payment",
    stateless_http=True,
    transport_security=PAYMENT_TRANSPORT_SECURITY,
    instructions=(
        "Open the in-chat mock checkout for a booking the user has already "
        "submitted, and record a synthetic confirmation. No real payment is "
        "processed and no payment details are accepted or stored."
    ),
)


def _project(source: dict[str, Any] | None, allowed: tuple[str, ...]) -> dict[str, Any]:
    """Keep only `allowed` keys that are actually present."""
    record = source or {}
    return {key: record[key] for key in allowed if key in record}


@mcp.tool(
    meta={
        "ui/resourceUri": CHECKOUT_RESOURCE_URI,
        "ui": {"resourceUri": CHECKOUT_RESOURCE_URI},
    }
)
def open_mock_checkout(booking: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    """Open the in-chat mock checkout for a booking that has been submitted.

    Args:
        booking: The submitted booking record, exactly as it was stored.
        listing: The full listing record exactly as it came back from
            search_listings. Pass the stored record verbatim -- never
            retype, summarise or reconstruct its values.

    Returns the checkout definition and the values to render it with. This
    server does not look either record up: re-fetching would make it a
    second source of truth able to diverge from the persisted session,
    which is precisely what Principle I's grounding channel exists to
    prevent. The caller supplies the authoritative records, exactly as it
    does for `open_booking_form`.
    """
    return {
        "resourceUri": CHECKOUT_RESOURCE_URI,
        "booking": _project(booking, BOOKING_DISPLAY_FIELDS),
        "listing": _project(listing, LISTING_DISPLAY_FIELDS),
        # Not decoration. spec.md US4 AS1 requires the UI to be
        # "unambiguously labeled as a mock/demo payment", and sending the
        # flag from the server means the label is a property of the
        # protocol rather than a string the bundle happens to contain and
        # could lose in a redesign.
        "mock": True,
        "notice": "MOCK CHECKOUT — no real payment is processed and no card details are stored.",
    }


@mcp.tool()
def confirm_mock_payment(
    booking_id: str,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the mock authorization and issue a synthetic confirmation.

    Args:
        booking_id: The booking being paid for. Supplied by the backend
            from persisted session state, never taken from the browser.
        fields: Anything the checkout App submitted. **Nothing here is
            retained.** `payment/store.PAYMENT_FIELDS` is an empty
            allowlist, so `normalise()` discards every key, whatever it is
            called -- see that module's docstring for why the allowlist is
            empty rather than curated. The argument exists so that a
            direct MCP client (this endpoint is reachable on the compose
            network) has its payload dropped at a real boundary instead of
            landing somewhere by accident.

    Returns {"ok": true, "confirmation": {...}} or {"ok": false,
    "errors": {...}}. Errors are returned rather than raised, matching
    `submit_booking`: an MCP error would collapse to "something went
    wrong" in the iframe, and per HANDOFF §8.7a it would not raise into
    the agent anyway.
    """
    errors = store.validate(booking_id)
    if errors:
        return {"ok": False, "errors": errors}

    # Applied even though it provably returns {} today. The call is the
    # mechanism; deleting it because the result is currently empty is how
    # an allowlist becomes a comment.
    discarded = store.normalise(fields)

    # The mock "authorization" step Principle III names. It reads nothing
    # -- see store.authorise.
    if not store.authorise(discarded):  # pragma: no cover - always approves
        return {"ok": False, "errors": {"_": "The mock authorization did not complete."}}

    return {"ok": True, "confirmation": store.new_confirmation(booking_id)}


# spec.md US4 AS1's deny-by-default CSP, declared on the **resource**, not
# the tool -- ext-apps types the tool's own `csp` field as `never`
# precisely to stop people putting it there. Empty lists are not the same
# as omitting the keys: omitted means "host default", stated-and-empty is
# an explicit, auditable "this document talks to nobody and loads
# nothing". Both are genuinely empty here because the bundle is entirely
# self-contained, and no sandbox permission is requested at all.
#
# It matters more on this App than on the booking form: a checkout screen
# that could open a connection is the one surface where "mock" would stop
# being a claim anyone should take on trust.
CHECKOUT_RESOURCE_META = {
    "ui": {
        "csp": {"connectDomains": [], "resourceDomains": []},
        "permissions": {},
    }
}


@mcp.resource(
    CHECKOUT_RESOURCE_URI, mime_type=CHECKOUT_MIME_TYPE, meta=CHECKOUT_RESOURCE_META
)
def checkout_ui() -> str:
    """The mock checkout's UI, as one self-contained HTML document.

    Self-contained is a hard constraint, not a preference: the host
    renders this in an iframe sandboxed with `allow-scripts` but *without*
    `allow-same-origin`, so the document has an opaque origin and cannot
    fetch a sibling script, stylesheet or font from this server.
    Everything it needs is inlined at build time by
    `mcp-apps-ui/checkout/`.
    """
    return CHECKOUT_HTML_PATH.read_text()


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "payment",
        "checkout_resource": CHECKOUT_RESOURCE_URI,
        "checkout_bundle_present": CHECKOUT_HTML_PATH.exists(),
    })


app = mcp.streamable_http_app()
