"""Constitution Principle V's third clause, which had never been true.

Principle V reads "every LLM call, tool call, **and phase transition**
emits an OpenTelemetry span", and plan.md and HANDOFF both recorded it as
PASS. The first two clauses were genuinely satisfied by
`setup_observability(auto_instrument=True)`, which patches LangChain so
anything inside a graph *run* is traced.

The third was not, and a grep for `get_tracer` / `start_as_current_span`
across agent-backend's production code returned nothing at all. Phase
transitions do not always happen inside a run: `_handle_action` writes one
through `aupdate_state` after a catalogue click, and the MCP App bridge
writes another when a booking is submitted. Both are real transitions;
neither executes a runnable, so neither produced a span.

`test_booking_state.py` pins that every transition *calls* the recorder.
This file pins that the recorder produces a real span with the right
attributes -- the M2.5 lesson split in two, because "a mechanism exists"
and "a mechanism is called" fail independently and this project has been
bitten by each.
"""
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability.spans import SPAN_NAME, record_phase_transition


@pytest.fixture
def exported(monkeypatch):
    """A private tracer provider, injected at the call site.

    Not `trace.set_tracer_provider`: that is a process-global that can only
    be set once, so a test using it would work or not depending on whether
    another module got there first -- the same collection-order fragility
    that broke the credential gate for four milestones (HANDOFF §3).
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer", lambda *a, **kw: provider.get_tracer("test")
    )
    return exporter


def test_a_transition_emits_a_span_with_its_cause(exported):
    record_phase_transition("sess-1", "RESULTS_READY", "FORM_FILLING", "select_listing")

    (span,) = exported.get_finished_spans()
    assert span.name == SPAN_NAME
    assert span.attributes["session.id"] == "sess-1"
    assert span.attributes["phase.from"] == "RESULTS_READY"
    assert span.attributes["phase.to"] == "FORM_FILLING"
    # The trigger is what makes a trace answer "why did this advance?"
    # rather than only "it did" -- the click path and the tool path reach
    # the same state method and are otherwise indistinguishable in a trace.
    assert span.attributes["phase.trigger"] == "select_listing"


def test_a_non_transition_emits_nothing(exported):
    """`save_interview_slots` runs on most interview turns and advances on
    one of them. A span per call would bury the four real transitions in
    noise, so the no-op case is filtered rather than recorded.
    """
    record_phase_transition("sess-1", "INTERVIEWING", "INTERVIEWING", "save_interview_slots")

    assert exported.get_finished_spans() == ()


def test_tracing_failure_cannot_break_a_transition(monkeypatch):
    """Fail-soft, the rule the whole tracing path follows (§8.28).

    A booking must not fail because the collector is unhappy. Simulated at
    the tracer rather than the exporter, because an exporter error is
    already swallowed by the SDK -- this covers the case where getting a
    tracer at all goes wrong.
    """
    def _explode(*args, **kwargs):
        raise RuntimeError("no tracer provider")

    monkeypatch.setattr("opentelemetry.trace.get_tracer", _explode)

    record_phase_transition("sess-1", "FORM_FILLING", "AWAITING_PAYMENT", "submit_booking")


def test_it_works_with_no_provider_registered_at_all():
    """The ordinary case in the deterministic suite and in any deployment
    where Phoenix is down: OTel hands back a no-op tracer and this must be
    a cheap nothing, not an error.
    """
    record_phase_transition("sess-1", "RESEARCHING", "RESULTS_READY", "record_research")
