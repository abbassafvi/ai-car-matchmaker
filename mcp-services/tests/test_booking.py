"""T033 — booking form validation rules (transport-free).

Mirrors tests/test_marketplace.py: the store holds the rules, so the rules
are tested here without a server, and test_booking_server.py covers the MCP
contract on top.
"""
from __future__ import annotations

from datetime import date

import pytest

from booking import store

VALID = {
    "full_name": "Dana Okoro",
    "email": "dana@example.com",
    "phone": "+1 (555) 010-9999",
    "pickup_date": "2026-09-15",
    "notes": "Prefer an afternoon pickup.",
}


def test_a_complete_submission_has_no_errors():
    assert store.validate(VALID) == {}


def test_every_required_field_is_reported_when_all_are_missing():
    errors = store.validate({})
    # All of them, not the first one: US3 AS2 says the form surfaces "the
    # specific missing field(s)", plural, in one round trip.
    assert set(errors) == set(store.REQUIRED_FIELDS)
    assert all(message.endswith("is required.") for message in errors.values())


def test_notes_is_optional():
    assert store.validate({**VALID, "notes": ""}) == {}


@pytest.mark.parametrize("missing", store.REQUIRED_FIELDS)
def test_each_required_field_is_individually_enforced(missing):
    errors = store.validate({**VALID, missing: ""})
    assert set(errors) == {missing}


def test_whitespace_only_does_not_satisfy_a_required_field():
    errors = store.validate({**VALID, "full_name": "   "})
    assert "full_name" in errors


@pytest.mark.parametrize("bad", ["dana", "dana@", "@example.com", "dana example.com"])
def test_an_obviously_invalid_email_is_rejected(bad):
    assert "email" in store.validate({**VALID, "email": bad})


def test_a_phone_number_needs_enough_digits():
    assert "phone" in store.validate({**VALID, "phone": "12"})
    # Punctuation people actually type must not count against them.
    assert store.validate({**VALID, "phone": "555-010-9999"}) == {}


def test_a_non_iso_pickup_date_is_rejected():
    assert "pickup_date" in store.validate({**VALID, "pickup_date": "next tuesday"})
    assert "pickup_date" in store.validate({**VALID, "pickup_date": "2026-13-45"})


def test_all_problems_are_reported_together():
    errors = store.validate({"full_name": "Dana", "email": "nope", "phone": "1"})
    assert set(errors) == {"email", "phone", "pickup_date"}


def test_normalise_trims_values():
    assert store.normalise({**VALID, "full_name": "  Dana Okoro  "})["full_name"] == "Dana Okoro"


def test_normalise_drops_fields_outside_the_allowlist():
    """Constitution Principle III, at the boundary that enforces it."""
    polluted = {
        **VALID,
        "card_number": "4111 1111 1111 1111",
        "cvv": "123",
        "session_id": "not-yours",
    }
    clean = store.normalise(polluted)
    assert set(clean) <= set(store.FIELDS)
    assert "card_number" not in clean and "cvv" not in clean
    # Non-vacuity: the allowlisted fields did survive, so this is asserting
    # a filter rather than an empty dict.
    assert clean["full_name"] == "Dana Okoro"


def test_no_payment_field_is_even_definable():
    """The form has no payment surface at all -- Principle III is a schema
    property here, not a runtime check that could be bypassed.
    """
    joined = " ".join(store.FIELDS).lower()
    for banned in ("card", "cvv", "cvc", "iban", "account", "routing", "pan"):
        assert banned not in joined


def test_booking_ids_are_synthetic_and_unique():
    ids = {store.new_booking_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith(store.BOOKING_ID_PREFIX) for i in ids)


def test_a_booking_id_does_not_embed_submitted_data():
    """A reference gets printed, logged and traced, so it must not carry
    anything the user typed.
    """
    booking_id = store.new_booking_id().lower()
    for value in VALID.values():
        assert value.lower() not in booking_id


# --- pickup-date sanity (M4a Phase C audit, finding 9) --------------------
#
# `validate` used to accept any parseable date. So the form took a pickup
# in the past, and -- worse for a demo -- a pickup *before* the car was
# available, with the availability date printed three rows above the input
# on the same screen. Neither is a security problem; both make the product
# look like it does not read the record it is showing.


def test_a_pickup_date_in_the_past_is_rejected():
    errors = store.validate(
        {**VALID, "pickup_date": "2026-08-08"}, today=date(2026, 8, 9)
    )
    assert "past" in errors["pickup_date"]


def test_today_is_an_acceptable_pickup_date():
    """The boundary, pinned: "not in the past" must not quietly mean
    "strictly after today" and reject a same-day pickup.
    """
    assert store.validate(
        {**VALID, "pickup_date": "2026-08-09"}, today=date(2026, 8, 9)
    ) == {}


def test_a_pickup_before_the_car_is_available_is_rejected():
    errors = store.validate(
        {**VALID, "pickup_date": "2026-09-01"},
        available_from="2026-09-18",
        today=date(2026, 8, 9),
    )
    # The message names the date the user needs, rather than telling them
    # they are wrong and making them go and find it.
    assert "2026-09-18" in errors["pickup_date"]


def test_the_availability_rule_does_not_run_without_an_availability_date():
    """`available_from` is optional because this server never looks a
    listing up -- a second source of listing values is exactly what
    Principle I's grounding channel exists to avoid. Omitted, the rule is
    simply skipped rather than guessed at.
    """
    assert store.validate(
        {**VALID, "pickup_date": "2026-09-01"}, today=date(2026, 8, 9)
    ) == {}


def test_an_unparseable_pickup_date_reports_only_the_format_problem():
    """One message per field, and the right one: a date that could not be
    parsed must not also be accused of being in the past.
    """
    errors = store.validate(
        {**VALID, "pickup_date": "next tuesday"},
        available_from="2026-09-18",
        today=date(2026, 8, 9),
    )
    assert errors["pickup_date"] == "Enter a pickup date as YYYY-MM-DD."


def test_a_valid_pickup_on_the_availability_date_itself_is_accepted():
    assert store.validate(
        {**VALID, "pickup_date": "2026-09-18"},
        available_from="2026-09-18",
        today=date(2026, 8, 9),
    ) == {}
