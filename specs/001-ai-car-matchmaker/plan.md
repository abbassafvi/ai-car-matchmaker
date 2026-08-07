# Implementation Plan: AI Car Matchmaker

**Branch**: `001-ai-car-matchmaker` | **Date**: 2026-08-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-ai-car-matchmaker/spec.md`

## Summary

A multistep agent (LangChain DeepAgents) interviews a user, searches a mock
car marketplace via MCP tools, and returns ranked, explained recommendations
rendered live via A2UI, then hands off to two required MCP Apps (booking
form, mock checkout) rendered as sandboxed iframes inside the same chat —
no navigation away from the conversation at any point. State persists
across all phases via a LangGraph checkpointer so sessions survive
disconnects. Every LLM call, tool call, and phase transition is traced via
OpenTelemetry into Arize Phoenix.

## Technical Context

**Language/Version**: Python 3.14 (agent-backend, mcp-services) · TypeScript
on Node 22, build-time only (mcp-apps-ui bundles, frontend)

**Primary Dependencies**: `langchain`, `deepagents` (LangGraph),
`langchain-google-genai` (primary LLM client) and `langchain-openai`
(alternative providers — see LLM Provider note below), `mcp`
(Python SDK, Streamable HTTP transport — **pinned `>=1.24,<2`**, because
`langchain-mcp-adapters` 0.3.x requires `mcp<2.0.0` while `mcp` 2.0.0 is
already on PyPI, so an unpinned install splits the two sides of the
protocol across a major version), `langchain-mcp-adapters` (MCP tools →
LangChain tool adapters — **VERIFIED at M3 start** against 0.3.2, see
HANDOFF §8.1–8.7; the adapters produce async-only tools, which is what
forced the whole agent path to `ainvoke`), `arize-phoenix-otel`,
`openinference-instrumentation-langchain`,
React + Vite, `@a2ui/react` + `@a2ui/web_core` (v0_9 subpath —
**resolved**: this is a real published npm package, not a hand-rolled Lit
embed as originally planned; see M2 findings in tasks.md),
`@modelcontextprotocol/ext-apps`

**LLM Provider** (resolved M2, revised M2.5, revised again M3 Phase A):
`agent/llm.py` selects a client from `LLM_PROVIDER` (`google` |
`openai_compatible`), with `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`
alongside it, so switching provider or model stays a config change. Two
providers are in use, for different jobs:

- **Development runs on Groq** (`LLM_PROVIDER=openai_compatible`,
  `LLM_BASE_URL=https://api.groq.com/openai/v1`,
  `LLM_MODEL=openai/gpt-oss-120b`). Its free tier allows ~1000 requests/day
  against Gemini's ~20, which is what makes M3's behavioural tests (T021,
  T029) and the T046 eval run affordable rather than deferred.
- **Gemini stays the demo/rehearsal provider** via the native
  `langchain-google-genai` client, default `gemini-3.6-flash`. `google` is
  still `agent/llm.py`'s built-in default provider.

Why native rather than Gemini's OpenAI-compatibility endpoint, which would
have been the smaller change: Gemini 3.x are thinking models whose function
calls carry a `thought_signature` that must be echoed back on the next
turn. The compatibility layer drops it, so the **second** turn of any
tool-using conversation fails with `400 INVALID_ARGUMENT — Function call is
missing a thought_signature`. Reproduced directly through
`langchain_openai` against the compat endpoint, not fixed by
`reasoning_effort`, and confirmed absent with the native client on the same
interview turn. Every phase of this agent is tool-driven, so the compat
path is unusable for Gemini 3.x.

The `openai_compatible` path was **verified end-to-end at M3 Phase A**
against Groq, through the real agent path (`build_interview_agent` →
`save_interview_state`): a two-turn tool-using conversation survives with
correct overwrite-not-append semantics. That is the same multi-turn tool
calling Gemini's compat endpoint and NVIDIA NIM both failed, so the path is
no longer theoretical. (NVIDIA NIM itself remains unusable from this dev
environment — its non-streaming `/chat/completions` did not respond, and
large tool-laden requests hung even when streaming. OpenRouter's free tier
is exhausted.)

Operational constraints, per provider:

- **Gemini** free tier allows ~20 requests/day/model — a smoke test, not a
  live demo or an eval run. A billed key is required before the demo.
- **Groq** rate-limits on **tokens per minute** (8000/min for
  `openai/gpt-oss-120b`), not just requests, and the reservation counts
  prompt + `max_tokens`. This is why `agent/llm.py` carries
  `DEFAULT_MAX_TOKENS_BY_PROVIDER` (google 4096 / openai_compatible 1024):
  measured on the real agent path, 4096 gave 39s and 68s turns where 1024
  gave 2.2s and 1.7s. A 20-70s "hang" on Groq is retry backoff, not a dead
  call.

