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
    candidate_listings: list[str] = Field(default_factory=list)
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

    def available_tools(self) -> list[str]:
        """Explicit phase gate (Constitution Principle II): the tool names
        exposed to the model for this session's current phase.

        Delegates to the module-level table so there is exactly one gate
        definition -- agent/graph.py binds real tool objects from that same
        table when constructing each phase's agent.
        """
        return tool_names_for_phase(self.phase)
