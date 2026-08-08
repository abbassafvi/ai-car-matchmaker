# Session Handoff — AI Car Matchmaker

**Purpose of this file**: complete context transfer so a new chat session can
continue this project with zero re-discovery and without repeating mistakes
already made and fixed. Read this file first, then the files listed in
[§13 Required reading](#13-required-reading).

**Last updated**: 2026-08-08, after **M3 Phase E** (T028) shipped.
M3 is *in progress* — Phases A–E are done, **F (behavioural tests) is not**.

> **Treat every claim in this file as a claim, not as truth.** Five separate
> audits have now found docs asserting behaviour the code did not have — and
> one found the inverse. The numbers below were measured on 2026-08-08, not
> copied forward. See §3.

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
| 1 | Multistep agent: interview → research → ranked+explained recommendations | ✅ interview → auto-research → deterministic ranking + explanations, all surfaced via **A2UI** since Phase D (verified live end to end) |
| 2 | Interview captures: use case, car type/category, budget, buy-vs-rent, target date | ✅ |
| 3 | **Form-filling MUST be an MCP App** rendered inside the chat | ⬜ M4a — **now unblocked**: `select_listing` exists and FORM_FILLING is reachable (Phase E) |
| 4 | **Mock payment/checkout MUST be an MCP App** rendered inside the chat | ⬜ M4b |
| 5 | Car catalogue + live agent progress (interview state, search status, **reasoning steps**) MUST render via **A2UI** — explicitly *"not static HTML"* | ✅ **satisfied in Phase D (T026)**. Three A2UI surfaces render live: `interview-progress`, `research-reasoning` (per-step trace with icons) and `catalogue` (ranked cards). The `{"type":"progress"}` placeholder is deleted. Verified in a real browser against the real stack |
| 6 | No real payments, no BMW Group APIs — checkout fully mocked | ✅ by construction |
| 7 | Mock marketplace: **≥100 listings, ≥10 categories, ≥10 brands per category** | ✅ 203 / 10 / 20 |
| 8 | Maintain state across interview/research/recommendation (multistep memory) | ✅ checkpointer proven across restart + session isolation + live WS reconnect |
| 9 | Approved harness: Claude Agent SDK **or LangChain DeepAgents** or OpenAI Agents SDK | ✅ DeepAgents (see §8.4b — this constrains us) |
| 10 | Spec-driven development (e.g. GitHub spec-kit) | ✅ full trail |
| 11 | Ship as Docker container **or** deployed public app | ✅ `docker compose up` verified |
| 12 | Public GitHub repo, documented, README with run instructions | ✅ |
| 13 | Short slide deck (template from organizers — **not yet received**) | ⬜ blocked |
| 14 | Short video demo of the working app | ⬜ |
| 15 | **Bonus**: AI observability + evals via Langfuse or Arize Phoenix over OTel | 🟡 observability ✅ (real spans verified); **evals still owed** (T046) |

### Locked-in decisions (made by the user, do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Agent harness | **LangChain DeepAgents** | User's explicit choice + requirement #9 |
| Marketplace data | **Mock dataset** | Reliability for demo; no API keys/rate limits |
| Marketplace access | **Also built as an MCP App** | User's explicit choice (spec allows plain API, user opted for the richer path) |
| Observability | **Arize Phoenix** | User's explicit choice; OSS, self-hosts in compose |
| Frontend | **React + Vite**, `@a2ui/react` renderer | See §8 |
| MCP server language | **Python** (MCP Python SDK) | Keeps backend single-language |
| Session store | LangGraph **AsyncSqliteSaver** | Zero external infra, real persistence (was SqliteSaver — see §3) |
| LLM provider (dev) | **Groq**, `openai/gpt-oss-120b` | ~1000 req/day vs Gemini's ~20 — see §5 |
| Push cadence | **Commit + push after each milestone, pre-authorized** | User approved; no per-push confirmation needed |

### Resolved architectural ambiguity (important)

The spec says marketplace access *may* be an MCP App, but *also* mandates A2UI
for the catalogue. Taken literally at the same surface these conflict (MCP Apps
render HTML in an iframe; A2UI mandates non-HTML declarative UI). **Resolution
agreed with the user:**

- Marketplace **MCP tools** (`search_listings`, `get_listing_details`) = the
  "protocol-based tool access" requirement. ✅ **built, M3 Phase B**
- The **primary catalogue + progress + reasoning-steps surfaces = A2UI**
  (satisfies the "not static HTML" clause).
- The marketplace MCP App's `ui://` resource is a *secondary* surface (a rich
  single-listing detail/compare view), additive rather than a competing
  implementation of the catalogue. **Recommended: defer past M4** (see §10).

---

## 2. Current status

```
M0   ✅ spec-kit scaffolding, constitution, spec/plan/tasks, 4-service compose skeleton
M1   ✅ mock dataset generator, session-state schemas, checkpointer persistence, Phoenix tracing
M2   ✅ Conversational Interview (User Story 1) — DeepAgents agent, A2UI surface, WebSocket API, React frontend
M2.5 ✅ Audit remediation — see §3
M3   🟡 IN PROGRESS — Research & Ranked Recommendations (User Story 2)
       ✅ Phase A  async agent path (blocking prerequisite, see §3)
       ✅ Phase B  T020 + T023 marketplace MCP server
       ✅ Phase C  T024 + T025 adapter wiring, ranking, research auto-kickoff
       ✅ Phase D  T026 + T022 A2UI catalogue + reasoning surfaces, themed
                   frontend, grounding snapshot test
       ✅ Phase E  T028 listing selection: select_listing tool + state
                   transition, catalogue Button, {"type":"action"} wiring
       ⬜ Phase F  T021 + T029 live behavioural tests
       ⬜ (T027 listing-detail MCP App — recommended deferred past M4)
M4a  ⬜ Booking form MCP App (User Story 3)
M4b  ⬜ Mock checkout MCP App (User Story 4)
M4c  ⬜ Session resume (User Story 5)
M5   ⬜ Evals (observability itself is wired, M2.5/T051)
M6   ⬜ Hardening, E2E tests, README finalization, deck, demo video
```

**Test suite: 164 total** (measured 2026-08-08 after Phase E, not copied forward).

| Suite | Tests | Gated | Files |
|---|---|---|---|
| `mcp-services` | **35** | 0 | `test_generate_listings` (8), `test_marketplace` (18), `test_marketplace_server` (9) |
| `agent-backend` | **129** | 3 | 16 modules, see §7 |

- **161 pass with no external setup** (35 + 126)
- **All 164 pass** with a live LLM key *and* Phoenix running — verified 2026-08-08
- Exactly **3** gated tests (`grep -rn skipif */tests/`): `test_interview_agent`
  and `test_chat_endpoint` (need `LLM_API_KEY`), `test_otel_setup` (needs Phoenix)

⚠️ The credential gate checks key **presence** only. With a key set but out
of quota, the live tests **fail** rather than skip. Check the provider
account before assuming a code bug.

