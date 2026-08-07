# Session Handoff — AI Car Matchmaker

**Purpose of this file**: complete context transfer so a new chat session can
continue this project with zero re-discovery and without repeating mistakes
already made and fixed. Read this file first, then the files listed in
[§13 Required reading](#13-required-reading).

**Last updated**: 2026-08-08, after **M2.5** (audit remediation) shipped and
was pushed (`fc54d31`).

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

| # | Requirement | Status |
|---|---|---|
| 1 | Multistep agent: interview → research → ranked+explained recommendations | 🟡 interview done; research = M3 |
| 2 | Interview captures: use case, car type/category, budget, buy-vs-rent, target date | ✅ |
| 3 | **Form-filling MUST be an MCP App** rendered inside the chat | ⬜ M4a |
| 4 | **Mock payment/checkout MUST be an MCP App** rendered inside the chat | ⬜ M4b |
| 5 | Car catalogue + live agent progress (interview state, search status, **reasoning steps**) MUST render via **A2UI** — explicitly *"not static HTML"* | 🟡 progress surface live; catalogue + reasoning = M3 |
| 6 | No real payments, no BMW Group APIs — checkout fully mocked | ✅ by construction |
| 7 | Mock marketplace: **≥100 listings, ≥10 categories, ≥10 brands per category** | ✅ 203 / 10 / 20 |
| 8 | Maintain state across interview/research/recommendation (multistep memory) | ✅ checkpointer proven across restart + session isolation |
| 9 | Approved harness: Claude Agent SDK **or LangChain DeepAgents** or OpenAI Agents SDK | ✅ DeepAgents |
| 10 | Spec-driven development (e.g. GitHub spec-kit) | ✅ full trail |
| 11 | Ship as Docker container **or** deployed public app | ✅ `docker compose up` verified |
| 12 | Public GitHub repo, documented, README with run instructions | ✅ |
| 13 | Short slide deck (template from organizers — **not yet received**) | ⬜ blocked |
| 14 | Short video demo of the working app | ⬜ |
| 15 | **Bonus**: AI observability + evals via Langfuse or Arize Phoenix over OTel | 🟡 observability ✅ (real spans verified); **evals still owed** (T046) |

### Locked-in decisions (made by the user, do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Agent harness | **LangChain DeepAgents** | User's explicit choice |
| Marketplace data | **Mock dataset** | Reliability for demo; no API keys/rate limits |
| Marketplace access | **Also built as an MCP App** | User's explicit choice (spec allows plain API, user opted for the richer path) |
| Observability | **Arize Phoenix** | User's explicit choice; OSS, self-hosts in compose |
| Frontend | **React + Vite**, `@a2ui/react` renderer | See §8 |
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
M2.5 ✅ Audit remediation — see §3. Two Constitution principles were recorded
        as PASS in plan.md while having no production code path at all.
M3   ⬜ NEXT — Research & Ranked Recommendations (User Story 2), T020–T029
M4a  ⬜ Booking form MCP App (User Story 3)
M4b  ⬜ Mock checkout MCP App (User Story 4)
M4c  ⬜ Session resume (User Story 5)
M5   ⬜ Evals (observability itself is now wired, M2.5/T051)
M6   ⬜ Hardening, E2E tests, README finalization, deck, demo video
```

**Test suite**: 53 total.
- **47 pass with no external setup** — 39 `agent-backend` + 8 `mcp-services`
- **All 53 pass** with a live LLM key *and* Phoenix running (verified 2026-08-08)

⚠️ The credential gate checks key **presence** only. With a key set but out
of quota, the live tests **fail** rather than skip. Check the provider
account before assuming a code bug.

**Git log** (main, clean, synced with origin):
```
fc54d31  M2.5 follow-up: fix enum/float leaking into the A2UI progress surface
b5a0bcb  M2.5: audit remediation — wire observability and the phase gate, swap LLM provider
fa5faec  Add HANDOFF.md — full session context transfer document
6cef214  M2: Conversational Interview (User Story 1) end to end
33598e6  M1: mock dataset, session-state schema, checkpointer persistence, tracing
4c70a45  M0 audit fixes: track .specify/.gitignore, sync task checkboxes, document dataset assumption
```

---

## 3. M2.5 — what the pre-M3 audit found (read before trusting any doc)

A full audit (fresh clone, fresh venv, fresh Docker build, live stack, live
WebSocket session) ran before M3. It found that **plan.md's Constitution
Check table recorded two principles as PASS while the code had no such path
at all**:

| Was claimed | Reality found | Now |
|---|---|---|
| Principle V — "OTel registration is process-level init" | `setup_observability()` had **zero** production callers. A live session against the running stack produced **zero spans** in Phoenix. FR-012 and the observability *bonus* were unmet. | Called from FastAPI lifespan *before* any agent is built; fail-soft. Verified: **8 real spans** for one session. `test_observability_wiring.py` |
| Principle II — "tool list is filtered per-phase in graph.py" | `available_tools()` had **zero** production callers; `build_interview_agent()` hardcoded its tools. | `TOOLS_BY_PHASE` is the single gate; `PhaseAgentRegistry` builds one agent per phase from it. `test_phase_gate.py` |

Also fixed: `agent.invoke()` blocking the async event loop (serialized all
concurrent sessions); backend dying at startup without an API key; frontend
Docker build ignoring `package-lock.json`; no guard that committed
`listings.json` matched its generator; Gemini content-blocks sent where the
frontend expects a string; `TransactionType.BUY` / `30000.0` shown to users.

**Lesson worth keeping**: "tests pass" and "a table says PASS" did not mean
the feature existed. What caught both was **running the live stack and
querying Phoenix for actual spans**, plus **grepping for call sites** of
functions the docs claimed were load-bearing. Do this again before M4.

---

## 4. Architecture

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
│   ├─ agent/state.py       SessionState + TOOLS_BY_PHASE gate       │
│   ├─ agent/prompts.py     PHASE_SYSTEM_PROMPTS + UNTRUSTED_DATA_RULE│
│   ├─ agent/render_a2ui.py deterministic domain → A2UI JSON         │
│   ├─ agent/llm.py         Gemini via langchain-google-genai        │
│   ├─ api/main.py          WebSocket bridge + message_text()        │
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

## 5. Environment facts (this machine)

| Item | Value |
|---|---|
| Working dir | `/home/abbas/ai-car-matchmaker` |
| Python | 3.14.4 — venv at `./.venv` (gitignored) |
| Node | 22.22.1 (npm 10.9.8 inside the node:22-slim build image) |
| Docker | 29.6.1, Compose v5.3.1 |
| Git | 2.53.0, user `Abbas` / `mohdabbassafvi23@gmail.com` |
| **`gh` CLI** | **NOT INSTALLED**, and `sudo apt-get` **fails** (no TTY for auth). Use the **GitHub REST API via `curl`** instead. |
| GitHub token | In `~/.git-credentials` (scope: `repo`). Extract with:<br>`TOKEN=$(sed -nE 's#https://([^:@]+:)?([^@]+)@github.com#\2#p' ~/.git-credentials \| head -1)` |
| `uv` / `specify` | Installed at `~/.local/bin` — `export PATH="$HOME/.local/bin:$PATH"` |
| spec-kit CLI flag | It is `--integration claude`, **not** `--ai`; also needs `--ignore-agent-tools` here |
| ⚠️ Sandbox | Outbound POSTs to LLM providers **fail inside the default tool sandbox**. Live-LLM commands need `dangerouslyDisableSandbox: true`. `GET`s often work, which makes this confusing — a provider "outage" is usually this. |

**Secrets**: `agent-backend/.env` holds `LLM_API_KEY` (gitignored, `chmod 600`,
verified absent from both the built image and the JS bundle).
`agent-backend/.env.example` is the committed no-secrets template. Never
commit real values; never echo the key into logs or traces. **Scan staged
diffs before committing** (`git diff --cached | grep -E "^\+" | grep -E "<key pattern>"`).

### ⚠️ LLM provider status (changed in M2.5 — read all of this)

- **Current**: Google Gemini, `LLM_PROVIDER=google`, default model
  `gemini-3.6-flash`, via the **native** `langchain-google-genai` client.
- **Gemini free tier is ~20 requests/day/model.** Enough for a smoke test,
  *not* for a demo, and not for M3's behavioral tests or the T046 eval run.
  **A billed key is needed.** Each model has its own quota, so switching
  `LLM_MODEL` buys headroom during development.
- **`gemini-2.5-*` is unusable** — rejected for newly-created keys with
  "no longer available to new users". Don't retry it.
- **Do NOT switch Gemini to its OpenAI-compat endpoint.** Gemini 3.x are
  thinking models; their function calls carry a `thought_signature` that
  must be echoed back. The compat layer drops it, so the **second** turn of
  every tool-using conversation dies with `400 INVALID_ARGUMENT`. Verified
  directly; `reasoning_effort` does **not** fix it. Every phase of this
  agent is tool-driven, so the compat path is unusable for Gemini.
- **OpenRouter is exhausted** — free tier, ~$0 left. A 20-token probe
  succeeds; the app's configured calls return `402`. No longer wired.
- **NVIDIA NIM was tried as a fallback and did not work here** — `/models`
  responds fine, but non-streaming `/chat/completions` returned nothing in
  120 s, and large tool-laden requests hung even when streaming. The
  `openai_compatible` provider path exists and is wired but is
  **unverified end-to-end**.

---

## 6. How to run everything

```bash
cd /home/abbas/ai-car-matchmaker

# Full stack (what judges will run)
docker compose up --build
#   frontend        http://localhost:3000
#   agent-backend   http://localhost:8000/health
#   mcp-services    http://localhost:8100
#   phoenix         http://localhost:16006

# Tests (run the FULL suite together, never file-by-file — see §8.11)
source .venv/bin/activate
(cd mcp-services  && python -m pytest tests/ -q)
(cd agent-backend && python -m pytest tests/ -q)
#   6 tests auto-skip without LLM_API_KEY / running Phoenix — correct behavior

# With live LLM (costs quota — see §5) and Phoenix:
set -a && . agent-backend/.env && set +a
(cd agent-backend && python -m pytest tests/ -q)   # 45 pass, 0 skip

# Regenerate mock dataset (deterministic — output is byte-identical each run)
python mcp-services/data/generate_listings.py

# Dev servers (preferred over docker for iteration; .claude/launch.json is configured)
#   use the Browser pane's preview_start with {name: "agent-backend"} / {name: "frontend"}
```

**Always `docker compose down` when finished** — don't leave containers running.

**Health endpoint tells you the config state**:
`{"status":"ok","llm_configured":true,"tracing_enabled":true}` — `degraded`
means no LLM key; `tracing_enabled:false` means Phoenix registration failed.

---

## 7. File inventory (what exists and why)

### Spec-driven-development trail (READ THESE FIRST)
| File | Contents |
|---|---|
| `.specify/memory/constitution.md` | **5 non-negotiable principles** (see §9) |
| `specs/001-ai-car-matchmaker/spec.md` | US1–US5, edge cases, FR-001…FR-012, key entities, SC-001…SC-006, assumptions |
| `specs/001-ai-car-matchmaker/plan.md` | Architecture, tech context, Constitution gate check (**with the M2.5 correction recorded**), project structure |
| `specs/001-ai-car-matchmaker/tasks.md` | **T001–T059 across M0–M6**, incl. **Phase 3.5 = M2.5** audit-remediation tasks T051–T059 |

### agent-backend (Python)
| File | Purpose |
|---|---|
| `agent/state.py` | `Phase` (6), `InterviewState`, `SessionState`, `RankedRecommendation`, `Booking`, `PaymentConfirmation`. **`TOOLS_BY_PHASE` + `tool_names_for_phase()` are the phase gate**; `SessionState.available_tools()` delegates to them. `save_interview_slots()` **overwrites, never appends** |
| `agent/graph.py` | (a) M1's minimal `build_graph()`/`compiled_graph()` persistence scaffold — **keep as-is**, `test_graph_persistence.py` depends on its exact shape. (b) `TOOL_REGISTRY` (name→tool), `tools_for_phase()`, `build_agent_for_phase()`, **`PhaseAgentRegistry`** (one cached agent per phase — this is what makes Principle II real), `build_interview_agent()` convenience wrapper, `CarMatchmakerState(DeepAgentState)` carrying `session: dict` |
| `agent/tools.py` | `save_interview_state` — a `@tool` returning a LangGraph `Command` to update state |
| `agent/prompts.py` | `PHASE_SYSTEM_PROMPTS` — one prompt per phase (a missing entry fails at startup). Listing-facing phases embed `UNTRUSTED_DATA_RULE` (**Principle IV**) |
| `agent/llm.py` | `build_model()` selects by `LLM_PROVIDER`: `google` → `ChatGoogleGenerativeAI` (default `gemini-3.6-flash`); `openai_compatible` → `ChatOpenAI` + `LLM_BASE_URL`. `is_configured()`, `LLMNotConfiguredError`. `DEFAULT_MAX_TOKENS=4096` (thinking models burn budget before emitting tool calls) |
| `agent/render_a2ui.py` | `build_interview_surface_init()` / `_update()`, `_display()` (formats enums/floats without substituting values). **A2UI v0.9**, catalog `https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json` |
| `api/main.py` | FastAPI. `GET /health` (reports degraded), `WS /ws/{session_id}`. Owns SqliteSaver lifespan, registers observability, selects agent by phase, runs `agent.invoke` via `asyncio.to_thread`, normalizes content via **`message_text()`** |
| `observability/otel_setup.py` | `setup_observability()` → `phoenix.otel.register(..., protocol="grpc", auto_instrument=True)` |
| `.env` / `.env.example` | Secrets / committed template |
| `tests/` | **10 modules**: `test_state`, `test_tools`, `test_graph_persistence`, `test_render_a2ui`, `test_chat_endpoint`, `test_chat_endpoint_error_handling`, `test_interview_agent`, `test_otel_setup`, **`test_phase_gate`**, **`test_observability_wiring`**, **`test_message_text`** |

### mcp-services (Python)
| File | Purpose |
|---|---|
| `data/generate_listings.py` | Deterministic generator, `SEED=20260807`. 10 categories × 20 brands = 200 + **3 adversarial prompt-injection probes** (`ADV-0001..0003`) = **203 listings** |
| `data/listings.json` | Committed output; a test now asserts it equals `generate()` |
| `tests/test_generate_listings.py` | **8 tests** incl. the SC-006 compliance check and the committed-file guard |
| `app_stub.py` | Still the M0 health stub — **replace in M3 (T023)** with the real MCP servers |
| `marketplace/`, `booking/`, `payment/` | Empty dirs on disk (git doesn't track empty dirs) |

### frontend (React + Vite + TypeScript)
`src/App.tsx` (chat + A2UI surface), `src/main.tsx`, `index.html`,
`package.json` (**`@a2ui/react` + `@a2ui/web_core` v0.10.2**, React 19,
Vite 8), multi-stage `Dockerfile` (**`npm ci` with the lockfile** → nginx).

---

## 8. Hard-won findings — READ BEFORE CODING (do not rediscover these)

Every one is verified, not assumed.

### LLM provider (M2.5)
1. **Gemini 3.x + OpenAI-compat = broken tool calling.** `thought_signature`
   is dropped; turn 2 of any tool conversation 400s. Use the native client.
   See §5.
2. **Gemini returns `AIMessage.content` as a *list of content blocks***, not
   a string. `api/main.py`'s `message_text()` flattens it at the wire
   boundary and drops thinking/reasoning blocks. Any new place that reads
   `.content` must go through it.
3. **`(str, Enum)` members stringify as `TransactionType.BUY`**, not `buy` —
   `Enum` overrides `__str__`. Use `.value` for anything user-facing.
   `render_a2ui._display()` handles this plus whole-dollar floats.

### DeepAgents / LangGraph
4. **`create_deep_agent` always installs `FilesystemMiddleware`**, binding 9
   built-in tools (`ls`, `read_file`, `write_file`, `edit_file`, `delete`,
   `glob`, `grep`, `execute`, `task`) in **every** phase, outside our gate.
   **Not removable** via its public API (`middleware=` appends to the base
   stack, it doesn't replace it). Safe today because the default
   `StateBackend` is a **virtual filesystem in graph state** — never touches
   the host — and has **no `execute` method**, so shell execution is inert.
   `test_phase_gate.py` pins the built-in set and asserts
   `StateBackend.execute` stays absent. **Re-evaluate at M3**, when
   untrusted listing text starts reaching the model.
5. **A DeepAgents agent's tools are fixed at construction.** That's why the
   phase gate is one agent *per phase* (`PhaseAgentRegistry`) rather than
   filtering at call time.
6. `InjectedState` **only resolves inside a real compiled graph**. Unit tests
   must call the tool via `save_interview_state.func(...)` directly.
7. `SqliteSaver.from_conn_string()` is a **context manager**, use `with`.
8. Graph state must be **plain-JSON-able** — `SessionState` is stored as
   `.model_dump(mode="json")` under `session`, rehydrated in app code.
9. **Do not "clean up" M1's `build_graph`/`_touch` scaffold.** A fast
   LLM-free graph is the right tool for testing persistence in isolation.
10. Compiled-agent tool introspection:
    `agent.nodes["tools"].bound.tools_by_name` (note: **not** `_tools_by_name`).

### A2UI
11. **Use protocol v0.9, not v1.0.** `@a2ui/react` v0.10.2 ships v0_8/v0_9
    builds only — there is no v1_0 export. v0.9's shapes are compatible.
12. **`@a2ui/react@0.10.2`'s `"./styles/structural.css"` export is broken** —
    points at a file not in the published package. Import dropped; components
    render unstyled but functional. Styling is an open item (§11).
13. `@a2ui/react` **does exist on npm** — the original "hand-roll a Lit embed"
    assumption was wrong, in our favor.

### Phoenix
14. **Reading spans back**: `GET /v1/spans?project_name=…` **does not work**
    (needs a POST body → 422). Working path: `GET /v1/projects` → find by
    name → `GET /v1/projects/{id}/spans`.
15. Phoenix takes **~15–20 s** to become HTTP-ready. Poll, don't sleep.
16. Ingestion is async even after `force_flush()` — poll with a deadline.
17. `setup_observability()` must run **before** any agent is constructed —
    `auto_instrument` patches LangChain globally.
18. Tracing must be **fail-soft**: an unreachable collector must not take the
    app down. It's an observability aid, not a request-path dependency.

### pytest
19. **Never** set env vars at module level (`os.environ.setdefault(...)`) in a
    test file. It executes at **collection time** and leaks into *other*
    modules' `skipif` evaluations — this really happened. Use function-scoped
    `monkeypatch.setenv`.
20. **Run the full suite together**, not file-by-file — the leak above was
    invisible in isolation.
21. Credential gates check key **presence**, so an out-of-quota key produces
    **failures, not skips**. Check the account before debugging code.

### Tooling / environment
22. `.gitignore`'s `.env.*` pattern wrongly excluded **`.env.example`**. Fixed
    with an explicit negation — don't reintroduce.
23. `.gitignore` also once wrongly excluded **`.specify/.gitignore`**.
24. The Browser tool's **coordinate-based clicks/typing don't reliably trigger
    React's controlled-input handlers.** Workaround: set the input via the
    **native value setter + `dispatchEvent`**, click via `.click()`. Tooling
    quirk, **not an app bug**.
25. No `sudo`, no `gh` — use `curl` + the token from `~/.git-credentials`.
26. **Concurrent heavy background jobs cause spurious failures** — a
    `docker compose build` running alongside a big `pip install` failed
    `npm ci` once, then passed cleanly on its own. Re-run before debugging.

---

## 9. The 5 constitution principles (enforce in all future code)

Full text in `.specify/memory/constitution.md`.

1. **Grounded Recommendations (NON-NEGOTIABLE)** — every price/spec/availability
   shown must be traceable verbatim to a tool-call result. The LLM never retypes
   numeric listing data; `render_a2ui.py` reads structured output directly and
   may *format* but never substitute.
2. **Explicit Phase Gating** — a *code-enforced* state machine. `TOOLS_BY_PHASE`
   is the single gate definition; `PhaseAgentRegistry` builds one agent per
   phase from it. Transactional tools are unreachable out of phase because
   they are never bound. *(Genuinely enforced since M2.5 — see §3.)*
3. **Mock-Only Transactions** — no real payment path, no BMW APIs, no
   persistence of card-like data in DB/logs/traces. Synthetic confirmation IDs only.
4. **Untrusted Data Boundary** — marketplace listing text and MCP-App form input
   are **data, never instructions**. `UNTRUSTED_DATA_RULE` is already embedded
   in every listing-facing phase prompt and asserted by `test_phase_gate.py`.
   **The behavioral proof is still owed**: T029 must show the three `ADV-*`
   probes cause zero deviation.
5. **Full Observability** — every LLM call, tool call, and phase transition emits
   an OTel span. Process-level registration, not opt-in per call site.
   *(Genuinely wired since M2.5 — see §3.)*

---

## 10. NEXT UP: M3 — Research & Ranked Recommendations (User Story 2)

Tasks **T020–T029** in `tasks.md` (Phase 4).

| Task | Work |
|---|---|
| T023 | `mcp-services/marketplace/`: real MCP server (Python SDK) exposing `search_listings`, `get_listing_details` over **Streamable HTTP**; replace `mcp-services/app_stub.py`. Add `mcp` to `mcp-services/requirements.txt` |
| T024 | Wire `langchain-mcp-adapters` into agent-backend. **⚠️ API still unverified — check it against the installed version before writing code.** Add to `agent-backend/requirements.txt` |
| T025 | `agent/graph.py`: RESEARCHING phase behavior (search → rank → reasoning), transition to RESULTS_READY. **Register the new tools in `TOOL_REGISTRY`** — the gate already names them |
| T026 | `agent/render_a2ui.py`: **two new A2UI surfaces** — reasoning-steps (live during search) *and* catalogue. Both fed from structured tool output only (Principle I) |
| T027 | `mcp-apps-ui/listing-detail/`: the marketplace MCP App iframe (single-listing deep-dive) |
| T028 | Frontend: render both surfaces; wire listing selection back to the agent |
| T020 | Unit tests: hard filters (category, budget, transaction_type, availability) |
| T021 | Integration test: zero-match → agent **relaxes a constraint and says so**, never fabricates |
| T022 | Snapshot test: A2UI catalogue values **exactly equal** tool-call record values (Principle I / SC-002) |
| T029 | **Security test**: the 3 `ADV-*` seeded listings must cause **zero** behavioral deviation (Principle IV) |

### 🔴 OPEN DECISION — the user has not answered this yet

**M3's behavioral tests (T021, T029) need many live LLM calls, and the Gemini
free tier allows ~20/day/model.** T029 is the one that actually proves
Principle IV. Options put to the user (they deferred answering):

1. **Build M3 now, defer the live tests** — implement everything with
   deterministic non-LLM tests; write T021/T029 to auto-skip until a billed
   key exists. Fastest to a demoable MVP; security proof lands later.
2. **User provides a billed key first** — build M3 with T021/T029 exercised
   live throughout. Slower to start, Principle IV proven properly.
3. **Scripted fake model for the behavioral tests** — deterministic, zero API
   calls, plus a thin live smoke test. Proves plumbing and our prompt
   construction, but not real model behavior.

**Ask the user which before starting M3.**

### Layout note

`mcp-apps-ui/` and `frontend/src/{chat,a2ui,mcp-app-host}/` don't exist yet;
`mcp-services/{marketplace,booking,payment}/` exist but are empty (git doesn't
track empty dirs). M2's frontend went into `frontend/src/App.tsx` directly.
Create as needed — plan.md's tree is the intended target, not current reality.

---

## 11. Open items / known gaps

- **🔴 LLM quota** — Gemini free tier ~20 req/day/model. **A billed key is
  required** for the demo, for M3's T021/T029, and for the T046 eval run.
- **Evals (bonus #15) still owed** — observability is real now, evals are not.
- **Slide deck template** — organizers haven't provided it. T049 blocked.
- **Demo video** — T050. Recording is the user's to do; the agent can script it.
- **A2UI styling** — components render unstyled (§8.12). Needs styling for polish.
- **`langchain-mcp-adapters` API unverified** — check at M3 start.
- **`docker-compose.yml` has no `healthcheck:` blocks** — `depends_on` only
  waits for container start, not readiness. Harmless today; worth adding.
- **Nothing consumes `Phase.RESEARCHING` yet** — the phase flips but no code
  acts on it, so the interview agent keeps running. That's M3/T025's job.
- **API keys were pasted into a chat transcript** (Gemini + an NVIDIA NIM key).
  Never committed. **Recommend rotating both after the hackathon.**

---

## 12. Working agreements with the user

- **Do NOT immediately write code.** Understand → evaluate → design → validate →
  *then* implement. The user re-confirms this every session.
- **Work in phases**, don't build everything in one response.
- **Verify, don't assume.** The user values live end-to-end verification
  (real browser, real Docker build, real span queries) over "tests pass."
  Every audit so far found real bugs this way.
- **Audit before advancing.** The user asks for a re-check of prior milestones
  before starting a new one. Bar: **fresh `git clone` into a temp dir + fresh
  venv + fresh docker build + live stack**.
- **Be objective**; challenge the docs and the plan where a better approach exists.
  Distinguish facts / assumptions / recommendations / unknowns. Never fabricate.
- **Push cadence is pre-authorized**: commit + push after each milestone once
  its tests pass. No need to ask each time.
- **Keep `tasks.md` checkboxes truthful as you go.**
- **Report failures honestly with the actual output.** If a claim in a doc
  turns out false, say so plainly and record the correction rather than
  quietly editing it.

---

## 13. Required reading

For a new session, read in this order:

1. **`HANDOFF.md`** ← this file (full context + gotchas)
2. **`.specify/memory/constitution.md`** — the 5 principles all code must honor
3. **`specs/001-ai-car-matchmaker/spec.md`** — user stories, FRs, success criteria
4. **`specs/001-ai-car-matchmaker/tasks.md`** — task state + per-task notes
   (Phase 3's "Live-verification findings", **Phase 3.5 = M2.5 remediation**,
   Phase 4 = next work)
5. **`specs/001-ai-car-matchmaker/plan.md`** — architecture + the corrected
   Constitution Check table
6. **`README.md`** — run instructions

Then, before writing M3 code:

7. `agent-backend/agent/state.py` — `TOOLS_BY_PHASE` gate + entity shapes
8. `agent-backend/agent/graph.py` — `PhaseAgentRegistry` / `TOOL_REGISTRY`;
   M3 registers its new tools here
9. `agent-backend/agent/prompts.py` — `UNTRUSTED_DATA_RULE` (Principle IV)
10. `agent-backend/agent/render_a2ui.py` — the surface pattern to copy for
    the catalogue/reasoning surfaces
11. `agent-backend/api/main.py` — the WebSocket contract the frontend depends on
12. `agent-backend/tests/test_phase_gate.py` — how the gate is proven; M3 must
    keep it passing
13. `mcp-services/data/generate_listings.py` — the listing schema M3 will query

**Suggested opening prompt for the new chat** — copy this verbatim:

> Read `/home/abbas/ai-car-matchmaker/HANDOFF.md` in full, then everything it
> lists under §13 Required reading.
>
> This is the Amulate Summer Hackathon 2026 "AI Car Matchmaker" project.
> M0, M1, M2 and M2.5 are complete, tested and pushed to `main` (`fc54d31`).
> M3 (Research & Ranked Recommendations, tasks T020–T029) is next.
>
> Do **not** write any code yet. First:
> 1. Confirm you have full context, and tell me anything in the docs that
>    looks wrong, stale, or self-contradictory — a previous audit found two
>    Constitution principles marked PASS with no implementation, so treat the
>    docs as claims to verify, not as truth.
> 2. Verify the `langchain-mcp-adapters` API against the installed version
>    before designing around it (HANDOFF §10 / T024 flags it as unverified).
> 3. Give me your M3 plan, and answer the open decision in HANDOFF §10 about
>    how to handle T021/T029 given the ~20 requests/day Gemini quota.
>
> Note: outbound POSTs to LLM providers fail inside the default tool sandbox —
> live-LLM commands need `dangerouslyDisableSandbox: true`.
