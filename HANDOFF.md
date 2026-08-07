# Session Handoff — AI Car Matchmaker

**Purpose of this file**: complete context transfer so a new chat session can
continue this project with zero re-discovery and without repeating mistakes
already made and fixed. Read this file first, then the files listed in
[§12 Required reading](#12-required-reading).

**Last updated**: 2026-08-08, after **M2.5** (audit remediation) shipped.

---

## 1. What this project is

Amulate Summer Hackathon 2026 submission: **AI Car Matchmaker** — a multistep
AI agent that (1) interviews a user conversationally about the car they want
to buy or rent, (2) researches car marketplaces on their behalf, (3) presents
ranked, explained recommendations, and (4) lets them complete a booking form
and a *mocked* checkout **without leaving the chat**.

- **GitHub**: https://github.com/abbassafvi/ai-car-matchmaker (public)
- **Local path**: `/home/abbas/ai-car-matchmaker`
- **Owner**: `abbassafvi` (Abbas, mohdabbassafvi23@gmail.com)

### Hackathon hard requirements (non-negotiable)

| # | Requirement |
|---|---|
| 1 | Multistep agent: interview → research → ranked+explained recommendations |
| 2 | Interview captures: use case, car type/category, budget, buy-vs-rent, target date |
| 3 | **Form-filling MUST be an MCP App** rendered inside the chat |
| 4 | **Mock payment/checkout MUST be an MCP App** rendered inside the chat |
| 5 | Car catalogue + live agent progress (interview state, search status, **reasoning steps**) MUST render via **A2UI** — explicitly *"not static HTML"* |
| 6 | No real payments, no BMW Group APIs — checkout fully mocked |
| 7 | Mock marketplace: **≥100 listings, ≥10 categories, ≥10 brands per category** (real marketplaces allowed as an alternative; we chose mock) |
| 8 | Maintain state across interview/research/recommendation (multistep memory) |
| 9 | Built on an approved harness: Claude Agent SDK **or LangChain DeepAgents** or OpenAI Agents SDK |
| 10 | Spec-driven development (e.g. GitHub spec-kit) |
| 11 | Ship as Docker container **or** deployed public app |
| 12 | Public GitHub repo, documented, README with run instructions |
| 13 | Short slide deck (template to be provided by organizers — **not yet received**) |
| 14 | Short video demo of the working app |
| 15 | **Bonus**: AI observability + evals via Langfuse or Arize Phoenix over OpenTelemetry |

### Locked-in decisions (made by the user, do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Agent harness | **LangChain DeepAgents** | User's explicit choice |
| Marketplace data | **Mock dataset** | Reliability for demo; no API keys/rate limits |
| Marketplace access | **Also built as an MCP App** | User's explicit choice (spec allows plain API, user opted for the richer path) |
| Observability | **Arize Phoenix** | User's explicit choice; OSS, self-hosts in compose |
| Frontend | **React + Vite**, `@a2ui/react` renderer | See §7 deviation note |
| MCP server language | **Python** (MCP Python SDK) | Keeps backend single-language |
| Session store | LangGraph **SqliteSaver** | Zero external infra, real persistence |
| Push cadence | **Commit + push after each milestone, pre-authorized** | User approved; no per-push confirmation needed |

### Resolved architectural ambiguity (important)

The spec says marketplace access *may* be an MCP App, but *also* mandates A2UI
for the catalogue. Taken literally at the same surface these conflict (MCP Apps
render HTML in an iframe; A2UI mandates non-HTML declarative UI). **Resolution
agreed with the user:**

- Marketplace **MCP tools** (`search_listings`, `get_listing_details`) = the
  "protocol-based tool access" requirement.
- The **primary catalogue + progress + reasoning-steps surfaces = A2UI** (satisfies
  the "not static HTML" clause).
- The marketplace MCP App's `ui://` resource is a *secondary* surface (a rich
  single-listing detail/compare view), additive rather than a competing
  implementation of the catalogue.

---

## 2. Current status: M0, M1, M2, M2.5 complete

```
M0   ✅ spec-kit scaffolding, constitution, spec/plan/tasks, 4-service compose skeleton
M1   ✅ mock dataset generator, session-state schemas, checkpointer persistence, Phoenix tracing
M2   ✅ Conversational Interview (User Story 1) — DeepAgents agent, A2UI surface, WebSocket API, React frontend
M2.5 ✅ Audit remediation — see §13. Two Constitution principles were
        recorded as PASS while having no production code path at all.
M3   ⬜ NEXT — Research & Ranked Recommendations (User Story 2)
M4a  ⬜ Booking form MCP App (User Story 3)
M4b  ⬜ Mock checkout MCP App (User Story 4)
M4c  ⬜ Session resume (User Story 5)
M5   ⬜ Evals (observability itself is now wired, M2.5/T051)
M6   ⬜ Hardening, E2E tests, README finalization, deck, demo video
```