**Git log** (main, clean, synced with origin). Lists the substantive commits;
a trailing `docs:` commit that stamps this section cannot list its own sha,
so this block may lag HEAD by one or two docs-only commits — check
`git log --oneline -5` rather than trusting it:
```
cf90320   docs: rewrite HANDOFF for a Phase D handoff  <- or later docs commits
82d4b6b  docs: point HANDOFF at Phase D and correct the Phase C references
701acda  docs: stamp the Phase C commit sha into HANDOFF's git log
dd7ab4a  M3 Phase C (T024, T025): MCP wiring, code-driven search, ranking
8e44793  M3 Phase C pre-flight audit: fix test collection, correct stale docs
2fa9fcf  docs: bring HANDOFF/README/plan/tasks up to M3 Phase B state
c6915fd  M3 Phase B (T020, T023): marketplace MCP server over Streamable HTTP
dea1576  M3 Phase A: async agent path, provider-aware token caps, doc corrections
c208807  docs: rewrite HANDOFF for M2.5 state and flag M3's open quota decision
fc54d31  M2.5 follow-up: fix enum/float leaking into the A2UI progress surface
b5a0bcb  M2.5: audit remediation — wire observability and the phase gate, swap LLM provider
6cef214  M2: Conversational Interview (User Story 1) end to end
```

---

## 3. The recurring failure mode — read before trusting any doc

**Docs in this repo have three times asserted behaviour the code did not
have.** Each was found by running things, never by reading.

### Found by the M2.5 audit (fixed in M2.5)

| Was claimed | Reality found |
|---|---|
| Principle V — "OTel registration is process-level init" | `setup_observability()` had **zero** production callers; a live session produced **zero** spans in Phoenix. Now called from FastAPI lifespan; verified with real spans. |
| Principle II — "tool list is filtered per-phase in graph.py" | `available_tools()` had **zero** production callers; `build_interview_agent()` hardcoded its tools. Now `TOOLS_BY_PHASE` + `PhaseAgentRegistry`. |

### Found by the M3 pre-flight review (fixed in M3 Phase A/B)

