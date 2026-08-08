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
    # The constraints the *user* actually gave, before any relaxation.
    # `query` is overwritten with each rung, so without this the original is
    # gone by the time the brief is written -- and the model cannot say what
    # changed if it is only shown the result. Measured live (T021): given
    # only the relaxed query, gpt-oss-120b described a $28,000-$36,000 band
    # as the user's "original" range when they had asked for $28,000-$30,000.
    # Accurate on every number it printed, and still wrong about the fact
    # spec.md US2 AS2 exists to guarantee.
    original_query: dict[str, Any] = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    # Parallel to `steps`, one semantic kind per step. It exists so the A2UI
    # reasoning surface (T026) can choose an icon per step without parsing
    # the step's prose -- a renderer that sniffed strings for "No matches"
    # would silently mislabel the trace the first time the wording changed.
    # `steps` stays a plain list[str] because it is also the model-facing
    # and test-facing form.
    step_kinds: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def found(self) -> bool:
        return bool(self.listings)

    def add_step(self, kind: str, text: str) -> None:
        """Record one reasoning step and its kind, keeping the two lists in
        lockstep. Always use this rather than appending to `steps` directly.
        """
        self.steps.append(text)
        self.step_kinds.append(kind)


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
        unavailable = ResearchOutcome(
            error="The marketplace search tool is not available right now.",
        )
        unavailable.add_step("error", "Marketplace unavailable — no search could be run.")
        return unavailable

    query = query_from_interview(interview)
    outcome = ResearchOutcome(query=query, original_query=dict(query))
    outcome.add_step("search", _describe_query(query))

    try:
        structured = await _call_search(search, query, slate_size)

        for step, label in RELAXATION_LADDER:
            if structured["listings"]:
                break
            widened = _relax(query, step)
            if widened is None:
                continue
            outcome.relaxed.append(step)
            outcome.add_step(
                "relax", f"No matches — relaxing the {label} and searching again."
            )
            query = widened
            structured = await _call_search(search, query, slate_size)

        outcome.query = structured.get("query", query)
        outcome.listings = structured["listings"]
    except Exception as exc:
        log.exception("Research failed")
        outcome.error = str(exc)
        outcome.add_step("error", "Search failed — no results could be retrieved.")
        return outcome

    if not outcome.listings:
        outcome.add_step("empty", "Still no matches after relaxing every constraint.")
        return outcome

    outcome.add_step(
        "found", f"Found {len(outcome.listings)} matching listings — ranking them."
    )
    outcome.recommendations = rank(outcome.listings, interview)
    outcome.listings = order_listings_by(outcome.listings, outcome.recommendations)
    outcome.add_step(
        "top",
        f"Top pick: {outcome.recommendations[0].listing_id} "
        f"(fit {outcome.recommendations[0].fit_score:.2f}).",
    )
    return outcome


def _applied(query: dict[str, Any]) -> str:
    """Only the constraints that were actually set, as a plain mapping."""
    return str({k: v for k, v in query.items() if v is not None})


def _describe_query(query: dict[str, Any]) -> str:
    """A human-readable account of the constraints actually being applied."""
    applied = {k: v for k, v in query.items() if v is not None}
    if not applied:
        return "Searching the marketplace with no constraints."
    rendered = ", ".join(f"{k}={v}" for k, v in applied.items())
    return f"Searching the marketplace for {rendered}."


def relaxed_labels(relaxed: list[str]) -> str:
    """Ladder step keys rendered as the phrases a user would recognise.

    The keys ("availability") are internal; the ladder already carries a
    human label for each ("target availability date"), so the brief and the
    reasoning trace name the same thing rather than leaking a variable name
    into the chat.
    """
    labels = dict(RELAXATION_LADDER)
    return ", ".join(labels.get(step, step) for step in relaxed)


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
        # The constraints are spelled out because the previous version asked
        # the model to "say which constraints were tried" without telling it
        # what they were. Measured live (T021): gpt-oss-120b filled the gap
        # with a plausible markdown table asserting "Transaction type: all
        # types (sale, lease, etc.)" when the search had only ever asked for
        # `buy`. No listing was invented, so Principle I's letter held -- but
        # the user was still told something untrue about their own search.
        #
        # The formatting rule is repeated here for the same reason it exists
        # in the found branch (T026 finding (e)): the chat bubble renders
        # markdown as literal asterisks, and this branch never got the fix.
        return (
            "The marketplace returned NO listings.\n"
            f"The user originally asked for: {_applied(outcome.original_query)}\n"
            f"The widest search actually run was: {_applied(outcome.query)}\n"
            f"Constraints relaxed along the way: "
            f"{relaxed_labels(outcome.relaxed) or 'none'}\n"
            "Tell the user plainly that nothing matched, name only the "
            "constraints listed above -- do not invent, assume or add any "
            "others -- and ask which one they would like to change. Do not "
            "invent listings. Write 2-3 plain sentences: no markdown, no "
            "tables, no bullet points, no asterisks, no numbered lists."
        )

    lines = [
        "A marketplace search has already been run for you and the results "
        "are ranked below. These are authoritative tool-call records.",
        "",
        f"Constraints applied: {outcome.query}",
    ]
    if outcome.relaxed:
        lines.insert(2, f"The user originally asked for: {_applied(outcome.original_query)}")
        lines.append(
            f"NOTE: nothing matched the original constraints, so these were "
            f"relaxed: {relaxed_labels(outcome.relaxed)}. Say so explicitly. "
            f"The line above is what they asked for; the line below is what "
            f"was actually searched after widening."
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
        # The A2UI catalogue (T026) is already on screen beside the chat,
        # showing every listing as a card with price, specs, availability,
        # source and the ranker's own reasoning. Before Phase D there was no
        # catalogue, so the model re-listing everything was the only way the
        # user saw it; now it duplicates the cards and buries the chat in a
        # numbered list. Ask for the part a card cannot give: the judgement.
        "IMPORTANT: the user can already SEE all of these listings as cards "
        "next to this chat, with prices, specs, availability and reasoning. "
        "Do NOT re-list them or repeat their numbers.",
        "Instead write 2-3 short sentences: say how many you found, name your "
        "top pick and why it suits what they told you, and invite them to "
        "ask about any of them. Plain sentences only -- no markdown, no "
        "bullet points, no asterisks, no numbered lists.",
        "If you do mention a number, it must appear verbatim above -- never "
        "compute, round, or add one.",
    ]

    # spec.md US2 AS2 is "relaxes AND states which constraint it relaxed", and
    # the NOTE higher up was not enough to get the second half: measured live
    # (T021, gpt-oss-120b), the model read the closing instructions -- which
    # are last and concrete -- and opened with "Four listings matched your
    # criteria" for a slate that only existed because the availability filter
    # had been dropped. Every value in that sentence was grounded and the
    # sentence was still false. So the disclosure is restated here, last,
    # with the specific wording that went wrong called out.
    if outcome.relaxed:
        lines += [
            "",
            f"CRITICAL: these listings do NOT meet everything the user asked "
            f"for. Nothing matched, so the {relaxed_labels(outcome.relaxed)} "
            f"was relaxed to find them. Your FIRST sentence must say that "
            f"plainly. Do NOT say they 'matched your criteria' or 'meet your "
            f"requirements' -- they do not.",
        ]
    return "\n".join(lines)