**Test suite**: 53 total. 47 pass with **no external setup**; all 53 pass
with a live LLM key and Phoenix running (verified 2026-08-08).
- `agent-backend`: 39 unconditional, 45 with Phoenix + LLM key
- `mcp-services`: 8

⚠️ The credential gate checks key **presence** only. With a key set but out
of quota, the live tests **fail** rather than skip. Check the provider
account before assuming a code bug.

**Git log** (main, clean, synced with origin):
```
6cef214  M2: Conversational Interview (User Story 1) end to end
33598e6  M1: mock dataset, session-state schema, checkpointer persistence, tracing
4c70a45  M0 audit fixes: track .specify/.gitignore, sync task checkboxes, document dataset assumption
68ff04c  Remap Phoenix host ports to avoid collision with existing host container
ff56417  M0: spec-kit scaffolding, constitution, spec/plan/tasks, repo skeleton
```

---

## 3. Architecture

```
┌──────────────── frontend (React + Vite, port 3000) ────────────────┐
│  chat shell (src/App.tsx)                                          │
│   ├─ @a2ui/react renderer  → interview progress, catalogue,        │
│   │                           reasoning steps  [A2UI protocol v0.9] │
│   └─ MCP Apps host (M4)    → sandboxed iframes: booking, checkout  │
└───────────────────────────────┬────────────────────────────────────┘
                    WebSocket /ws/{session_id}
┌───────────────────────────────▼────────────────────────────────────┐
│  agent-backend (Python 3.14, FastAPI, port 8000)                   │
│   ├─ agent/graph.py       PhaseAgentRegistry: one agent per phase  │
│   ├─ agent/tools.py       save_interview_state (Command-based)     │
│   ├─ agent/state.py       SessionState + phase gate                │
│   ├─ agent/render_a2ui.py deterministic domain → A2UI JSON         │
│   ├─ agent/llm.py         Gemini via langchain-google-genai        │
│   ├─ api/main.py          WebSocket bridge                         │
│   └─ SqliteSaver checkpointer → /app/data/sessions.sqlite (volume) │
└──────┬─────────────────────────────────────────┬───────────────────┘
       │ (M3: MCP Streamable HTTP)               │ OTel gRPC
┌──────▼──────────────────────┐        ┌─────────▼──────────┐
│ mcp-services (port 8100)    │        │ phoenix            │
│  marketplace / booking /    │        │ UI    :16006       │
│  payment MCP servers        │        │ OTLP  :14317       │
│  + data/listings.json (203) │        └────────────────────┘
└─────────────────────────────┘
```

**Port note**: Phoenix host ports are **16006** (UI) and **14317** (OTLP gRPC),
*not* the defaults 6006/4317 — an unrelated pre-existing container
(`phoenix-mind-service`) on this dev host already occupies those. Container-internal
ports are unchanged (6006/4317).

---

## 4. Environment facts (this machine)

| Item | Value |
|---|---|
| Working dir | `/home/abbas/ai-car-matchmaker` |
| Python | 3.14.4 — venv at `./.venv` (gitignored) |
| Node | 22.22.1, npm 9.2.0 |
| Docker | 29.6.1, Compose v5.3.1 |
| Git | 2.53.0, user `Abbas` / `mohdabbassafvi23@gmail.com` |
| **`gh` CLI** | **NOT INSTALLED**, and `sudo apt-get` **fails** (no TTY for auth). Use the **GitHub REST API via `curl`** instead. |
| GitHub token | In `~/.git-credentials` (scope: `repo`). Extract with:<br>`TOKEN=$(sed -nE 's#https://([^:@]+:)?([^@]+)@github.com#\2#p' ~/.git-credentials \| head -1)` |
| `uv` / `specify` | Installed at `~/.local/bin` — `export PATH="$HOME/.local/bin:$PATH"` |
| spec-kit CLI flag | It is `--integration claude`, **not** `--ai`; also needs `--ignore-agent-tools` here |

**Secrets**: `agent-backend/.env` holds `LLM_API_KEY` (gitignored, verified
absent from both the built image and the JS bundle).
`agent-backend/.env.example` is the committed no-secrets template. Never
commit real values; never echo the key into logs or traces.

