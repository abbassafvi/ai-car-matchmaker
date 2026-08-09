"""Deterministic domain-object -> A2UI JSON mapping (Constitution
Principle I): the LLM never authors this JSON directly, it only produces
the InterviewState that this module renders from.

Targets A2UI protocol v0.9, not the newer v1.0 documented in the spec repo
-- checked before writing this: the only real, installable renderer today
(@a2ui/react on npm, v0.10.2) only ships v0_8/v0_9 subpath builds, no v1_0
export yet. v0.9's message envelope and the Column/Card/Row/CheckBox/Text
components used here are shape-compatible with v1.0's (confirmed by
fetching and comparing specification/v0_9/docs/a2ui_protocol.md and
specification/v0_9/catalogs/basic/catalog.json against their v1_0
counterparts in the a2ui-project/a2ui repo) -- only the "version" field
value and catalog URL differ. Revisit when the react renderer ships a v1_0
build.
  - createSurface{surfaceId, catalogId}
  - updateComponents{surfaceId, components: [...]}
  - updateDataModel{surfaceId, path, value}
Components used are all defined in the "basic" catalog this module
references via CATALOG_ID -- using anything outside that catalog would
violate A2UI's own security model (agents may only use pre-approved
catalog components).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from agent.ranking import applicable_price, money, price_unit
from agent.state import InterviewState, RankedRecommendation

CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
INTERVIEW_SURFACE_ID = "interview-progress"
REASONING_SURFACE_ID = "research-reasoning"
CATALOGUE_SURFACE_ID = "catalogue"

# The action name a catalogue Button dispatches to the client, which the
# client relays back over the WebSocket as {"type": "action"}. Deliberately
# the same string as the `select_listing` tool: the button and the model
# reach the same code path (SessionState.select_listing), so a click and a
# "I'll take the Jeep" cannot diverge in behaviour.
SELECT_LISTING_ACTION = "select_listing"

# Cancel action sent by the frontend when the user dismisses a booking form
# or checkout card.  Resets the session back to RESULTS_READY so they can
# pick a different car or change preferences.
CANCEL_SELECTION_ACTION = "cancel_selection"

# Icons are inline SVG path data, not catalog icon names.
#
# A2UI v0.9's `Icon.name` accepts either a name from a fixed enum or an
# `{"svgPath": ...}` object. The enum path is tempting and wrong here: the
# renderer implements it as a Material Symbols *ligature font*, so without
# that font loaded every icon renders as its own literal name -- verified
# live, the first catalogue read "payment", "location_on", "calendar_today"
# down the page. Loading the font would mean either a runtime dependency on
# Google's CDN (breaks an offline demo, and plan.md's constraint is that the
# stack runs with no external managed services) or committing a binary.
# `svgPath` renders an inline <svg viewBox="0 0 24 24">, so it is
# self-contained, offline-safe and deterministic.
#
# The paths below are simple hand-authored 24x24 glyphs rather than copied
# icon-set data.
ICON_PATHS = {
    "tag": "M2 12 12 2h8v8L10 20 2 12zm14-6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
    "list": "M4 6h16v2H4zM4 11h12v2H4zM4 16h8v2H4z",
    "pin": "M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z",
    "calendar": "M7 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7zm12 8v9H5v-9h14z",
    "search": "M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z",
    "warning": "M12 2 1 21h22L12 2zm0 4.5 7.5 13h-15L12 6.5zM11 10h2v5h-2v-5zm0 6h2v2h-2v-2z",
    "check": "M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z",
    "star": "m12 2 2.9 6.3 6.8.8-5 4.6 1.3 6.8L12 17.2 5.9 20.5l1.3-6.8-5-4.6 6.8-.8L12 2z",
    "info": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z",
    "error": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z",
}


def icon(name: str) -> dict:
    """An `Icon.name` value: inline SVG path data, never a font ligature."""
    return {"svgPath": ICON_PATHS[name]}


def _fit_label(score: float) -> str:
    """Qualitative fit label — replaces the raw decimal."""
    if score >= 0.75:
        return "Strong match"
    if score >= 0.50:
        return "Good match"
    return "Stretch"


# Semantic step kind (agent/research.py) -> icon. The mapping lives here
# rather than in research.py so the domain layer never names UI assets, and
# an unrecognised kind falls back to a neutral icon rather than rendering
# nothing.
STEP_KIND_ICONS = {
    "search": "search",
    "relax": "warning",
    "found": "check",
    "top": "star",
    "empty": "info",
    "error": "error",
}
DEFAULT_STEP_ICON = "info"

# Deliberately NO `Image` component anywhere in this module. A2UI v0.9's
# Image requires a `url`, and no listing record carries one (the dataset has
# 15 fields, none of them an image). Binding an invented or stock URL would
# put a value on screen that traces to no tool-call result -- exactly what
# Constitution Principle I exists to prevent, in the one surface T022 exists
# to prove is clean. `Icon` is used instead: its glyphs are fixed inline SVG
# paths chosen by us, so an icon is chrome, never a claim about a listing.

# (InterviewState field, human-readable label) -- order matches the
# interview's natural flow.
REQUIRED_SLOTS: list[tuple[str, str]] = [
    ("use_case", "What you'll use it for"),
    ("category", "Car type"),
    ("budget_max", "Budget"),
    ("transaction_type", "Buy or rent"),
    ("target_date", "When you need it"),
]


def _display(value) -> str:
    """Render a slot value as the user should see it.

    Two traps this exists to avoid, both caught in live verification:

    - `TransactionType` is a `(str, Enum)`, and Enum overrides `__str__`, so
      plain `str()` yields "TransactionType.BUY" -- an internal repr leaking
      onto the user's screen. Use `.value` ("buy").
    - Budgets arrive as floats, so `str()` yields "30000.0". Show whole
      dollars as whole numbers.

    Note this only ever *formats* a value already present in state; it never
    substitutes or invents one (Constitution Principle I).
    """
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _slot_rows(interview: InterviewState) -> list[dict]:
    rows = []
    for key, label in REQUIRED_SLOTS:
        value = getattr(interview, key)
        rows.append({
            "key": key,
            "label": label,
            "filled": value is not None and value != "",
            "value": "" if value is None else _display(value),
        })
    return rows


def build_interview_surface_init(interview: InterviewState) -> list[dict]:
    """One-time setup: createSurface + the static component tree + initial
    data. Send on the first turn of a session only.
    """
    return [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": INTERVIEW_SURFACE_ID,
                "catalogId": CATALOG_ID,
            },
        },
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": INTERVIEW_SURFACE_ID,
                "components": [
                    {
                        "id": "root",
                        "component": "Column",
                        "children": ["interview_header", "slot_list"],
                    },
                    {
                        "id": "interview_header",
                        "component": "Text",
                        "text": "What you've told me",
                        "variant": "h2",
                    },
                    {
                        "id": "slot_list",
                        "component": "List",
                        "children": {"path": "/slots", "componentId": "slot_card"},
                        "direction": "vertical",
                    },
                    {"id": "slot_card", "component": "Card", "child": "slot_row"},
                    {
                        "id": "slot_row",
                        "component": "Row",
                        "children": ["slot_check", "slot_value"],
                    },
                    {
                        "id": "slot_check",
                        "component": "CheckBox",
                        "label": {"path": "label"},
                        "value": {"path": "filled"},
                    },
                    {
                        "id": "slot_value",
                        "component": "Text",
                        "text": {"path": "value"},
                    },
                ],
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": INTERVIEW_SURFACE_ID,
                "path": "/",
                "value": {"slots": _slot_rows(interview)},
            },
        },
    ]


def build_interview_surface_update(interview: InterviewState) -> dict:
    """Incremental update for every turn after the first: only the data
    model changes -- the component tree from build_interview_surface_init
    is reused by the renderer, per A2UI's incremental-update pattern.
    """
    return {
        "version": "v0.9",
        "updateDataModel": {
            "surfaceId": INTERVIEW_SURFACE_ID,
            "path": "/slots",
            "value": _slot_rows(interview),
        },
    }


# --- reasoning-steps surface (T026) --------------------------------------
#
# Hackathon requirement #5 and FR-005 name "reasoning steps" as a surface
# that must render via A2UI. This replaces the {"type": "progress"} JSON
# placeholder api/main.py sent through Phase C -- which, worth recording,
# no frontend code ever consumed: App.tsx handled chat/a2ui/error only, so
# those steps were generated, streamed and silently dropped.


def _step_rows(steps: list[str], kinds: list[str]) -> list[dict]:
    """One row per reasoning step, with its icon resolved from its kind.

    `kinds` is zipped defensively rather than indexed: the two lists are
    written in lockstep by `ResearchOutcome.add_step`, but a shorter/absent
    kinds list must degrade to a neutral icon, not raise mid-render.
    """
    padded = list(kinds) + [""] * max(0, len(steps) - len(kinds))
    return [
        {"text": text, "icon": icon(STEP_KIND_ICONS.get(kind, DEFAULT_STEP_ICON))}
        for text, kind in zip(steps, padded)
    ]


def _reasoning_components() -> list[dict]:
    return [
        # MUST be id "root": the renderer resolves a surface's entry point by
        # that well-known id, not by declaration order. Naming it anything
        # else leaves the surface stuck on "[Loading root...]" forever --
        # created, populated, and invisible. Caught in live verification;
        # component ids are scoped per surface, so every surface has its own
        # "root".
        {
            "id": "root",
            "component": "Column",
            "children": ["reasoning_header", "reasoning_list"],
        },
        {
            "id": "reasoning_header",
            "component": "Text",
            "text": "How I searched",
            "variant": "h2",
        },
        {
            "id": "reasoning_list",
            "component": "List",
            "children": {"path": "/steps", "componentId": "step_row"},
            "direction": "vertical",
        },
        {
            "id": "step_row",
            "component": "Row",
            "children": ["step_icon", "step_text"],
            "align": "center",
        },
        # Icon.name accepts a DataBinding (verified against the installed
        # v0_9 catalog schema), so each step carries its own icon without
        # the renderer having to parse the step's prose.
        {"id": "step_icon", "component": "Icon", "name": {"path": "icon"}},
        {"id": "step_text", "component": "Text", "text": {"path": "text"}},
    ]


def build_reasoning_surface_init(steps: list[str], kinds: list[str] | None = None) -> list[dict]:
    """createSurface + component tree + initial steps. Once per connection."""
    return [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": REASONING_SURFACE_ID,
                "catalogId": CATALOG_ID,
            },
        },
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": REASONING_SURFACE_ID,
                "components": _reasoning_components(),
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": REASONING_SURFACE_ID,
                "path": "/",
                "value": {"steps": _step_rows(steps, kinds or [])},
            },
        },
    ]


def build_reasoning_surface_update(steps: list[str], kinds: list[str] | None = None) -> dict:
    """Data-only update for every research pass after the first."""
    return {
        "version": "v0.9",
        "updateDataModel": {
            "surfaceId": REASONING_SURFACE_ID,
            "path": "/steps",
            "value": _step_rows(steps, kinds or []),
        },
    }


# --- catalogue surface (T026) --------------------------------------------


def _transaction_type(interview: dict[str, Any]) -> str | None:
    """Unwrap a TransactionType enum to its wire value (§8.23's trap again)."""
    value = interview.get("transaction_type")
    return value.value if isinstance(value, Enum) else value


def _specs(listing: dict[str, Any]) -> str:
    """Condition/spec line, built only from fields present on the record.

    Absent fields are omitted rather than rendered as "None" or filled with
    a plausible default -- an invented spec would breach Principle I just as
    surely as an invented price.
    """
    parts = []
    if listing.get("mileage") is not None:
        parts.append(f"{listing['mileage']:,} miles")
    if listing.get("fuel_type"):
        parts.append(_display(listing["fuel_type"]))
    if listing.get("seats") is not None:
        parts.append(f"{listing['seats']} seats")
    return " · ".join(parts)


def _catalogue_rows(
    listings: list[dict[str, Any]],
    recommendations: list[RankedRecommendation],
    interview: dict[str, Any],
    selected_listing_id: str | None = None,
) -> list[dict]:
    """One data row per listing, read straight off the verbatim tool record.

    Every string here is either a value copied from the record, a value
    *formatted* from it (money/thousands separators), or the deterministic
    ranker's own `reasoning`. Nothing is summarised, inferred or recalled,
    and `description` is never touched: it arrives wrapped in
    `<untrusted_listing_data>` and is attacker-controlled prose, so binding
    it to a Text component would put both the delimiters and the payload on
    the user's screen (Principle IV; T022 asserts this).
    """
    by_id = {rec.listing_id: rec for rec in recommendations}
    transaction_type = _transaction_type(interview)
    rows = []

    for position, listing in enumerate(listings, start=1):
        rec = by_id.get(listing["id"])
        price = applicable_price(listing, transaction_type)
        # Per listing, not per query -- a "both" slate holds both bases, and
        # a daily rate shown without "/day" is a number the user cannot act on.
        unit = price_unit(listing, transaction_type)

        rows.append({
            # Carried for Phase E's Button action context; not rendered.
            "id": listing["id"],
            "rank_label": f"#{rec.rank if rec else position}",
            "title": (
                f"{_display(listing.get('year'))} {listing.get('brand')} "
                f"{listing.get('model')}"
            ),
            "price_display": f"{money(price)}{unit}" if price is not None else "",
            "specs": _specs(listing),
            "location": _display(listing.get("location") or ""),
            "availability": (
                f"Available {listing['availability_date']}"
                if listing.get("availability_date") else ""
            ),
            "source": _display(listing.get("listing_source") or ""),
            "reasoning": rec.reasoning if rec else "",
            "fit_label": _fit_label(rec.fit_score) if rec else "",
            # Selection state is data, not a separate component tree: A2UI
            # has no conditional rendering, so the button's label carries the
            # state and every card keeps the same shape.
            "select_label": (
                "✓ Selected" if listing["id"] == selected_listing_id else "Choose this one"
            ),
        })

    return rows


def _catalogue_components() -> list[dict]:
    """The card tree. No `Image` -- see this module's header for why."""
    return [
        # id "root" is load-bearing -- see the note in _reasoning_components.
        {
            "id": "root",
            "component": "Column",
            "children": ["catalogue_header", "catalogue_list"],
        },
        {
            "id": "catalogue_header",
            "component": "Text",
            "text": "Recommended for you",
            "variant": "h2",
        },
        {
            "id": "catalogue_list",
            "component": "List",
            "children": {"path": "/listings", "componentId": "listing_card"},
            "direction": "vertical",
        },
        {"id": "listing_card", "component": "Card", "child": "listing_body"},
        {
            "id": "listing_body",
            "component": "Column",
            "children": [
                "listing_headline",
                "listing_price_row",
                "listing_specs_row",
                "listing_location_row",
                "listing_available_row",
                "listing_divider",
                "listing_why",
                "listing_source_text",
                "listing_select",
            ],
        },
        {
            "id": "listing_headline",
            "component": "Row",
            "children": ["listing_rank", "listing_title", "listing_fit"],
            "align": "center",
        },
        {
            "id": "listing_rank",
            "component": "Text",
            "text": {"path": "rank_label"},
            "variant": "caption",
        },
        {
            "id": "listing_title",
            "component": "Text",
            "text": {"path": "title"},
            "variant": "h3",
        },
        {
            "id": "listing_fit",
            "component": "Text",
            "text": {"path": "fit_label"},
            "variant": "caption",
        },
        {
            "id": "listing_price_row",
            "component": "Row",
            "children": ["price_icon", "listing_price"],
            "align": "center",
        },
        {"id": "price_icon", "component": "Icon", "name": icon("tag")},
        {
            "id": "listing_price",
            "component": "Text",
            "text": {"path": "price_display"},
            "variant": "h4",
        },
        {
            "id": "listing_specs_row",
            "component": "Row",
            "children": ["specs_icon", "listing_specs"],
            "align": "center",
        },
        {"id": "specs_icon", "component": "Icon", "name": icon("list")},
        {"id": "listing_specs", "component": "Text", "text": {"path": "specs"}},
        {
            "id": "listing_location_row",
            "component": "Row",
            "children": ["location_icon", "listing_location"],
            "align": "center",
        },
        {"id": "location_icon", "component": "Icon", "name": icon("pin")},
        {"id": "listing_location", "component": "Text", "text": {"path": "location"}},
        {
            "id": "listing_available_row",
            "component": "Row",
            "children": ["calendar_icon", "listing_available"],
            "align": "center",
        },
        {"id": "calendar_icon", "component": "Icon", "name": icon("calendar")},
        {
            "id": "listing_available",
            "component": "Text",
            "text": {"path": "availability"},
        },
        {"id": "listing_divider", "component": "Divider", "axis": "horizontal"},
        {"id": "listing_why", "component": "Text", "text": {"path": "reasoning"}},
        {
            "id": "listing_source_text",
            "component": "Text",
            "text": {"path": "source"},
            "variant": "caption",
        },
        # `Button` requires BOTH `child` and `action` -- there is no
        # decorative Button in v0.9. The action's context value is a
        # DataBinding, and the renderer resolves an action against the
        # per-row DataContext (verified in web_core's resolveAction), so one
        # templated button yields the right listing id per card rather than
        # needing one component per card.
        {
            "id": "listing_select",
            "component": "Button",
            "child": "listing_select_label",
            "variant": "primary",
            "action": {
                "event": {
                    "name": SELECT_LISTING_ACTION,
                    "context": {"listing_id": {"path": "id"}},
                },
            },
        },
        {
            "id": "listing_select_label",
            "component": "Text",
            "text": {"path": "select_label"},
        },
    ]


def build_catalogue_surface_init(
    listings: list[dict[str, Any]],
    recommendations: list[RankedRecommendation],
    interview: dict[str, Any],
    selected_listing_id: str | None = None,
) -> list[dict]:
    """createSurface + component tree + the ranked slate. Once per connection.

    Sent both when research completes *and* on reconnect for a session that
    already has recommendations -- `SessionState.candidate_listings` is
    persisted precisely so a resumed RESULTS_READY session does not render
    an empty catalogue (tasks.md T025(iii)).
    """
    return [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": CATALOGUE_SURFACE_ID,
                "catalogId": CATALOG_ID,
            },
        },
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": CATALOGUE_SURFACE_ID,
                "components": _catalogue_components(),
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": CATALOGUE_SURFACE_ID,
                "path": "/",
                "value": {"listings": _catalogue_rows(
                    listings, recommendations, interview, selected_listing_id
                )},
            },
        },
    ]


def build_catalogue_surface_update(
    listings: list[dict[str, Any]],
    recommendations: list[RankedRecommendation],
    interview: dict[str, Any],
    selected_listing_id: str | None = None,
) -> dict:
    """Data-only update when a later search replaces the slate."""
    return {
        "version": "v0.9",
        "updateDataModel": {
            "surfaceId": CATALOGUE_SURFACE_ID,
            "path": "/listings",
            "value": _catalogue_rows(
                listings, recommendations, interview, selected_listing_id
            ),
        },
    }
