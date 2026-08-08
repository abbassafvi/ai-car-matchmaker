"""T033 — booking form validation rules (transport-free).

Mirrors tests/test_marketplace.py: the store holds the rules, so the rules
are tested here without a server, and test_booking_server.py covers the MCP
contract on top.
"""
from __future__ import annotations

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
