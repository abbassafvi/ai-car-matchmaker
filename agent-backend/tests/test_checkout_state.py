"""M4b — `SessionState.confirm_payment`, the sixth phase transition.

All six transitions live in `agent/state.py` so that Principle II's state
machine is one readable module rather than something scattered across the
callers that happen to trigger it. This is the last one:
AWAITING_PAYMENT -> CONFIRMED.

Like `submit_booking` it is **not** reachable from a model tool -- the
values arrive through the MCP App bridge -- so the guards here are the
only thing standing between an untrusted iframe message and a confirmed
transaction. They are tested as refusals, not as happy paths.
"""
import pytest

from agent.ranking import rank
from agent.state import Booking, PaymentConfirmation, Phase, SessionState

LISTING = {
    "id": "LST-0042", "brand": "Jeep", "model": "Cherokee", "category": "SUV",
    "year": 2023, "price": 24500, "transaction_type": "buy",
    "rent_price_per_day": None, "mileage": 31000, "fuel_type": "Petrol",
    "seats": 5, "location": "Austin, TX", "description": "a car",
    "listing_source": "AutoNation", "availability_date": "2026-09-18",
}
INTERVIEW = {"category": "SUV", "budget_max": 25000.0, "transaction_type": "buy"}

BOOKING_ID = "BKG-1A2B3C4D5E"


def confirmation(booking_id: str = BOOKING_ID) -> PaymentConfirmation:
    return PaymentConfirmation(
        id="PMT-0123456789",
        booking_id=booking_id,
        confirmation_code="TE7D-46NF-SF6J",
        status="MOCK_CONFIRMED",
        created_at="2026-08-09T12:30:00+00:00",
    )


def awaiting_payment() -> SessionState:
    """Driven through the real transitions, never by setting `phase`.

    The precondition under test is "a booking was submitted"; a hand-set
    phase would prove the method works in a state the machine cannot
    reach.
    """
    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    session.record_research([LISTING], rank([LISTING], INTERVIEW))
    session.select_listing("LST-0042")
    session.submit_booking(Booking(
        id=BOOKING_ID, listing_id="LST-0042", session_id="s1",
        submitted_form_fields={"full_name": "Dana Okoro"}, status="SUBMITTED",
    ))
    return session


# --- the happy path --------------------------------------------------------


def test_confirming_a_payment_advances_to_confirmed():
    session = awaiting_payment()
    session.confirm_payment(confirmation())

    assert session.phase == Phase.CONFIRMED
    assert session.payment_confirmation.confirmation_code == "TE7D-46NF-SF6J"
    assert session.payment_confirmation.status == "MOCK_CONFIRMED"


def test_the_booking_survives_confirmation():
    """CONFIRMED is the last screen of the demo and it has to be able to
    show what was bought, so nothing about the booking or the slate may be
    cleared on the way in.
    """
    session = awaiting_payment()
    session.confirm_payment(confirmation())

    assert session.booking.id == BOOKING_ID
    assert session.selected_listing_id == "LST-0042"
    assert session.selected_listing()["price"] == 24500


def test_the_confirmation_record_holds_no_payment_instrument_field():
    """spec.md's PaymentConfirmation entity: *"explicitly no payment
    instrument fields"*. Asserted on the persisted model, so a field added
    to the schema fails here rather than in a leak review.
    """
    session = awaiting_payment()
    session.confirm_payment(confirmation())

    persisted = session.model_dump(mode="json")["payment_confirmation"]
    assert set(persisted) == {
        "id", "booking_id", "confirmation_code", "status", "created_at",
    }


def test_the_whole_session_round_trips_through_json_after_confirmation():
    """Graph state must be plain-JSON-able (§8.15), and this is the first
    transition that adds a nested model to it.
    """
    session = awaiting_payment()
    session.confirm_payment(confirmation())

    restored = SessionState.model_validate(session.model_dump(mode="json"))
    assert restored.phase == Phase.CONFIRMED
    assert restored.payment_confirmation.confirmation_code == "TE7D-46NF-SF6J"
    assert restored.booking.id == BOOKING_ID


