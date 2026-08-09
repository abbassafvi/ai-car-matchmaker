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

# Default weights — sums to 1.0.
WEIGHTS = {"value": 0.45, "recency": 0.30, "mileage": 0.25}

# Use-case-specific weight overrides.
USE_CASE_WEIGHTS: dict[str, dict[str, float]] = {
    "family": {"value": 0.35, "recency": 0.25, "mileage": 0.40},  # mileage/seats matter most
    "commuting": {"value": 0.50, "recency": 0.20, "mileage": 0.30},  # fuel efficiency / value
    "road_trip": {"value": 0.30, "recency": 0.40, "mileage": 0.30},  # newer + seats
    "work": {"value": 0.55, "recency": 0.15, "mileage": 0.30},  # value first
    "off_road": {"value": 0.35, "recency": 0.30, "mileage": 0.35},  # balanced
}


def _weights_for_use_case(interview: dict[str, Any]) -> dict[str, float]:
    """Return weight set tuned to the stated use case."""
    use_case = (interview.get("use_case") or "").lower().replace(" ", "_")
    return USE_CASE_WEIGHTS.get(use_case, WEIGHTS)


def price_basis(listing: dict[str, Any], transaction_type: str | None) -> str:
    """"buy" or "rent" -- which price this listing is being judged on.

    Mirrors `mcp-services/marketplace/store.price_basis`. The duplication is
    intentional and is the cost of the MCP boundary: the two services are
    separate deployables that share a protocol, not a codebase. Keep them in
    step -- a divergence here would rank against a different number than the
    server filtered on.

    The listing matters as much as the request. Under "both" the slate holds
    sale-only cars, rent-only cars and cars offered either way, so the query
    alone cannot say which number applies.
    """
    if transaction_type == "rent":
        return "rent"
    if transaction_type == "both" and listing.get("transaction_type") not in ("buy", "both"):
        return "rent"
    return "buy"


def price_unit(listing: dict[str, Any], transaction_type: str | None) -> str:
    """"/day" when this listing is priced as a rental, else "".

    Per listing, not per query, which is the bit that was wrong: the suffix
    used to be `"/day" if transaction_type == "rent" else ""`, so in a
    "both" search a rent-only car was shown at a *sale* price with no unit
    on it -- a number the user could not act on, presented as if they could.
    """
    return "/day" if price_basis(listing, transaction_type) == "rent" else ""


def applicable_price(listing: dict[str, Any], transaction_type: str | None) -> Optional[float]:
    """The price that a budget for `transaction_type` compares against."""
    if price_basis(listing, transaction_type) == "rent":
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


def money(amount: float) -> str:
    """Whole dollars with thousands separators; no invented cents.

    Public because `render_a2ui` formats the same prices for the catalogue
    surface. One formatter, so a card and the reasoning line printed beneath
    it can never disagree about how the same number is written.
    """
    return f"${amount:,.0f}"


_money = money  # retained for readability inside this module


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

    unit = price_unit(listing, transaction_type)
    parts = [
        f"{listing['year']} {listing['brand']} {listing['model']} "
        f"at {_money(price)}{unit}" if price is not None
        else f"{listing['year']} {listing['brand']} {listing['model']}"
    ]

    # Only compare against the budget when the two are the same *kind* of
    # number. A single `budget_max` carries no basis of its own, so under
    # "both" it can only be read as the purchase budget the user almost
    # certainly stated -- and subtracting a daily rate from it produces
    # "$130/day — $24,870 under your $25,000 budget", which is arithmetic
    # performed on two unrelated quantities and presented to the user as a
    # fact. Saying nothing about headroom is the honest alternative; the
    # rate itself is still shown, and it is still a real number off the
    # record.
    budget_comparable = price_basis(listing, transaction_type) == (
        "rent" if transaction_type == "rent" else "buy"
    )
    if price is not None and budget_max is not None and budget_comparable:
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

    # Value is scored WITHIN a price basis, never across one.
    #
    # A "both" slate mixes sale prices with daily rates, and the two are one
    # or two orders of magnitude apart. Scored together, `budget_max - price`
    # hands every rental almost the entire budget as headroom, so every
    # rental beats every purchase on the dimension that carries the most
    # weight -- the ranking would be sorted by price basis with the actual
    # comparison buried inside it. Normalising each group against its own
    # peers makes "good value for a rental" and "good value for a purchase"
    # comparable numbers, which is what a mixed slate needs.
    bases = [price_basis(l, transaction_type) for l in listings]
    filled = _filled(prices, max)
    value_scores = [0.5] * len(listings)
    for basis in ("buy", "rent"):
        idx = [i for i, b in enumerate(bases) if b == basis]
        if not idx:
            continue
        group = [filled[i] for i in idx]
        if budget_max:
            # Headroom against the stated budget, when we have one: it
            # answers "how much of my budget does this leave me?" rather
            # than merely "which of these is cheapest".
            group_scores = _normalise(
                [budget_max - price for price in group], higher_is_better=True
            )
        else:
            group_scores = _normalise(group, higher_is_better=False)
        for position, i in enumerate(idx):
            value_scores[i] = group_scores[position]

    recency_scores = _normalise(_filled(years, min), higher_is_better=True)
    mileage_scores = _normalise(_filled(mileages, max), higher_is_better=False)

    scored = []
    w = _weights_for_use_case(interview)
    for listing, value, recency, mileage in zip(
        listings, value_scores, recency_scores, mileage_scores
    ):
        fit = (
            w["value"] * value
            + w["recency"] * recency
            + w["mileage"] * mileage
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
