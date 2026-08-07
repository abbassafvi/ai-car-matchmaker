# AI Car Matchmaker Constitution

## Core Principles

### I. Grounded Recommendations (NON-NEGOTIABLE)
Every price, spec, and availability value shown to the user MUST be traceable
verbatim to a specific tool-call result. The LLM never retypes or paraphrases
numeric/factual listing data from memory; a deterministic rendering layer
reads structured tool output directly to build UI. This eliminates
hallucinated prices/specs as a failure class rather than mitigating it with
prompting.

### II. Explicit Phase Gating
The interview → research → recommend → form-fill → payment flow is a
code-enforced state machine, not an emergent LLM decision. A tool (e.g.
`open_booking_form`) is only exposed to the model once its precondition is
met (e.g. a listing is selected). The agent cannot skip, reorder, or
hallucinate its way past a phase boundary.

### III. Mock-Only Transactions
No real payment processing, no real BMW Group APIs, no persistence of
real-looking payment credentials anywhere (DB, logs, traces) even
transiently. The checkout MCP App is explicitly labeled as a mock. Any
card-like input is discarded server-side immediately after the mock
"authorization" step; only a synthetic confirmation ID is retained.

### IV. Untrusted Data Boundary
Marketplace listing content and any free-text submitted through MCP App
forms is treated as data, never as instructions. Prompt templates wrap such
content with explicit untrusted-data delimiters. This holds even though the
dataset is mocked, since adversarial content may be seeded deliberately for
evaluation.

### V. Full Observability
Every LLM call, tool call, and phase transition emits an OpenTelemetry span
via Arize Phoenix. No code path is exempted from instrumentation — the trace
is the audit log for "explain your reasoning," not just the chat transcript.

## Technology Constraints

- Agent harness: LangChain DeepAgents (LangGraph), Python.
- Protocol-based tool access via MCP (Python SDK, Streamable HTTP transport)
  for marketplace search, booking, and payment.
- Form-filling and payment MUST be implemented as MCP Apps rendered inside
  the chat itself (hackathon hard requirement) — no navigation away from the
  conversation to complete a booking or mock purchase.
- Car catalogue and live agent progress (interview state, search status,
  reasoning steps) MUST be rendered via A2UI — never static HTML.
- Mock marketplace dataset: ≥100 listings, ≥10 categories, ≥10 brands per
  category, generated deterministically (not hand-authored, not
  LLM-authored).
- Observability: Arize Phoenix via OpenTelemetry (`arize-phoenix-otel` +
  OpenInference LangChain instrumentation).
- Deployment: Docker Compose, single-command bring-up (`docker compose up`).

## Development Workflow

- Spec-driven: constitution → spec → plan → tasks → implement, via spec-kit.
- Work proceeds in milestones (M0–M6, see `specs/001-ai-car-matchmaker/tasks.md`).
- A milestone is not "done" until its own test suite passes.
- Commits are pushed to `origin main` on `abbassafvi/ai-car-matchmaker` after
  each milestone lands and its tests pass — this cadence is pre-authorized;
  no per-push confirmation is required.

## Governance

This constitution supersedes ad hoc implementation decisions. Any violation
of a Core Principle must be recorded in `plan.md`'s Complexity Tracking
table with an explicit justification and a note on why a simpler,
compliant alternative was rejected. Amendments to this document require a
version bump and a note in "Last Amended."

**Version**: 1.0.0 | **Ratified**: 2026-08-07 | **Last Amended**: 2026-08-07