# --- the refusals ----------------------------------------------------------


def test_payment_cannot_be_confirmed_before_the_payment_phase():
    """Nothing may skip to CONFIRMED. The App bridge is a network path, so
    this is reachable by a crafted message, not just by a bug.
    """
    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    session.record_research([LISTING], rank([LISTING], INTERVIEW))
    session.select_listing("LST-0042")
    assert session.phase == Phase.FORM_FILLING

    with pytest.raises(ValueError, match="only be confirmed from AWAITING_PAYMENT"):
        session.confirm_payment(confirmation())

    assert session.phase == Phase.FORM_FILLING
    assert session.payment_confirmation is None


def test_payment_cannot_be_confirmed_without_a_submitted_booking():
    session = awaiting_payment()
    session.booking = None

    with pytest.raises(ValueError, match="no submitted booking"):
        session.confirm_payment(confirmation())

    assert session.phase == Phase.AWAITING_PAYMENT


def test_a_draft_booking_is_not_enough():
    session = awaiting_payment()
    session.booking.status = "DRAFT"

    with pytest.raises(ValueError, match="no submitted booking"):
        session.confirm_payment(confirmation())


def test_a_confirmation_for_a_different_booking_is_refused():
    """The iframe is untrusted input: its idea of what is being paid for
    has to agree with the session's.
    """
    session = awaiting_payment()

    with pytest.raises(ValueError, match="BKG-SOMEONE-ELSE"):
        session.confirm_payment(confirmation("BKG-SOMEONE-ELSE"))

    assert session.phase == Phase.AWAITING_PAYMENT
    assert session.payment_confirmation is None


def test_a_payment_cannot_be_confirmed_twice():
    """A retry, a double-click or a reconnect must not mint a second
    confirmation -- the same duplicate guard `submit_booking` needed, and
    for the same reason: the App bridge is a network path.
    """
    session = awaiting_payment()
    session.confirm_payment(confirmation())
    first = session.payment_confirmation.id

    with pytest.raises(ValueError, match="already been confirmed"):
        session.confirm_payment(confirmation())

    assert session.payment_confirmation.id == first
    assert session.phase == Phase.CONFIRMED


def test_a_refused_confirmation_leaves_the_phase_untouched():
    """Every refusal above raises *before* mutating. Asserted as a group
    because a guard that raised after assigning would leave a session in
    CONFIRMED with no confirmation -- worse than either outcome alone.
    """
    for mutate in (
        lambda s: setattr(s, "booking", None),
        lambda s: setattr(s.booking, "status", "DRAFT"),
    ):
        session = awaiting_payment()
        mutate(session)
        with pytest.raises(ValueError):
            session.confirm_payment(confirmation())
        assert session.phase == Phase.AWAITING_PAYMENT
        assert session.payment_confirmation is None


# --- Principle V: the sixth transition emits its own span -----------------


def test_confirming_payment_emits_a_phase_transition_span(monkeypatch):
    """Principle V's third clause. `auto_instrument` only traces things
    inside a graph *run*, and this transition happens outside one (the App
    bridge), so the span is emitted from beside the mutation in
    `SessionState` rather than from the caller -- exactly as the other
    five are.
    """
    recorded: list = []
    monkeypatch.setattr(
        "agent.state.record_phase_transition",
        lambda *args: recorded.append(args),
    )

    session = awaiting_payment()
    recorded.clear()  # ignore the transitions that built the fixture
    session.confirm_payment(confirmation())

    assert recorded == [("s1", "AWAITING_PAYMENT", "CONFIRMED", "confirm_payment")]


def test_a_refused_confirmation_emits_no_span():
    """A trace that shows a transition which did not happen is worse than
    no trace: Principle V calls the trace the audit log.
    """
    recorded: list = []
    session = awaiting_payment()

    import agent.state as state_module
    original = state_module.record_phase_transition
    state_module.record_phase_transition = lambda *args: recorded.append(args)
    try:
        with pytest.raises(ValueError):
            session.confirm_payment(confirmation("BKG-WRONG"))
    finally:
        state_module.record_phase_transition = original

    assert recorded == []
