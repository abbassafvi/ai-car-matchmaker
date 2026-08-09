"""The two transitions M4a Phase C added, and the one it had to fix.

Every case below was reproduced against the shipped code before it was
written, in the M4a Phase C audit. They were all *latent*: committed,
tested, green, and unreachable by a user because nothing had wired
FORM_FILLING up yet -- which is exactly why no existing test caught them.

- **A stale booking survived re-selection.** With a booking for A, picking
  B moved `selected_listing_id` and left `booking.listing_id == "A"`.
  spec.md's Edge Cases require the prior in-progress booking to be
  "discarded, not silently merged"; the booking form would otherwise have
  submitted against the wrong car.
- **FORM_FILLING was a one-way door for prose but not for clicks.** The
  gate bound no `select_listing` there, so "actually, the Kia" had no tool
  -- while `_handle_action` runs ahead of the gate, so clicking another
  card worked. Phase E's convergence guarantee turned out to be a property
  of one phase rather than of the design.
- **There was no `submit_booking` transition at all**, so US3 AS3
  (FORM_FILLING -> AWAITING_PAYMENT) had nowhere to live.

The last block covers Principle V, which said "every LLM call, tool call,
and phase transition emits an OTel span" while nothing in the codebase
emitted a span explicitly -- so the two transitions that happen outside a
graph run emitted none at all.
"""
import pytest

from agent.ranking import rank
from agent.state import Booking, Phase, SessionState

INTERVIEW = {"category": "SUV", "budget_max": 25000.0, "transaction_type": "buy"}


def listing(id_, **kw):
    base = {
        "id": id_, "brand": "Jeep", "model": "Cherokee", "category": "SUV",
        "year": 2022, "price": 17391, "transaction_type": "buy",
        "rent_price_per_day": 90, "mileage": 34000, "fuel_type": "Petrol",
        "seats": 5, "location": "Austin, TX",
        "description": "<untrusted_listing_data>a car</untrusted_listing_data>",
        "listing_source": "AutoNation — Dealership",
        "availability_date": "2026-08-20",
    }
    base.update(kw)
    return base


def booked_session() -> SessionState:
    """A session in FORM_FILLING with a draft booking for LST-0001."""
    session = SessionState(session_id="s1", phase=Phase.RESEARCHING)
    slate = [listing("LST-0001"), listing("LST-0002", price=21000)]
    session.record_research(slate, rank(slate, INTERVIEW))
    session.select_listing("LST-0001")
    session.booking = Booking(
        id="BKG-OLD", listing_id="LST-0001", session_id="s1", status="DRAFT",
        submitted_form_fields={"full_name": "Dana Okoro"},
    )
    return session


def draft(session: SessionState, listing_id: str | None = None) -> Booking:
    return Booking(
        id="BKG-NEW",
        listing_id=listing_id or session.selected_listing_id,
        session_id=session.session_id,
        status="SUBMITTED",
        submitted_form_fields={"full_name": "Dana Okoro", "email": "dana@example.com"},
    )


# --- re-selection discards the old booking --------------------------------


def test_reselecting_a_different_car_discards_the_booking():
    """spec.md Edge Cases, and the reason this is not just tidiness: the
    booking carries the *other* car's id, so keeping it would let the form
    submit a booking for a car the user visibly moved away from.
    """
    session = booked_session()
    session.select_listing("LST-0002")

    assert session.selected_listing_id == "LST-0002"
    assert session.booking is None, "the booking for LST-0001 must not survive"


def test_reselecting_the_same_car_keeps_the_booking():
    """The discard is targeted, not a reset. Re-confirming the same car --
    which a model may well do -- must not throw away what the user typed.
    """
    session = booked_session()
    session.select_listing("LST-0001")

    assert session.booking is not None
    assert session.booking.id == "BKG-OLD"
    assert session.booking.submitted_form_fields == {"full_name": "Dana Okoro"}


def test_form_filling_is_not_a_one_way_door():
    """The prose path can now do what the click path could always do."""
    session = booked_session()
    assert session.phase == Phase.FORM_FILLING
    assert "select_listing" in session.available_tools()

    session.select_listing("LST-0002")
    assert session.phase == Phase.FORM_FILLING
    assert session.selected_listing_id == "LST-0002"