Credentials via `agent-backend/.env` (gitignored, never committed —
`.env.example` documents the required keys).

**Storage**: SQLite — one file for the LangGraph checkpointer (session
state), one JSON file for the mock listings dataset. The runtime
checkpointer is **`AsyncSqliteSaver`** (M3 Phase A): MCP-adapted tools are
async-only, which forces `agent.ainvoke`, and the sync `SqliteSaver` raises
`NotImplementedError` on every async method. It runs in WAL mode, so the
`.sqlite-wal`/`.sqlite-shm` sidecars are gitignored alongside the db.
`test_graph_persistence.py` deliberately keeps using the sync saver against
the same file and schema, to cover the persistence contract in isolation.

**Testing**: `pytest` (agent-backend, mcp-services), Playwright (E2E across
the full stack), `vitest` (frontend/mcp-apps-ui units)

**Target Platform**: Linux, Docker Compose (also runnable natively for dev)

**Project Type**: Multi-service web application

**Performance Goals**: Interview turn round-trip < 3s p95 excluding raw LLM
latency; search+rank over the mock dataset < 2s

**Constraints**: No real payment integration anywhere in the code path; the
full stack must run with no external managed services beyond the LLM API
(Phoenix, session store, and dataset are all self-hosted/local)

**Scale/Scope**: Hackathon demo scale — low concurrent sessions, ~250-350
mock listings

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Grounded Recommendations | UI values sourced only from tool-call records, never LLM-retyped | PARTIAL (materially advanced in M3 Phase C) — listing data now reaches the user, and it is grounded end to end: the search query is built from persisted interview state rather than from the model (`agent/research.py`), ranking is deterministic Python over the tool artifact (`agent/ranking.py`), and the verbatim records are persisted in `SessionState.candidate_listings`. Verified live: four recommended listings byte-identical to `listings.json` on price/year/mileage/category, and all 11 numbers in the model's narration traceable to the slate. Still PARTIAL because the **A2UI surface** is the part the principle names and that is T026/T022 (Phase D) — today the values reach the user as chat prose |
| II. Explicit Phase Gating | Transactional tools unavailable outside their phase | PASS (since M2.5) — `TOOLS_BY_PHASE` in `agent/state.py` is the single gate definition, and `agent/graph.py` builds one agent per phase from it; covered by `test_phase_gate.py` |
| III. Mock-Only Transactions | No real payment path exists | PENDING — nothing to enforce yet; `confirm_mock_payment` lands in M4b |
| IV. Untrusted Data Boundary | Listing/user text never treated as instructions | PARTIAL (improved in M3 Phase B) — the *rule* is in every listing-facing prompt (`agent/prompts.py`), and the delimiters it refers to are now genuinely emitted: `store.wrap_untrusted()` wraps each `description` server-side, at the tool-output boundary, before it can reach the model. Confirmed live that the `ADV-0001` payload arrives inside the delimiters via `langchain-mcp-adapters`. Still PARTIAL because what remains is the **behavioural** proof — T029 must show the three `ADV-*` probes cause zero deviation. A wrapper the model ignores is not a boundary |
| V. Full Observability | Every call/transition traced | PASS (since M2.5) — `setup_observability()` is called from the FastAPI lifespan before any agent is built; covered by `test_observability_wiring.py` + `test_otel_setup.py` |

### Correction (M2.5)

Rows II and V previously read PASS and were **wrong**. An audit before M3
found that `available_tools()` and `setup_observability()` each had zero
production callers — the phase gate was an unused data structure, and a
full live session emitted zero spans to a running Phoenix. Both are now
genuinely wired and regression-tested. Recorded here rather than silently
edited, because the failure mode worth remembering is that a Constitution
Check table can pass review while describing code that does not exist.

### Correction (M3 start)

The same failure mode recurred twice more, found by the pre-M3 review:

- **Row I read PASS.** It was PASS for a mechanism, not for the principle:
  `render_a2ui.py` is genuinely deterministic, but every value it has ever
  rendered came from the user's own interview answers. No listing price or
  spec had ever passed through it, because no tool returned listing data.
  Downgraded to PARTIAL until T022/T026.
- **Row IV described delimiters that no code produces.**
  `<untrusted_listing_data>` appears exactly twice in the repository: in the
  prompt telling the model how to treat delimited content, and in the test
  asserting that prompt says so. Nothing wraps anything. The rule was
  self-referential.

The lesson generalises: a gate row is only meaningful against the *subject
matter* of its principle, and a test that asserts a prompt contains a rule
proves the rule was written, not that it is enforced.

### Correction (M3 Phase C start)

A fourth audit, run before Phase C. This one found the failure mode
**inverted** — docs understating what the code does — which is worth
recording because every previous instance ran the other way and a reader
who has internalised "the docs oversell" will mis-weigh these.