⚠️ **LLM provider status** (changed in M2.5):
- **OpenRouter is exhausted** — free tier, ~$0 left. A 20-token probe
  succeeds; the app's configured calls return `402`. No longer used.
- **Now on Google Gemini** (`LLM_PROVIDER=google`, default model
  `gemini-3.6-flash`), via the **native** `langchain-google-genai` client.
- **Gemini free tier is ~20 requests/day/model.** Enough for a smoke test,
  *not* for a demo or the T046 eval run. A billed key is needed before the
  demo. Each model has its own quota, so switching `LLM_MODEL` buys more
  headroom during development.
- **Do not switch Gemini to its OpenAI-compat endpoint.** Gemini 3.x are
  thinking models; their function calls carry a `thought_signature` that
  must be echoed back, the compat layer drops it, and the *second* turn of
  every tool-using conversation dies with `400 INVALID_ARGUMENT`. Verified;
  `reasoning_effort` does not fix it.
- **NVIDIA NIM was tried as a fallback and did not work here** — its
  non-streaming `/chat/completions` returned nothing in 120s, and large
  tool-laden requests hung even when streaming. `/models` responds fine.
  The `openai_compatible` provider path exists and is wired, but is
  **unverified end-to-end**.

---

## 5. How to run everything

```bash
cd /home/abbas/ai-car-matchmaker

# Full stack (what judges will run)
docker compose up --build
#   frontend        http://localhost:3000
#   agent-backend   http://localhost:8000/health
#   mcp-services    http://localhost:8100
#   phoenix         http://localhost:16006

# Tests
source .venv/bin/activate
(cd agent-backend && python -m pytest tests/ -v)
(cd mcp-services && python -m pytest tests/ -v)
#   3 tests auto-skip without LLM_API_KEY / running Phoenix — that's correct behavior

# Regenerate mock dataset (deterministic — output is byte-identical each run)
python mcp-services/data/generate_listings.py

# Dev servers (preferred over docker for iteration; .claude/launch.json is configured)
#   use the Browser pane's preview_start with {name: "agent-backend"} / {name: "frontend"}
```

**Always `docker compose down` when finished** — don't leave containers running.

---

## 6. File inventory (what exists and why)

### Spec-driven-development trail (READ THESE FIRST)
| File | Contents |
|---|---|
| `.specify/memory/constitution.md` | **5 non-negotiable principles** (see §8) |
| `specs/001-ai-car-matchmaker/spec.md` | 5 prioritized user stories (US1–US5), edge cases, FR-001…FR-012, key entities, SC-001…SC-006, assumptions |
| `specs/001-ai-car-matchmaker/plan.md` | Architecture, tech context, constitution gate check, project structure |
| `specs/001-ai-car-matchmaker/tasks.md` | **T001–T050 across M0–M6**, with completion state + detailed per-task notes on deviations and live findings |

### agent-backend (Python)
| File | Purpose |
|---|---|
| `agent/state.py` | `Phase` enum (6 phases), `InterviewState`, `SessionState`, `RankedRecommendation`, `Booking`, `PaymentConfirmation`. Has `missing_slots()`, `is_complete()`, `save_interview_slots()` (**overwrites, never appends**), and `available_tools()` (**the per-phase tool gate**) |
| `agent/graph.py` | Two things: (a) M1's minimal `build_graph()`/`compiled_graph()` persistence scaffold — **keep as-is**, `test_graph_persistence.py` depends on its exact shape; (b) M2's `build_interview_agent(checkpointer)` = real `create_deep_agent(...)`, plus `CarMatchmakerState(DeepAgentState)` carrying `session: dict` |
| `agent/tools.py` | `save_interview_state` — a `@tool` returning a LangGraph `Command` to update state |
| `agent/prompts.py` | `PHASE_SYSTEM_PROMPTS` — one prompt per phase. Listing-facing phases carry `UNTRUSTED_DATA_RULE` (Principle IV) |
| `agent/llm.py` | `build_model()` selects a client from `LLM_PROVIDER` (`google` → `ChatGoogleGenerativeAI`, default model `gemini-3.6-flash`; `openai_compatible` → `ChatOpenAI` + `LLM_BASE_URL`). Raises `LLMNotConfiguredError` if `LLM_API_KEY` is missing |
| `agent/render_a2ui.py` | `build_interview_surface_init()` / `build_interview_surface_update()`. **A2UI protocol v0.9**, catalog `https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json` |
| `api/main.py` | FastAPI. `GET /health`, `WS /ws/{session_id}`. Owns the SqliteSaver lifespan |
| `observability/otel_setup.py` | `setup_observability()` → `phoenix.otel.register(..., protocol="grpc", auto_instrument=True)` |
| `app_stub.py` | **Dead M0 leftover** — safe to delete (Dockerfile now runs uvicorn) |
| `.env` / `.env.example` | Secrets / committed template |
| `tests/` | 7 test modules (see §2) |

