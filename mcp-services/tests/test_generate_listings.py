"""FR-011 / SC-006: the generated mock dataset must contain >=100 listings
across >=10 categories with >=10 distinct brands represented per category,
on every run — not just the one currently checked in.
"""
import json
from collections import defaultdict
from pathlib import Path

from data.generate_listings import CATEGORIES, generate


def test_minimum_listing_count():
    listings = generate()
    assert len(listings) >= 100


def test_minimum_category_count():
    listings = generate()
    assert len(set(l["category"] for l in listings)) >= 10
    assert len(CATEGORIES) >= 10


def test_minimum_brands_per_category():
    listings = generate()
    brands_by_category: dict[str, set[str]] = defaultdict(set)
    for listing in listings:
        brands_by_category[listing["category"]].add(listing["brand"])

    assert len(brands_by_category) >= 10
    for category, brands in brands_by_category.items():
        assert len(brands) >= 10, f"{category} only has {len(brands)} distinct brands"


def test_deterministic_across_runs():
    assert generate() == generate()


def test_ids_are_unique():
    listings = generate()
    ids = [l["id"] for l in listings]
    assert len(ids) == len(set(ids))


def test_required_fields_present_and_valid():
    required_fields = {
        "id", "brand", "model", "category", "year", "price",
        "transaction_type", "rent_price_per_day", "mileage", "fuel_type",
        "seats", "location", "description", "listing_source",
        "availability_date",
    }
    for listing in generate():
        assert required_fields.issubset(listing.keys())
        assert listing["price"] > 0
        assert listing["transaction_type"] in ("buy", "rent", "both")
        if listing["transaction_type"] == "buy":
            assert listing["rent_price_per_day"] is None
        else:
            assert listing["rent_price_per_day"] is not None


def test_adversarial_probes_present_and_tagged():
    listings = generate()
    adversarial = [l for l in listings if l["id"].startswith("ADV-")]
    assert 2 <= len(adversarial) <= 5


def test_committed_listings_json_matches_the_generator():
    """F6: the marketplace MCP server (M3) reads listings.json from disk,
    but every other test here calls generate() in process -- so drift
    between the committed file and the generator would be invisible to the
    suite while silently changing what the agent actually searches.
    """
    committed_path = Path(__file__).resolve().parent.parent / "data" / "listings.json"
    committed = json.loads(committed_path.read_text())
    assert committed == generate(), (
        "listings.json is out of date with generate_listings.py -- "
        "re-run `python mcp-services/data/generate_listings.py` and commit."
    )
