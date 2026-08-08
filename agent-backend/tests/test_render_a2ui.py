"""Validates generated messages against the actual A2UI v0.9 protocol
shape (message envelope + createSurface/updateComponents/updateDataModel
field requirements), per specification/v0_9/docs/a2ui_protocol.md in the
a2ui-project/a2ui repo -- not just "does it look plausible." v0.9, not the
newer v1.0, because that's what the only real installable renderer
(@a2ui/react on npm) currently ships -- see render_a2ui.py's module
docstring.
"""
from agent.render_a2ui import (
    CATALOG_ID,
    INTERVIEW_SURFACE_ID,
    build_interview_surface_init,
    build_interview_surface_update,
)
from agent.state import InterviewState

KNOWN_MESSAGE_TYPES = {
    "createSurface", "updateComponents", "updateDataModel",
    "deleteSurface", "actionResponse", "callFunction",
}
# Components used here, all defined in the basic catalog.
KNOWN_COMPONENTS = {"Column", "List", "Card", "Row", "CheckBox", "Text"}


def _assert_valid_envelope(msg: dict):
    assert msg["version"] == "v0.9"
    msg_type_keys = set(msg.keys()) & KNOWN_MESSAGE_TYPES
    assert len(msg_type_keys) == 1, f"message must carry exactly one known message type, got {msg_type_keys}"


def test_init_produces_createSurface_then_updateComponents_then_updateDataModel():
    messages = build_interview_surface_init(InterviewState())
    assert len(messages) == 3
    for m in messages:
        _assert_valid_envelope(m)

    assert "createSurface" in messages[0]
    assert messages[0]["createSurface"]["surfaceId"] == INTERVIEW_SURFACE_ID
    assert messages[0]["createSurface"]["catalogId"] == CATALOG_ID

    assert "updateComponents" in messages[1]
    uc = messages[1]["updateComponents"]
    assert uc["surfaceId"] == INTERVIEW_SURFACE_ID
    ids = {c["id"] for c in uc["components"]}
    assert "root" in ids
    for c in uc["components"]:
        assert "id" in c and "component" in c
        assert c["component"] in KNOWN_COMPONENTS

    assert "updateDataModel" in messages[2]
    udm = messages[2]["updateDataModel"]
    assert udm["surfaceId"] == INTERVIEW_SURFACE_ID
    assert udm["path"] == "/"
    assert "slots" in udm["value"]


def test_init_reflects_empty_interview_as_all_unfilled():
    messages = build_interview_surface_init(InterviewState())
    slots = messages[2]["updateDataModel"]["value"]["slots"]
    assert len(slots) == 5
    assert all(s["filled"] is False for s in slots)
    assert all(s["value"] == "" for s in slots)


def test_update_only_sends_updateDataModel():
    interview = InterviewState(use_case="commute", category="Sedan")
    msg = build_interview_surface_update(interview)
    _assert_valid_envelope(msg)
    assert "updateDataModel" in msg
    assert msg["updateDataModel"]["path"] == "/slots"


def test_update_reflects_partially_filled_slots():
    interview = InterviewState(use_case="commute", category="Sedan")
    msg = build_interview_surface_update(interview)
    slots_by_key = {s["key"]: s for s in msg["updateDataModel"]["value"]}
    assert slots_by_key["use_case"]["filled"] is True
    assert slots_by_key["use_case"]["value"] == "commute"
    assert slots_by_key["budget_max"]["filled"] is False


def test_no_hallucination_values_come_only_from_interview_state():
    """Constitution Principle I: every rendered value must trace back to
    the InterviewState fields, never something the renderer invents.

    The renderer may *format* (see _display), but the underlying number
    must survive round-tripping unchanged -- formatting must never alter
    the value itself.
    """
    interview = InterviewState(budget_max=25000.0)
    msg = build_interview_surface_update(interview)
    slots_by_key = {s["key"]: s for s in msg["updateDataModel"]["value"]}
    assert float(slots_by_key["budget_max"]["value"]) == interview.budget_max


def test_enum_slots_render_their_value_not_the_python_repr():
    """Caught in live verification against the running stack: because
    TransactionType is a (str, Enum) and Enum overrides __str__, the
    progress surface was showing the user "TransactionType.BUY" instead of
    "buy".
    """
    from agent.state import TransactionType

    interview = InterviewState(transaction_type=TransactionType.BUY)
    msg = build_interview_surface_update(interview)
    slots = {s["key"]: s for s in msg["updateDataModel"]["value"]}
    assert slots["transaction_type"]["value"] == "buy"


def test_whole_dollar_budgets_render_without_a_trailing_decimal():
    interview = InterviewState(budget_max=30000.0)
    msg = build_interview_surface_update(interview)
    slots = {s["key"]: s for s in msg["updateDataModel"]["value"]}
    assert slots["budget_max"]["value"] == "30000"


def test_no_rendered_slot_value_leaks_a_python_repr():
    """Blanket guard: nothing user-facing should carry a class name or an
    object repr, whatever type a slot happens to hold.
    """
    from agent.state import TransactionType

    interview = InterviewState(
        use_case="commute", category="Sedan", budget_max=25000.0,
        transaction_type=TransactionType.RENT, target_date="2026-09-01",
    )
    msg = build_interview_surface_update(interview)
    for slot in msg["updateDataModel"]["value"]:
        assert "object at 0x" not in slot["value"]
        assert "TransactionType." not in slot["value"]
