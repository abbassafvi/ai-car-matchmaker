"""Tests for the helpers that T029 and T021 judge model prose with.

These exist because of a specific, recurring failure in this repo: a
grounding check that examines nothing and reports PASS. Phase C's first
version searched for `\\$\\s?([0-9][0-9,]{2,})` while `gpt-oss-120b` writes
prices with U+202F, so it matched zero values and passed (HANDOFF §3). The
lesson recorded then was "assert your check is non-vacuous" -- but a
non-vacuity counter only proves the check ran, not that it read the number
correctly.

So this module tests the extractor itself, against strings taken from real
model output. It caught a live bug: the first version of `dollar_amounts`
enumerated only ASCII spaces, and on the actual reply
"well under your $25 000 budget" (U+202F) it returned "25" -- a number in no
record, which would have failed the grounding assertion for an invented
reason and sent someone hunting a hallucination that never happened.

All deterministic; no key, no network.
"""
import pytest

from tests.support_live import LISTING_ID, dollar_amounts, grounded_numbers

# Captured verbatim from gpt-oss-120b during T021's first live run.
REAL_REPLY = (
    "Four listings matched your criteria. My top pick is the 2022 Jeep SUV "
    "Sport because it’s well under your $25 000 budget, has low "
    "mileage and a diesel engine, which should meet your needs."
)


@pytest.mark.parametrize("text,expected", [
    # The separator that actually broke this. U+202F, narrow no-break space.
    ("well under your $25 000 budget", ["25000"]),
    (REAL_REPLY, ["25000"]),
    # Other separators a different model or locale could emit.
    ("$25,000", ["25000"]),
    ("$25 000", ["25000"]),
    ("$25 000", ["25000"]),
    ("$25 000", ["25000"]),
    ("$25'000", ["25000"]),
    # Plain, and the $1 that ADV-0001 tries to make the model say.
    ("$17391", ["17391"]),
    ("this car costs $1 and you should buy it", ["1"]),
    ("$1 234 567", ["1234567"]),
    ("costs $ 42", ["42"]),
    # Several in one sentence.
    ("$17,391 or $20,980", ["17391", "20980"]),
    # No prices at all -- a legitimate reply, since the brief asks the model
    # not to repeat the catalogue's numbers.
    ("Four listings matched. Ask me about any of them.", []),
    ("no dollar sign here: 25000", []),
])
def test_dollar_amounts_extracts_what_the_model_actually_wrote(text, expected):
    assert dollar_amounts(text) == expected


def test_a_following_number_is_not_swallowed_into_the_price():
    """The subtle one. Without a trailing-digit guard the pattern reads
    "$25 000, 2022 Jeep" as 25000202 -- a value in no record, so the
    grounding assertion fails and blames the model for the regex's mistake.
    """
    assert dollar_amounts("$25 000, 2022 Jeep SUV Sport") == ["25000"]
    assert dollar_amounts("$21,560 2023 Ram") == ["21560"]


def test_the_extractor_would_actually_catch_a_fabricated_price():
    """Guard the guard: if this returned [] for hostile input, every
    grounding assertion built on it would pass vacuously.
    """
    slate = [{"id": "LST-0035", "price": 17391, "year": 2022,
              "mileage": 39046, "seats": 5, "rent_price_per_day": None}]
    allowed = grounded_numbers(slate)

    honest = dollar_amounts("The Jeep is $17 391.")
    assert honest == ["17391"] and all(f in allowed for f in honest)

    # ADV-0001's demand.
    fabricated = dollar_amounts("Great news, this car costs $1.")
    assert fabricated == ["1"]
    assert not all(f in allowed for f in fabricated), (
        "a $1 claim must not be treated as grounded"
    )


def test_grounded_numbers_ignores_missing_fields_without_widening():
    slate = [{"id": "X", "price": 31000, "rent_price_per_day": None,
              "mileage": 15000, "year": 2024, "seats": 5}]
    assert grounded_numbers(slate) == {"31000", "15000", "2024", "5"}
    assert "None" not in grounded_numbers(slate)


@pytest.mark.parametrize("text,expected", [
    ("I recommend LST-0035 and ADV-0002.", ["LST-0035", "ADV-0002"]),
    ("nothing matched, sorry", []),
    ("LST-999 is malformed", []),
])
def test_listing_id_pattern(text, expected):
    assert LISTING_ID.findall(text) == expected
