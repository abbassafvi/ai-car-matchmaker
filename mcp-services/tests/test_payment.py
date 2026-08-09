"""T039 — the mock checkout's rules, and Constitution Principle III.

This is the module M4b exists to earn. Principle III was free in M4a (the
booking form has no payment field, so there was nothing to discard) and
plan.md row III says so explicitly: *"M4b is where it stops being free."*

The tests below are in three groups:

  1. the allowlist actually drops payment-shaped input;
  2. the allowlist cannot quietly *gain* a payment-shaped field later,
     which is the only way group 1 can regress;
  3. the confirmation record is synthetic and carries nothing derived
     from what was submitted.

`test_payment_server.py` repeats the first through the real MCP tool, and
T036 (Phase E) repeats it through the real App bridge against a running
Phoenix -- three layers, because §3's standing lesson is that a guarantee
proven at one layer is not proven at the next.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from payment import store

# A realistic hostile payload: every field a checkout form could plausibly
# carry, none of which may survive. The card numbers are the standard test
# PANs -- deliberately real-shaped, because a value that does not look like
# a card number would not prove anything.
CARD_PAYLOAD = {
    "card_number": "4111 1111 1111 1111",
    "cardNumber": "4242424242424242",
    "pan": "5555555555554444",
    "cvv": "123",
    "cvc": "456",
    "expiry": "12/29",
    "exp_month": "12",
    "exp_year": "2029",
    "cardholder_name": "Dana Okoro",
    "billing_zip": "78701",
    "account_number": "000123456789",
    "iban": "GB33BUKB20201555555555",
}


# --- 1. the allowlist drops payment-shaped input --------------------------


def test_the_allowlist_is_empty_on_purpose():
    """The design statement, asserted so a future edit has to face it.

    An empty allowlist is a stronger guarantee than a curated one: there
    is no instrument field to forget to exclude, because no submitted
    field is retained at all.
    """
    assert store.PAYMENT_FIELDS == {}


def test_normalise_discards_every_payment_field():
    assert store.normalise(CARD_PAYLOAD) == {}


def test_no_card_digit_survives_normalisation():
    """Not just "the dict is empty" -- the digits are gone from the value.

    Asserted separately because a future allowlist entry could reintroduce
    a card number under an innocent-looking key, and an emptiness check
    against `PAYMENT_FIELDS` would follow the allowlist rather than
    contradict it.
    """
    survived = str(store.normalise(CARD_PAYLOAD))
    for value in CARD_PAYLOAD.values():
        assert value not in survived
    assert not store.looks_like_a_card_number(survived)


def test_normalise_tolerates_nothing_and_nonsense():
    assert store.normalise(None) == {}
    assert store.normalise({}) == {}
    assert store.normalise({"": "", "x": None}) == {}


def test_authorise_approves_without_reading_anything():
    """The mock authorization step Principle III names.

    Both properties matter: it approves (there is no real gateway, and a
    decline path would mean inventing a reason -- a fabricated value on a
    screen), and it inspects nothing (a card number this function reads is
    a live local one traceback away from a log line).
    """
    assert store.authorise(CARD_PAYLOAD) is True
    assert store.authorise({}) is True
    assert store.authorise(None) is True


# --- 2. the allowlist cannot quietly gain a payment field -----------------


def test_no_payment_instrument_field_can_be_added_to_the_allowlist():
    """The guard on the guard.

    Every test above passes trivially while `PAYMENT_FIELDS` is empty, so
    none of them survives the edit that makes this interesting: someone
    adding `"card_last4"` or `"cardholder_name"` because the checkout
    screen wanted it. This is the test that goes red then, and it names
    the principle in its failure so the reader does not have to go looking.
    """
    offending = [
        name
        for name in store.PAYMENT_FIELDS
        if any(hint in name.lower() for hint in store.FORBIDDEN_FIELD_HINTS)
    ]
    assert not offending, (
        f"Constitution Principle III: {offending} would be retained from a "
        f"checkout submission. No payment-instrument field may enter "
        f"PAYMENT_FIELDS -- discard it at the boundary instead."
    )


def test_the_forbidden_hints_actually_match_real_field_names():
    """Non-vacuity for the test above (§3 lesson 15).

    A hint list that matched nothing would let the guard pass forever
    while proving nothing. So: the names a real payment form uses must be
    caught by it.
    """
    for name in ("card_number", "cardNumber", "cvv", "cvc", "exp_month",
                 "pan", "account_number", "iban"):
        assert any(hint in name.lower() for hint in store.FORBIDDEN_FIELD_HINTS), name

    # ...and it must not be so broad that it forbids every plausible field,
    # which would make it a ban rather than a filter.
    for benign in ("full_name", "email", "pickup_date", "notes"):
        assert not any(hint in benign for hint in store.FORBIDDEN_FIELD_HINTS), benign


def test_the_card_detector_reads_what_it_claims_to():
    """§3 lesson 15 again, on the helper T036 will lean on.

    A detector that silently matched nothing would make every "no card
    number leaked" assertion in this milestone vacuous -- the Phase F
    U+202F bug in a new costume, where the check ran and compared the
    wrong thing.
    """
    for card_like in ("4111111111111111", "4111 1111 1111 1111",
                      "4111-1111-1111-1111", "ref 5555555555554444 end"):
        assert store.looks_like_a_card_number(card_like), card_like

    for not_a_card in ("", "BKG-1A2B3C4D5E", "PMT-99", "2026-09-18",
                       "555-010-9999", "dana@example.com"):
        assert not store.looks_like_a_card_number(not_a_card), not_a_card


# --- 3. the confirmation record is synthetic ------------------------------


def test_validate_requires_a_booking_reference():
    assert set(store.validate(None)) == {"booking_id"}
    assert set(store.validate("   ")) == {"booking_id"}
    assert store.validate("BKG-1A2B3C4D5E") == {}


def test_a_confirmation_carries_exactly_the_spec_entity_fields():
    """spec.md's PaymentConfirmation: *"explicitly no payment instrument
    fields"*. Asserted as an exact set, so an added field is a failure
    rather than something nobody notices.
    """
    confirmation = store.new_confirmation("BKG-1A2B3C4D5E")
    assert set(confirmation) == {
        "id", "booking_id", "confirmation_code", "status", "created_at",
    }
    assert confirmation["booking_id"] == "BKG-1A2B3C4D5E"
    assert confirmation["status"] == store.MOCK_STATUS == "MOCK_CONFIRMED"
    assert confirmation["id"].startswith(store.CONFIRMATION_ID_PREFIX)


def test_confirmation_identifiers_are_synthetic_and_unique():
    """Random, not derived: an identifier that encodes personal or payment
    data is a leak in a field that gets printed, logged and traced.
    """
    ids = {store.new_confirmation_id() for _ in range(200)}
    codes = {store.new_confirmation_code() for _ in range(200)}
    assert len(ids) == 200
    assert len(codes) == 200


def test_the_confirmation_code_is_readable_aloud():
    """It gets read out during a demo, so no ambiguous glyphs."""
    code = store.new_confirmation_code()
    assert re.fullmatch(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){2}", code), code
    assert not set(code) & set("OI01")


def test_created_at_is_utc_and_round_trips():
    stamp = datetime(2026, 8, 9, 12, 30, tzinfo=timezone.utc)
    confirmation = store.new_confirmation("BKG-1", now=stamp)
    parsed = datetime.fromisoformat(confirmation["created_at"])
    assert parsed == stamp
    assert parsed.tzinfo is not None


def test_a_confirmation_built_after_a_hostile_submission_is_clean():
    """The end-to-end shape of Principle III inside this module.

    Submitting the hostile payload and then building a confirmation must
    leave no trace of it anywhere in the retained record -- which is
    structurally guaranteed here, because the confirmation is built from
    the booking id and two random values and never sees `fields` at all.
    That is the property this asserts.
    """
    store.normalise(CARD_PAYLOAD)
    store.authorise(CARD_PAYLOAD)
    confirmation = store.new_confirmation("BKG-1A2B3C4D5E")

    rendered = str(confirmation)
    for value in CARD_PAYLOAD.values():
        assert value not in rendered
    assert not store.looks_like_a_card_number(rendered)
