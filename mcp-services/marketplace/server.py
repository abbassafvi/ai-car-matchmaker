"""Marketplace MCP server (T023) — Streamable HTTP.

This is the "protocol-based tool access" the constitution's Technology
Constraints require: the agent reaches the catalogue over MCP rather than
importing it, which is also what lets the phase gate be meaningful (a tool
the agent was never handed is not merely discouraged, it is unreachable).

Tool bodies stay thin on purpose — all query logic lives in store.py so it
is testable without a transport (see tests/test_marketplace.py).

Transport note: stateless_http=True. langchain-mcp-adapters opens a fresh
session per tool call regardless, so per-session server state would be
bookkeeping with no beneficiary.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from marketplace import store

PORT = int(os.environ.get("MCP_SERVICES_PORT", "8100"))

mcp = FastMCP(
    "car-marketplace",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    instructions=(
        "Search a car marketplace. All prices, years and specs returned are "
        "authoritative records; never restate a value that did not come from "
        "one of these tools."
    ),
)


@mcp.tool()
def search_listings(
    category: Optional[str] = None,
    budget_max: Optional[float] = None,
    budget_min: Optional[float] = None,
    transaction_type: Optional[str] = None,
    available_by: Optional[str] = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search car listings against hard constraints. Returns matches only.

    All constraints are exclusionary: a listing that fails any of them is
    never returned. An empty list means nothing matched — say so and relax a
    named constraint rather than presenting near-misses.

    Args:
        category: One of Sedan, SUV, Truck, Minivan, Coupe, Convertible,
            Hatchback, Electric, Luxury, Sports. Omit to search all.
        budget_max: Maximum price in USD. For transaction_type="rent" this
            is compared against the daily rental rate, not the sale price.
        budget_min: Minimum price in USD, same basis as budget_max.
        transaction_type: "buy", "rent", or "both". "buy" also matches
            listings offered as "both"; "both" excludes nothing.
        available_by: ISO date (YYYY-MM-DD). Returns only listings available
            on or before it. Ignored if it is not a parseable ISO date.
        limit: Maximum number of listings to return (default 20), ordered
            cheapest first on the price applicable to transaction_type.

    Returns a dict with "listings" (the matches), "count", and "query" (the
    constraints actually applied).
    """
    query = {
        "category": category,
        "budget_max": budget_max,
        "budget_min": budget_min,
        "transaction_type": transaction_type,
        "available_by": available_by,
    }
    listings = store.search(**query, limit=limit)
    return {
        "listings": listings,
        "count": len(listings),
        # Echoing the applied constraints back is what lets the reasoning
        # surface state *why* a slate looks the way it does without the
        # model recalling the query from memory, and gives T021 an
        # unambiguous zero-result signal to relax against.
        "query": {k: v for k, v in query.items() if v is not None},
    }


@mcp.tool()
def get_listing_details(listing_id: str) -> dict[str, Any]:
    """Fetch the full record for one listing by its id (e.g. "LST-0042").

    Raises if the id is unknown, rather than inventing a listing.

    Returns a dict with a "listing" key.
    """
    listing = store.get_details(listing_id)
    if listing is None:
        raise ValueError(
            f"No listing with id {listing_id!r}. Use search_listings to find "
            f"valid ids; do not guess one."
        )
    # Wrapped in a named key, not returned bare: FastMCP places a dict
    # return at the top level of structured_content but a list return under
    # a "result" key, so returning records bare would make the grounding
    # channel's shape depend on the tool. Both tools now return an object
    # with a named key, and the agent-side reader is uniform.
    return {"listing": listing}


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Kept from the M0 stub so compose/README health checks still work."""
    return JSONResponse({
        "status": "ok",
        "service": "mcp-services",
        "servers": ["marketplace"],
        "listings": len(store.load_listings()),
    })


app = mcp.streamable_http_app()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
