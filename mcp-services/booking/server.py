"""Booking MCP server (T033) — an MCP App, mounted at /booking/mcp.

Hackathon hard requirement #3: form-filling must be an **MCP App** rendered
inside the chat. That is a different surface from the A2UI catalogue, and
deliberately so (see HANDOFF §1's resolved architectural ambiguity): A2UI is
declarative non-HTML UI, an MCP App is HTML in a sandboxed iframe. Both are
required by different clauses; neither replaces the other.

What makes this an MCP App rather than an ordinary MCP server, verified
against @modelcontextprotocol/ext-apps 1.7.5 by reading its wire types and
then by running a client against this server:

  - a resource whose URI is `ui://` and whose MIME type is
    `text/html;profile=mcp-app`, returning the self-contained UI, and
  - a tool whose `_meta` carries `ui/resourceUri` pointing at it, which is
    how a host knows the tool has a UI to render.

The `_meta` key is written twice, flat and nested. ext-apps' own
`registerAppTool` emits both forms and hosts read either, so matching it
costs one line and removes a compatibility question.

Shape copied from marketplace/server.py: thin tool bodies, all rules in a
transport-free store.py, `stateless_http=True`, a `/health` custom route.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from booking import store

FORM_RESOURCE_URI = "ui://booking/form.html"
FORM_MIME_TYPE = "text/html;profile=mcp-app"
FORM_HTML_PATH = Path(__file__).resolve().parent / "static" / "form.html"

# Fields the form may display about the chosen car. `description` is
# deliberately absent: it is the one attacker-controlled field in a listing
# and it arrives wrapped in <untrusted_listing_data> delimiters, so
# rendering it would put both the delimiters and third-party prose on a
# user's screen (HANDOFF §8.21b, Principle IV).
LISTING_DISPLAY_FIELDS = (
    "id", "brand", "model", "year", "category", "price",
    "transaction_type", "rent_price_per_day", "mileage", "fuel_type",
    "seats", "location", "listing_source", "availability_date",
)

mcp = FastMCP(
    "car-booking",
    stateless_http=True,
    instructions=(
        "Open and submit the in-chat booking form for a car the user has "
        "already selected. Never invent listing values; the caller supplies "
        "the authoritative record."
    ),
)


def _display_listing(listing: dict[str, Any] | None) -> dict[str, Any]:
    """Project a listing to the fields the form may show.

    An allowlist, not a denylist: a new field added to the dataset should
    have to be opted in to the UI, not opted out of it.
    """
    source = listing or {}
    return {key: source[key] for key in LISTING_DISPLAY_FIELDS if key in source}


@mcp.tool(
    meta={
        "ui/resourceUri": FORM_RESOURCE_URI,
        "ui": {"resourceUri": FORM_RESOURCE_URI},
    }
)
def open_booking_form(listing: dict[str, Any]) -> dict[str, Any]:
    """Open the in-chat booking form for the car the user has selected.

    Args:
        listing: The full listing record exactly as it came back from
            search_listings. Pass the stored record verbatim -- never
            retype, summarise or reconstruct its values.

    Returns the form definition and the listing values to pre-fill it with.
    """
    return {
        "resourceUri": FORM_RESOURCE_URI,
        "listing": _display_listing(listing),
        "fields": [
            {"name": name, "label": label, "required": required}
            for name, (label, required) in store.FIELDS.items()
        ],
    }


@mcp.tool()
def submit_booking(listing_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and submit a completed booking form.

    Args:
        listing_id: Id of the listing being booked.
        fields: The submitted form values.

    Returns {"ok": true, "booking": {...}} on success, or {"ok": false,
    "errors": {field: message}} when validation fails. Validation is
    server-side and authoritative -- the form's own checks are a
    convenience, not the guarantee.
    """
    errors = store.validate(fields)
    if errors:
        # Not an exception: the caller has to hand these back to the form so
        # the user can fix them without losing what they already typed
        # (spec.md US3 AS2). An MCP error would collapse that to "something
        # went wrong" and, per HANDOFF §8.7a, would not raise into the agent
        # anyway.
        return {"ok": False, "errors": errors}

    return {
        "ok": True,
        "booking": {
            "id": store.new_booking_id(),
            "listing_id": listing_id,
            # Only allowlisted fields survive -- see store.normalise and
            # Constitution Principle III.
            "submitted_form_fields": store.normalise(fields),
            "status": "SUBMITTED",
        },
    }


# spec.md US3 AS1 requires a deny-by-default CSP. In MCP Apps that is
# declared on the **resource**, not the tool (the tool's own `csp` field is
# typed `never` precisely to stop people putting it there), under the `ui`
# namespace in `_meta`. Empty lists are not the same as omitting the keys:
# omitted means "host default", stated-and-empty is an explicit, auditable
# "this form talks to nobody and loads nothing". The form is entirely
# self-contained, so both are genuinely empty, and no sandbox permission
# (camera/microphone/geolocation/clipboard) is requested at all.
FORM_RESOURCE_META = {
    "ui": {
        "csp": {"connectDomains": [], "resourceDomains": []},
        "permissions": {},
    }
}


@mcp.resource(FORM_RESOURCE_URI, mime_type=FORM_MIME_TYPE, meta=FORM_RESOURCE_META)
def booking_form_ui() -> str:
    """The booking form's UI, as one self-contained HTML document.

    Self-contained is a hard constraint, not a preference: the host renders
    this in an iframe sandboxed with `allow-scripts` but *without*
    `allow-same-origin`, so the document has an opaque origin and cannot
    fetch a sibling script, stylesheet or font from this server. Everything
    it needs is inlined at build time.
    """
    return FORM_HTML_PATH.read_text()


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "booking",
        "form_resource": FORM_RESOURCE_URI,
        "form_bundle_present": FORM_HTML_PATH.exists(),
    })


app = mcp.streamable_http_app()
