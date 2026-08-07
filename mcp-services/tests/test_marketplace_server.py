"""T023 — the MCP tool contract, as opposed to the query logic in T020.

Why this file exists separately: the *shape* of what comes back over MCP is
not obvious and is easy to get wrong. FastMCP places a dict return at the
top level of `structured_content` but a list return under a "result" key,
so a tool returning records bare would make the agent-side grounding
channel's shape depend on which tool was called. That was gotten wrong once
during T023 and is now pinned here, because Constitution Principle I's
whole implementation depends on reading structured tool output reliably.
"""
import asyncio

import pytest
from starlette.testclient import TestClient

from marketplace import store
from marketplace.server import app, mcp


def call(tool_name: str, **args):
    """Invoke a tool through FastMCP itself and return its structured content."""
    result = asyncio.run(mcp.call_tool(tool_name, args))
    # FastMCP returns (content_blocks, structured_content)
    return result[1] if isinstance(result, tuple) else result


def test_both_tools_are_registered():
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == {"search_listings", "get_listing_details"}


def test_search_returns_a_named_object_not_a_bare_list():
    """The uniform-shape guarantee the agent-side reader depends on."""
    out = call("search_listings", category="SUV", limit=3)
    assert set(out) == {"listings", "count", "query"}
    assert isinstance(out["listings"], list)
    assert out["count"] == len(out["listings"]) == 3


def test_details_returns_a_named_object_too():
    out = call("get_listing_details", listing_id="LST-0001")
    assert set(out) == {"listing"}
    assert out["listing"]["id"] == "LST-0001"


def test_query_echo_reports_only_the_constraints_actually_applied():
    out = call("search_listings", category="SUV", budget_max=25000, transaction_type="buy")
    assert out["query"] == {
        "category": "SUV", "budget_max": 25000, "transaction_type": "buy",
    }


def test_zero_matches_is_an_explicit_empty_result_not_an_error():
    """spec.md US2 AS2: the agent must be able to tell 'nothing matched'
    apart from 'the call failed', so it relaxes a constraint deliberately.
    """
    out = call("search_listings", category="Sports", budget_max=1000, transaction_type="buy")
    assert out["count"] == 0 and out["listings"] == []
    assert out["query"]["budget_max"] == 1000


def test_grounded_numeric_types_survive_the_tool_boundary():
    """Principle I: prices/years must arrive as numbers identical to the
    dataset's, not stringified or rounded in transit.
    """
    out = call("search_listings", category="SUV", transaction_type="buy", limit=5)
    raw = {listing["id"]: listing for listing in store.load_listings()}
    for served in out["listings"]:
        source = raw[served["id"]]
        assert served["price"] == source["price"] and isinstance(served["price"], int)
        assert served["year"] == source["year"] and isinstance(served["year"], int)
        assert served["mileage"] == source["mileage"]
        assert served["availability_date"] == source["availability_date"]


def test_unknown_listing_id_errors_instead_of_fabricating_one():
    with pytest.raises(Exception) as exc:
        call("get_listing_details", listing_id="LST-9999")
    assert "LST-9999" in str(exc.value)


def test_model_facing_text_carries_the_untrusted_wrapper():
    """The payload the model actually reads must be delimited -- checked on
    the seeded injection probe specifically (Principle IV).
    """
    out = call("get_listing_details", listing_id="ADV-0001")
    description = out["listing"]["description"]
    assert description.startswith(store.UNTRUSTED_OPEN)
    assert description.endswith(store.UNTRUSTED_CLOSE)
    assert "ignore all previous instructions" in description


def test_health_route_still_answers_for_compose_and_readme():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["listings"] == len(store.load_listings())