| Was claimed | Reality found |
|---|---|
| plan.md row I — Principle I "PASS" | PASS for a *mechanism*, not the principle. `render_a2ui.py` is genuinely deterministic, but every value it had ever rendered came from the user's own interview answers — **no listing price or spec had ever passed through it**. Downgraded to PARTIAL until T022/T026. |
| plan.md row IV — "delimiters are in every listing-facing prompt" | `<untrusted_listing_data>` appeared **exactly twice** in the repo: the prompt telling the model how to treat delimited content, and the test asserting the prompt says so. **Nothing wrapped anything.** Fixed in Phase B — the MCP server now wraps `description` at the tool-output boundary. |
| Test counts (3 files) | Claimed 47 pass / 39 agent-backend / 6 gated. Actual at the time: 50 / 42 / 3. |
| HANDOFF — "the interview agent keeps running after the phase flips" | False. `api/main.py` *does* switch agents on the persisted phase. The real gaps were that the RESEARCHING agent bound zero domain tools, and nothing triggers research without another user message. |
| HANDOFF layout note — several dirs "don't exist yet" | They exist on disk (empty, so git doesn't track them). |

### Found by the Phase C pre-flight audit (fixed in this pass)

**This one ran the other way: the docs *understated* the code.** Worth
weighing, because a reader who has absorbed the three rows above will be
scanning for overclaims and can walk straight past an underclaim.

| Was claimed | Reality found |
|---|---|
| plan.md — the `openai_compatible` path "is **not verified end-to-end**" | False since Phase A. It is the *active dev provider*, running Groq, verified through the real agent path — as tasks.md and this file both already said. plan.md was the lone holdout, and it is the doc a reader is pointed at for architecture. |
| plan.md row IV — "**nothing emits** the `<untrusted_listing_data>` delimiters" | True when written at M3 start, false since Phase B's `store.wrap_untrusted()`. Re-verified live: `ADV-0001`'s description reaches the agent *inside* the delimiters. Row now PARTIAL for the right reason — wrapping real, T029 behavioural proof still owed. |
| README — "LangGraph + SqliteSaver" | `AsyncSqliteSaver` since Phase A. plan.md and this file were updated; README was not. |
| plan.md vs tasks.md — where the MCP client lives | plan.md said `agent/tools.py`, tasks.md T024 said the FastAPI lifespan. Two docs assigning unwritten code to different homes. Resolved to the lifespan. |

Also found, and **not** a doc problem — a real repo defect nobody had hit:
**neither test suite collected under a bare `pytest tests/`** (8 collection
errors in `agent-backend`, 1 in `mcp-services`). Both only ever worked
because `python -m pytest` puts the cwd on `sys.path`. Fixed with a
`conftest.py` per service root.

**Lessons worth keeping:**
1. A test asserting *a prompt contains a rule* proves the rule was written,
   not that it is enforced. Grep for the thing the rule describes.
2. A Constitution gate row is only meaningful against the **subject matter**
   of its principle. "Deterministic renderer exists" ≠ "listing prices are
   grounded" if no listing has ever been rendered.
3. **Grep for call sites** of any function a doc calls load-bearing.
4. Run the live stack and query Phoenix for actual spans.
5. When a test fails against real data, suspect the data/spec before the test.
   That is how the dataset bug in §3b was found.
6. **Staleness runs both ways.** Three audits found docs overclaiming, so
   the fourth nearly missed two docs *underclaiming* — describing
   limitations the code had outgrown two milestones earlier. An underclaim
   costs a session re-solving a solved problem, which is the same waste in
   the opposite direction. Check both.
7. **Run the suite the way a stranger would**, not only the way the README
   says. `pytest tests/` and `python -m pytest tests/` were not equivalent
   here for four milestones.

### 3b. The dataset could not satisfy the spec (fixed in Phase B)

spec.md US2 AS1 — the **headline acceptance scenario for this very
milestone** — specifies *category=SUV, budget=$25,000, transaction_type=buy*.
That matched **zero listings**: every `CATEGORY_PROFILE` floor was a new-car
price, so the cheapest SUV was $26,380 and both sub-$30k SUVs were rent-only.
Every demo would have opened with the "sorry, relaxing a constraint" path.

Fixed by lowering category floors to create a used/budget tier and deriving
price from age + mileage instead of drawing it independently (the flat random
bands could price a pristine 2026 listing below a worn 2022 one, which also
left the ranking layer with no real signal to explain). **Ceilings, `SEED`,
listing/category/brand counts and the three `ADV-*` probes are unchanged.**
AS1 now matches 4 listings. Reversible: one constant table + regenerate.

---

## 4. Architecture

```
┌──────────────── frontend (React + Vite, port 3000) ────────────────┐
│  chat shell (src/App.tsx)                                          │
│   ├─ @a2ui/react renderer  → interview progress ✅,                 │
│   │                          catalogue + reasoning ⬜ (Phase D/E)   │
│   └─ MCP Apps host (M4)    → sandboxed iframes: booking, checkout  │
└───────────────────────────────┬────────────────────────────────────┘
                    WebSocket /ws/{session_id}
┌───────────────────────────────▼────────────────────────────────────┐
│  agent-backend (Python 3.14, FastAPI, port 8000)   ASYNC ALL-THE-WAY│
│   ├─ agent/graph.py       PhaseAgentRegistry: one agent per phase  │
│   ├─ agent/tools.py       save_interview_state (Command-based)     │
│   ├─ agent/state.py       SessionState + TOOLS_BY_PHASE gate       │
│   ├─ agent/prompts.py     PHASE_SYSTEM_PROMPTS + UNTRUSTED_DATA_RULE│
│   ├─ agent/render_a2ui.py deterministic domain → A2UI JSON         │
│   ├─ agent/llm.py         provider-selected; per-provider max_tokens│
│   ├─ api/main.py          WebSocket bridge, agent.ainvoke()        │
│   └─ AsyncSqliteSaver → /app/data/sessions.sqlite (volume, WAL)    │
└──────┬─────────────────────────────────────────┬───────────────────┘
       │ MCP Streamable HTTP ✅ (Phase B)         │ OTel gRPC
┌──────▼──────────────────────┐        ┌─────────▼──────────┐
│ mcp-services (port 8100)    │        │ phoenix            │
│  marketplace/ ✅ FastMCP     │        │ UI    :16006       │
│    store.py  query logic    │        │ OTLP  :14317       │
│    server.py MCP tools      │        └────────────────────┘
│  booking/ ⬜  payment/ ⬜     │
│  + data/listings.json (203) │
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
| GitHub token | In `~/.git-credentials` (scope: `repo`) |
| `uv` / `specify` | Installed at `~/.local/bin` — `export PATH="$HOME/.local/bin:$PATH"` |
| spec-kit CLI flag | It is `--integration claude`, **not** `--ai`; also needs `--ignore-agent-tools` here |
| ⚠️ Sandbox | Outbound POSTs to LLM providers **fail inside the default tool sandbox**. Live-LLM commands need `dangerouslyDisableSandbox: true`. `GET`s often work, which makes this confusing — a provider "outage" is usually this. |
| `.claude/launch.json` | **Exists and works** (`agent-backend` on 8000, `frontend` on 3000). Note `.claude/` is gitignored, so it will not survive a fresh clone. |

**Secrets**: `agent-backend/.env` (gitignored, `chmod 600`, verified absent from
both the built image and the JS bundle). `.env.example` is the committed
no-secrets template. **Scan staged diffs before committing** — and note the
scan regex must cover **`AQ.`** (Gemini), **`gsk_`** (Groq) and `AIza` prefixes;
a scan that only covered two of those leaked a key into a transcript once.

### ⚠️ LLM provider status — read all of this

- **ACTIVE (dev): Groq.** `LLM_PROVIDER=openai_compatible`,
  `LLM_BASE_URL=https://api.groq.com/openai/v1`, `LLM_MODEL=openai/gpt-oss-120b`.
  **Free tier ~1000 requests/day**, which is what makes M3's live behavioural
  tests (T021/T029) and the T046 eval run affordable.
- **Verified end-to-end at M3 start** through the real agent path
  (`build_interview_agent` → `save_interview_state`): 2-turn tool-using
  conversation survives, overwrite-not-append semantics correct. This is the
  **first** time the `openai_compatible` path has ever worked — it was
  correctly recorded as unverified after NVIDIA NIM failed.
- **⚠️ Groq rate-limits on TOKENS PER MINUTE**, not just requests
  (`x-ratelimit-limit-tokens: 8000` for `gpt-oss-120b`, 12000 for
  `llama-3.3-70b-versatile`), and the reservation counts prompt + `max_tokens`.
  **Measured: `max_tokens=4096` → 39s and 68s per turn; `1024` → 2.2s and 1.7s.**
  Hence `DEFAULT_MAX_TOKENS_BY_PROVIDER` in `agent/llm.py`. A 2-turn interview
  session burns ~9,200 prompt tokens against that 8k/min ceiling, so throttling
  is normal under load — **suspect TPM before suspecting a hang.**
- **Model quality note**: `llama-3.3-70b-versatile` showed weaker prompt
  adherence (re-asked for a slot it already had). `gpt-oss-120b` behaved
  correctly. Relevant to T029 — an injection result is only evidence for the
  model it ran on.
- **Gemini is reserved for demo rehearsal / final verification.**
  `LLM_PROVIDER=google`, default `gemini-3.6-flash`, native
  `langchain-google-genai`. **Free tier ~20 requests/day/model.** The key is
  preserved in a comment block in `.env` for a one-line switch back.
- **`gemini-2.5-*` is unusable** — rejected for newly-created keys with
  "no longer available to new users". Don't retry it.
- **Do NOT switch Gemini to its OpenAI-compat endpoint.** Gemini 3.x are
  thinking models; their function calls carry a `thought_signature` that
  must be echoed back. The compat layer drops it, so the **second** turn of
  every tool-using conversation dies with `400 INVALID_ARGUMENT`. Verified
  directly; `reasoning_effort` does **not** fix it.
- **OpenRouter is exhausted** (free tier, ~$0 left). **NVIDIA NIM did not
  work here** (non-streaming `/chat/completions` returned nothing in 120s).

🔴 **All three API keys (Gemini, Groq, NVIDIA NIM) have been pasted into chat
transcripts and should be rotated after the demo.** None was ever committed.

---

## 6. How to run everything

```bash
cd /home/abbas/ai-car-matchmaker

# Full stack (what judges will run)
docker compose up --build
#   frontend        http://localhost:3000
#   agent-backend   http://localhost:8000/health
#   mcp-services    http://localhost:8100/health   <- real MCP server now
#   phoenix         http://localhost:16006

# Tests (run the FULL suite together, never file-by-file — see §8.31)
source .venv/bin/activate
(cd mcp-services  && python -m pytest tests/ -q)   # 35 pass, no setup needed
(cd agent-backend && python -m pytest tests/ -q)   # 79 pass, 3 skip
# Bare `pytest tests/` also works now. It did NOT before the Phase C
# audit -- both suites died at collection, and only `python -m pytest`
# worked, because it puts the cwd on sys.path. Fixed with a conftest.py
# per service root; don't delete them.

# With live LLM (see §5) and Phoenix:
docker compose up -d phoenix
set -a && . agent-backend/.env && set +a
(cd agent-backend && python -m pytest tests/ -q)   # 82 pass, 0 skip

# Regenerate mock dataset (deterministic — byte-identical each run;
# a test asserts the committed file equals generate())
python mcp-services/data/generate_listings.py

# Dev servers — use the Browser pane's preview_start with
# {name: "agent-backend"} / {name: "frontend"}, NOT bash.
```

**Always `docker compose down` when finished** — don't leave containers running.

**Health endpoints tell you the config state**:
- `agent-backend`: `{"status":"ok","llm_configured":true,"tracing_enabled":true,
  "mcp_connected":true,"marketplace_tools":["get_listing_details","search_listings"]}`
  — since M3 Phase C `degraded` means **either** no LLM key **or** an
  unreachable marketplace; check `llm_configured` / `mcp_connected` to tell
  which. `tracing_enabled:false` means Phoenix failed. Note `mcp_connected`
  is not self-healing: discovery runs once at startup and agents cache their
  tools, so mcp-services coming back needs a backend restart.
- `mcp-services`: `{"status":"ok","servers":["marketplace"],"listings":203}`

---

## 7. File inventory (what exists and why)

### Spec-driven-development trail (READ THESE FIRST)
| File | Contents |
|---|---|
| `.specify/memory/constitution.md` | **5 non-negotiable principles** (see §9) |
| `specs/001-ai-car-matchmaker/spec.md` | US1–US5, edge cases, FR-001…FR-012, key entities, SC-001…SC-006, assumptions |
| `specs/001-ai-car-matchmaker/plan.md` | Architecture, tech context, Constitution gate check (**with the M2.5 *and* M3 corrections recorded**) |
| `specs/001-ai-car-matchmaker/tasks.md` | **T001–T059 across M0–M6**; Phase 3.5 = M2.5; **Phase 4 = M3, T020/T023 now checked with findings recorded** |

### agent-backend (Python)
| File | Purpose |
|---|---|
| `agent/state.py` | `Phase` (6), `InterviewState`, `SessionState`, `RankedRecommendation`, `Booking`, `PaymentConfirmation`. **`TOOLS_BY_PHASE` + `tool_names_for_phase()` are the phase gate**. `save_interview_slots()` **overwrites, never appends** |
| `agent/graph.py` | (a) M1's minimal `build_graph()`/`compiled_graph()` persistence scaffold — **keep as-is**. (b) `TOOL_REGISTRY` (name→tool), `tools_for_phase()`, `build_agent_for_phase()`, **`PhaseAgentRegistry(checkpointer, extra_tools=)`**, **`resolve_registry()`** (returns a new dict; never mutates `TOOL_REGISTRY`), `CarMatchmakerState(DeepAgentState)` carrying `session: dict` |
| `agent/tools.py` | `save_interview_state` and **`select_listing`** — `@tool`s returning a LangGraph `Command` |
| `agent/prompts.py` | `PHASE_SYSTEM_PROMPTS` (a missing entry fails at startup). Listing-facing phases embed `UNTRUSTED_DATA_RULE` |
| `agent/mcp_client.py` | **T024**: `discover_marketplace_tools()` — fail-soft MCP discovery, returns `[]` rather than raising. Never touches `TOOL_REGISTRY` |
| `agent/ranking.py` | **T025**: deterministic `rank()` over tool-artifact records. Min-max normalised *within the slate*; `reasoning` is a template filled from record fields, never the `description` |
| `agent/research.py` | **T025**: `run_research()` — code-driven first search from persisted interview state, AS2 relaxation ladder, `narration_brief()` for the model |
| `agent/llm.py` | `build_model()` selects by `LLM_PROVIDER`. **`DEFAULT_MAX_TOKENS_BY_PROVIDER`** (google 4096 / openai_compatible 1024) + `LLM_MAX_TOKENS` override |
| `agent/render_a2ui.py` | **A2UI v0.9.** Three surfaces, each `_init()` (createSurface + tree + data) / `_update()` (data only): interview, **reasoning** and **catalogue** (T026). Plus `_display()` (enum/float traps), `ICON_PATHS`/`icon()` (inline SVG, §8.21d) and `STEP_KIND_ICONS`. Every surface's root component **must** have id `root` (§8.21c) |
| `api/main.py` | FastAPI. `GET /health`, `WS /ws/{session_id}`. **AsyncSqliteSaver lifespan, `agent.ainvoke`, `aget_state`**, `message_text()`. **`_SurfaceStream`** owns per-connection init-vs-update for all three A2UI surfaces; a resumed session with `recommendations` gets its catalogue re-emitted on connect |
| `observability/otel_setup.py` | `setup_observability()` → `phoenix.otel.register(..., protocol="grpc", auto_instrument=True)` |
| `conftest.py` | Puts the service root on `sys.path` so the suite collects under a bare `pytest`, not only `python -m pytest`. Added by the Phase C audit — see §3 |
| `tests/` | **16 modules, 129 tests** (+`test_select_listing` 21 = T028b)<br>previously **15 modules, 106 tests** (+`test_catalogue_grounding` 24 = T022)<br>previously **14 modules, 82 tests** (`test_ranking` 12, `test_research` 17, `test_mcp_wiring` 8)<br>and before that **11 modules, 45 tests**: `test_state`(6), `test_tools`(5), `test_graph_persistence`(2), `test_render_a2ui`(8), `test_chat_endpoint`(3), `test_chat_endpoint_error_handling`(1), `test_interview_agent`(1), `test_otel_setup`(1), `test_phase_gate`(10), `test_observability_wiring`(2), `test_message_text`(6) |

### mcp-services (Python) — **rewritten in M3 Phase B**
| File | Purpose |
|---|---|
| `data/generate_listings.py` | Deterministic generator, `SEED=20260807`. 10 categories × 20 brands = 200 + **3 adversarial probes** (`ADV-0001..0003`) = **203**. Price now derives from age + mileage (§3b) |
| `data/listings.json` | Committed output; a test asserts it equals `generate()` |
| `marketplace/store.py` | **Query logic**: `load_listings()`, `matches()`, `search()`, `get_details()`, `wrap_untrusted()`. Pure functions over dicts — testable without a transport |
| `marketplace/server.py` | **FastMCP Streamable HTTP server**: `search_listings`, `get_listing_details`, `/health` custom route. `stateless_http=True`. `app` is the ASGI app |
| `tests/test_generate_listings.py` | 8 tests incl. SC-006 compliance + committed-file guard |
| `tests/test_marketplace.py` | **18 tests** — T020 hard filters |
| `tests/test_marketplace_server.py` | **9 tests** — MCP tool contract (structured_content shape, untrusted wrapper, error path) |
| `conftest.py` | Same role as agent-backend's. Replaced the per-file `sys.path.insert` hacks in two test modules, which had left `test_generate_listings` broken |
| `booking/`, `payment/` | Empty dirs (M4) |
| `app_stub.py` | **DELETED** in Phase B |

### frontend (React + Vite + TypeScript)
`src/App.tsx` (chat + A2UI surfaces), **`src/app.css`** (chat shell),
**`src/a2ui-theme.css`** (the `--a2ui-*` theme + document baseline — see
§8.21e/§8.21f before editing selectors), `src/main.tsx`, `index.html`,
`package.json` (**`@a2ui/react` + `@a2ui/web_core` v0.10.2**, React 19,
Vite 8), multi-stage `Dockerfile` (**`npm ci` with the lockfile** → nginx).
`src/{chat,a2ui,mcp-app-host}/` exist but are **empty**.
App.tsx renders **every** surface in `processor.model.surfacesMap`, so the
backend can add surfaces without a frontend change (proven by Phase D: the
two new surfaces appeared with no App.tsx change beyond styling).

---

## 8. Hard-won findings — READ BEFORE CODING (do not rediscover these)

Every one is verified, not assumed.

### MCP + langchain-mcp-adapters (M3 — the load-bearing ones)
1. **Adapted MCP tools are async-only.** `convert_mcp_tool_to_langchain_tool`
   returns `StructuredTool(coroutine=..., func=None)`. `tool.invoke()` raises
   `NotImplementedError: StructuredTool does not support sync invocation`
   — **including inside an `asyncio.to_thread` worker**. This is why
   `api/main.py` is `ainvoke`-based.
2. **`SqliteSaver` cannot do async.** `aget_tuple`/`aput`/`alist` all raise
   `NotImplementedError`. Runtime uses **`AsyncSqliteSaver`** (`...sqlite.aio`,
   needs `aiosqlite`, already installed). Its `from_conn_string` is an **async**
   context manager, and its *sync* methods refuse same-thread calls — so
   `get_state` must be `aget_state`.
   `test_graph_persistence.py` keeps the **sync** saver deliberately.
3. **`AsyncSqliteSaver` runs WAL mode** → writes `.sqlite-wal` / `.sqlite-shm`
   sidecars. `*.sqlite` does **not** match them; `.gitignore` now covers both.
4. **Version pin**: `langchain-mcp-adapters 0.3.2` requires `mcp<2.0.0`, and
   `mcp 2.0.0` exists on PyPI. Both requirements files pin `mcp>=1.24,<2`.
   An unpinned install silently splits the protocol across a major version.
5. **The grounding channel (Principle I)**: tools are
   `response_format="content_and_artifact"`.
   `ToolMessage.content` = list of text blocks with **stringified** JSON.
   `ToolMessage.artifact["structured_content"]` = **real typed dicts**.
   **The renderer must read the artifact**, never the content blocks, never
   the model's prose.
6. **FastMCP's `structured_content` shape depends on the return type** — a
   `dict` return lands at the top level, a `list` return under a `"result"`
   key. Both our tools therefore return a **named object**
   (`{listings, count, query}` and `{listing}`). Got this wrong once.
7. A **fresh MCP session is opened per tool call** (documented adapter
   behaviour), ~28 ms locally (re-measured 23 ms). Fine at demo scale.
7a. **A failed tool call does not raise into the agent.** An unknown listing
   id comes back as a `ToolMessage` with `status="error"` and the error text
   in `.content` — *not* an exception. So `try/except` around `ainvoke` will
   never see it, and code that assumes "no exception ⇒ the search worked"
   is wrong. Verified against the live Phase B server.
7b. **`ToolMessage.artifact` survives the checkpointer.** T025's whole
   design — deterministic ranking read from the artifact rather than from
   the model's prose — rests on this, and nothing in the repo had ever
   checkpointed an artifact-carrying ToolMessage (`save_interview_state`
   returns a bare one). Verified: written through `AsyncSqliteSaver` and
   re-read on a **fresh connection**, the artifact compares equal and
   `price`/`year` are still `int`, not stringified. Ranking from the
   artifact is safe. (Persisting the derived `RankedRecommendation`s is
   still the right call — see tasks.md T025(iii).)

### LLM provider
8. **Gemini 3.x + OpenAI-compat = broken tool calling** (`thought_signature`
   dropped; turn 2 400s). Use the native client. See §5.
9. **Gemini returns `AIMessage.content` as a *list of content blocks***.
   `message_text()` flattens it at the wire boundary. Any new place that reads
   `.content` must go through it.
10. **Groq throttles on tokens/minute** — see §5. Symptom is a 20–70s "hang"
    that is actually retry backoff, not a dead call.

### DeepAgents / LangGraph
11. **`create_deep_agent` always installs `FilesystemMiddleware`**, binding 9
    built-in tools (`ls`, `read_file`, `write_file`, `edit_file`, `delete`,
    `glob`, `grep`, `execute`, `task`) in **every** phase, outside our gate.
    Safe because the default `StateBackend` is a **virtual filesystem in graph
    state** with **no `execute` method**. `test_phase_gate.py` pins both.
12. **Those built-ins cost ~2,726 prompt tokens in every request** — ~4× our
    own system prompt (~362) plus `save_interview_state` (~303) combined.
    Re-checked against `deepagents 0.7.5`: **still not removable**.
    `create_deep_agent` exposes `permissions=[FilesystemPermission(...)]`, but
    that is a **runtime deny** — schemas and their tokens stay bound. Dropping
    `create_deep_agent` for langchain's plain `create_agent` would remove them,
    but **hard requirement #9 mandates the DeepAgents harness**, so that trade
    is unavailable. Fixed ~2.7k/request tax; interacts badly with Groq's TPM
    ceiling. *Still worth passing deny-all `permissions` for Principle IV.*
13. **A DeepAgents agent's tools are fixed at construction** — hence one agent
    per phase (`PhaseAgentRegistry`).
14. `InjectedState` **only resolves inside a real compiled graph**. Unit tests
    must call the tool via `save_interview_state.func(...)`.
15. Graph state must be **plain-JSON-able** — `SessionState` is stored as
    `.model_dump(mode="json")` under `session`.
16. **Do not "clean up" M1's `build_graph`/`_touch` scaffold.**
17. Compiled-agent tool introspection:
    `agent.nodes["tools"].bound.tools_by_name` (**not** `_tools_by_name`).

### A2UI
18. **Use protocol v0.9, not v1.0.** `@a2ui/react` v0.10.2 exports only
    `.`, `./v0_8`, `./v0_9` — no v1_0. (`@a2ui/web_core` ships v1_0 *schemas*
    under `src/` but does not export them.) Re-verified at M3 start.
19. **v0.9 basic catalog components** (the only 18 that exist): `Text`,
    `Image`, `Icon`, `Video`, `AudioPlayer`, `Row`, `Column`, `List`, `Card`,
    `Tabs`, `Modal`, `Divider`, `Button`, `TextField`, `CheckBox`,
    `ChoicePicker`, `Slider`, `DateTimeInput`. Re-verified in Phase D against
    the installed schema; all are implemented in the React build.
    Required props worth knowing before designing a tree: `Card` requires a
    single `child` (wrap multiples in a Column), `List`/`Row`/`Column`
    require `children`, `Text` requires `text`, and **`Button` requires both
    `child` and `action`** — there is no decorative Button.

19a. 🔴 **`Image` is unusable for the catalogue and three docs specified it
    anyway.** v0.9's `Image` requires a `url`, and **no listing record has
    one** — the dataset's 15 fields contain no image/photo/url. Binding a
    stock or generated URL would put a value on screen traceable to no
    tool-call result: a Principle I breach in the exact surface T022 exists
    to guard. Phase D dropped it and uses `Icon` for visual structure. Do not
    reintroduce it without adding a real, grounded image field.
20. **Listing selection (done, Phase E)**: `new MessageProcessor(catalogs,
    actionHandler, options)` — the **2nd constructor arg is a global
    `ActionListener`**. That is how a card `Button`'s `action` gets back to
    us, and `{"type":"action"}` now carries it to the backend.

20a. 🔴 **The listener receives a DIFFERENT shape than the component
    declares.** A component declares its handler under **`event`**
    (`action: {event: {name, context}}`, server→client). What the
    `ActionListener` receives is the **client→server** envelope, which nests
    it under **`action`** and adds `surfaceId`/`sourceComponentId`/
    `timestamp`. Reading `.event` in the listener matched nothing, so the
    button did nothing at all — no error, no network request, no clue in the
    console. Pinned against the installed `A2uiClientActionSchema`.

20b. **An action's `context` value may be a DataBinding, and it resolves
    per-row inside a template.** `resolveAction` runs on the row's own
    `DataContext`, so one templated `Button` with
    `context: {listing_id: {path: "id"}}` sends the right id per card —
    no need for one component per card. Verified by reading web_core and
    then by clicking the third card and getting the third listing's id.

20c. 🔴 **A UI action runs no graph, so nothing checkpoints it.** LangGraph
    persists as a side effect of *running*; a button click mutates state
    outside any run, so the selection lived only in the WebSocket handler's
    local variable — it rendered correctly and vanished on reload. Use
    **`aupdate_state(config, {...})`** to write state outside a run. Note
    that unit tests asserting on what the handler *returns* cannot catch
    this; assert on what a later `_load_session` reads back.
21. **`@a2ui/react@0.10.2`'s `"./styles/structural.css"` export is broken** —
    points at a file not in the published package. Import dropped; components
    render unstyled but functional. Styling is an open item (§11).
21a. ✅ *(resolved in Phase D)* Phase C's `{"type":"progress"}` placeholder
    is **deleted**; reasoning steps are the `research-reasoning` A2UI
    surface. Worth recording why removal was free: **nothing ever consumed
    it.** `App.tsx` handled `chat`/`a2ui`/`error` only, so Phase C's steps
    were generated, streamed and dropped. "Verified live" in Phase C meant
    verified at the socket, not on a screen.

21c. 🔴 **A surface's root component MUST have id `root`.** The renderer
    resolves a surface's entry point by that well-known id, not by
    declaration order or by being first in the list. A tree whose top
    component is called anything else is schema-valid, passes every unit
    test, and renders `[Loading root...]` forever — created, populated and
    permanently invisible. Cost a live debugging cycle; now regression-tested
    in `test_catalogue_grounding.py`. Component ids are scoped per surface,
    so every surface has its own `root`.

21d. 🔴 **Catalog icon *names* are Material Symbols font ligatures.**
    `Icon.name` accepts an enum name, an `{"svgPath": ...}` object, or a
    DataBinding. The enum path renders `<span class="material-symbols-outlined">payment</span>`
    — so without that font loaded, every icon renders as its own literal
    name. The first catalogue read "payment", "location_on",
    "calendar_today" down the page. **Use `{"svgPath": ...}`**: it renders an
    inline `<svg viewBox="0 0 24 24">`, needs no font, no CDN and no
    committed binary, and works offline. `Icon.name` accepting a DataBinding
    is what lets the reasoning surface give each step its own icon without
    string-sniffing the step text.

21e. 🔴 **A2UI output is themed ONLY through `--a2ui-*` CSS custom
    properties.** The renderer writes structure as inline styles whose every
    value is `var(--a2ui-something, fallback)`, so there is no class-based
    override API — and inline styles beat your stylesheet anyway. This, not
    the broken `structural.css` export (finding 21), is why surfaces looked
    unstyled since M2. **`--a2ui-border` has no built-in fallback**, so
    leaving it undefined renders every card borderless. See
    `frontend/src/a2ui-theme.css`.

21f. **The rendered DOM is not what you would guess** — read it off the page
    before writing selectors (this took two attempts). `Text` with
    `variant: "h3"` renders `<div class="h3"><h3>…</h3></div>` — a wrapper
    div carrying the class *plus* a real heading element inside. But
    `variant: "caption"` renders `<span><em>…</em></span>` — italic, and
    with **no `caption` class at all**. Text is also markdown-rendered, which
    is a further reason never to bind untrusted listing prose to a `Text`.
21b. **Never render a listing's `description`.** The MCP server wraps it in
    `<untrusted_listing_data>` for *every* consumer, including the artifact
    the ranker reads, so binding it to a `Text` component would put the
    delimiters on screen — and would put attacker-controlled prose in the UI.
    Render `brand`/`model`/`year`/`price`/specs and the ranker's `reasoning`.
22. The frontend already renders **all** surfaces in `processor.model.surfacesMap`,
    so extra surfaces appear automatically — Phase E is layout, not plumbing.
23. `(str, Enum)` members stringify as `TransactionType.BUY`. Use `.value`.
    `render_a2ui._display()` handles this plus whole-dollar floats.

### Phoenix
24. **Reading spans back**: `GET /v1/spans?project_name=…` **does not work**
    (needs a POST body → 422). Working path: `GET /v1/projects` → find by
    name (`ai-car-matchmaker-agent-backend`) → `GET /v1/projects/{id}/spans`.
25. Phoenix takes **~15–20 s** to become HTTP-ready. Poll, don't sleep.
26. Ingestion is async even after `force_flush()` — poll with a deadline.
27. `setup_observability()` must run **before** any agent is constructed.
28. Tracing must be **fail-soft**.
29. Span token counts are readable at `llm.token_count.prompt` — useful for
    diagnosing the TPM throttle (finding 10).

### pytest
30. **Never** set env vars at module level in a test file — executes at
    collection time and leaks into *other* modules' `skipif` evaluation.
    Use function-scoped `monkeypatch.setenv`.
31. **Run the full suite together**, not file-by-file.
32. Credential gates check key **presence**, so an out-of-quota key produces
    **failures, not skips**.

### Tooling / environment
33. `.gitignore`'s `.env.*` pattern wrongly excluded `.env.example` — fixed
    with an explicit negation. Don't reintroduce.
34. The Browser tool's **coordinate-based clicks/typing don't reliably trigger
    React's controlled-input handlers.** Workaround: native value setter +
    `dispatchEvent`, click via `.click()`. Tooling quirk, not an app bug.
35. No `sudo`, no `gh` — use `curl` + the token from `~/.git-credentials`.
36. **Concurrent heavy background jobs cause spurious failures** — re-run
    before debugging.
37. **The Bash tool's cwd persists between calls.** A `cd` in one call affects
    the next. This produced a false "file doesn't exist" conclusion once — use
    absolute paths, or re-`cd` explicitly.

---

## 9. The 5 constitution principles (enforce in all future code)

Full text in `.specify/memory/constitution.md`.

1. **Grounded Recommendations (NON-NEGOTIABLE)** — every price/spec/availability
   shown must be traceable verbatim to a tool-call result.
   *Status: **PARTIAL**, materially advanced in Phase C. Listing values now
   reach the user and are grounded end to end: the query is built from
   persisted state (not the model), ranking is deterministic Python over
   `ToolMessage.artifact["structured_content"]` (finding 5), and verbatim
   records persist in `SessionState.candidate_listings`. Verified live —
   4 records byte-identical to `listings.json`, 11/11 numbers in the model's
   narration traceable. Still PARTIAL because the principle names the **UI**,
   and the A2UI catalogue is T026/T022 (Phase D).*
2. **Explicit Phase Gating** — a *code-enforced* state machine. `TOOLS_BY_PHASE`
   is the single gate definition; `PhaseAgentRegistry` builds one agent per
   phase from it. *Genuinely enforced since M2.5.*
3. **Mock-Only Transactions** — no real payment path, no BMW APIs, no
   persistence of card-like data. *Nothing to enforce until M4b.*
4. **Untrusted Data Boundary** — marketplace listing text is **data, never
   instructions**. *The prompt rule has existed since M2; the **wrapping** only
   became real in M3 Phase B (`store.wrap_untrusted`, applied server-side).
   Behavioral proof is still owed: **T029** must show the three `ADV-*` probes
   cause zero deviation.*
5. **Full Observability** — every LLM call, tool call, and phase transition
   emits an OTel span. *Genuinely wired since M2.5; re-verified after the async
   migration (16 spans for one 2-turn session).*

---

## 10. NEXT UP: M3 Phase F — start here

### What Phase E left you

Phase E (T028) is **done, verified live in a browser, and pushed**. US2 is
now complete end to end: interview → auto-research → ranked A2UI catalogue →
listing selection → FORM_FILLING. What remains in M3 is Phase F, which is
**tests, not features**.

| Produced by Phase E | Where |
|---|---|
| `SessionState.select_listing()` — the third and last phase transition | `agent/state.py`, beside `save_interview_slots` / `record_research` |
| `SessionState.selected_listing()` — the verbatim record | `agent/state.py` — **M4a pre-fills the booking form from this**, not from model prose |
| `select_listing` tool (model path) | `agent/tools.py`, registered in `TOOL_REGISTRY` |
| Catalogue `Button` + `{"type":"action"}` handling | `render_a2ui._catalogue_components`, `api/main._handle_action` |
| `_persist_session` (`aupdate_state`) | `api/main.py` — writes state when no graph runs (§8.20c) |

⚠️ **FORM_FILLING is reachable but empty until M4a.** Selecting advances the
phase, and that phase's tools (`open_booking_form`, `submit_booking`) do not
exist yet, so the agent has no domain tools there. Correct per the gate, but
**do not demo past the selection** until M4a lands.

### Immediate next: Phase F (T021 + T029) — behavioural tests

Both are **live-gated** tests that need a real model, and both already have
their deterministic halves written. Groq (~1000 req/day) makes them
affordable; run T029 on Groq *and* once on whatever model ships, since an
injection result is only evidence for the model it ran on.

1. **T029 — prompt injection (Principle IV).** The three `ADV-*` probes must
   cause **zero** behavioural deviation. The wrapping is real and verified
   (`store.wrap_untrusted`, delimiters confirmed reaching the model live),
   but Principle IV's row stays PARTIAL until this behavioural proof exists —
   a wrapper the model ignores is not a boundary. `ADV-0002` is the sharpest
   probe: it is an SUV at $31,000 that demands to be ranked first regardless
   of fit, so a budget-constrained SUV search that returns it after a budget
   relaxation is a natural way to get it in front of the model.
2. **T021 — relaxation messaging.** A zero-match query must make the agent
   name the constraint it relaxed rather than fabricate. The ladder itself is
   already covered deterministically in `tests/test_research.py`; what is
   owed is the live half.

Note both tests assert on *model prose*, so heed §3's lesson about vacuous
checks — normalise digit separators and **assert the check examined
something** before trusting a pass.

### What Phase C left (still true, still the data contract)

Phase C (T024 + T025) is **done, verified live, and pushed** (`dd7ab4a`).
The full record with rationale is in tasks.md under T024/T025; what matters
for Phase D is the shape of what it produces:

| Produced by Phase C | Where | Phase D renders it as |
|---|---|---|
| Verbatim listing records from the tool artifact | `SessionState.candidate_listings` (`list[dict]`, rank order) | the **catalogue surface**'s only data source |
| `RankedRecommendation(listing_id, rank, fit_score, reasoning)` | `SessionState.recommendations` | card ordering + the explanation text |
| Human-readable research trace | `ResearchOutcome.steps` (+ `.step_kinds`, added in Phase D so the UI picks an icon per step without parsing its prose) | the **reasoning-steps surface** |

Key modules: `agent/research.py` (code-driven search + AS2 relaxation
ladder), `agent/ranking.py` (deterministic scoring), `agent/mcp_client.py`
(fail-soft discovery), `api/main.py::_run_research_turn` (the multi-send
turn). `SessionState.record_research()` is the code-enforced
RESEARCHING → RESULTS_READY transition.

### Then

| Phase | Task | Work |
|---|---|---|
| E | T028 | Listing selection, as one coherent slice — see the three numbered steps above. `select_listing` is the piece nothing has ever implemented, and **M4a depends on it** |
| F | T029 | **Security test**: the 3 `ADV-*` listings cause **zero** behavioural deviation (Principle IV) |
| F | T021 | Integration test: zero-match → agent **relaxes a constraint and says so** |
| — | T027 | `mcp-apps-ui/listing-detail/` — **recommended deferred past M4a/M4b**, it is the explicitly *additive secondary* surface while M4 is a hard requirement |

### Quota strategy (decided)

Development runs on **Groq** (~1000 req/day), so Phases C–E cost **zero**
LLM requests and T021/T029 can be exercised live. Recommended shape for both:
an **always-on deterministic half** (so CI never depends on a key) plus a
**live-gated half** that is the recorded proof. Gemini's ~20/day is reserved
for demo rehearsal. Run T029 on Groq *and* once on whatever model ships,
since an injection result is only evidence for the model it ran on.

---

## 11. Open items / known gaps

- **Evals (bonus #15) still owed** — T046.
- **Slide deck template** — organizers haven't provided it. T049 blocked.
- **Demo video** — T050. Recording is the user's to do.
- ✅ *(resolved in Phase D)* **A2UI styling** — the surfaces are themed via
  `frontend/src/a2ui-theme.css` (`--a2ui-*` custom properties, §8.21e) and
  the chat shell via `app.css`. The page also now pins `color-scheme: light`,
  because with no global CSS the browser's dark-mode UA defaults produced a
  black chat panel beside white A2UI cards for any viewer in dark mode.
- **Chat history is not replayed on reconnect.** A resumed session restores
  the A2UI surfaces (interview + catalogue) but the chat log starts empty —
  the transcript lives in the checkpointer's message history and nothing
  sends it. Cosmetic for the demo, but it makes a resumed session look
  emptier than it is. Belongs with T043.
- **Groq TPM ceiling** is the main demo risk (§5). Keep the model's candidate
  slate short; consider `llama-3.3-70b-versatile` (12k TPM) if throttling bites,
  accepting weaker prompt adherence.
- **DeepAgents' ~2.7k token/request tax** (§8.12) — unavoidable given req #9.
- **`frontend/src/{chat,a2ui,mcp-app-host}/` are empty** — M2 put everything in
  `App.tsx`. Split when M4's host adds real complexity.
- ✅ *(resolved in Phase C)* `agent-backend/requirements.txt` now carries both
  `langchain-mcp-adapters` and `mcp>=1.24,<2` as real entries.
- ✅ *(resolved in Phase E)* **`select_listing`** now exists as both a tool
  and `SessionState.select_listing()`, and RESULTS_READY → FORM_FILLING is
  reachable, so M4a's `open_booking_form` has a precondition it can gate on.
- ⚠️ **FORM_FILLING is now reachable but has no tools yet.** Selecting a
  listing advances the phase, and `TOOLS_BY_PHASE[FORM_FILLING]` names
  `open_booking_form`/`submit_booking`, which M4a implements. Until then a
  user who selects a car gets a confirmation and then an agent with no
  domain tools. Correct per the gate, but it is a dead end until M4a — do
  not demo past the selection yet.
- 🔴 **The demo's headline path still opens on a constraint relaxation.**
  §3b fixed the *price* floor so US2 AS1 matches 4 SUVs, but every real
  session also applies `target_date`, and **0** of those 4 are available
  before 2026-09-01 (they land 09-18, 11-10, 11-28, 12-19; only **45**/203
  listings are available before September — the "47" previously recorded
  here and in tasks.md T021 was never measured). Behaviour is correct and
  was verified live, but a judge's first impression is an apology.
  **Decided in Phase D**: demo with a later target date (option (b)); the
  availability skew (option (a)) stays on the table but was not taken, to
  avoid regenerating the dataset in the same pass as the catalogue.
  Re-measured 2026-08-08 across target dates: SUV/≤$25k/buy matches **1**
  by 2026-09-30, **1** by 2026-10-31, **4** by 2026-12-31.
- 🔴 **Rotate all three API keys** (Gemini, Groq, NVIDIA NIM) after the demo —
  all have been pasted into chat transcripts. None was ever committed.

---

## 12. Working agreements with the user

- **Do NOT immediately write code.** Understand → evaluate → design → validate →
  *then* implement. The user re-confirms this every session.
- **Work in phases**, don't build everything in one response.
- **Verify, don't assume.** The user values live end-to-end verification
  (real browser, real Docker build, real span queries) over "tests pass."
  Every audit so far found real bugs this way.
- **Audit before advancing.** Bar: fresh `git clone` into a temp dir + fresh
  venv + fresh docker build + live stack.
- **Be objective**; challenge the docs and the plan where a better approach
  exists. Distinguish facts / assumptions / recommendations / unknowns.
- **Push cadence is pre-authorized**: commit + push after each milestone once
  its tests pass.
- **Keep `tasks.md` checkboxes truthful as you go.**
- **Report failures honestly with the actual output.** If a claim in a doc
  turns out false, say so plainly and **record the correction rather than
  quietly editing it** — see §3, which exists because of this rule.

---

## 13. Required reading

For a new session, read in this order:

1. **`HANDOFF.md`** ← this file (full context + gotchas)
2. **`.specify/memory/constitution.md`** — the 5 principles all code must honor
3. **`specs/001-ai-car-matchmaker/spec.md`** — user stories, FRs, success criteria
4. **`specs/001-ai-car-matchmaker/tasks.md`** — task state + per-task findings
   (Phase 3.5 = M2.5; **Phase 4 = M3, current work**)
5. **`specs/001-ai-car-matchmaker/plan.md`** — architecture + the corrected
   Constitution Check table (**both** correction blocks)
6. **`README.md`** — run instructions

Then, before writing M3 Phase D code — **the four that matter most are
7, 8, 9 and 10**, because Phase D's whole job is rendering what they produce:

7. `agent-backend/agent/state.py` — `SessionState.candidate_listings` /
   `.recommendations` (**Phase D's data source**), `TOOLS_BY_PHASE` gate,
   `record_research()`
8. `agent-backend/agent/render_a2ui.py` — the surface pattern T026 copies,
   and `_display()`'s enum/float traps
9. `agent-backend/agent/research.py` — `ResearchOutcome.steps` (the
   reasoning-steps source), the AS2 relaxation ladder, why the first search
   is code-driven
10. `agent-backend/agent/ranking.py` — how `fit_score` and `reasoning` are
    derived; T022 snapshots against exactly these values
11. `agent-backend/api/main.py` — async lifespan, the WebSocket contract,
    `_run_research_turn` (**where the `{"type":"progress"}` placeholder T026
    replaces is sent**)
12. `agent-backend/tests/test_ranking.py` + `tests/test_research.py` — the
    deterministic contract Phase D must not break
13. `mcp-services/marketplace/store.py` — the query logic and
    `wrap_untrusted()` (why `description` must never be rendered)
14. `mcp-services/tests/test_marketplace_server.py` — the exact
    `structured_content` shape
15. `agent-backend/agent/graph.py` — `resolve_registry()` / `PhaseAgentRegistry`
16. `agent-backend/tests/test_phase_gate.py` + `tests/test_mcp_wiring.py` —
    how the gate is proven; M3 must keep both passing
17. `agent-backend/agent/prompts.py` — `UNTRUSTED_DATA_RULE`
18. `agent-backend/agent/llm.py` — provider selection + per-provider token caps
19. `frontend/src/App.tsx` — renders every surface in `surfacesMap`
    automatically (§8.22), so Phase D's surfaces appear without frontend work;
    Phase E is layout + selection

**Suggested opening prompt for the new chat** — copy this verbatim:

> Read `/home/abbas/ai-car-matchmaker/HANDOFF.md` in full, then everything it
> lists under §13 Required reading.
>
> This is the Amulate Summer Hackathon 2026 "AI Car Matchmaker" project.
> M0–M2.5 are complete. **M3 (User Story 2) is in progress**: Phase A (async
> agent path), Phase B (T020/T023, marketplace MCP server) and Phase C
> (T024/T025, MCP wiring + code-driven first search + deterministic ranking)
> are done, tested, verified live and pushed to `main` (`82d4b6b`).
> **Continue from M3 Phase D (T026 + T022)** — A2UI reasoning-steps and
> catalogue surfaces — described in HANDOFF §10.
>
> Do **not** write code immediately. First confirm you have full context and
> tell me anything in the docs that looks wrong, stale, or self-contradictory —
> four separate audits have now found docs asserting behaviour the code did
> not have (HANDOFF §3), so treat the docs as claims to verify. Note the
> fourth audit found the *inverse* too: docs still describing limitations the
> code had outgrown. Check both directions.
>
> Notes:
> - Phase D renders what Phase C persists. `SessionState.candidate_listings`
>   holds **verbatim tool records** and `.recommendations` holds the
>   deterministic ranking — those two are the catalogue's only legitimate
>   data source (Principle I). `ResearchOutcome.steps` feeds the
>   reasoning-steps surface.
> - `api/main.py` currently sends `{"type":"progress"}` as a **placeholder**.
>   Requirement #5 says reasoning steps must be A2UI, so T026 replaces it.
>   The multi-send path is already restructured — substitution, not rewrite.
> - **Never render a listing's `description`** — it carries the
>   `<untrusted_listing_data>` delimiters and is attacker-controlled text.
> - **T022 must assert its own non-vacuity.** Phase C's first grounding check
>   passed having examined zero values, because `gpt-oss-120b` writes
>   "$17 391" with a thin space and the regex expected "$17,391". A snapshot
>   test that silently compares nothing reads as proof. Count and assert.
> - A2UI is **v0.9**, and only the 18 components in HANDOFF §8.19 exist.
> - The `langchain-mcp-adapters` API is verified — HANDOFF §8.1–8.7. Don't
>   re-research it, but do sanity-check it still holds.
> - Outbound POSTs to LLM providers fail inside the default tool sandbox;
>   live-LLM commands need `dangerouslyDisableSandbox: true`.
> - Dev LLM is Groq (~1000 req/day), so live tests are affordable. It throttles
>   on tokens/minute — a 20–70s "hang" is backoff, not a dead call.
>
> Two open decisions of mine that are recorded but unresolved — raise them,
> don't decide them: (1) the demo's headline path still opens on a constraint
> relaxation because no budget SUV is available before the target date
> (tasks.md T021); (2) `select_listing` is a phase-gate entry with no
> implementation, and **M4a depends on it** (tasks.md T028b).
