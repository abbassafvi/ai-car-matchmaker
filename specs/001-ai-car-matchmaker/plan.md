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

**Primary Dependencies**: `langchain`, `deepagents` (LangGraph), `mcp`
(Python SDK, Streamable HTTP transport), `langchain-mcp-adapters` (MCP
tools → LangChain tool adapters — **NEEDS VERIFICATION** against current
API in M2), `arize-phoenix-otel`, `openinference-instrumentation-langchain`,
React + Vite, Lit-based A2UI renderer, `@modelcontextprotocol/ext-apps`

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
| I. Grounded Recommendations | UI values sourced only from tool-call records, never LLM-retyped | PASS — enforced by `render_a2ui.py` reading structured tool output directly (see agent-backend design) |
| II. Explicit Phase Gating | Transactional tools unavailable outside their phase | PASS — tool list is filtered per-phase in `agent/graph.py` before being handed to the model |
| III. Mock-Only Transactions | No real payment path exists | PASS — `confirm_mock_payment` has no external payment gateway dependency; card-like fields discarded post-validation |
| IV. Untrusted Data Boundary | Listing/user text never treated as instructions | PASS — prompt templates delimit untrusted content explicitly |
| V. Full Observability | Every call/transition traced | PASS — OTel registration is process-level init in `agent-backend`, not opt-in per call site |

No violations identified. Complexity Tracking table below is empty as a
result.

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
│   ├── chat/                       # chat shell, message stream (WS/SSE client)
│   ├── a2ui/                       # Lit renderer integration
│   └── mcp-app-host/               # our Host impl: iframe sandbox, CSP,
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
