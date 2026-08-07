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

from agent.state import InterviewState

CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
INTERVIEW_SURFACE_ID = "interview-progress"

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
                        "children": {"path": "/slots", "componentId": "slot_card"},
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
