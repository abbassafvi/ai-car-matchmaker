"""Booking form validation, deliberately separate from the MCP transport.

Same split as marketplace/store.py, for the same reason: the rules live in
pure functions over plain dicts so tests can exercise the whole validation
contract without standing up a server (spec.md US3 AS2 is a *server-side*
guarantee, so it has to be testable server-side).

Constitution Principle III, planned in rather than retrofitted: this module
defines the complete set of fields a booking may carry, and none of them is
a payment instrument. `FIELDS` is the allowlist -- `normalise()` drops
everything else, so a card number typed into a tampered form is discarded
here, at the boundary, and can never reach a session record, a log line or
an OTel span. M4b's checkout is the only place payment is even modelled,
and it keeps nothing either.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any, Optional

# The one place the form's shape is defined. The MCP App's HTML renders
# these, the server validates these, and anything else submitted is dropped.
# (label, required) -- label is what an error message names, so it is the
# user-facing wording rather than the field key.
FIELDS: dict[str, tuple[str, bool]] = {
    "full_name": ("Full name", True),
    "email": ("Email address", True),
    "phone": ("Phone number", True),
    "pickup_date": ("Pickup date", True),
    "notes": ("Notes", False),
}

REQUIRED_FIELDS = [name for name, (_, required) in FIELDS.items() if required]

# Deliberately loose. This is a demo booking form, and an over-strict
# pattern that rejects a judge's real address mid-demo is a worse failure
# than one that accepts an odd-looking address: the value is never used to
# send anything. It only has to catch "obviously not an email".
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Digits, with the punctuation people actually type. Counted after
# stripping, so "+1 (555) 010-9999" passes and "12" does not.
_PHONE_DIGITS = re.compile(r"\d")

BOOKING_ID_PREFIX = "BKG-"


def normalise(fields: dict[str, Any] | None) -> dict[str, str]:
    """Trim, stringify, and drop anything outside `FIELDS`.

    The allowlist is the Principle III enforcement point. It runs *before*
    validation so that an unknown field cannot survive by being valid, and
    before persistence so nothing outside this dict is ever stored.
    """
    incoming = fields or {}
    return {
        name: str(incoming.get(name, "")).strip()
        for name in FIELDS
        if str(incoming.get(name, "")).strip()
    }


def validate(
    fields: dict[str, Any] | None,
    *,
    available_from: str | None = None,
    today: date | None = None,
) -> dict[str, str]:
    """Field-name -> error message, empty when the submission is valid.

    Returns *all* problems rather than the first, because spec.md US3 AS2
    requires the iframe to surface "the specific missing field(s)" -- a
    one-error-at-a-time API would make the user resubmit once per mistake
    and would make "without losing already-entered data" pointless.

    `available_from` is the chosen car's `availability_date`. It is passed
    in rather than looked up, because this server deliberately never
    re-fetches a listing -- a second source of truth for listing values is
    exactly what Principle I's grounding channel exists to avoid, so the
    caller supplies the authoritative record (see server.py). Omitted, the
    availability rule simply does not run.

    `today` is injectable so the past-date rule is testable without
    freezing the clock or writing a test that expires.
    """
    clean = normalise(fields)
    errors: dict[str, str] = {}

    for name in REQUIRED_FIELDS:
        if not clean.get(name):
            label, _ = FIELDS[name]
            errors[name] = f"{label} is required."

    email = clean.get("email")
    if email and not _EMAIL.match(email):
        errors["email"] = "Enter an email address in the form name@example.com."

    phone = clean.get("phone")
    if phone and len(_PHONE_DIGITS.findall(phone)) < 7:
        errors["phone"] = "Enter a phone number with at least 7 digits."

    # Three separate rules, deliberately ordered cheapest-first and each
    # returning before the next can produce a confusing second message
    # about a date that could not be parsed in the first place.
    #
    # The last two were missing entirely until the M4a Phase C audit: the
    # form accepted a pickup date in the past, and a pickup date *before*
    # the car was even available -- with the availability date printed on
    # the same screen, three rows above the input. Neither is a security
    # problem; both make the demo look like nobody read the record it is
    # showing.
    pickup = clean.get("pickup_date")
    pickup_date = _parse_iso(pickup)
    if pickup and pickup_date is None:
        errors["pickup_date"] = "Enter a pickup date as YYYY-MM-DD."
    elif pickup_date is not None:
        if pickup_date < (today or date.today()):
            errors["pickup_date"] = "Choose a pickup date that is not in the past."
        else:
            available = _parse_iso(available_from)
            if available is not None and pickup_date < available:
                errors["pickup_date"] = (
                    f"This car is not available until {available.isoformat()}. "
                    "Choose that date or later."
                )

    return errors


def _parse_iso(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def new_booking_id() -> str:
    """A synthetic booking reference. Random, not derived from anything the
    user typed -- a reference that encodes personal data is a leak in a
    field that gets printed, logged and traced.
    """
    return f"{BOOKING_ID_PREFIX}{uuid.uuid4().hex[:10].upper()}"
