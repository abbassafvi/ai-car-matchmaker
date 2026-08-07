"""LangGraph app. `compiled_graph`/`GraphState`/`build_graph` are the
minimal M1 scaffold that proves cross-process persistence via SqliteSaver
(kept as-is — test_graph_persistence.py depends on this exact shape, and a
fast, LLM-free graph is the right tool for testing the persistence layer in
isolation). `build_interview_agent` (M2) is the real DeepAgents-based agent
that actually runs the interview phase.
"""
from __future__ import annotations

from typing import TypedDict

from deepagents import create_deep_agent
from deepagents.graph import DeepAgentState
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.llm import build_model
from agent.prompts import PHASE_SYSTEM_PROMPTS
from agent.state import Phase, SessionState, tool_names_for_phase
from agent.tools import save_interview_state


class GraphState(TypedDict):
    session: dict  # SessionState.model_dump() — dict at the graph-state
    # boundary because LangGraph's default reducer needs plain-JSON-able
    # state; SessionState is the typed view application code works with.


def _touch(state: GraphState) -> GraphState:
    """Placeholder node: proves persistence, not behavior."""
    return state


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("touch", _touch)
    graph.add_edge(START, "touch")
    graph.add_edge("touch", END)
    return graph


def compiled_graph(checkpointer):
    return build_graph().compile(checkpointer=checkpointer)


def new_session_state(session_id: str) -> dict:
    return SessionState(session_id=session_id).model_dump(mode="json")


class CarMatchmakerState(DeepAgentState):
    """DeepAgentState plus our domain SessionState, carried alongside the
    message history in the same checkpointed graph state.
    """
    session: dict


# Name -> tool object. The phase gate in agent/state.py names the tools
# allowed per phase; this maps those names onto real callables. Tools for
# phases not yet implemented (M3 search, M4 booking/payment) are simply
# absent, so those phases currently bind an empty tool set rather than
# silently exposing something they shouldn't.
TOOL_REGISTRY = {
    "save_interview_state": save_interview_state,
}


def tools_for_phase(phase: Phase) -> list:
    """Resolve the phase gate's tool *names* to bound tool objects.

    Constitution Principle II is enforced right here: a tool the gate
    doesn't list for this phase is never handed to the model, so it cannot
    be called out of order regardless of what the model or a malicious
    listing description tries to do.
    """
    return [
        TOOL_REGISTRY[name]
        for name in tool_names_for_phase(phase)
        if name in TOOL_REGISTRY
    ]


def build_agent_for_phase(phase: Phase, checkpointer, model=None):
    """Build the agent for a single phase, with only that phase's tools."""
    return create_deep_agent(
        model=model or build_model(),
        tools=tools_for_phase(phase),
        system_prompt=PHASE_SYSTEM_PROMPTS[phase],
        state_schema=CarMatchmakerState,
        checkpointer=checkpointer,
    )


class PhaseAgentRegistry:
    """One agent per phase, built lazily and cached.

    DeepAgents fixes a agent's tool set at construction time, so a single
    agent instance cannot express "different tools in different phases".
    Building one per phase is what makes the gate real. They all share the
    same model, checkpointer and state schema, so a session's message
    history and SessionState carry across phase changes untouched -- only
    the bound tools and system prompt differ.
    """

    def __init__(self, checkpointer):
        self._checkpointer = checkpointer
        self._model = build_model()
        self._agents: dict[Phase, object] = {}

    def for_phase(self, phase: Phase):
        if phase not in self._agents:
            self._agents[phase] = build_agent_for_phase(
                phase, self._checkpointer, model=self._model
            )
        return self._agents[phase]


def build_interview_agent(checkpointer):
    """The INTERVIEWING-phase agent (US1), kept as a named convenience for
    tests that exercise the interview specifically.
    """
    return build_agent_for_phase(Phase.INTERVIEWING, checkpointer)
