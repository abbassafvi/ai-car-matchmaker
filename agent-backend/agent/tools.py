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

# What users say, mapped onto the three values `TransactionType` accepts.
#
# `transaction_type` is a strict enum, so anything else raised
# `ValidationError` straight out of this tool -- and a tool that raises
# aborts the whole agent turn (the model never sees the exception), which
# the user meets as "Something went wrong processing that message." The
# reachable triggers were not exotic: "I want to lease a car" produced
# `lease`, and a capitalised `Buy` was enough on its own.
#
# Financing and leasing are genuinely not supported by the marketplace
# (a listing is `buy`, `rent` or `both`), so they are mapped to their
# nearest honest neighbour and the model is told to say so -- see the
# unmapped branch in `_coerce_transaction_type`.
_TRANSACTION_SYNONYMS = {
    "buy": "buy", "purchase": "buy", "purchasing": "buy", "own": "buy",
    "buying": "buy", "finance": "buy", "financing": "buy",
    "rent": "rent", "rental": "rent", "renting": "rent", "hire": "rent",
    "lease": "rent", "leasing": "rent", "subscription": "rent",
    "both": "both", "either": "both", "any": "both",
    "buy or rent": "both", "rent or buy": "both",
}


# The price basis a user's own word implies for any budget they state in the
# same breath -- which is NOT always the basis of the value we map it to.
#
# "Lease" is the case that matters. It maps to `rent`, because a rental is
# the closest thing this marketplace offers. But someone who says "lease a
# Sedan under $30,000" is quoting a total commitment, not a day rate: read
# as a daily budget, $30,000 excludes nothing at all, so an explicitly
# stated constraint silently becomes no constraint. The mapped *value* and
# the basis of the *number beside it* have to be tracked separately.
_BUDGET_BASIS_OF_WORD = {
    "rent": "rent", "rental": "rent", "renting": "rent", "hire": "rent",
}