- **The LLM Provider section above said the `openai_compatible` path was
  "not verified end-to-end".** False since M3 Phase A: it is the *active
  development provider*, running Groq, verified through the real agent path
  and recorded as such in both tasks.md's Phase 4 quota decision and
  HANDOFF §5. plan.md was the only doc still carrying the old status, and
  it was the one a reader is told to trust for architecture. Corrected
  above, along with the missing Groq TPM constraint.
- **Row IV still said "nothing emits the delimiters".** True when written
  at M3 start; false since Phase B, which added `store.wrap_untrusted()`.
  The row is now PARTIAL for the correct reason — the wrapping is real, the
  behavioural proof (T029) is what is still owed. Verified live before
  editing: the `ADV-0001` description arrives at the agent inside
  `<untrusted_listing_data>` via `langchain-mcp-adapters`.
- **The Project Structure block put "MCP client wiring" in `agent/tools.py`**,
  while tasks.md T024 and HANDOFF §10 put it in the FastAPI lifespan. Two
  docs specifying different homes for code that had not been written yet.
  Resolved in favour of the lifespan (see the Project Structure note) —
  discovery is async and must happen once, before `PhaseAgentRegistry`
  fixes each agent's tools at construction.

Fourth lesson, then: **staleness is a two-sided failure.** "Verify the docs
against the code" has to include verifying that a doc is not still
describing a limitation the code has since outgrown, because that costs a
session re-solving a solved problem.

Known deviation, accepted: `create_deep_agent` always installs
`FilesystemMiddleware`, which binds nine built-in tools (`ls`, `read_file`,
`write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`, `task`) in
every phase, outside our gate. They are not removable through its public
API. They are acceptable because the default `StateBackend` is a virtual
filesystem held in graph state — it never touches the host, and it exposes
no `execute` implementation, so shell execution is inert.
`test_phase_gate.py` pins both the exact built-in set and the absence of
`StateBackend.execute`, so a dependency upgrade that widens the agent's
reach fails the suite instead of passing unnoticed.

## Project Structure

### Documentation (this feature)

```text
specs/001-ai-car-matchmaker/
├── plan.md              # this file
├── tasks.md             # Phase 2 output
└── (research.md, data-model.md, contracts/ folded into this plan for
    hackathon scope rather than split into separate files)
```

### Source Code (repository root)

```text
agent-backend/                     # Python — DeepAgents orchestrator
├── agent/
│   ├── graph.py                   # LangGraph app, phase gate, tool filtering
│   ├── state.py                   # SessionState/InterviewState schemas (pydantic)
│   ├── tools.py                   # locally-defined tools (save_interview_state).
│   │                              #   NOT the MCP client: discovery is async and
│   │                              #   happens once in api/'s FastAPI lifespan, then
│   │                              #   the tools are handed to PhaseAgentRegistry,
│   │                              #   which must have them before it constructs an
│   │                              #   agent (DeepAgents fixes tools at construction)
│   ├── render_a2ui.py             # deterministic domain object -> A2UI JSON
│   └── prompts.py
├── api/                            # WebSocket/SSE chat endpoint (FastAPI)
├── observability/otel_setup.py     # Phoenix/OTel registration
└── tests/

mcp-services/                       # Python — 3 MCP servers, one process
├── marketplace/                    # search_listings, get_listing_details tools
├── booking/                        # open_booking_form (ui://), submit_booking
├── payment/                        # open_mock_checkout (ui://), confirm_mock_payment
├── data/
│   ├── generate_listings.py        # deterministic mock data generator
│   └── listings.json               # generated output (checked in for repro)
└── tests/

mcp-apps-ui/                        # TypeScript, browser-only bundles (no server)
├── listing-detail/                 # Vite + ext-apps App class
├── booking-form/
└── checkout/

frontend/                           # React + Vite
├── src/
│   ├── App.tsx                     # chat shell + @a2ui/react rendering (M2;
│   │                               #   single component so far, deliberately
│   │                               #   not split into chat/a2ui/ subfolders
│   │                               #   until mcp-app-host/ in M4 adds real
│   │                               #   complexity worth separating)
│   └── mcp-app-host/               # M4: our Host impl: iframe sandbox, CSP,
│                                   #   postMessage bridge (adapted from
│                                   #   ext-apps/examples/basic-host)
└── tests/

docker-compose.yml                  # frontend, agent-backend, mcp-services, phoenix
```

**Structure Decision**: Multi-service web application (Option 2 variant),
extended from 2 services (backend/frontend) to 4 logical units because MCP
servers must be independently network-addressable (Streamable HTTP) from
both the agent backend and, for `ui://` resource fetches, the frontend's
MCP-Apps host — collapsing them into the agent-backend process would break
that addressability. `mcp-apps-ui` is deliberately not a running service:
it produces static assets consumed by `mcp-services` at serve time.

## Complexity Tracking

*(empty — no constitution violations to justify)*