def test_refining_from_form_filling_falls_back_and_clears_everything():
    """The fifth transition, and the only backwards one.

    A new slate may not contain the chosen car at all, and `select_listing`
    refuses ids outside the slate -- so carrying the selection forward
    would leave the session pointing at something it can no longer act on.
    """
    session = booked_session()
    fresh = [listing("LST-0009", price=9000)]
    session.refine_results(fresh, rank(fresh, INTERVIEW))

    assert session.phase == Phase.RESULTS_READY
    assert session.selected_listing_id is None
    assert session.booking is None
    assert session.candidate_ids() == ["LST-0009"]


# --- the submit transition ------------------------------------------------


def test_submitting_a_booking_advances_to_awaiting_payment():
    """spec.md US3 AS3."""
    session = booked_session()
    session.submit_booking(draft(session))

    assert session.phase == Phase.AWAITING_PAYMENT
    assert session.booking.status == "SUBMITTED"
    assert session.booking.listing_id == "LST-0001"


def test_a_second_submit_is_refused():
    """The App bridge is a network path: a retry, a double-click or a
    reconnect must not produce two bookings for one car.
    """
    session = booked_session()
    session.submit_booking(draft(session))

    # No hand-set phase any more. This line used to read
    #     session.phase = Phase.FORM_FILLING  # as if the client replayed
    # which was a state the machine cannot produce: a real replay arrives
    # with the phase already advanced, and the *phase* guard answered it
    # first, so the duplicate guard below never ran in production. M4b
    # reordered the guards in SessionState.submit_booking so the replay
    # path reaches the check that describes it. Found by writing the same
    # test for confirm_payment and watching it fail on the wrong message.
    assert session.phase == Phase.AWAITING_PAYMENT

    with pytest.raises(ValueError, match="already been submitted"):
        session.submit_booking(draft(session))
    assert session.booking.id == "BKG-NEW"
    assert session.phase == Phase.AWAITING_PAYMENT


def test_a_booking_for_a_different_car_than_the_selected_one_is_refused():
    """The iframe is untrusted input like any other. Its idea of which
    listing this is has to agree with the session's, or the backend would
    be taking the browser's word for what the user chose.
    """
    session = booked_session()

    with pytest.raises(ValueError, match="LST-0002"):
        session.submit_booking(draft(session, listing_id="LST-0002"))
    assert session.phase == Phase.FORM_FILLING


def test_a_booking_cannot_skip_straight_past_form_filling():
    """Principle II: no phase-skipping, including by the App bridge."""
    session = SessionState(session_id="s1", phase=Phase.RESULTS_READY)

    with pytest.raises(ValueError, match="FORM_FILLING"):
        session.submit_booking(draft(session, listing_id="LST-0001"))
    assert session.phase == Phase.RESULTS_READY


# --- Principle V: transitions emit spans ----------------------------------


@pytest.fixture
def emitted(monkeypatch):
    """Capture what `SessionState` reports, at the seam.

    Patched here rather than asserting against a real exporter because the
    OTel tracer provider is a process-global that other tests in this suite
    also touch; the thing worth pinning at this level is that every
    transition method *calls* the recorder with the right arguments. That
    the recorder builds a real span is `test_phase_spans.py`'s job -- the
    M2.5 lesson being that a mechanism nobody calls is decorative, so both
    halves need their own test.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(
        "agent.state.record_phase_transition",
        lambda session_id, from_phase, to_phase, trigger: calls.append(
            (session_id, from_phase, to_phase, trigger)
        ),
    )
    return calls


def test_every_phase_transition_reports_itself(emitted):
    session = SessionState(session_id="s1")
    session.save_interview_slots(
        use_case="commute", category="SUV", budget_max=25000.0,
        transaction_type="buy", target_date="2026-12-31",
    )
    slate = [listing("LST-0001")]
    session.record_research(slate, rank(slate, INTERVIEW))
    session.select_listing("LST-0001")
    session.submit_booking(draft(session))

    assert [(c[1], c[2], c[3]) for c in emitted] == [
        ("INTERVIEWING", "RESEARCHING", "save_interview_slots"),
        ("RESEARCHING", "RESULTS_READY", "record_research"),
        ("RESULTS_READY", "FORM_FILLING", "select_listing"),
        ("FORM_FILLING", "AWAITING_PAYMENT", "submit_booking"),
    ]
    assert {c[0] for c in emitted} == {"s1"}


def test_the_backwards_transition_reports_itself_too(emitted):
    session = booked_session()
    emitted.clear()
    fresh = [listing("LST-0009")]
    session.refine_results(fresh, rank(fresh, INTERVIEW))

    assert emitted == [("s1", "FORM_FILLING", "RESULTS_READY", "refine_results")]
