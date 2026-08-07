"""Deterministic ranking (T025). No LLM involvement, by design.

spec.md's `RankedRecommendation` entity says it is "derived from a search
result — never independently authored by the LLM", and Constitution
Principle I says every price/spec shown must be traceable verbatim to a
tool-call result. Both are satisfied structurally here: every number this
module emits is read from a listing record that came out of the search
tool's artifact, and the `reasoning` text is a template filled from those
same fields. Nothing is estimated, rounded, or recalled.

A secondary benefit that matters on this project specifically: ranking in
Python instead of in the prompt keeps request size down, and Groq's limit is
tokens per minute (HANDOFF §5).

Scores are min-max normalised *within the returned slate* rather than
against absolute constants. That is deliberate -- it makes the comparison
mean "best of what actually matched your constraints", which is the question
the user asked, and it avoids inventing magic thresholds ("under 30k miles
is good") that would be judgements this module has no business making.
"""
from __future__ import annotations

from typing import Any, Optional

from agent.state import RankedRecommendation

# Sums to 1.0. Price headroom leads because budget is the constraint users
# state most concretely; age and mileage follow as the two condition proxies
# present in every record.
WEIGHTS = {"value": 0.45, "recency": 0.30, "mileage": 0.25}


def applicable_price(listing: dict[str, Any], transaction_type: str | None) -> Optional[float]:
    """The price that a budget for `transaction_type` compares against.

    Mirrors `mcp-services/marketplace/store._price_for`. The duplication is
    intentional and is the cost of the MCP boundary: the two services are
    separate deployables that share a protocol, not a codebase. Keep them in
    step -- a divergence here would rank against a different number than the
    server filtered on.
    """
    if transaction_type == "rent":
        return listing.get("rent_price_per_day")
    return listing.get("price")


def _normalise(values: list[float], *, higher_is_better: bool) -> list[float]:
    """Min-max to 0..1, with every-value-equal collapsing to a neutral 0.5.

    The degenerate cases matter here: a single-listing slate and a slate
    where every car is the same year both hit it, and neither should let one
    listing claim a full point on a dimension that did not discriminate.
    """
    if not values:
        return []
    low, high = min(values), max(values)
    if high == low:
        return [0.5] * len(values)
    spread = high - low
    return [
        ((value - low) / spread) if higher_is_better else ((high - value) / spread)
        for value in values
    ]


def _money(amount: float) -> str:
    """Whole dollars with thousands separators; no invented cents."""
    return f"${amount:,.0f}"


def _reasoning(listing: dict[str, Any], interview: dict[str, Any]) -> str:
    """A grounded, human-readable justification.

    Every substituted value is read straight off the listing record. The
    listing's `description` is deliberately never used: it is untrusted
    marketplace prose (it arrives wrapped in `<untrusted_listing_data>`),
    and Principle I says the numbers come from structured fields.
    """
    transaction_type = interview.get("transaction_type")
    price = applicable_price(listing, transaction_type)
    budget_max = interview.get("budget_max")

    unit = "/day" if transaction_type == "rent" else ""
    parts = [
        f"{listing['year']} {listing['brand']} {listing['model']} "
        f"at {_money(price)}{unit}" if price is not None
        else f"{listing['year']} {listing['brand']} {listing['model']}"
    ]

    if price is not None and budget_max is not None:
        headroom = budget_max - price
        if headroom >= 0:
            parts.append(f"{_money(headroom)} under your {_money(budget_max)} budget")
        else:
            # Only reachable after a budget relaxation, and saying so is the
            # honest thing -- spec.md US2 AS2 forbids quietly presenting
            # out-of-budget matches as if they fit.
            parts.append(f"{_money(-headroom)} over your {_money(budget_max)} budget")

    if listing.get("mileage") is not None:
        parts.append(f"{listing['mileage']:,} miles")
    if listing.get("fuel_type"):
        parts.append(str(listing["fuel_type"]))
    if listing.get("seats") is not None:
        parts.append(f"{listing['seats']} seats")
    if listing.get("availability_date"):
        parts.append(f"available {listing['availability_date']}")

    return " — ".join([parts[0], ", ".join(parts[1:])]) if len(parts) > 1 else parts[0]


def rank(
    listings: list[dict[str, Any]],
    interview: dict[str, Any],
) -> list[RankedRecommendation]:
    """Rank a candidate slate, best fit first.

    Returns one `RankedRecommendation` per listing, `rank` starting at 1.
    Ordering ties break on listing id so the same slate always ranks the
    same way -- snapshot tests (T022) and the eval set both depend on that.
    """
    if not listings:
        return []

    transaction_type = interview.get("transaction_type")
    budget_max = interview.get("budget_max")

    prices = [applicable_price(l, transaction_type) for l in listings]
    years = [l.get("year") for l in listings]
    mileages = [l.get("mileage") for l in listings]

    # A missing value must not win the dimension it is missing from. Falling
    # back to the worst observed value keeps an incomplete record rankable
    # without letting the gap flatter it.
    def _filled(values: list, worst) -> list[float]:
        present = [v for v in values if v is not None]
        fallback = worst(present) if present else 0.0
        return [float(v) if v is not None else float(fallback) for v in values]

    value_basis = _filled(prices, max)
    if budget_max:
        # Headroom against the stated budget, when we have one: it answers
        # "how much of my budget does this leave me?" rather than merely
        # "which of these is cheapest".
        value_basis = [budget_max - price for price in value_basis]
        value_scores = _normalise(value_basis, higher_is_better=True)
    else:
        value_scores = _normalise(value_basis, higher_is_better=False)

    recency_scores = _normalise(_filled(years, min), higher_is_better=True)
    mileage_scores = _normalise(_filled(mileages, max), higher_is_better=False)

    scored = []
    for listing, value, recency, mileage in zip(
        listings, value_scores, recency_scores, mileage_scores
    ):
        fit = (
            WEIGHTS["value"] * value
            + WEIGHTS["recency"] * recency
            + WEIGHTS["mileage"] * mileage
        )
        scored.append((round(fit, 4), listing))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))

    return [
        RankedRecommendation(
            listing_id=listing["id"],
            rank=position,
            fit_score=fit,
            reasoning=_reasoning(listing, interview),
        )
        for position, (fit, listing) in enumerate(scored, start=1)
    ]


def order_listings_by(
    listings: list[dict[str, Any]],
    recommendations: list[RankedRecommendation],
) -> list[dict[str, Any]]:
    """The same records, reordered to match `recommendations`.

    Keeps the persisted slate and the persisted ranking in one order so the
    catalogue (T026) can render them positionally without re-sorting, and so
    `candidate_listings[0]` is always the top recommendation.
    """
    by_id = {listing["id"]: listing for listing in listings}
    return [by_id[rec.listing_id] for rec in recommendations if rec.listing_id in by_id]
