"""Marketplace query logic, deliberately separate from the MCP transport.

Keeping the filters here (pure functions over plain dicts) rather than
inside the FastMCP tool bodies is what lets T020 test the hard-filter
contract without standing up a server, and lets the agent-side ranking
reason about the same records the tools return.

Constitution Principle I: these functions only ever *select* and *project*
records loaded from the committed dataset. Nothing here computes, rounds,
or synthesises a price, year or spec -- a value in the output is
byte-identical to the same value in listings.json.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "listings.json"

# Constitution Principle IV. `description` is the one free-text field that
# comes from the "marketplace" rather than from us or the user, so it is the
# one field an injection payload can ride in on. It is wrapped here, at the
# boundary where it enters tool output, because tool output is what
# langchain-mcp-adapters serialises into the model's context -- the agent
# side never gets a chance to wrap it later.
#
# The wrapper is deliberately *not* stripped for rendering: the A2UI
# catalogue renders brand/model/year/price/specs, never listing prose, so
# the delimiters never reach a user's screen.
UNTRUSTED_OPEN = "<untrusted_listing_data>"
UNTRUSTED_CLOSE = "</untrusted_listing_data>"


@lru_cache(maxsize=1)
def load_listings(path: str | None = None) -> tuple[dict[str, Any], ...]:
    """The committed dataset. Cached: it is immutable at runtime and a test
    (`test_generate_listings.py`) already guards it against generator drift.
    """
    raw = json.loads(Path(path or DATA_PATH).read_text())
    return tuple(raw)


def wrap_untrusted(listing: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose `description` carries untrusted-data delimiters."""
    out = dict(listing)
    out["description"] = f"{UNTRUSTED_OPEN}{listing.get('description', '')}{UNTRUSTED_CLOSE}"
    return out


def _parse_iso(value: str | None) -> Optional[date]:
    """Parse an ISO date, or None if it isn't one.

    The interview prompt lets the model pass through whatever the user said
    when it can't infer a real date ("next month"), so target_date is not
    guaranteed to be ISO. Returning None lets callers *skip* the
    availability filter rather than silently matching nothing -- a
    zero-result search caused by an unparseable date would look identical to
    a genuinely empty result set and would send the agent into a pointless
    constraint-relaxation loop.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _price_for(listing: dict[str, Any], transaction_type: str | None) -> Optional[float]:
    """The price a budget should be compared against, for this intent.

    A budget means different things for buying and renting: $30,000 is a
    purchase price but a nonsensical daily rate. Comparing a rental
    enquiry's budget against the vehicle's *sale* price would filter out
    every affordable rental of an expensive car, which is the opposite of
    what the user asked. So the applicable price follows the intent.
    """
    if transaction_type == "rent":
        return listing.get("rent_price_per_day")
    return listing.get("price")


def matches(
    listing: dict[str, Any],
    *,
    category: str | None = None,
    budget_max: float | None = None,
    budget_min: float | None = None,
    transaction_type: str | None = None,
    available_by: str | None = None,
) -> bool:
    """Hard filters (spec.md US2 AS1). Every one is exclusionary: a listing
    that fails any of them is not a candidate, and the agent is not offered
    the chance to argue otherwise.
    """
    if category and listing.get("category") != category:
        return False

    # "buy" must also match listings offered as "both", and likewise for
    # "rent" -- spec.md US2 AS1 says buy-or-both. "both" as a *request*
    # means the user is open to either, so nothing is excluded.
    if transaction_type in ("buy", "rent"):
        if listing.get("transaction_type") not in (transaction_type, "both"):
            return False

    price = _price_for(listing, transaction_type)
    if budget_max is not None:
        if price is None or price > budget_max:
            return False
    if budget_min is not None:
        if price is None or price < budget_min:
            return False

    wanted_by = _parse_iso(available_by)
    if wanted_by is not None:
        avail = _parse_iso(listing.get("availability_date"))
        # An unparseable availability date in the data is treated as a
        # non-match rather than a pass: silently including a listing whose
        # availability we cannot verify would breach the grounding rule.
        if avail is None or avail > wanted_by:
            return False

    return True


def search(
    *,
    category: str | None = None,
    budget_max: float | None = None,
    budget_min: float | None = None,
    transaction_type: str | None = None,
    available_by: str | None = None,
    limit: int = 20,
    listings: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Listings satisfying every supplied constraint, cheapest first.

    Ordering is deterministic (applicable price, then id) so the same query
    always returns the same slate -- snapshot tests and the eval set both
    depend on that, and a stable order also makes the agent's ranking
    reproducible.
    """
    source = listings if listings is not None else load_listings()
    hits = [
        listing
        for listing in source
        if matches(
            listing,
            category=category,
            budget_max=budget_max,
            budget_min=budget_min,
            transaction_type=transaction_type,
            available_by=available_by,
        )
    ]
    hits.sort(key=lambda listing: (
        _price_for(listing, transaction_type) if _price_for(listing, transaction_type) is not None
        else float("inf"),
        listing["id"],
    ))
    return [wrap_untrusted(listing) for listing in hits[:limit]]


def get_details(listing_id: str, listings: Iterable[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    source = listings if listings is not None else load_listings()
    for listing in source:
        if listing["id"] == listing_id:
            return wrap_untrusted(listing)
    return None
