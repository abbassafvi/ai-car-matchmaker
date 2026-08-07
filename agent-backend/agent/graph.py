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
from agent.prompts import INTERVIEW_SYSTEM_PROMPT
from agent.state import SessionState
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


def build_interview_agent(checkpointer):
    """The real INTERVIEWING-phase agent (US1). Later phases (research,
    form-fill, payment) extend this same pattern in M3/M4 with their own
    tool sets, gated by SessionState.available_tools() per Constitution
    Principle II.
    """
    return create_deep_agent(
        model=build_model(),
        tools=[save_interview_state],
        system_prompt=INTERVIEW_SYSTEM_PROMPT,
        state_schema=CarMatchmakerState,
        checkpointer=checkpointer,
    )
