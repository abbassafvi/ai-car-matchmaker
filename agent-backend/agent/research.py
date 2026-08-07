"""T025 — the RESEARCHING phase: search, relax if needed, rank, hand off.

**The first search is code-driven, not model-driven.** The agent does not
choose the search arguments; this module builds them from the interview
slots the user actually gave and calls the tool directly. Three reasons,
recorded because the alternative was a live option:

1. Constitution Principle I becomes true by construction on the headline
   path. The model never has to recall a budget correctly, because it is
   never asked to -- the constraint goes from persisted state into the tool
   call without passing through a prompt.
2. It removes an LLM round trip from the critical path of every session.
3. It keeps the request small, which matters against Groq's tokens-per-minute
   ceiling (HANDOFF §5).

The model is still very much in the loop: it narrates the ranked slate, it
answers follow-ups, and it drives any further searches with the tools the
phase gate binds for RESEARCHING/RESULTS_READY. What it does not do is
originate the numbers.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.ranking import order_listings_by, rank
from agent.state import RankedRecommendation

log = logging.getLogger(__name__)

# How many listings reach the model and the catalogue. Deliberately small:
# HANDOFF §5's demo risk is Groq's TPM ceiling, and a slate longer than this
# is not something a user reads anyway.
DEFAULT_SLATE_SIZE = 5

SEARCH_TOOL = "search_listings"


@dataclass
class ResearchOutcome:
    """What one research pass produced. Everything the caller needs to
    persist, narrate, or render, with no re-derivation required.
    """
    listings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[RankedRecommendation] = field(default_factory=list)
    query: dict[str, Any] = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def found(self) -> bool:
        return bool(self.listings)


def query_from_interview(interview: dict[str, Any]) -> dict[str, Any]:
    """Map interview slots onto `search_listings` arguments.

    `target_date` becomes `available_by` only if it is a real ISO date --
    the interview prompt lets the model pass through whatever the user said
    ("next month") when it cannot infer one, and the server treats an
    unparseable date as "no constraint" anyway. Sending it regardless would
    be harmless but makes the echoed query misleading.
    """
    transaction_type = interview.get("transaction_type")
    if hasattr(transaction_type, "value"):  # tolerate a TransactionType enum
        transaction_type = transaction_type.value

    return {
        "category": interview.get("category"),
        "budget_max": interview.get("budget_max"),
        "budget_min": interview.get("budget_min"),
        "transaction_type": transaction_type,
        "available_by": interview.get("target_date"),
    }


# spec.md US2 AS2: on zero matches the agent must relax a *named* constraint
# rather than fabricate or silently widen. Ordered least-painful first --
# a later availability date is a smaller compromise than a different budget,
# which is in turn smaller than abandoning the body style the user asked for.
# Each step is skipped when it would not actually change the query, so an
# already-unconstrained search does not "relax" something it never applied.
RELAXATION_LADDER: list[tuple[str, str]] = [
    ("availability", "target availability date"),
    ("budget", "budget ceiling (raised 20%)"),
    ("category", "car category"),
]

BUDGET_RELAXATION_FACTOR = 1.2


def _relax(query: dict[str, Any], step: str) -> Optional[dict[str, Any]]:
    """Apply one ladder step, or None if it would be a no-op."""
    relaxed = dict(query)
    if step == "availability":
        if not query.get("available_by"):
            return None
        relaxed["available_by"] = None
    elif step == "budget":
        if not query.get("budget_max"):
            return None
        relaxed["budget_max"] = round(query["budget_max"] * BUDGET_RELAXATION_FACTOR, 2)
    elif step == "category":
        if not query.get("category"):
            return None
        relaxed["category"] = None
    return relaxed


async def _call_search(tool, query: dict[str, Any], limit: int) -> dict[str, Any]:
    """Invoke the adapted MCP search tool and return its structured content.

    Reads `ToolMessage.artifact["structured_content"]` -- the typed channel
    (HANDOFF §8.5) -- never the stringified JSON in `.content` and never the
    model's account of it. Note that a tool failure arrives as a ToolMessage
    with `status == "error"` rather than as an exception (§8.7a), so it is
    checked explicitly here.
    """
    message = await tool.ainvoke({
        "args": {**{k: v for k, v in query.items() if v is not None}, "limit": limit},
        "id": f"research-{uuid.uuid4().hex[:8]}",
        "name": tool.name,
        "type": "tool_call",
    })

    if getattr(message, "status", None) == "error":
        raise RuntimeError(f"search_listings failed: {message.content}")

    artifact = getattr(message, "artifact", None) or {}
    structured = artifact.get("structured_content")
    if not isinstance(structured, dict) or "listings" not in structured:
        raise RuntimeError(
            "search_listings returned no structured_content -- the grounding "
            f"channel is broken, refusing to fall back to prose. Got: {artifact!r}"
        )
    return structured


async def run_research(
    interview: dict[str, Any],
    tools: list,
    *,
    slate_size: int = DEFAULT_SLATE_SIZE,
) -> ResearchOutcome:
    """Search on the interview's constraints, relaxing only if nothing matched.

    Returns an outcome rather than raising: a research failure should leave
    the user with an explanation in the chat, not a dropped socket.
    """
    search = next((t for t in tools if t.name == SEARCH_TOOL), None)
    if search is None:
        return ResearchOutcome(
            error="The marketplace search tool is not available right now.",
            steps=["Marketplace unavailable — no search could be run."],
        )

    query = query_from_interview(interview)
    outcome = ResearchOutcome(query=query)
    outcome.steps.append(_describe_query(query))

    try:
        structured = await _call_search(search, query, slate_size)

        for step, label in RELAXATION_LADDER:
            if structured["listings"]:
                break
            widened = _relax(query, step)
            if widened is None:
                continue
            outcome.relaxed.append(step)
            outcome.steps.append(f"No matches — relaxing the {label} and searching again.")
            query = widened
            structured = await _call_search(search, query, slate_size)

        outcome.query = structured.get("query", query)
        outcome.listings = structured["listings"]
    except Exception as exc:
        log.exception("Research failed")
        outcome.error = str(exc)
        outcome.steps.append("Search failed — no results could be retrieved.")
        return outcome

    if not outcome.listings:
        outcome.steps.append("Still no matches after relaxing every constraint.")
        return outcome

    outcome.steps.append(f"Found {len(outcome.listings)} matching listings — ranking them.")
    outcome.recommendations = rank(outcome.listings, interview)
    outcome.listings = order_listings_by(outcome.listings, outcome.recommendations)
    outcome.steps.append(
        f"Top pick: {outcome.recommendations[0].listing_id} "
        f"(fit {outcome.recommendations[0].fit_score:.2f})."
    )
    return outcome


def _describe_query(query: dict[str, Any]) -> str:
    """A human-readable account of the constraints actually being applied."""
    applied = {k: v for k, v in query.items() if v is not None}
    if not applied:
        return "Searching the marketplace with no constraints."
    rendered = ", ".join(f"{k}={v}" for k, v in applied.items())
    return f"Searching the marketplace for {rendered}."


def narration_brief(outcome: ResearchOutcome) -> str:
    """The message handed to the model so it can present the slate.

    Built from the artifact, so the model is *reading* the numbers rather
    than recalling them. Listing descriptions are included deliberately,
    still carrying the server's `<untrusted_listing_data>` delimiters: the
    boundary is only meaningful if untrusted text actually crosses it, and
    T029's adversarial probes need a path to the model to prove they are
    inert.
    """
    if outcome.error:
        return (
            "The marketplace search failed with: "
            f"{outcome.error}\nTell the user plainly that the search could not "
            "run and that they can retry. Do not invent listings."
        )

    if not outcome.found:
        return (
            "The marketplace returned NO listings, even after relaxing "
            f"{', '.join(outcome.relaxed) or 'nothing'}. Tell the user that "
            "nothing matched, say which constraints were tried, and ask which "
            "one they would like to change. Do not invent listings."
        )

    lines = [
        "A marketplace search has already been run for you and the results "
        "are ranked below. These are authoritative tool-call records.",
        "",
        f"Constraints applied: {outcome.query}",
    ]
    if outcome.relaxed:
        lines.append(
            f"NOTE: nothing matched the original constraints, so these were "
            f"relaxed: {', '.join(outcome.relaxed)}. Say so explicitly."
        )
    lines.append("")

    by_id = {listing["id"]: listing for listing in outcome.listings}
    for rec in outcome.recommendations:
        listing = by_id.get(rec.listing_id, {})
        lines.append(
            f"#{rec.rank} [{rec.listing_id}] {listing.get('year')} "
            f"{listing.get('brand')} {listing.get('model')} "
            f"({listing.get('category')}) — price={listing.get('price')} "
            f"rent_per_day={listing.get('rent_price_per_day')} "
            f"mileage={listing.get('mileage')} fuel={listing.get('fuel_type')} "
            f"seats={listing.get('seats')} "
            f"available={listing.get('availability_date')} "
            f"source={listing.get('listing_source')}"
        )
        lines.append(f"    why: {rec.reasoning}")
        lines.append(f"    listing_description: {listing.get('description', '')}")

    lines += [
        "",
        "Present these to the user in rank order, briefly, tying each to what "
        "they said they needed. Use ONLY the numbers above -- do not compute, "
        "round, or add any value that is not printed here.",
    ]
    return "\n".join(lines)
