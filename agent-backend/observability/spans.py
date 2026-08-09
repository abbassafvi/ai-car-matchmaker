"""Explicit spans for the things no instrumentation library can see.

Constitution Principle V says "every LLM call, tool call, **and phase
transition** emits an OpenTelemetry span". The first two arrive for free:
`setup_observability()` registers with `auto_instrument=True`, which patches
LangChain/LangGraph so every model call and tool call inside a graph *run*
is traced.

Phase transitions are not covered by that, and the M4a Phase C audit found
they never had been. `api/main.py::_handle_action` performs a real
RESULTS_READY -> FORM_FILLING transition through `aupdate_state`, outside
any run -- LangGraph persists it, but no runnable executes, so nothing
emits a span. The booking submitted through the MCP App bridge is a second
transition with the same shape. Grepped before writing this: there was not
one explicit span anywhere in agent-backend's production code.

So the span is emitted from inside `SessionState` itself, next to the
transition it describes, rather than at each call site. That is the M2.5
lesson applied: a mechanism that every caller must remember to invoke is
one forgotten call site away from being decorative, and Principle V's
wording is about the transition, not about who triggered it.

Fail-soft, like everything else on the tracing path (HANDOFF §8.28): with
no provider registered, `get_tracer` hands back a no-op tracer, and
anything that still goes wrong is swallowed. An observability aid must
never be able to fail a booking.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

TRACER_NAME = "ai-car-matchmaker.phase"
SPAN_NAME = "phase.transition"


def record_phase_transition(
    session_id: str,
    from_phase: str,
    to_phase: str,
    trigger: str,
) -> None:
    """Emit one span for a completed phase transition.

    `trigger` names the code path that caused it (the `SessionState` method),
    which is what makes a trace answer "why did this session advance?" rather
    than merely "it did". A no-op when the phase did not actually change --
    `save_interview_slots` is called on most interview turns and only some of
    them advance.
    """
    if from_phase == to_phase:
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer(TRACER_NAME)
        with tracer.start_as_current_span(SPAN_NAME) as span:
            span.set_attribute("session.id", session_id)
            span.set_attribute("phase.from", from_phase)
            span.set_attribute("phase.to", to_phase)
            span.set_attribute("phase.trigger", trigger)
    except Exception:  # pragma: no cover - tracing must never break a turn
        log.debug("Could not emit a phase-transition span", exc_info=True)
