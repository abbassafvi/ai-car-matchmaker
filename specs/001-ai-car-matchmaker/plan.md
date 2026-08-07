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
(Python SDK, Streamable HTTP transport), `langchain-mcp-adapters` (MCP
tools → LangChain tool adapters — still **NEEDS VERIFICATION** in M3, not
yet used), `arize-phoenix-otel`, `openinference-instrumentation-langchain`,
React + Vite, `@a2ui/react` + `@a2ui/web_core` (v0_9 subpath —
**resolved**: this is a real published npm package, not a hand-rolled Lit
embed as originally planned; see M2 findings in tasks.md),
`@modelcontextprotocol/ext-apps`

**LLM Provider** (resolved M2, revised M2.5): Google Gemini via the native
`langchain-google-genai` client. `agent/llm.py` selects a client from
`LLM_PROVIDER` (`google` | `openai_compatible`), with `LLM_MODEL` /
`LLM_API_KEY` / `LLM_BASE_URL` alongside it, so switching provider or model
stays a config change. Default model `gemini-3.6-flash`.

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

The `openai_compatible` path is retained for other providers (OpenRouter,
NVIDIA NIM). It is **not verified end-to-end** — NVIDIA NIM's
non-streaming `/chat/completions` did not respond from the dev environment,
and large tool-laden requests hung even when streaming.

Operational constraint: the Gemini **free tier allows ~20 requests per day
per model**, enough for a smoke test but not a live demo or an eval run
(T046). A billed key is required before the demo.

Credentials via `agent-backend/.env` (gitignored, never committed —
`.env.example` documents the required keys).

**Storage**: SQLite — one file for the LangGraph checkpointer (session
state), one for the mock listings dataset

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
| I. Grounded Recommendations | UI values sourced only from tool-call records, never LLM-retyped | PARTIAL — the deterministic rendering layer exists (`render_a2ui.py`, covered by `test_render_a2ui.py`), but so far it renders only interview slots the *user* supplied. No listing price/spec has ever reached the UI, because no tool returns listing data yet. The principle's actual subject matter is unproven until T022/T026 (M3) |
| II. Explicit Phase Gating | Transactional tools unavailable outside their phase | PASS (since M2.5) — `TOOLS_BY_PHASE` in `agent/state.py` is the single gate definition, and `agent/graph.py` builds one agent per phase from it; covered by `test_phase_gate.py` |
| III. Mock-Only Transactions | No real payment path exists | PENDING — nothing to enforce yet; `confirm_mock_payment` lands in M4b |
| IV. Untrusted Data Boundary | Listing/user text never treated as instructions | PARTIAL — the *rule* is in every listing-facing prompt (`agent/prompts.py`), asserted by `test_phase_gate.py`. But **nothing emits the `<untrusted_listing_data>` delimiters the rule refers to**: the only two occurrences in the repo are the prompt that describes them and the test that checks the prompt describes them. M3 must wrap listing text at the tool-output boundary, then T029 supplies the behavioral proof against the seeded `ADV-*` probes |
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
│   ├── tools.py                   # save_interview_state + MCP client wiring
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
