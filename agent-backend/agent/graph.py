"""M1 (Foundational): a minimal LangGraph app whose only purpose is to prove
cross-process persistence via SqliteSaver — the foundation US5 (Session
Resume) depends on. The real interview/research/transaction nodes land in
M2+ (see specs/001-ai-car-matchmaker/tasks.md).
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.state import SessionState


class GraphState(TypedDict):
    session: dict  # SessionState.model_dump() — dict at the graph-state
    # boundary because LangGraph's default reducer needs plain-JSON-able
    # state; SessionState is the typed view application code works with.


def _touch(state: GraphState) -> GraphState:
    """Placeholder node: M1 proves persistence, not behavior. Real phase
    nodes (interview/research/form/payment) replace this in M2-M4.
    """
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
