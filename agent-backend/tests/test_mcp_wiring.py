"""T024 — marketplace tool discovery and injection into the phase gate.

The design constraint this file exists to enforce: runtime-discovered tools
are *injected* into a registry, never installed into the module-level
`TOOL_REGISTRY`. A lifespan that mutated that global would make
`test_phase_gate.py` assert one thing under pytest (where discovery never
runs) and another under the app, which is the sort of divergence that hides
a broken gate rather than exposing it.
"""
import pytest
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import TOOL_REGISTRY, PhaseAgentRegistry, resolve_registry, tools_for_phase
from agent.mcp_client import discover_marketplace_tools
from agent.state import TOOLS_BY_PHASE, Phase


@pytest.fixture(autouse=True)
def _dummy_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-dummy-not-a-real-key")


def fake_mcp_tool(name):
    """Async-only, like the real adapted MCP tools (HANDOFF §8.1)."""
    async def _run(**kwargs):
        return {}

    return StructuredTool.from_function(
        coroutine=_run, name=name, description=f"fake {name}",
        response_format="content_and_artifact",
    )


MARKETPLACE = [fake_mcp_tool("search_listings"), fake_mcp_tool("get_listing_details")]


def test_resolve_registry_does_not_mutate_the_module_level_registry():
    before = dict(TOOL_REGISTRY)
    resolved = resolve_registry(MARKETPLACE)

    assert TOOL_REGISTRY == before, "the import-time registry must stay static"
    assert "search_listings" in resolved
    assert "search_listings" not in TOOL_REGISTRY


def test_resolve_registry_keeps_the_locally_defined_tools():
    resolved = resolve_registry(MARKETPLACE)
    assert "save_interview_state" in resolved


def test_injected_tools_resolve_for_the_phases_the_gate_names_them_for():
    resolved = resolve_registry(MARKETPLACE)

    researching = {t.name for t in tools_for_phase(Phase.RESEARCHING, resolved)}
    assert researching == {"search_listings", "get_listing_details"}

    results_ready = {t.name for t in tools_for_phase(Phase.RESULTS_READY, resolved)}
    # select_listing landed in Phase E (T028b); before that it was named by
    # the gate and resolved to nothing, which this assertion used to record.
    #
    # `search_listings` came *out* of RESULTS_READY in M4a Phase C. The
    # model could call it there, but nothing writes `candidate_listings`
    # outside a research pass -- so it would find a car, describe it, the
    # user would say "that one", and `select_listing` would refuse it as
    # not being in the current slate. Reproduced before the change:
    # "'LST-0099' is not in the current candidate slate (LST-0001,
    # LST-0002)". `refine_search` replaces it with a path that updates the
    # slate. `refine_search` itself is absent here because this registry is
    # built from raw marketplace tools only -- it is a local wrapper from
    # `tools.build_research_tools`, which is the point: the gate names it,
    # and a name the registry cannot resolve is simply not bound.
    assert results_ready == {"get_listing_details", "select_listing", "save_interview_state"}
    assert "search_listings" not in results_ready


def test_injection_cannot_widen_the_gate():
    """The gate table decides which *names* are permitted; injection only
    decides whether a permitted name resolves to an object. A discovered
    tool the gate never named must not become callable anywhere.
    """
    resolved = resolve_registry(MARKETPLACE + [fake_mcp_tool("delete_everything")])

    for phase in Phase:
        bound = {t.name for t in tools_for_phase(phase, resolved)}
        assert "delete_everything" not in bound
        assert bound <= set(TOOLS_BY_PHASE[phase])


def test_interviewing_never_sees_the_marketplace_tools():
    """Principle II: search is not reachable before the interview completes."""
    resolved = resolve_registry(MARKETPLACE)
    bound = {t.name for t in tools_for_phase(Phase.INTERVIEWING, resolved)}
    assert bound == {"save_interview_state"}


def test_registry_binds_injected_tools_onto_the_real_agents():
    """End of the chain: the tools reach an actually-compiled agent, not
    just a dict. Checked against the agent's own bound tool names.
    """
    registry = PhaseAgentRegistry(InMemorySaver(), extra_tools=MARKETPLACE)

    researching = set(registry.for_phase(Phase.RESEARCHING).nodes["tools"].bound.tools_by_name)
    assert {"search_listings", "get_listing_details"} <= researching

    interviewing = set(registry.for_phase(Phase.INTERVIEWING).nodes["tools"].bound.tools_by_name)
    assert "search_listings" not in interviewing


def test_registry_without_marketplace_tools_still_builds_every_phase():
    """Fail-soft: mcp-services being down degrades research, it does not
    stop the backend from serving the interview.
    """
    registry = PhaseAgentRegistry(InMemorySaver(), extra_tools=[])
    for phase in Phase:
        assert registry.for_phase(phase) is not None
    assert registry.tool_names() == set(TOOL_REGISTRY)


@pytest.mark.asyncio
async def test_discovery_returns_empty_instead_of_raising_when_unreachable():
    """Nothing listens on port 9 (the discard protocol), so this exercises
    the real failure path rather than a mocked one.
    """
    assert await discover_marketplace_tools("http://127.0.0.1:9/mcp") == []
