"""Session/interview/transaction schemas — spec.md's "Key Entities" made
concrete. These are the shapes that flow through the LangGraph checkpointer
(agent/graph.py) and that render_a2ui.py reads to build UI, never the LLM's
own words (Constitution Principle I).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from observability.spans import record_phase_transition

REQUIRED_INTERVIEW_SLOTS = ["use_case", "category", "budget_max", "transaction_type", "target_date"]


class Phase(str, Enum):
    INTERVIEWING = "INTERVIEWING"
    RESEARCHING = "RESEARCHING"
    RESULTS_READY = "RESULTS_READY"
    FORM_FILLING = "FORM_FILLING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    CONFIRMED = "CONFIRMED"


# The phase gate itself (Constitution Principle II). Module-level rather
# than a SessionState method so agent/graph.py can bind tools for a phase
# without needing a session instance -- this table is the single source of
# truth for which tools the model is even allowed to see, and graph.py
# builds its per-phase agents directly from it.
#
# Three properties of this table were decided by the M4a Phase C audit and
# are load-bearing rather than incidental:
#
# 1. **`submit_booking` is deliberately absent from FORM_FILLING.** Its MCP
#    signature takes free-form `fields`, so a model-callable version could
#    fabricate the user's name and email into a booking they never made. It
#    is reachable only through the MCP App bridge -- iframe -> host ->
#    backend -- where the values are the ones the user actually typed. A
#    name left in this table that nothing binds is exactly the hole M2.5
#    left with `select_listing`, so it is removed rather than merely unbound.
# 2. **`search_listings` is absent from RESULTS_READY.** The model could
#    call it there, but nothing writes `candidate_listings` outside
#    `record_research`/`refine_results` -- so the model would find a car,
#    describe it, and then `select_listing` would refuse it as "not in the
#    current candidate slate". `refine_search` replaces it: same capability,
#    but it updates the slate, the catalogue and the selection precondition
#    together. `get_listing_details` stays: it is read-only and answers
#    questions about cars already on screen.
# 3. **`select_listing` and `refine_search` are bound in FORM_FILLING.**
#    Without them the phase was a one-way door for anyone who *typed*
#    "actually, the Kia", while `_handle_action` let anyone who *clicked*
#    another card straight through -- the click path and the prose path
#    diverging again after Phase E made them converge.
TOOLS_BY_PHASE: dict["Phase", list[str]] = {
    Phase.INTERVIEWING: ["save_interview_state"],
    Phase.RESEARCHING: ["search_listings", "get_listing_details"],
    Phase.RESULTS_READY: [
        "get_listing_details", "select_listing", "refine_search", "save_interview_state",
    ],
    Phase.FORM_FILLING: ["open_booking_form", "select_listing", "refine_search"],
    Phase.AWAITING_PAYMENT: ["open_mock_checkout", "confirm_mock_payment"],
    Phase.CONFIRMED: [],
}


def tool_names_for_phase(phase: "Phase") -> list[str]:
    """Tool names permitted in `phase`. Transactional tools are simply
    absent outside their phase, so the model cannot call them -- the gate
    is enforced by what gets bound, not by asking the model nicely.
    """
    return list(TOOLS_BY_PHASE[phase])


class TransactionType(str, Enum):
    BUY = "buy"
    RENT = "rent"
    BOTH = "both"


class InterviewState(BaseModel):
    use_case: Optional[str] = None
    category: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    transaction_type: Optional[TransactionType] = None
    target_date: Optional[str] = None  # ISO date string; parsed/validated at the tool boundary
    location: Optional[str] = None
    must_have_features: list[str] = Field(default_factory=list)

    def missing_slots(self) -> list[str]:
        return [slot for slot in REQUIRED_INTERVIEW_SLOTS if getattr(self, slot) in (None, "")]

    def is_complete(self) -> bool:
        return not self.missing_slots()


class RankedRecommendation(BaseModel):
    listing_id: str
    rank: int
    fit_score: float
    reasoning: str


class Booking(BaseModel):
    id: str
    listing_id: str
    session_id: str
    submitted_form_fields: dict = Field(default_factory=dict)
    status: str = "DRAFT"  # DRAFT | SUBMITTED


class PaymentConfirmation(BaseModel):
    id: str
    booking_id: str
    confirmation_code: str
    status: str = "MOCK_CONFIRMED"
    created_at: str


class SessionState(BaseModel):
    session_id: str
    phase: Phase = Phase.INTERVIEWING
    interview: InterviewState = Field(default_factory=InterviewState)

    # Verbatim listing records as they came out of the search tool's
    # artifact -- NOT ids, and not anything re-derived. This is the
    # persisted form of the Principle I grounding channel: what T026 renders
    # and what T022 snapshots against must both read from here, so that a
    # value on screen is traceable to a specific tool-call result even after
    # a reconnect or a backend restart.
    #
    # Records rather than ids because re-fetching on every reconnect would
    # make the catalogue depend on the marketplace still being reachable and
    # still returning the same rows, which is exactly the coupling the
    # grounding rule exists to avoid. `candidate_ids()` derives the id list
    # spec.md's entity description talks about.
    candidate_listings: list[dict] = Field(default_factory=list)

    # Deterministically derived from candidate_listings (agent/ranking.py),
    # never authored by the model -- spec.md's RankedRecommendation entity
    # says so explicitly. Persisted rather than recomputed per turn so a
    # resumed session shows the same ranking it showed before.
    recommendations: list[RankedRecommendation] = Field(default_factory=list)
    selected_listing_id: Optional[str] = None
    booking: Optional[Booking] = None
    payment_confirmation: Optional[PaymentConfirmation] = None

    # How many times the booking form has been asked for. Not a domain
    # concept -- it is the handshake between a tool that runs inside the
    # graph and a WebSocket connection that does not.
    #
    # `open_booking_form` cannot push anything to the browser itself: it
    # executes inside an agent run, while the MCP App envelope is written by
    # `api/main.py` on a connection the tool knows nothing about. A counter
    # in persisted state lets the connection notice "the session has asked
    # for the form more times than I have sent it" and act, which also makes
    # the behaviour survive a reconnect (US5) instead of depending on a
    # message the browser may have missed. A boolean would not survive the
    # user asking to see the form a second time.
    booking_form_requests: int = 0

    def save_interview_slots(self, **updates) -> "SessionState":
        """Overwrite (never append/merge-append) — Constitution Principle II
        + spec.md Edge Cases: contradictory answers must overwrite, not
        accumulate.
        """
        previous = self.phase
        current = self.interview.model_dump()
        current.update({k: v for k, v in updates.items() if v is not None})
        self.interview = InterviewState(**current)
        if self.interview.is_complete() and self.phase == Phase.INTERVIEWING:
            self.phase = Phase.RESEARCHING
        self._traced(previous, "save_interview_slots")
        return self

    def _traced(self, previous: Phase, trigger: str) -> None:
        """Emit Principle V's phase-transition span, if the phase moved.

        Called from every transition method below rather than from their
        callers: a transition happens in three different execution contexts
        (inside a graph run via a tool, outside one via `_handle_action`'s
        `aupdate_state`, and outside one again via the MCP App bridge), and
        only the first is covered by `auto_instrument`. Putting the emit
        beside the mutation is what makes "every phase transition emits a
        span" true regardless of who triggered it. Fail-soft -- see
        observability/spans.py.
        """
        record_phase_transition(self.session_id, previous.value, self.phase.value, trigger)

    def candidate_ids(self) -> list[str]:
        """Ids of the current candidate slate, in rank order."""
        return [listing["id"] for listing in self.candidate_listings]

    def record_research(
        self,
        listings: list[dict],
        recommendations: list["RankedRecommendation"],
    ) -> "SessionState":
        """Store a completed research pass and advance the phase.

        The RESEARCHING -> RESULTS_READY transition lives here, next to
        `save_interview_slots`'s INTERVIEWING -> RESEARCHING, so that every
        phase transition in the system is a code path in this module rather
        than something a model decides it has finished (Principle II).

        This is the *first* research pass only. A later refinement, from
        RESULTS_READY or FORM_FILLING, goes through `refine_results` --
        which has to clear a selection this method must leave alone.
        """
        previous = self.phase
        self.candidate_listings = listings
        self.recommendations = recommendations
        if self.phase == Phase.RESEARCHING:
            self.phase = Phase.RESULTS_READY
        self._traced(previous, "record_research")
        return self

    def refine_results(
        self,
        listings: list[dict],
        recommendations: list["RankedRecommendation"],
    ) -> "SessionState":
        """Replace the slate after the user asked for a different search.

        The *fourth* transition, and the only one that runs backwards:
        {RESULTS_READY, FORM_FILLING} -> RESULTS_READY.

        Backwards is the point. Before this existed, FORM_FILLING was a
        one-way door -- a user who said "actually, show me cheaper ones"
        after picking a car had no tool that could help them, while the same
        user clicking a different catalogue card got through, because
        `_handle_action` runs ahead of the phase gate. Making the retreat an
        explicit, code-enforced route is what keeps Principle II's state
        machine honest in both directions, rather than leaving one direction
        to a UI accident.

        The selection and any in-progress booking are **discarded**, not
        carried over: a new slate may not even contain the previously chosen
        listing, and `select_listing` refuses ids outside the slate, so
        keeping them would leave the session pointing at a car it can no
        longer act on. spec.md's Edge Cases require the discard to be
        explicit rather than a silent merge.
        """
        previous = self.phase
        self.candidate_listings = listings
        self.recommendations = recommendations
        self.selected_listing_id = None
        self.booking = None
        if self.phase in (Phase.RESULTS_READY, Phase.FORM_FILLING):
            self.phase = Phase.RESULTS_READY
        self._traced(previous, "refine_results")
        return self

    def select_listing(self, listing_id: str) -> "SessionState":
        """Record the user's chosen listing and advance to FORM_FILLING.

        The third phase transition in the system, deliberately sitting
        beside `save_interview_slots` and `record_research` so that every
        transition remains one code path in one module (Principle II)
        rather than something a model announces it has done.

        **Re-selecting is allowed, and discards a booking for the old car.**
        Callable from FORM_FILLING as well as RESULTS_READY: the user is
        entitled to change their mind after the form opens, and spec.md's
        Edge Cases are explicit that the prior in-progress booking is
        "discarded, not silently merged". Before this, a session that
        selected A, started a booking, then selected B ended up with
        `selected_listing_id == "B"` and a booking still pointing at A --
        which the booking form would then have submitted against the wrong
        car. The phase stays FORM_FILLING when it is already there; only the
        car and the (now void) booking change.

        **The id must already be in the candidate slate.** That is a
        Principle I guarantee as much as a Principle II one: the slate is
        the set of listings that actually came back from a tool call, so
        refusing anything else means a selection can never be made against a
        listing id the model invented, or against one from a previous search
        that is no longer on screen. Raising rather than silently ignoring,
        because a selection that appears to succeed and does not is the
        worst of the three outcomes -- M4a's booking form would then open on
        nothing.
        """
        if listing_id not in self.candidate_ids():
            raise ValueError(
                f"{listing_id!r} is not in the current candidate slate "
                f"({', '.join(self.candidate_ids()) or 'empty'})."
            )
        previous = self.phase
        self.selected_listing_id = listing_id
        if self.booking is not None and self.booking.listing_id != listing_id:
            self.booking = None
        if self.phase == Phase.RESULTS_READY:
            self.phase = Phase.FORM_FILLING
        self._traced(previous, "select_listing")
        return self

    def submit_booking(self, booking: "Booking") -> "SessionState":
        """Record a submitted booking and advance to AWAITING_PAYMENT.

        The fifth and final transition of the pre-payment flow (spec.md US3
        AS3), and the only one that is *not* reachable from a model tool:
        `submit_booking` is deliberately absent from `TOOLS_BY_PHASE`
        because its free-form `fields` argument would let a model invent the
        user's contact details. The values arrive from the MCP App iframe,
        through the host bridge, into `api/main.py` -- and land here, so the
        transition itself still lives in this module with the other four.

        Three refusals, all raising rather than passing silently, because a
        booking that appears to succeed and does not is the worst outcome:

        - wrong phase: nothing may skip straight to payment;
        - already submitted: the App bridge is a network path and a retry, a
          double-click or a reconnect must not produce two bookings for one
          car (§14 recommendation 6);
        - a booking for a car that is not the selected one: the iframe is
          untrusted input like any other, so its idea of which listing this
          is has to agree with the session's.
        """
        if self.phase != Phase.FORM_FILLING:
            raise ValueError(
                f"A booking can only be submitted from FORM_FILLING "
                f"(this session is in {self.phase.value})."
            )
        if self.booking is not None and self.booking.status == "SUBMITTED":
            raise ValueError(
                f"Booking {self.booking.id} has already been submitted for this session."
            )
        if booking.listing_id != self.selected_listing_id:
            raise ValueError(
                f"Booking is for {booking.listing_id!r} but the selected listing is "
                f"{self.selected_listing_id!r}."
            )
        previous = self.phase
        self.booking = booking
        self.phase = Phase.AWAITING_PAYMENT
        self._traced(previous, "submit_booking")
        return self

    def selected_listing(self) -> Optional[dict]:
        """The verbatim tool record for the selected listing, if any.

        M4a pre-fills the booking form from this rather than from anything
        the model wrote (Principle I), which is why it returns the record
        and not just the id.
        """
        if not self.selected_listing_id:
            return None
        return next(
            (l for l in self.candidate_listings if l["id"] == self.selected_listing_id),
            None,
        )

    def available_tools(self) -> list[str]:
        """Read-only view of the tool names permitted in this session's phase.

        ⚠️ **This is NOT the enforcement point, despite what its name and
        this method's former docstring suggested.** Nothing in production
        calls it -- verified by grep, twice. The gate is enforced by
        `agent/graph.py::tools_for_phase()`, which resolves
        `tool_names_for_phase()` to real tool objects at agent construction;
        a tool the table does not name is simply never bound.

        Kept because `test_phase_gate.py` uses it to assert that this view
        and the binding path cannot drift apart, and deliberately
        re-documented rather than deleted: the M2.5 audit's headline finding
        was that this exact method had zero production callers while being
        recorded as the gate, and the remediation built a *different*
        mechanism rather than wiring this one up. Anyone editing this
        expecting to change what the model can call would be editing the
        wrong function.
        """
        return tool_names_for_phase(self.phase)
