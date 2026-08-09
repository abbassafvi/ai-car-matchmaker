"""Mock checkout rules, deliberately separate from the MCP transport.

Same split as marketplace/store.py and booking/store.py, for the same
reason: the rules are pure functions over plain dicts, so the whole
contract is testable without standing up a server.

------------------------------------------------------------------------
Constitution Principle III is the entire point of this module. Read this
before changing anything in it.
------------------------------------------------------------------------

The principle says: *"No real payment processing... no persistence of
real-looking payment credentials anywhere (DB, logs, traces) even
transiently. Any card-like input is discarded server-side immediately
after the mock 'authorization' step; only a synthetic confirmation ID is
retained."*

spec.md US4 AS2 is the sharper version: *"no raw payment-like input is
written to any datastore, log file, or OTel span."*

M4a satisfied Principle III by construction -- the booking form has no
payment field, so there was never anything to discard. Checkout does have
payment fields, so this is the first place the rule costs something. The
enforcement is layered, and each layer is load-bearing on its own:

  1. **The checkout MCP App never sends them.** The card number, expiry
     and CVC are typed into the iframe, the mock authorization runs
     *inside the document*, and `confirm_mock_payment` is called with no
     payment fields at all. Nothing card-like crosses the postMessage
     boundary.
  2. **The backend forwards nothing from the browser.** `booking_id`
     comes from persisted session state, not from the App's message, so
     even a tampered or compromised App has no channel into the
     `call_structured` hop -- which matters specifically because that hop
     is an instrumented `StructuredTool.ainvoke`, i.e. the one place a
     value could land in an OTel span (US4 AS2's third prohibition).
  3. **This allowlist**, which is what you are reading. It is the layer
     that survives the other two being bypassed -- `/payment/mcp` is a
     real MCP endpoint on the compose network, and a client that is not
     our App can call `confirm_mock_payment` with whatever it likes.

`PAYMENT_FIELDS` is **empty on purpose**, and that is a stronger statement
than a carefully-curated list would be: *no field submitted through
checkout is ever retained, whatever it is called*. There is no
"instrument" field to forget to exclude, because there is no retained
field at all. The confirmation record is built entirely from a synthetic
id, a synthetic code, and the `booking_id` the caller already had.

Anything tempted to add an entry here should first check
`test_payment.py::test_no_payment_instrument_field_can_be_added_to_the_allowlist`,
which exists to make that a deliberate, visible act rather than a
one-line drive-by.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# The allowlist. Empty by design -- see the module docstring.
#
# Same shape as booking/store.py's FIELDS ({name: (label, required)}) so
# the two read as the same mechanism rather than two different ideas, and
# so `normalise()` below is recognisably the same function.
PAYMENT_FIELDS: dict[str, tuple[str, bool]] = {}

# Field names that must never appear in `PAYMENT_FIELDS`, checked by a
# test rather than by convention. Not a runtime filter -- `normalise()`
# already drops everything, so this catches the *future* edit that adds an
# allowlist entry, which is the only way the guarantee above can regress.
FORBIDDEN_FIELD_HINTS = (
    "card", "pan", "cvv", "cvc", "csc", "expiry", "exp_month", "exp_year",
    "security_code", "account_number", "routing", "iban", "sort_code", "track",
)

CONFIRMATION_ID_PREFIX = "PMT-"
CONFIRMATION_CODE_GROUPS = 3
CONFIRMATION_CODE_GROUP_LEN = 4

# Ambiguous glyphs removed: a confirmation code is read aloud and retyped
# during a demo, and "is that a zero or an O" is a bad thirty seconds.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

MOCK_STATUS = "MOCK_CONFIRMED"


def normalise(fields: dict[str, Any] | None) -> dict[str, str]:
    """Trim, stringify, and drop anything outside `PAYMENT_FIELDS`.

    With an empty allowlist this always returns `{}`, which is the point:
    a card number submitted straight to this MCP server by something that
    is not our App is discarded here, at the boundary, before validation
    and before anything is built from it.

    Written as the general allowlist filter rather than as `return {}` on
    purpose. The two are equivalent today, and only one of them stays
    correct if someone adds a field -- and `return {}` would make the
    allowlist a comment instead of a mechanism.
    """
    incoming = fields or {}
    return {
        name: str(incoming.get(name, "")).strip()
        for name in PAYMENT_FIELDS
        if str(incoming.get(name, "")).strip()
    }


def validate(booking_id: str | None) -> dict[str, str]:
    """Field-name -> error message, empty when the request is valid.

    Deliberately thin compared to `booking/store.py::validate`, and for a
    structural reason rather than laziness: the booking form's inputs are
    the *user's* free text, so almost everything there needs checking,
    whereas everything this tool acts on is supplied by the backend from
    persisted state. The only thing that can be wrong is a missing
    `booking_id`, and that is a caller bug rather than a user mistake.

    Returns a dict rather than raising, matching `submit_booking`'s
    contract: an MCP error would collapse to "something went wrong" in the
    iframe and lose the context (spec.md US3 AS2's reasoning, which
    applies to any App-facing tool).
    """
    errors: dict[str, str] = {}
    if not (booking_id or "").strip():
        errors["booking_id"] = "A booking reference is required before payment."
    return errors


def authorise(fields: dict[str, Any] | None = None) -> bool:
    """The mock "authorization" step Constitution Principle III names.

    It always approves, and it **reads nothing**. Both properties are
    deliberate:

    - *Always approves* because there is no real gateway and inventing a
      decline path would mean inventing a reason, which is a fabricated
      value on a screen (Principle I) dressed up as realism.
    - *Reads nothing* because the moment this function inspects a card
      number, that number is a live local, one traceback away from a log
      line. The principle allows card-like input to be discarded
      immediately *after* authorization; this design never lets it arrive,
      which is strictly stronger and considerably easier to prove.

    `fields` is accepted and ignored so the signature documents the
    boundary rather than hiding it -- a reader asking "where does the card
    number go?" finds the answer here instead of finding no mention of it.
    """
    return True


def new_confirmation_id() -> str:
    """Synthetic internal id for the confirmation record.

    Random, not derived from the booking, the listing or anything the user
    typed: an identifier that encodes personal or payment data is a leak in
    a field that gets printed, logged and traced. Same rule as
    `booking/store.py::new_booking_id`.
    """
    return f"{CONFIRMATION_ID_PREFIX}{uuid.uuid4().hex[:10].upper()}"


def new_confirmation_code() -> str:
    """The human-readable code the user is told to quote.

    `secrets` rather than `random`: this is the only value standing in for
    "proof the transaction happened", and a predictable one would make the
    mock misleading about the shape of the real thing even though nothing
    is at stake.
    """
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CONFIRMATION_CODE_GROUP_LEN))
        for _ in range(CONFIRMATION_CODE_GROUPS)
    ]
    return "-".join(groups)


def new_confirmation(
    booking_id: str,
    *,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """The whole retained record -- spec.md's `PaymentConfirmation` entity.

    Five fields, and the entity description in spec.md spells out why the
    sixth does not exist: *"explicitly no payment instrument fields"*. It
    is built here rather than in `server.py` so that the complete set of
    things this system keeps about a payment is defined in one readable
    place, next to the allowlist that keeps everything else out.

    `now` is injectable so `created_at` is assertable without freezing the
    clock, the same reason `booking/store.py::validate` takes `today`.
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "id": new_confirmation_id(),
        "booking_id": booking_id,
        "confirmation_code": new_confirmation_code(),
        "status": MOCK_STATUS,
        # Explicit "+00:00" rather than a bare "Z": `datetime.fromisoformat`
        # only learned to parse "Z" in 3.11, and the agent-backend side
        # round-trips this through pydantic.
        "created_at": stamp.isoformat(),
    }


_CARD_LIKE = re.compile(r"(?:\d[ -]?){13,19}")


def looks_like_a_card_number(text: str) -> bool:
    """True if `text` contains a run of 13-19 digits (spaces/dashes ok).

    A test helper that lives in production code on purpose: it is the
    definition T036 asserts against, and a definition that lives only in a
    test file is one the next person writes a second, differently-wrong
    copy of. §3 lesson 15 -- test the test's parser -- applies directly,
    so `test_payment.py` exercises this against real card-shaped strings
    and real non-card strings before relying on it.
    """
    return _CARD_LIKE.search(text or "") is not None
