"""Session/interview/transaction schemas — spec.md's "Key Entities" made
concrete. These are the shapes that flow through the LangGraph checkpointer
(agent/graph.py) and that render_a2ui.py reads to build UI, never the LLM's
own words (Constitution Principle I).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

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
TOOLS_BY_PHASE: dict["Phase", list[str]] = {
    Phase.INTERVIEWING: ["save_interview_state"],
    Phase.RESEARCHING: ["search_listings", "get_listing_details"],
    Phase.RESULTS_READY: ["search_listings", "get_listing_details", "select_listing"],
    Phase.FORM_FILLING: ["open_booking_form", "submit_booking"],
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

    def save_interview_slots(self, **updates) -> "SessionState":
        """Overwrite (never append/merge-append) — Constitution Principle II
        + spec.md Edge Cases: contradictory answers must overwrite, not
        accumulate.
        """
        current = self.interview.model_dump()
        current.update({k: v for k, v in updates.items() if v is not None})
        self.interview = InterviewState(**current)
        if self.interview.is_complete() and self.phase == Phase.INTERVIEWING:
            self.phase = Phase.RESEARCHING
        return self

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
        """
        self.candidate_listings = listings
        self.recommendations = recommendations
        if self.phase == Phase.RESEARCHING:
            self.phase = Phase.RESULTS_READY
        return self

    def select_listing(self, listing_id: str) -> "SessionState":
        """Record the user's chosen listing and advance to FORM_FILLING.

        The third and last phase transition in the system, deliberately
        sitting beside `save_interview_slots` and `record_research` so that
        every transition remains one code path in one module (Principle II)
        rather than something a model announces it has done.

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
        self.selected_listing_id = listing_id
        if self.phase == Phase.RESULTS_READY:
            self.phase = Phase.FORM_FILLING
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
