"""Model-facing tools. Every one of them mutates graph state rather than
just returning content, which is the LangGraph "state-updating tool"
pattern: return a Command instead of a plain value, read current state via
InjectedState, and write the required ToolMessage yourself since returning
a Command bypasses the normal auto-wrapping (verified against the installed
langgraph/langchain-core versions before writing this -- Command must carry
the ToolMessage in its `messages` update or the graph never sees a response
to the tool call).

Two of them -- `open_booking_form` and `refine_search` -- are built by
factories at the bottom of this file rather than declared at module level,
because they need MCP tools that only exist once the FastAPI lifespan has
discovered them. The factory shape is not incidental; see
`build_booking_tools` for why a closure is the safe way to do this and
injecting the raw MCP tool is not.
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


# --- tools that need runtime MCP dependencies ----------------------------
#
# Built by factories, not declared at module level, and the difference
# matters more than it looks.
#
# The obvious way to give the agent the booking server's tools is to add
# them to `PhaseAgentRegistry(extra_tools=...)` beside the marketplace
# ones. That would be a Principle I violation shipped silently.
# `graph.resolve_registry()` resolves extras *over* the local registry --
# `registry[tool.name] = tool`, extras win -- and the raw MCP
# `open_booking_form` has the schema `{listing: object}`, **required**: the
# entire record, retyped by the model as tool arguments. Injecting it would
# therefore replace anything we define under that name, and every test
# would stay green while the model hand-copied prices into a booking.
#
# So the raw MCP tools never enter the registry. They are captured in a
# closure here, and what the registry sees is a wrapper whose schema the
# model *cannot* use to launder a value: `open_booking_form` takes no
# model-supplied arguments at all. The verbatim record comes from
# `SessionState.selected_listing()`, which is what a tool call actually
# returned. Principle I stops being prompt-enforced and becomes structural.

OPEN_BOOKING_FORM_TOOL = "open_booking_form"


def build_booking_tools(booking_mcp_tools: list) -> list:
    """Model-facing booking tools, closed over the discovered MCP tools.

    Returns `[]` when the booking server was unreachable at startup, which
    leaves FORM_FILLING with no `open_booking_form` to bind. That is the
    fail-soft behaviour the rest of the stack already uses: the phase gate
    names a tool, and a name the registry cannot resolve is simply not
    bound (`graph.tools_for_phase`), so a degraded booking server produces
    an agent that cannot open a form rather than a backend that will not
    start.

    Note `submit_booking` is deliberately **not** wrapped and **not**
    returned. It is not a model tool at any phase (see `TOOLS_BY_PHASE`);
    the MCP App bridge in `api/main.py` calls it directly with the values
    the user typed into the iframe.
    """
    open_form_mcp = next(
        (t for t in booking_mcp_tools if t.name == OPEN_BOOKING_FORM_TOOL), None
    )
    if open_form_mcp is None:
        return []

    @tool
    async def open_booking_form(
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None,
    ) -> Command:
        """Show the booking form for the car the user has already chosen.

        Takes no arguments -- it always opens the form for the currently
        selected listing, and fills in that car's details itself. Call it
        when the user is ready to book, or asks to see the form again.
        """
        from agent.mcp_client import call_structured

        session = SessionState.model_validate(state["session"])
        listing = session.selected_listing()
        if listing is None:
            # An ordinary ToolMessage, not an exception: the model can
            # recover by asking which car they meant, and per §8.7a it
            # would never see the exception anyway.
            return Command(update={"messages": [ToolMessage(
                "No listing is selected yet, so there is nothing to book. Ask "
                "the user which of the recommended listings they want, then "
                "record it with select_listing first.",
                tool_call_id=tool_call_id,
            )]})

        # The verbatim record goes to the server, not through the model.
        # The server echoes back only the display-safe projection
        # (`LISTING_DISPLAY_FIELDS`), which drops the attacker-controlled
        # `description` before it can reach the iframe (Principle IV).
        payload = await call_structured(open_form_mcp, {"listing": listing})

        session.booking_form_requests += 1
        return Command(update={
            "session": session.model_dump(mode="json"),
            "messages": [ToolMessage(
                f"The booking form for {listing['id']} is now open in the chat, "
                f"pre-filled with the car's details. Tell the user to complete "
                f"and submit it there. Do not ask them for their name, email, "
                f"phone or pickup date -- the form collects those.",
                tool_call_id=tool_call_id,
                artifact={"open_booking_form": payload},
            )],
        })

    return [open_booking_form]


def build_research_tools(marketplace_tools: list) -> list:
    """`refine_search`, closed over the marketplace tools.

    This exists because there were two search paths with unequal
    privileges. The model could call `search_listings` directly in
    RESULTS_READY, but **nothing writes `candidate_listings` outside a
    research pass** -- so the model would find a car, describe it to the
    user, the user would say "that one", and `select_listing` would refuse
    it as not being in the current candidate slate. Reproduced before this
    was written: `'LST-0099' is not in the current candidate slate
    (LST-0001, LST-0002)`.

    `refine_search` closes that by making the state-updating path the only
    path: the raw `search_listings` is no longer bound after RESEARCHING,
    and this runs the same code-driven pass the first search used --
    relaxation ladder, deterministic ranking, catalogue and all -- then
    commits it through `SessionState.refine_results`.
    """
    from agent.research import SEARCH_TOOL

    if not any(t.name == SEARCH_TOOL for t in marketplace_tools):
        return []

    @tool
    async def refine_search(
        use_case: Optional[str] = None,
        category: Optional[str] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        transaction_type: Optional[str] = None,
        target_date: Optional[str] = None,
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None,
    ) -> Command:
        """Search again with changed requirements, replacing the results.

        Use this whenever the user wants different cars than the ones
        currently recommended -- a new budget, a different category, a
        different date, or "show me something cheaper". Pass only the
        fields that changed; everything else is kept.

        This replaces the recommendations on screen and clears any listing
        the user had already chosen, so do not call it to answer a question
        about the cars already shown.

        category must be one of: Sedan, SUV, Truck, Minivan, Coupe,
        Convertible, Hatchback, Electric, Luxury, Sports.
        transaction_type must be one of: buy, rent, both.
        """
        from agent.research import narration_brief, run_research

        session = SessionState.model_validate(state["session"])
        session.save_interview_slots(
            use_case=use_case,
            category=category,
            budget_min=budget_min,
            budget_max=budget_max,
            transaction_type=transaction_type,
            target_date=target_date,
        )

        outcome = await run_research(
            session.interview.model_dump(mode="json"), marketplace_tools
        )
        if outcome.error:
            # The slate is left exactly as it was: a failed refinement must
            # not throw away results the user can still act on.
            return Command(update={"messages": [ToolMessage(
                f"The search could not be run: {outcome.error} Tell the user "
                "plainly and offer to try again. The previous recommendations "
                "are still on screen.",
                tool_call_id=tool_call_id,
            )]})

        session.refine_results(outcome.listings, outcome.recommendations)

        # `narration_brief` rather than a bespoke message: it is the one
        # place that knows how to describe a search honestly, including the
        # US2 AS2 relaxation disclosure and the plain-prose rule that two
        # live defects in Phase F were needed to get right. A second
        # hand-written brief here would be a second chance to get it wrong.
        return Command(update={
            "session": session.model_dump(mode="json"),
            "messages": [ToolMessage(
                narration_brief(outcome),
                tool_call_id=tool_call_id,
                artifact={"refine_search": {
                    "listings": outcome.listings,
                    "steps": outcome.steps,
                    "step_kinds": outcome.step_kinds,
                }},
            )],
        })

    return [refine_search]


def build_runtime_tools(marketplace_tools: list, booking_tools: list) -> list:
    """Every tool that had to wait for MCP discovery, ready for
    `PhaseAgentRegistry(extra_tools=...)`.

    The marketplace tools are passed through as-is (they are model-facing
    by design and the gate names them for RESEARCHING). The booking tools
    are **not** -- only the wrapper built from them is. See
    `build_booking_tools`.
    """
    return [
        *marketplace_tools,
        *build_research_tools(marketplace_tools),
        *build_booking_tools(booking_tools),
    ]