### mcp-services (Python)
| File | Purpose |
|---|---|
| `data/generate_listings.py` | Deterministic generator, `SEED=20260807`. 10 categories × 20 brands = 200 + **3 adversarial prompt-injection probes** (ids `ADV-0001..0003`) = **203 listings** |
| `data/listings.json` | Committed output, verified byte-identical to a fresh generate |
| `tests/test_generate_listings.py` | 7 tests incl. the **SC-006 compliance check** |
| `app_stub.py` | Still the M0 health stub — **replace in M3** with the real MCP servers |

### frontend (React + Vite + TypeScript)
`src/App.tsx` (chat + A2UI surface), `src/main.tsx`, `index.html`,
`package.json` (**`@a2ui/react` + `@a2ui/web_core` v0.10.2**, React 19,
Vite 8), multi-stage `Dockerfile` (node build → nginx).

---

## 7. Hard-won findings — READ BEFORE CODING (do not rediscover these)

These cost real debugging time. Every one is verified, not assumed.

### A2UI
1. **Use protocol v0.9, not v1.0.** The docs advertise v1.0, but the only real
   installable renderer (`@a2ui/react` v0.10.2 on npm) ships **v0_8/v0_9 builds
   only — there is no v1_0 export**. Verified by fetching and diffing both spec
   versions; v0.9's message/component shapes are compatible with v1.0's.
2. **`@a2ui/react@0.10.2`'s `"./styles/structural.css"` export is broken** —
   points at a file not actually in the published package. The import was
   dropped; components render unstyled but functional. Styling is a known open
   item (see §10).
3. `@a2ui/react` **does exist on npm** — the original plan.md assumption that
   we'd hand-roll a Lit embed was wrong (in our favor). plan.md's text still
   says Lit in places; tasks.md T019 records the deviation.

### LangGraph / DeepAgents
4. `InjectedState` **only resolves inside a real compiled graph**. Unit tests
   must call the tool via `save_interview_state.func(...)` directly. Confirmed
   empirically.
5. `SqliteSaver.from_conn_string()` is a **context manager** (`Iterator[SqliteSaver]`),
   use `with ... as checkpointer:`.
6. Graph state must be **plain-JSON-able** — `SessionState` is stored as
   `.model_dump(mode="json")` under the `session` key, and rehydrated to the
   pydantic model in application code.
7. **Do not "clean up" M1's `build_graph`/`_touch` scaffold.** It's intentionally
   kept: a fast LLM-free graph is the right tool for testing the persistence
   layer in isolation, and `test_graph_persistence.py` depends on its shape.

### Phoenix
8. **Reading spans back**: `GET /v1/spans?project_name=…` **does not work**
   (that route needs a POST body → 422). The working read path is:
   `GET /v1/projects` → find project by name → `GET /v1/projects/{id}/spans`.
9. Phoenix takes **~15–20 s** to become HTTP-ready after container start. Poll,
   don't sleep-and-hope.
10. Ingestion is async even after `force_flush()` — poll with a deadline.

### pytest
11. **Never** set env vars at module level (`os.environ.setdefault(...)`) in a
    test file. It executes at **collection time** and leaks into *other* modules'
    `skipif` evaluations — this actually happened and caused a live-LLM test to
    attempt a real call with a fake key instead of skipping. Use function-scoped
    `monkeypatch.setenv`, which pytest auto-reverts.
12. **Run the full suite together**, not file-by-file — the leak above was
    invisible in isolation.

### Tooling / environment
13. `.gitignore`'s `.env.*` pattern wrongly excluded **`.env.example`** (the
    committed template). Fixed with an explicit negation — don't reintroduce.
14. Earlier, `.gitignore` also wrongly excluded **`.specify/.gitignore`**, a
    legitimate spec-kit file. Fixed in `4c70a45`.
15. The Browser tool's **coordinate-based clicks/typing don't reliably trigger
    React's controlled-input handlers.** Workaround that works: set the input
    via the **native value setter + `dispatchEvent`**, and click via `.click()`.
    This is a tooling quirk, **not an app bug** — confirmed by driving the
    WebSocket directly from the console first.
