"""Tools exposed to the interview-phase agent. save_interview_state needs
to mutate graph state (not just return content to the model), which is the
LangGraph "state-updating tool" pattern: return a Command instead of a
plain value, read current state via InjectedState, and write the required
ToolMessage yourself since returning a Command bypasses the normal
auto-wrapping (verified against the installed langgraph/langchain-core
versions before writing this -- Command must carry the ToolMessage in its
`messages` update or the graph never sees a response to the tool call).
"""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from agent.state import SessionState


@tool
def save_interview_state(
    use_case: Optional[str] = None,
    category: Optional[str] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    transaction_type: Optional[str] = None,
    target_date: Optional[str] = None,
    location: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Save whichever interview slots the user has just provided.

    Only pass the fields the user actually mentioned in this turn; leave
    the rest unset. Call this every time the user gives you new or changed
    information, even if it contradicts an earlier answer -- the newest
    value always overwrites the old one, it never merges or appends.

    category must be one of: Sedan, SUV, Truck, Minivan, Coupe,
    Convertible, Hatchback, Electric, Luxury, Sports.
    transaction_type must be one of: buy, rent, both.
    """
    session = SessionState.model_validate(state["session"])
    session.save_interview_slots(
        use_case=use_case,
        category=category,
        budget_min=budget_min,
        budget_max=budget_max,
        transaction_type=transaction_type,
        target_date=target_date,
        location=location,
    )
    return Command(update={
        "session": session.model_dump(mode="json"),
        "messages": [ToolMessage("Interview state saved.", tool_call_id=tool_call_id)],
    })


@tool
def select_listing(
    listing_id: str,
    state: Annotated[dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Record which listing the user has chosen, once they have picked one.

    Pass the exact listing id as shown in the recommendations (e.g.
    "LST-0035"). Only ids from the current recommendations are accepted --
    never invent one, and never guess at an id for a car the user described
    in words without checking it against the list you were given.
    """
    session = SessionState.model_validate(state["session"])

    # A rejected selection comes back as an ordinary ToolMessage rather than
    # an exception, so the model can recover by asking the user which of the
    # listings it actually showed them they meant. Raising here would abort
    # the turn and strand the user (and HANDOFF §8.7a notes the agent never
    # sees exceptions from tools anyway).
    try:
        session.select_listing(listing_id)
    except ValueError as exc:
        return Command(update={"messages": [
            ToolMessage(
                f"Could not select that listing: {exc} Ask the user which of "
                "the recommended listings they mean.",
                tool_call_id=tool_call_id,
            ),
        ]})

    listing = session.selected_listing() or {}
    return Command(update={
        "session": session.model_dump(mode="json"),
        "messages": [ToolMessage(
            f"Selected {listing_id} ({listing.get('year')} {listing.get('brand')} "
            f"{listing.get('model')}). The booking step is next.",
            tool_call_id=tool_call_id,
        )],
    })
