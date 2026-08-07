---
description: "Task list for AI Car Matchmaker (001-ai-car-matchmaker)"
---

# Tasks: AI Car Matchmaker

**Input**: Design documents from `specs/001-ai-car-matchmaker/`

**Prerequisites**: plan.md, spec.md

**Tests**: Included — requested implicitly by the constitution's Grounded
Recommendations and Explicit Phase Gating principles, which are only
verifiable with automated tests.

**Organization**: Tasks are grouped by user story (US1-US5 from spec.md),
each independently testable. A Setup and Foundational phase precede all
stories. Milestone IDs (M0-M6) from the agreed roadmap are noted per phase
for tracking/commit-cadence purposes.

## Phase 1: Setup — M0

- [x] T001 Initialize spec-kit (`.specify/`) and this spec/plan/tasks set
- [x] T002 [P] Create repo skeleton: `agent-backend/`, `mcp-services/`,
      `mcp-apps-ui/`, `frontend/` per plan.md's Project Structure
- [x] T003 [P] `docker-compose.yml` stub with 4 services (frontend,
      agent-backend, mcp-services, phoenix) — health-check only, no logic yet
- [x] T004 [P] Root `README.md` with run instructions (updated incrementally
      per milestone) and `.gitignore` (must exclude `.claude/` credentials
      per spec-kit's own security note)
- [x] T005 Commit + push M0 to `origin main`

**Checkpoint**: `docker compose up` boots 4 empty-but-healthy containers —
verified live (all 4 respond: frontend 200, agent-backend/mcp-services
health JSON, Phoenix UI 200). Host ports for Phoenix were remapped to
16006/14317 to avoid a collision with an unrelated pre-existing container
on the dev host; internal container ports are untouched.

---

## Phase 2: Foundational — M1

**Purpose**: Core infrastructure every user story depends on.

**⚠️ CRITICAL**: No user story work starts until this phase is complete.

- [x] T006 `mcp-services/data/generate_listings.py`: deterministic mock
      dataset generator — 10 categories × 20-brand pool cross-product,
      fields per spec.md's Listing entity, includes `listing_source`
      distinguishing rental-platform vs. dealership provenance (203 listings
      generated: 200 cross-product + 3 adversarial probes)
- [x] T007 Automated check enforcing SC-006 (≥100 listings / ≥10 categories
      / ≥10 brands per category) run as part of the generator's own test
      (`mcp-services/tests/test_generate_listings.py`, 7 tests, all pass)
- [x] T008 [P] `agent-backend/agent/state.py`: SessionState/InterviewState
      pydantic schemas per spec.md's Key Entities
      (`agent-backend/tests/test_state.py`, 6 tests, all pass)
- [x] T009 [P] LangGraph `SqliteSaver` checkpointer wiring in
      `agent-backend/agent/graph.py` — persistence proven across two
      independent checkpointer connections against the same SQLite file
      (simulated restart), not just unit-tested in isolation
      (`agent-backend/tests/test_graph_persistence.py`, 2 tests, all pass)
- [x] T010 [P] `agent-backend/observability/otel_setup.py`: Phoenix
      registration (`arize-phoenix-otel` + `openinference-instrumentation-langchain`).
      Verified live against a running Phoenix container — emitted span and
      its exact attributes confirmed present via Phoenix's REST API, not
      just "no exception raised"
      (`agent-backend/tests/test_otel_setup.py`, integration test,
      auto-skips when Phoenix isn't running)
- [x] T011 Seed 2-3 adversarial listing descriptions (prompt-injection
      probes) into the generated dataset for later use in T029 (3 seeded,
      id-prefixed `ADV-` for easy targeting, covered by
      `test_adversarial_probes_present_and_tagged`)

**Checkpoint**: Mock data generation + SC-006 check + session persistence
+ tracing are all independently verified before any user story begins —
16 automated tests total (7 dataset + 6 state + 2 persistence + 1 otel,
the last of which auto-skips without a running Phoenix), all passing.

---

## Phase 3: User Story 1 - Conversational Interview (P1) 🎯 MVP — M2

**Goal**: Agent captures all 5 interview slots conversationally, live
progress visible via A2UI.

**Independent Test**: Per spec.md US1 — multi-turn conversation including
one contradiction, verify persisted state + A2UI progress surface.

### Tests for User Story 1

- [ ] T012 [P] [US1] Unit test: `save_interview_state` overwrites (not
      appends) on conflicting slot updates — `agent-backend/tests/test_state.py`
- [ ] T013 [P] [US1] Integration test: phase auto-transitions
      INTERVIEWING → RESEARCHING only once all 5 slots are non-null —
      `agent-backend/tests/test_phase_gate.py`

### Implementation for User Story 1

- [ ] T014 [US1] `agent-backend/agent/tools.py`: `save_interview_state` tool
- [ ] T015 [US1] `agent-backend/agent/prompts.py`: interview system prompt
      (ask only missing slots; untrusted-data delimiters per Principle IV)
- [ ] T016 [US1] `agent-backend/agent/graph.py`: INTERVIEWING phase node +
      transition guard
- [ ] T017 [US1] `agent-backend/agent/render_a2ui.py`: interview-progress
      A2UI surface (checklist of the 5 slots)
- [ ] T018 [US1] `agent-backend/api/`: WebSocket/SSE chat endpoint streaming
      both chat text and A2UI surface updates
- [ ] T019 [US1] `frontend/src/chat/` + `frontend/src/a2ui/`: chat shell
      wired to the Lit A2UI renderer, rendering the interview-progress surface

**Checkpoint**: Full interview flow works end-to-end in the browser.

---

## Phase 4: User Story 2 - Research & Ranked Recommendations (P1) 🎯 MVP — M3

**Goal**: Search mock dataset, rank, explain, render live via A2UI
(reasoning-steps surface + catalogue surface).

**Independent Test**: Per spec.md US2 — seeded interview state, verify hard
filters + reasoning + exact-value A2UI rendering.

### Tests for User Story 2

- [ ] T020 [P] [US2] Unit test: `search_listings` hard filters (category,
      budget, transaction_type, availability) — `mcp-services/tests/test_marketplace.py`
- [ ] T021 [P] [US2] Integration test: zero-match query triggers constraint
      relaxation messaging, not fabricated results — `agent-backend/tests/test_research.py`
- [ ] T022 [P] [US2] Snapshot test: A2UI catalogue JSON values equal source
      tool-call record values exactly (Principle I / SC-002)

### Implementation for User Story 2

- [ ] T023 [US2] `mcp-services/marketplace/`: MCP server exposing
      `search_listings`, `get_listing_details` over Streamable HTTP
- [ ] T024 [US2] `agent-backend`: `langchain-mcp-adapters` wiring — verify
      current API against plan.md's flagged NEEDS VERIFICATION item, adjust
      integration code accordingly
- [ ] T025 [US2] `agent-backend/agent/graph.py`: RESEARCHING phase node
      (search → rank → reasoning generation), RESULTS_READY transition
- [ ] T026 [US2] `agent-backend/agent/render_a2ui.py`: reasoning-steps
      surface (distinct from catalogue) + catalogue surface, both fed from
      structured tool output only
- [ ] T027 [US2] `mcp-apps-ui/listing-detail/`: optional MCP App iframe for
      single-listing deep-dive (the "marketplace access as MCP App" choice)
- [ ] T028 [US2] `frontend`: render reasoning-steps + catalogue surfaces;
      wire listing selection back to the agent
- [ ] T029 [US2] Security test: T011's seeded adversarial listings produce
      zero behavioral deviation — `agent-backend/tests/test_prompt_injection.py`

**Checkpoint**: Interview → research → ranked, explained results works
end-to-end. This is the demoable MVP core.

---

## Phase 5: User Story 3 - In-Chat Booking Form via MCP App (P2) — M4a

**Goal**: Sandboxed, in-chat form-fill MCP App, gated on listing selection.

**Independent Test**: Per spec.md US3.

### Tests for User Story 3

- [ ] T030 [P] [US3] Contract test: `open_booking_form` unavailable to the
      model when no listing is selected (Principle II)
- [ ] T031 [P] [US3] Integration test: incomplete submission rejected
      server-side without data loss in the iframe

### Implementation for User Story 3

- [ ] T032 [US3] `mcp-apps-ui/booking-form/`: Vite + `@modelcontextprotocol/ext-apps`
      form bundle, pre-fill support
- [ ] T033 [US3] `mcp-services/booking/`: `open_booking_form` (ui://
      resource) + `submit_booking` tools, server-side schema validation
- [ ] T034 [US3] `frontend/src/mcp-app-host/`: Host implementation —
      iframe sandbox creation, deny-by-default CSP, postMessage bridge
      (adapted from `ext-apps/examples/basic-host`)
- [ ] T035 [US3] `agent-backend/agent/graph.py`: FORM_FILLING phase node,
      AWAITING_PAYMENT transition on valid submission

**Checkpoint**: User can select a listing and complete a booking form
without leaving the chat.

---

## Phase 6: User Story 4 - Mock Payment / Checkout via MCP App (P2) — M4b

**Goal**: Mocked, clearly-labeled in-chat checkout, zero real payment
surface.

**Independent Test**: Per spec.md US4.

### Tests for User Story 4

- [ ] T036 [P] [US4] Test: no card-like pattern appears in DB rows, logs,
      or OTel span attributes after a mock payment (Principle III)
- [ ] T037 [P] [US4] Contract test: `open_mock_checkout` unavailable
      without a SUBMITTED booking

### Implementation for User Story 4

- [ ] T038 [US4] `mcp-apps-ui/checkout/`: mock checkout bundle, explicit
      "MOCK — no real payment" labeling
- [ ] T039 [US4] `mcp-services/payment/`: `open_mock_checkout` (ui://) +
      `confirm_mock_payment` — discards payment-like input immediately,
      persists only a synthetic confirmation record
- [ ] T040 [US4] `agent-backend/agent/graph.py`: AWAITING_PAYMENT →
      CONFIRMED transition, chat summary generated from tool-call record only

**Checkpoint**: Full interview→payment flow works end-to-end without
leaving the chat window (SC-003).

---

## Phase 7: User Story 5 - Session Resume (P3) — M4c

**Goal**: Reconnect resumes at the correct phase with no data loss.

**Independent Test**: Per spec.md US5.

- [ ] T041 [US5] Integration test: kill/restart `agent-backend` mid-session,
      reconnect, verify phase + all captured entities intact (SC-005)
- [ ] T042 [US5] Integration test: two concurrent sessions do not leak state
      into each other
- [ ] T043 [US5] `frontend`: reconnect/resume UX (re-establish WS/SSE,
      re-render current phase's A2UI surface from persisted state)

**Checkpoint**: All 5 user stories independently functional and demoable.

---

## Phase 8: Polish & Cross-Cutting — M5 (observability) / M6 (hardening)

- [ ] T044 [P] Playwright E2E: full interview→payment path, asserting zero
      CSP violations and zero console errors
- [ ] T045 Verify Phoenix shows a complete trace (LLM calls, tool calls,
      phase transitions) for one full session
- [ ] T046 [P] Eval set: ~15 synthetic personas scored on SC-001/SC-002
      via Phoenix LLM-as-judge
- [ ] T047 README finalized as the single source of run instructions
- [ ] T048 Final Review checklist (plan.md/spec.md) walked and checked off
- [ ] T049 Slide deck outline drafted (pending hackathon-provided template)
- [ ] T050 Demo video recording script drafted

---

## Dependencies & Execution Order

- **Setup (M0)** → **Foundational (M1)** blocks all user stories
- **US1 (M2)** and **US2 (M3)** are both P1/MVP and mostly sequential (US2
  needs US1's interview state shape, though US2 can be tested independently
  via seeded state per its Independent Test)
- **US3 (M4a)** depends on US2 producing a selectable listing
- **US4 (M4b)** depends on US3 producing a SUBMITTED booking
- **US5 (M4c)** can be built in parallel with US3/US4 once Foundational's
  checkpointer (T009) exists, but is only *fully* testable once all phases
  exist to resume into
- **Polish (M5/M6)** depends on all desired user stories being complete

## Implementation Strategy

**MVP first**: M0 → M1 → M2 → M3, stop and validate (interview + ranked
recommendations working end-to-end), demo-able even before transactions
exist. Then M4a → M4b → M4c to complete the required MCP Apps and memory
requirements. M5/M6 close out observability and hardening.

**Commit/push cadence**: one commit (or small group) per completed
milestone checkpoint, pushed immediately per the constitution's
Development Workflow section — not per-task.