16. No `sudo`, no `gh` — use `curl` + the token from `~/.git-credentials`.

---

## 8. The 5 constitution principles (enforce in all future code)

Full text in `.specify/memory/constitution.md`.

1. **Grounded Recommendations (NON-NEGOTIABLE)** — every price/spec/availability
   shown must be traceable verbatim to a tool-call result. The LLM never retypes
   numeric listing data; `render_a2ui.py` reads structured tool output directly.
2. **Explicit Phase Gating** — the flow is a *code-enforced* state machine.
   `SessionState.available_tools()` decides which tools the model even sees.
   Transactional tools are unreachable out of phase.
3. **Mock-Only Transactions** — no real payment path, no BMW APIs, no
   persistence of card-like data in DB/logs/traces. Synthetic confirmation IDs only.
4. **Untrusted Data Boundary** — marketplace listing text and MCP-App form input
   are **data, never instructions**. Wrap in explicit untrusted-data delimiters.
   (Deferred in M2 since interview input is the user's own words; **REQUIRED in M3**
   when listing descriptions enter the prompt — the `ADV-*` probes exist to test this.)
5. **Full Observability** — every LLM call, tool call, and phase transition emits
   an OTel span. Process-level registration, not opt-in per call site.

---

## 9. NEXT UP: M3 — Research & Ranked Recommendations (User Story 2)

Tasks **T020–T029** in `tasks.md` (Phase 4). Summary:

| Task | Work |
|---|---|
| T023 | `mcp-services/marketplace/`: real MCP server (Python SDK) exposing `search_listings`, `get_listing_details` over **Streamable HTTP**; replace `mcp-services/app_stub.py` |
| T024 | Wire `langchain-mcp-adapters` into agent-backend. **⚠️ Its current API is unverified** — plan.md flags this as NEEDS VERIFICATION. Check the real API before writing code |
| T025 | `agent/graph.py`: RESEARCHING phase node (search → rank → reasoning), transition to RESULTS_READY |
| T026 | `agent/render_a2ui.py`: **two new A2UI surfaces** — reasoning-steps (live during search) *and* catalogue. Both fed from structured tool output only (Principle I) |
| T027 | `mcp-apps-ui/listing-detail/`: the marketplace MCP App iframe (single-listing deep-dive) |
| T028 | Frontend: render both surfaces; wire listing selection back to the agent |
| T020 | Unit tests: hard filters (category, budget, transaction_type, availability) |
| T021 | Integration test: zero-match → agent **relaxes a constraint and says so**, never fabricates |
| T022 | Snapshot test: A2UI catalogue values **exactly equal** tool-call record values (Principle I / SC-002) |
| T029 | **Security test**: the 3 `ADV-*` seeded listings must cause **zero** behavioral deviation (Principle IV) |

**Note**: `mcp-apps-ui/`, `frontend/src/{chat,a2ui,mcp-app-host}/`,
`mcp-services/{marketplace,booking,payment}/` directories don't exist yet — git
doesn't track empty dirs, and M2's frontend went into `frontend/src/App.tsx`
directly. Create as needed; plan.md's tree is the intended target layout, not
current reality.

---

## 13. M2.5 — what the pre-M3 audit found (read before trusting a doc)

A full audit (fresh clone, fresh venv, fresh Docker build, live stack, live
WebSocket session) ran before M3. It found that **plan.md's Constitution
Check table recorded two principles as PASS while the code had no such path
at all**:

| Was claimed | Reality found | Now |
|---|---|---|
| Principle V — "OTel registration is process-level init" | `setup_observability()` had **zero** production callers. A live session against the running stack produced **zero spans** in Phoenix. FR-012 and the observability *bonus* were unmet. | Called from FastAPI lifespan before any agent is built; fail-soft. `test_observability_wiring.py` |
| Principle II — "tool list is filtered per-phase in graph.py" | `available_tools()` had **zero** production callers; `build_interview_agent()` hardcoded its tools. | `TOOLS_BY_PHASE` is the single gate; `PhaseAgentRegistry` builds one agent per phase from it. `test_phase_gate.py` |

Also fixed: `agent.invoke()` blocking the async event loop (serialized all
concurrent sessions); backend dying at startup without an API key; frontend
Docker build ignoring `package-lock.json`; no guard that committed
`listings.json` matched its generator; Gemini content-blocks being sent
where the frontend expects a string.

