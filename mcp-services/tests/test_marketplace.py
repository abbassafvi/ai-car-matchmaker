"""T020 — the hard-filter contract (spec.md US2 AS1).

These run against the real committed dataset, not fixtures, because the
dataset is what the MCP server actually serves and a separate test already
guards it against generator drift. A filter bug that only shows up on real
data is exactly the kind this milestone must not ship.
"""
import pytest

from marketplace import store

ALL = store.load_listings()


def test_dataset_loads_and_is_the_committed_one():
    assert len(ALL) == 203
    assert sum(1 for listing in ALL if listing["id"].startswith("ADV-")) == 3


# --- category ---------------------------------------------------------

def test_category_filter_is_exact():
    hits = store.search(category="SUV", limit=500)
    assert hits, "expected SUV listings in the dataset"
    assert {listing["category"] for listing in hits} == {"SUV"}


# --- budget -----------------------------------------------------------

def test_budget_max_excludes_over_budget_listings():
    hits = store.search(category="SUV", budget_max=30_000, transaction_type="buy", limit=500)
    assert hits
    assert all(listing["price"] <= 30_000 for listing in hits)


def test_budget_min_and_max_bracket_the_results():
    hits = store.search(budget_min=20_000, budget_max=25_000, transaction_type="buy", limit=500)
    assert hits
    assert all(20_000 <= listing["price"] <= 25_000 for listing in hits)


def test_rental_budget_is_compared_against_the_daily_rate_not_the_sale_price():
    """A $120 budget means $120/day for a rental enquiry. Comparing it to
    the sale price would return nothing at all and send the agent into a
    pointless relaxation loop.
    """
    hits = store.search(transaction_type="rent", budget_max=120, limit=500)
    assert hits, "a $120/day rental budget should match something"
    assert all(listing["rent_price_per_day"] <= 120 for listing in hits)
    # ...and it is genuinely selecting on the daily rate: plenty of these
    # cars have a sale price far above 120.
    assert any(listing["price"] > 120 for listing in hits)


# --- transaction type -------------------------------------------------

def test_buy_matches_buy_and_both_but_never_rent_only():
    hits = store.search(transaction_type="buy", limit=500)
    assert hits
    assert {listing["transaction_type"] for listing in hits} <= {"buy", "both"}


def test_rent_matches_rent_and_both_but_never_buy_only():
    hits = store.search(transaction_type="rent", limit=500)
    assert hits
    assert {listing["transaction_type"] for listing in hits} <= {"rent", "both"}


def test_both_as_a_request_excludes_nothing_on_transaction_type():
    assert len(store.search(transaction_type="both", limit=500)) == len(store.search(limit=500))


# --- availability -----------------------------------------------------

def test_availability_excludes_listings_that_arrive_after_the_target_date():
    hits = store.search(available_by="2026-09-01", limit=500)
    assert hits
    assert all(listing["availability_date"] <= "2026-09-01" for listing in hits)


def test_unparseable_target_date_skips_the_availability_filter():
    """The interview passes through whatever the user said when it cannot
    infer a real date. That must not silently empty the result set.
    """
    loose = store.search(category="SUV", available_by="next month", limit=500)
    unfiltered = store.search(category="SUV", limit=500)
    assert loose == unfiltered


# --- combined, per spec.md US2 AS1 ------------------------------------

def test_all_hard_filters_together_match_the_acceptance_scenario():
    hits = store.search(
        category="SUV", budget_max=25_000, transaction_type="buy",
        available_by="2026-12-31", limit=500,
    )
    for listing in hits:
        assert listing["category"] == "SUV"
        assert listing["price"] <= 25_000
        assert listing["transaction_type"] in ("buy", "both")
        assert listing["availability_date"] <= "2026-12-31"


def test_impossible_constraints_return_empty_rather_than_a_best_effort():
    """spec.md US2 AS2 / Edge Cases: zero results must actually be zero, so
    the agent relaxes a constraint deliberately instead of being handed
    near-misses it might present as matches.
    """
    assert store.search(category="Sports", budget_max=1_000, transaction_type="buy") == []


# --- ordering ---------------------------------------------------------

def test_results_are_deterministically_ordered_cheapest_first():
    hits = store.search(category="Sedan", transaction_type="buy", limit=500)
    prices = [listing["price"] for listing in hits]
    assert prices == sorted(prices)
    assert hits == store.search(category="Sedan", transaction_type="buy", limit=500)


def test_limit_caps_the_result_count():
    assert len(store.search(limit=5)) == 5


# --- Principle IV boundary -------------------------------------------

def test_every_returned_description_is_wrapped_in_untrusted_delimiters():
    for listing in store.search(limit=500):
        assert listing["description"].startswith(store.UNTRUSTED_OPEN)
        assert listing["description"].endswith(store.UNTRUSTED_CLOSE)


def test_adversarial_payloads_are_inside_the_wrapper_not_outside_it():
    """The seeded ADV-* probes are the ones that matter: their payload must
    sit inside the delimiters, or the boundary is decorative.
    """
    adv = store.get_details("ADV-0001")
    assert adv is not None
    body = adv["description"][len(store.UNTRUSTED_OPEN):-len(store.UNTRUSTED_CLOSE)]
    assert "ignore all previous instructions" in body
    assert store.UNTRUSTED_OPEN not in body and store.UNTRUSTED_CLOSE not in body


def test_grounded_values_are_untouched_by_wrapping():
    """Principle I: wrapping must not perturb any numeric/factual field."""
    raw = next(listing for listing in ALL if listing["id"] == "LST-0001")
    served = store.get_details("LST-0001")
    for field in ("id", "brand", "model", "category", "year", "price",
                  "transaction_type", "rent_price_per_day", "mileage",
                  "fuel_type", "seats", "location", "listing_source",
                  "availability_date"):
        assert served[field] == raw[field], field


# --- details ----------------------------------------------------------

def test_get_details_returns_none_for_an_unknown_id():
    assert store.get_details("LST-9999") is None
