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

- [x] T012 [P] [US1] Unit test: `save_interview_state` overwrites (not
      appends) on conflicting slot updates —
      `agent-backend/tests/test_state.py` (SessionState layer, 6 tests) +
      `agent-backend/tests/test_tools.py` (tool layer, 5 tests, called via
      `.func` directly — `InjectedState` only resolves inside a real
      compiled graph, confirmed empirically before writing the tests)
- [x] T013 [P] [US1] Integration test: phase auto-transitions
      INTERVIEWING → RESEARCHING only once all 5 slots are non-null —
      `agent-backend/tests/test_interview_agent.py`, live LLM call,
      auto-skips without `LLM_API_KEY` (renamed from `OPENROUTER_API_KEY` in M2.5)

### Implementation for User Story 1

- [x] T014 [US1] `agent-backend/agent/tools.py`: `save_interview_state` tool
- [x] T015 [US1] `agent-backend/agent/prompts.py`: interview system prompt
      (ask only missing slots; untrusted-data delimiters deferred to M3 —
      interview input is the user's own words, not third-party content)
- [x] T016 [US1] `agent-backend/agent/graph.py`: real DeepAgents-based
      `build_interview_agent()`, additive alongside M1's minimal
      persistence-proof graph (kept as-is, still covers the checkpointer
      contract in isolation)
- [x] T017 [US1] `agent-backend/agent/render_a2ui.py`: interview-progress
      A2UI surface (checklist of the 5 slots). **Deviation from plan.md**:
      targets protocol **v0.9**, not v1.0 — verified the only real,
      installable renderer (`@a2ui/react` on npm, v0.10.2) ships v0_8/v0_9
      builds only, no v1_0 export yet; v0.9's message/component shapes are
      compatible with v1.0's, confirmed by comparing both spec versions
      directly before writing this
- [x] T018 [US1] `agent-backend/api/main.py`: FastAPI WebSocket endpoint
      (`/ws/{session_id}`) streaming chat text + A2UI surface updates,
      backed by the same SqliteSaver checkpointer proven in M1. Verified
      live end-to-end via a real WebSocket round trip
      (`agent-backend/tests/test_chat_endpoint.py`)
- [x] T019 [US1] `frontend/`: React + Vite chat shell. **Deviation from
      plan.md**: uses the real **`@a2ui/react`** package, not a hand-rolled
      Lit embed — `@a2ui/react` turned out to exist and be published on
      npm, which is strictly better than the planned approach (real
      official renderer vs. reimplementing one). Verified live in-browser
      against the full stack, including a real conversation turn.

**Live-verification findings** (bugs caught and fixed, not just noted):
- `@a2ui/react@0.10.2`'s `"./styles/structural.css"` export points at a
  file that isn't actually in the published package — dropped the import,
  components render unstyled but functional.
- The WebSocket handler had **no error handling** around `agent.invoke()`
  — any failure (observed live: OpenRouter account credits exhausted mid-session)
  killed the connection silently. Fixed with a try/except that sends a
  graceful `{"type": "error", ...}` message and keeps the connection alive;
  regression-tested without needing real LLM credits
  (`agent-backend/tests/test_chat_endpoint_error_handling.py`, monkeypatches
  the failure directly).
- That same regression test originally set its dummy API key via
  `os.environ.setdefault(...)` at **module level**, which executes at
  pytest collection time — leaking into `test_interview_agent.py`'s
  `skipif` check (evaluated at collection time too) and causing it to
  attempt a real API call with a fake key instead of skipping. Caught by
  running the full suite together, not the file in isolation. Fixed with
  function-scoped `monkeypatch.setenv`, which pytest auto-reverts.
- The Browser automation tool's coordinate-based click didn't reliably
  trigger the Send button's React handler (separately, typing didn't
  dispatch events React's controlled `<input>` recognized). Isolated by
  driving the WebSocket directly from the console first, then fixing the
  input via the native value setter + `dispatchEvent`, and the button via
  `.click()`. Confirmed as a tooling quirk, not an application bug, before
  moving on.

**Checkpoint**: Full interview flow verified end-to-end in the browser —
real WebSocket connection to the real backend, real `@a2ui/react` rendering
of the live interview-progress surface, real chat message rendering for
both success and graceful-failure paths, real Docker Compose build
(multi-stage frontend image, real `agent-backend` image with installed
deps) with secrets verified absent from both the built JS bundle and the
image layers. 23 automated tests total across `agent-backend` (19
unconditional + 4 live-LLM/Phoenix-gated, auto-skip cleanly without
credentials/Phoenix running — verified with `env -u LLM_API_KEY`).

---

## Phase 3.5: Audit Remediation — M2.5

**Why this phase exists**: a pre-M3 audit (fresh clone, fresh venv, fresh
Docker build, live stack, live WebSocket session) found that two
Constitution principles were recorded as PASS in plan.md while having **no
production code path at all**. Fixing them before M3 was mandatory: both
get materially more expensive once M3 adds a second tool and untrusted
listing text.

- [x] T051 **F1 — Observability was dead code.** `setup_observability()`
      had zero callers outside its own test; a full live session against
      the compose stack produced **zero spans** in a running Phoenix
      (`/v1/projects` returned only `default`, with an empty span list).
      FR-012 and Principle V were unmet. Now called from the FastAPI
      lifespan *before* any agent is constructed (auto-instrument patches
      LangChain globally, so ordering matters), and fail-soft so an
      unreachable Phoenix degrades tracing instead of taking the app down.
      `agent-backend/tests/test_observability_wiring.py`
- [x] T052 **F2 — The phase gate was never enforced.**
      `SessionState.available_tools()` had zero production callers;
      `build_interview_agent()` hardcoded its tool list. The gate is now a
      single module-level table (`TOOLS_BY_PHASE` in `agent/state.py`) that
      `agent/graph.py` builds one agent per phase from, via
      `PhaseAgentRegistry`. DeepAgents fixes an agent's tools at
      construction, so one-agent-per-phase is what makes the gate real.
      `agent-backend/tests/test_phase_gate.py`
- [x] T053 **F4 — `agent.invoke()` blocked the event loop.** It ran inline
      in an `async def` WebSocket handler, serializing every concurrent
      session behind each LLM round trip (spec.md US5 AS2 requires two
      simultaneous sessions). Now dispatched via `asyncio.to_thread`.
- [x] T054 **F7 — Backend died at startup without an API key.**
      `build_model()` raised inside lifespan, so `docker compose up` before
      creating `.env` killed the service. The app now boots degraded:
      `/health` reports `status: degraded`, and a chat turn returns a
      readable error naming the missing variable.
- [x] T055 **F5 — Frontend Docker build ignored the lockfile.**
      `COPY package.json` + `npm install` re-resolved caret ranges at build
      time, so a rebuild could silently pull a different `@a2ui/react` than
      the one verified to work. Now `COPY package.json package-lock.json`
      + `npm ci`.
- [x] T056 **F6 — No guard that `listings.json` matched the generator.**
      Every dataset test called `generate()` in process, but M3's MCP
      server reads the committed file. Drift would have been invisible.
      `mcp-services/tests/test_generate_listings.py`
- [x] T057 **F8/F10 — Docs asserted things the code did not do.** plan.md's
      Constitution Check rows II and V corrected (with the correction
      recorded, not silently edited); test counts reconciled; dead
      `agent-backend/app_stub.py` deleted; `mcp-services/.dockerignore`
      added.
- [x] T058 **LLM provider swap — OpenRouter → Google Gemini.** OpenRouter
      credits were exhausted (free tier, ~$0 left: a 20-token probe
      succeeded but the configured 1024-token calls returned 402), and the
      live-LLM tests *hard-failed* rather than skipping, because `skipif`
      only checked for key **presence**. `agent/llm.py` is now
      provider-selected (`LLM_PROVIDER=google|openai_compatible`).
      **Finding**: Gemini's OpenAI-compatibility endpoint cannot be used
      for Gemini 3.x — it drops the `thought_signature` that thinking
      models attach to function calls, so the second turn of every
      tool-using conversation fails `400 INVALID_ARGUMENT`. Verified
      directly; not fixable via `reasoning_effort`. The native client
      round-trips it correctly.
- [x] T059 **Content-block normalization.** Gemini returns
      `AIMessage.content` as a *list of content blocks*, not a string, so
      the WebSocket handler was about to send a JSON array where the
      frontend chat bubble expects text. Added `message_text()` at the
      wire boundary; reasoning/thinking blocks are dropped rather than
      shown. `agent-backend/tests/test_message_text.py`

**Accepted deviation**: `create_deep_agent` always installs
`FilesystemMiddleware`, binding nine built-in tools outside our gate. Not
removable via its public API. Safe because the default `StateBackend` is a
virtual filesystem in graph state with no `execute` implementation — shell
execution is inert and the host is untouched. `test_phase_gate.py` pins
both the built-in set and the absence of `StateBackend.execute` so a
dependency upgrade that widens the agent's reach fails loudly.

**Checkpoint**: 53 automated tests, up from 30. 47 pass with no external
setup (39 agent-backend + 8 mcp-services); all 53 pass with a live LLM key
and Phoenix running — verified live, including 8 real spans landing in
Phoenix for one session (LLM calls + the `save_interview_state` tool call),
where the pre-M2.5 code produced zero.

---

## Phase 4: User Story 2 - Research & Ranked Recommendations (P1) 🎯 MVP — M3

**Goal**: Search mock dataset, rank, explain, render live via A2UI
(reasoning-steps surface + catalogue surface).

**Independent Test**: Per spec.md US2 — seeded interview state, verify hard
filters + reasoning + exact-value A2UI rendering.

### 🔴 Open decision before starting (unanswered)

T021 and T029 are **behavioral** tests needing many live LLM calls, and the
Gemini free tier allows ~20 requests/day/model. T029 is the one that actually
proves Principle IV. Three options were put to the user, who deferred:

1. Build M3 now, write T021/T029 to auto-skip until a billed key exists.
2. User provides a billed key first; exercise both live throughout.
3. Scripted fake model for the behavioral tests + a thin live smoke test.

**Resolve this before writing M3 code.**

### What M2.5 already did for M3

- The phase gate already **names** `search_listings` / `get_listing_details`
  for `Phase.RESEARCHING` and `select_listing` for `RESULTS_READY`
  (`TOOLS_BY_PHASE` in `agent/state.py`). T025 only has to **register the
  real tool objects in `TOOL_REGISTRY`** (`agent/graph.py`) — the gate and
  its tests already exist and will start covering them automatically.
- `PHASE_SYSTEM_PROMPTS` already has RESEARCHING/RESULTS_READY prompts
  carrying `UNTRUSTED_DATA_RULE` (Principle IV delimiters), asserted by
  `test_phase_gate.py`. T029 supplies the *behavioral* proof.
- **Re-check the accepted deviation** recorded in Phase 3.5: DeepAgents binds
  9 built-in tools (incl. `write_file`, `execute`, `task`) in every phase,
  outside our gate. Inert today because the default `StateBackend` is virtual
  and has no `execute`. M3 is when untrusted listing text first reaches the
  model, so re-evaluate whether those need constraining.

### Tests for User Story 2

- [x] T020 [P] [US2] Unit test: `search_listings` hard filters (category,
      budget, transaction_type, availability) — `mcp-services/tests/test_marketplace.py`
      (18 tests) plus `tests/test_marketplace_server.py` (9 tests) for the
      MCP tool contract. **Dataset finding**: the first version of these
      tests failed against real data, and the code was right — spec.md US2
      AS1 ("budget $25,000, category SUV, transaction_type buy") matched
      **zero** listings, because every `CATEGORY_PROFILE` floor was a
      new-car price (cheapest SUV $26,380, and the only sub-$30k SUVs were
      rent-only). A dataset that cannot satisfy the spec's own headline
      acceptance scenario would have sent every demo into the zero-result
      relaxation path. Floors lowered to give each category a used/budget
      tier, and price is now derived from age + mileage rather than drawn
      independently (previously a pristine 2026 listing could be priced
      below a worn 2022 one, which gave the ranking layer nothing real to
      explain). Ceilings, seed, counts and the 3 `ADV-*` probes unchanged;
      AS1 now matches 4 listings.
- [ ] T021 [P] [US2] Integration test: zero-match query triggers constraint
      relaxation messaging, not fabricated results — `agent-backend/tests/test_research.py`
- [ ] T022 [P] [US2] Snapshot test: A2UI catalogue JSON values equal source
      tool-call record values exactly (Principle I / SC-002)

### Implementation for User Story 2

- [x] T023 [US2] `mcp-services/marketplace/`: MCP server exposing
      `search_listings`, `get_listing_details` over Streamable HTTP.
      `store.py` holds the query logic (testable without a transport),
      `server.py` is the thin FastMCP layer; `app_stub.py` deleted, the
      `/health` route carried over so compose/README keep working.
      Verified in Docker: image builds, container reports healthy, and
      `POST /mcp` answers the protocol.
      **Two contract findings worth keeping:**
      (a) FastMCP puts a *dict* return at the top level of
      `structured_content` but a *list* return under a `"result"` key, so
      returning records bare would make the Principle I grounding channel's
      shape depend on which tool was called. Both tools now return a named
      object (`listings`/`count`/`query`, and `listing`), pinned by
      `test_marketplace_server.py`.
      (b) Principle IV's boundary is now real rather than declared: the
      server wraps each `description` in `<untrusted_listing_data>` before
      it leaves, because tool output is what langchain-mcp-adapters
      serialises into the model's context — the agent side never gets a
      chance to wrap it later. Confirmed live that the `ADV-0001` payload
      arrives *inside* the delimiters.
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