**Accepted deviation**: `create_deep_agent` always installs
`FilesystemMiddleware`, binding 9 built-in tools (`ls`, `read_file`,
`write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`, `task`) in
*every* phase, outside our gate — not removable via its public API. Safe
because the default `StateBackend` is a virtual filesystem in graph state:
it never touches the host and has no `execute` implementation, so shell
execution is inert. `test_phase_gate.py` pins the built-in set and asserts
`StateBackend.execute` stays absent, so a dependency upgrade that widens
the agent's reach fails the suite. **Re-check this at M3**, when untrusted
listing text starts reaching the model.

**Lesson worth keeping**: "tests pass" and "a table says PASS" did not mean
the feature existed. The thing that caught both was running the live stack
and querying Phoenix for actual spans, plus grepping for call sites of
functions the docs claimed were load-bearing.

---

## 10. Open items / known gaps

- **Slide deck template** — organizers haven't provided it yet. T049 blocked.
- **Demo video** — T050. Recording is the user's to do; the agent can script it.
- **A2UI styling** — components render unstyled due to the broken CSS export
  (§7.2). Needs custom styling for demo polish.
- **LLM quota** — Gemini free tier is ~20 req/day/model. **A billed key is
  required before the demo and before the T046 eval run.**
- **`langchain-mcp-adapters` API unverified** — must be checked at M3 start.
- **`docker-compose.yml` has no `healthcheck:` blocks** — `depends_on` only
  waits for container start, not readiness. Harmless today (tracing is
  fail-soft) but worth adding for demo robustness.
- **Nothing consumes `Phase.RESEARCHING` yet** — `save_interview_slots()`
  flips the phase, but no code acts on it, so the interview agent keeps
  running. This is exactly M3/T025's job.

*(Resolved in M2.5: `app_stub.py` deleted; plan.md's stale Lit reference and
its two false Constitution PASS rows corrected; OpenRouter replaced.)*

---

## 11. Working agreements with the user

- **Do NOT immediately write code.** Understand → evaluate → design → validate →
  *then* implement. The user explicitly asked for this and re-confirms it.
- **Work in phases**, don't build everything in one response.
- **Verify, don't assume.** The user values live end-to-end verification
  (real browser, real Docker build) over "tests pass." Multiple real bugs were
  caught this way in M2.
- **Audit before advancing.** The user asks for a re-check of prior milestones
  before starting a new one. Both audits so far found real bugs — take it seriously,
  use a **fresh `git clone` into a temp dir + fresh venv + fresh docker build** as
  the bar (this is what caught the `.specify/.gitignore` issue).
- **Be objective**; challenge the docs and the plan where a better approach exists.
  Distinguish facts / assumptions / recommendations / unknowns. Never fabricate.
- **Push cadence is pre-authorized**: commit + push after each milestone once its
  tests pass. No need to ask each time.
- **Keep `tasks.md` checkboxes truthful as you go** (an early audit caught stale
  checkboxes; don't repeat that).
- Report failures honestly with the actual output.

---

## 12. Required reading

For a new session, read in this order:

1. **`HANDOFF.md`** ← this file (full context + gotchas)
2. **`.specify/memory/constitution.md`** — the 5 principles all code must honor
3. **`specs/001-ai-car-matchmaker/spec.md`** — user stories, FRs, success criteria
4. **`specs/001-ai-car-matchmaker/tasks.md`** — task state + detailed per-task
   notes (especially Phase 3's "Live-verification findings" and Phase 4 = next work)
5. **`specs/001-ai-car-matchmaker/plan.md`** — architecture (⚠️ Lit reference is stale)
6. **`README.md`** — run instructions

Then, before writing M3 code:

7. `agent-backend/agent/state.py` — the phase gate + entity shapes everything builds on
8. `agent-backend/agent/graph.py` — how the DeepAgents agent is assembled
9. `agent-backend/agent/render_a2ui.py` — the A2UI surface pattern to copy for
   the catalogue/reasoning surfaces
10. `agent-backend/api/main.py` — the WebSocket contract the frontend depends on
11. `mcp-services/data/generate_listings.py` — the listing schema M3 will query

**Suggested opening prompt for the new chat:**

> Read `/home/abbas/ai-car-matchmaker/HANDOFF.md` in full, then the files it
> lists under "Required reading". This is a hackathon project; M0/M1/M2 are
> done and pushed. Don't write code yet — confirm you have full context and
> tell me your plan for M3 (Research & Ranked Recommendations, tasks T020–T029).