def _coerce_transaction_type(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """`(value_to_store, note_for_the_model)`.

    Returns the value unchanged when it is already one of the three, a
    mapped value plus a note when it is a recognisable paraphrase, and
    `(None, note)` when it is not recognisable at all -- leaving the slot
    unset so the interview asks again, rather than storing a value that
    would search for something the user did not ask for.
    """
    if value is None:
        return None, None
    key = str(value).strip().lower()
    if key in ("buy", "rent", "both"):
        return key, None
    mapped = _TRANSACTION_SYNONYMS.get(key)
    if mapped is None:
        return None, (
            f"'{value}' is not a transaction type this marketplace supports. "
            "Ask the user whether they want to buy, rent, or are open to both."
        )
    if mapped != key:
        units = "a per-day rate" if mapped == "rent" else "a purchase price"
        return mapped, (
            f"This marketplace does not offer {value}. Tell the user that "
            f"plainly, in your own words, and say you are searching {mapped} "
            f"listings instead — do not present {mapped} as though it were "
            f"what they asked for. Note that a budget for {mapped} is "
            f"{units}, so if they gave a budget for something else, ask again "
            f"in those units."
        )
    return mapped, None


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
    stated_word = (transaction_type or "").strip().lower()
    transaction_type, note = _coerce_transaction_type(transaction_type)

    # A budget quoted alongside a *coerced* transaction type belongs to the
    # basis of the word the user actually used, not the one we mapped it to.
    # "Lease a Sedan under $30,000" arrives as one call: mapped to `rent`,
    # the $30,000 would be recorded as a per-day rate and would exclude
    # nothing. Dropping it here puts budget_max back in `missing_slots()`, so
    # the interview asks for a daily figure instead of inventing one.
    from agent.state import budget_basis_for

    budget_reset = False
    if budget_max is not None and transaction_type is not None:
        stated_basis = _BUDGET_BASIS_OF_WORD.get(stated_word, "buy")
        if stated_basis != budget_basis_for(transaction_type):
            budget_max = None
            budget_min = None
            budget_reset = True

    try:
        session.save_interview_slots(
            use_case=use_case,
            category=category,
            budget_min=budget_min,
            budget_max=budget_max,
            transaction_type=transaction_type,
            target_date=target_date,
            location=location,
        )
    except Exception as exc:
        # A tool that raises aborts the turn and strands the user with a
        # generic error, so anything the schema still refuses comes back as
        # an ordinary ToolMessage the model can act on -- the same contract
        # `select_listing` and `open_booking_form` already use.
        return Command(update={"messages": [ToolMessage(
            f"Could not save those details: {exc} Ask the user to restate the "
            "value in plainer terms, then call this tool again.",
            tool_call_id=tool_call_id,
        )]})
    parts = ["Interview state saved."]
    if note:
        parts.append(note)
    if budget_reset:
        units = "per day" if session.interview.transaction_type \
            and session.interview.transaction_type.value == "rent" else "in total"
        parts.append(
            "Their budget was not recorded, because the figure they gave was "
            f"for a different kind of transaction. Ask what they want to spend "
            f"{units}, and do not search until they answer."
        )
    return Command(update={
        "session": session.model_dump(mode="json"),
        "messages": [ToolMessage(" ".join(parts), tool_call_id=tool_call_id)],
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

# Named here beside its sibling, but deliberately never wrapped and never
# bound: `submit_booking` is not a model tool in any phase. The name exists
# so `api/main.py`'s MCP App bridge -- the only caller -- does not spell it
# as a string literal, and so a reader of this module sees both halves of
# the booking server and the asymmetry between them.
SUBMIT_BOOKING_TOOL = "submit_booking"

OPEN_MOCK_CHECKOUT_TOOL = "open_mock_checkout"

# The payment server's other half, named and deliberately never wrapped
# and never bound. `confirm_mock_payment` is not a model tool in any
# phase, for a sharper reason than `submit_booking`: its arguments would
# be card-like, and a model tool's arguments are written into the message
# history, checkpointed, and traced -- the three places spec.md US4 AS2
# forbids. Only the MCP App bridge in `api/main.py` calls it, and it
# forwards nothing the browser sent.
CONFIRM_MOCK_PAYMENT_TOOL = "confirm_mock_payment"


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


def build_checkout_tools(payment_mcp_tools: list) -> list:
    """Model-facing checkout tools, closed over the discovered MCP tools.

    The booking pattern, second instance. Returns `[]` when the payment
    server was unreachable at startup, which leaves AWAITING_PAYMENT with
    no `open_mock_checkout` to bind -- fail-soft, like every other
    downstream here.

    The raw `open_mock_checkout` takes `{booking, listing}` **required**:
    the model would retype the record *and the price it is about to
    charge*. That is Principle I inverted in the one surface where a
    wrong number is least forgivable, so the wrapper takes **no
    model-supplied arguments at all** and reads both records from
    persisted state.

    `confirm_mock_payment` is deliberately not wrapped and not returned.
    """
    open_checkout_mcp = next(
        (t for t in payment_mcp_tools if t.name == OPEN_MOCK_CHECKOUT_TOOL), None
    )
    if open_checkout_mcp is None:
        return []

    @tool
    async def open_mock_checkout(
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None,
    ) -> Command:
        """Show the mock checkout for the booking the user has submitted.

        Takes no arguments -- it always opens checkout for this session's
        booking and fills in the car and amount itself. Call it when the
        user is ready to pay, or asks to see the checkout again.
        """
        from agent.mcp_client import call_structured

        session = SessionState.model_validate(state["session"])
        listing = session.selected_listing()
        booking = session.booking

        if booking is None or booking.status != "SUBMITTED" or listing is None:
            # An ordinary ToolMessage, not an exception: per §8.7a the
            # model would never see the exception, and it can recover by
            # telling the user to finish the booking form first.
            return Command(update={"messages": [ToolMessage(
                "There is no submitted booking yet, so there is nothing to pay "
                "for. Tell the user to complete and submit the booking form "
                "first -- do not ask them for payment details.",
                tool_call_id=tool_call_id,
            )]})

        # Both verbatim records go to the server, not through the model.
        # The server echoes back only its display projections, which drop
        # the attacker-controlled `description` and the user's contact
        # details before either can reach the iframe.
        payload = await call_structured(
            open_checkout_mcp,
            {"booking": booking.model_dump(mode="json"), "listing": listing},
        )

        session.checkout_requests += 1
        return Command(update={
            "session": session.model_dump(mode="json"),
            "messages": [ToolMessage(
                f"The mock checkout for booking {booking.id} is now open in the "
                f"chat. Tell the user to complete it there. It is clearly "
                f"labelled as a mock and takes no real payment. Do NOT ask them "
                f"for card details in the chat -- the checkout collects those "
                f"and discards them.",
                tool_call_id=tool_call_id,
                artifact={"open_mock_checkout": payload},
            )],
        })

    return [open_mock_checkout]


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
        # Same coercion as `save_interview_state`, for the same reason: this
        # is the second door into the same strict enum.
        coerced, note = _coerce_transaction_type(transaction_type)
        had_budget = session.interview.budget_max is not None
        try:
            session.save_interview_slots(
                use_case=use_case,
                category=category,
                budget_min=budget_min,
                budget_max=budget_max,
                transaction_type=coerced,
                target_date=target_date,
            )
        except Exception as exc:
            return Command(update={"messages": [ToolMessage(
                f"Could not apply those changes: {exc} Ask the user to restate "
                "what they want changed. The previous recommendations are "
                "still on screen.",
                tool_call_id=tool_call_id,
            )]})

        # Switching between buying and renting drops a budget that was
        # stated in the other basis (see `SessionState.save_interview_slots`).
        # Searching anyway would run with no ceiling at all and return a
        # slate the user would read as "these fit my budget", so ask first.
        if had_budget and session.interview.budget_max is None:
            units = (
                "per day" if session.interview.transaction_type
                and session.interview.transaction_type.value == "rent"
                else "in total"
            )
            return Command(update={
                "session": session.model_dump(mode="json"),
                "messages": [ToolMessage(
                    f"{note + ' ' if note else ''}Their previous budget was for "
                    f"the other kind of transaction, so it no longer applies. "
                    f"Ask the user what they want to spend {units}, then call "
                    f"this tool again with the new budget_max. Do not search "
                    f"until they answer. The previous recommendations are "
                    f"still on screen.",
                    tool_call_id=tool_call_id,
                )],
            })

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


def build_runtime_tools(
    marketplace_tools: list, booking_tools: list, payment_tools: list | None = None
) -> list:
    """Every tool that had to wait for MCP discovery, ready for
    `PhaseAgentRegistry(extra_tools=...)`.

    The marketplace tools are passed through as-is (they are model-facing
    by design and the gate names them for RESEARCHING). The booking and
    payment tools are **not** -- only the wrappers built from them are.
    See `build_booking_tools` / `build_checkout_tools`.

    `payment_tools` defaults to `None` rather than being required so the
    M4a-era two-argument call sites keep working; every production caller
    passes all three.
    """
    return [
        *marketplace_tools,
        *build_research_tools(marketplace_tools),
        *build_booking_tools(booking_tools),
        *build_checkout_tools(payment_tools or []),
    ]
