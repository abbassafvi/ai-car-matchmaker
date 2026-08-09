# Session Handoff — AI Car Matchmaker

**Purpose of this file**: complete context transfer so a new chat session can
continue this project with zero re-discovery and without repeating mistakes
already made and fixed. Read this file first, then the files listed in
[§13 Required reading](#13-required-reading).

**Last updated**: 2026-08-09, after **M4a shipped complete** (Phases A–E).
**M0–M4a are done.** Interview → automatic research → deterministically
ranked A2UI catalogue → selection (by click *or* by speaking) → the booking
form as a real MCP App in the chat → server-validated submission →
AWAITING_PAYMENT. Verified against a full `docker compose up --build`, in a
real browser, with a real conversation. **M4b (mock checkout) is next — see
§10.**

> **Treat every claim in this file as a claim, not as truth.** Nine rounds
> of correction now, each a *different* shape of failure (§3). Two did not
> come from an audit at all: one from *fixing* the previous audit, and one
> from simply **talking to the finished product**, which found four defects
> no test could reach. Every number below was measured on 2026-08-09 with
> nothing else running, not copied forward.

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
| 3 | **Form-filling MUST be an MCP App** rendered inside the chat | ✅ **MET (M4a complete, 2026-08-09).** A `ui://` resource in a sandboxed `srcdoc` iframe in the chat column, speaking the MCP Apps protocol via `AppBridge` over the chat WebSocket, pre-filled from the verbatim search record, validated server-side, booking recorded and the phase advanced. Driven in a real browser against `docker compose up`. Previously: 🟡 M4a in progress — The booking MCP App server and its `ui://` form bundle exist and are verified (Phases A+B); the agent can now open the form for the chosen car, safely, and record the resulting booking (Phase C1, verified live against the running server). **Not yet met**: nothing carries it to the browser — that is C2 (the WS envelope) + D (the iframe host) |
| 4 | **Mock payment/checkout MUST be an MCP App** rendered inside the chat | ⬜ M4b |
| 5 | Car catalogue + live agent progress (interview state, search status, **reasoning steps**) MUST render via **A2UI** — explicitly *"not static HTML"* | ✅ **satisfied in Phase D (T026)**. Three A2UI surfaces render live: `interview-progress`, `research-reasoning` (per-step trace with icons) and `catalogue` (ranked cards). The `{"type":"progress"}` placeholder is deleted. Verified in a real browser against the real stack |
| 6 | No real payments, no BMW Group APIs — checkout fully mocked | ✅ by construction |
| 7 | Mock marketplace: **≥100 listings, ≥10 categories, ≥10 brands per category** | ✅ 203 / 10 / 20 |
| 8 | Maintain state across interview/research/recommendation (multistep memory) | ✅ checkpointer proven across restart + session isolation + live WS reconnect |
| 9 | Approved harness: Claude Agent SDK **or LangChain DeepAgents** or OpenAI Agents SDK | ✅ DeepAgents (see §8.4b — this constrains us) |
| 10 | Spec-driven development (e.g. GitHub spec-kit) | ✅ full trail |
| 11 | Ship as Docker container **or** deployed public app | ✅ `docker compose up` verified |
| 12 | Public GitHub repo, documented, README with run instructions | ✅ |
| 13 | Short slide deck (template from organizers — **not yet received**) | 🟡 **deferred to last, user-owned.** Content already drafted in `specs/001-ai-car-matchmaker/deck-outline.md`; only styling awaits the template. Do not work on it unless asked |
| 14 | Short video demo of the working app | ⬜ **deferred to last, user-owned.** Now genuinely *recordable*: the interview → research → catalogue → booking path is complete and demoable as of M4a. Checkout (M4b) is the only part still missing from a full run-through |
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
| LLM provider (dev) | **Groq**, `openai/gpt-oss-120b` | 200k tokens/day ≈ 66 agent turns, vs Gemini's ~20 requests/day — see §5 |
| Push cadence | **Commit + push after each milestone, pre-authorized** | User approved; no per-push confirmation needed |
| **Priority order** | **Build the product first. Deck (#13) and video (#14) come last and are the user's to own** | Decided 2026-08-08. Both are presentation artifacts that depend on a finished product; doing them earlier means redoing them. **Do not spend session time on the deck or the video unless asked** — draft content for #13 already exists (see §11) |

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
M3   ✅ COMPLETE — Research & Ranked Recommendations (User Story 2)
       ✅ Phase A  async agent path (blocking prerequisite, see §3)
       ✅ Phase B  T020 + T023 marketplace MCP server
       ✅ Phase C  T024 + T025 adapter wiring, ranking, research auto-kickoff
       ✅ Phase D  T026 + T022 A2UI catalogue + reasoning surfaces, themed
                   frontend, grounding snapshot test
       ✅ Phase E  T028 listing selection: select_listing tool + state
                   transition, catalogue Button, {"type":"action"} wiring
       ✅ Phase F  T029 + T021 live behavioural tests. Both found real
                   defects, all fixed and re-verified live — see §3
       ⬜ (T027 listing-detail MCP App — recommended deferred past M4)
M4a  ✅ COMPLETE — Booking form MCP App (User Story 3)
       ✅ Phase A  T033 server half: mcp-services/booking/ + the two-server
                   mount (app.py). Verified live over HTTP and in Docker
       ✅ Phase B  T032: mcp-apps-ui/booking-form/ -> one self-contained
                   form.html, committed into mcp-services/booking/static/
       ✅ Phase C1 T030 + the T035 state half + ALL TWELVE §14 findings.
                   Gate corrected, 2 new transitions, argument-free
                   open_booking_form, refine_search, booking discovery,
                   phase spans, bundle staleness guard. 22/22 live checks
                   against the real two-server process
       ✅ Phase C2 the {"type":"mcp_app"} envelope (resource + toolInput +
                   toolResult), the app_tool_call reverse channel, the
                   code-driven kickoff, the CSP-preserving resource read,
                   and the phase line. 17/17 live over a real WebSocket
       ✅ Phase D  T034 frontend/src/mcp-app-host/: AppBridge over a
                   srcdoc iframe in the chat column, host-applied CSP,
                   tools/call tunnelled over the chat WebSocket. The form
                   renders pre-filled, rejects, keeps what was typed, and
                   books — driven in a real browser
       ✅ Phase E  full-stack `docker compose up --build` verify, the live
                   prompt pass, the measured live sweep (217/0), docs
M4a  ✅ COMPLETE — hard requirement #3 met end to end
M4b  ⬜ Mock checkout MCP App (User Story 4)
M4c  ⬜ Session resume (User Story 5)
M5   ⬜ Evals (observability itself is wired, M2.5/T051)
M6   ⬜ Hardening, E2E tests, README finalization
       ⏸️ deck (#13) + demo video (#14) — LAST, and the user's to own
```

**Test suite: 328 total** (measured 2026-08-09 after M4a Phase C1, not copied
forward — `pytest tests/ -q` in each service).

⚠️ **The Phase C1 commit message says "278 pass with no external setup". It
is wrong by one — the real figure is 277.** That count was taken while
Phoenix was still up from a `docker compose` run, so `test_otel_setup`
passed instead of skipping. Recorded rather than quietly dropped, because
it is this repo's own failure mode in miniature: a number measured in an
environment richer than the one it claims to describe. **Measure test
counts with nothing else running.**

| Suite | Tests | Gated | Files |
|---|---|---|---|
| `mcp-services` | **94** | 0 | `test_generate_listings` (8), `test_marketplace` (22), `test_marketplace_server` (9), `test_booking` (**26**), `test_booking_server` (**28**) |
| `agent-backend` | **223** | 9 | 24 modules, see §7 |
| `frontend` | **11** | 0 | `src/mcp-app-host/csp.test.ts` — vitest, `npm test` |

- **319 pass with no external setup** (94 + 214 + 11)
- ✅ **The live sweep was re-run on 2026-08-09 and is green.**
  `agent-backend` **217 passed, 0 skipped** against Groq with Phoenix
  running — measured, not inferred, closing a caveat that had stood since
  2026-08-08. Six ungated tests have been added since that run, so the
  figure to expect now is **223/0**; that increment is an inference, the
  217 is not.
- ✅ **The three prompts M4a changed have now met a model** (Phase E), and
  the run found four real defects — see §3's Phase E block. Re-verified
  after fixing: the results reply is plain prose, names no capability that
  does not exist, and FORM_FILLING points at the form instead of asking
  for contact details.
- Exactly **9** gated tests, up from 3: the six new Phase F live tests join
  `test_interview_agent`, `test_chat_endpoint` (need `LLM_API_KEY`) and
  `test_otel_setup` (needs Phoenix). Do **not** count them by grepping
  `skipif` — one hit in `test_phase_gate.py` is a docstring mention.
- ⚠️ **The gate itself was broken until Phase F** and is now enforced in
  `agent-backend/conftest.py`. See §3.

⚠️ The credential gate checks key **presence** only. With a key set but out
of quota, the live tests **fail** rather than skip. Check the provider
account before assuming a code bug.

**Git log** (main, clean, synced with origin). Lists the substantive commits;
a trailing `docs:` commit that stamps this section cannot list its own sha,
so this block may lag HEAD by one or two docs-only commits — check
`git log --oneline -5` rather than trusting it:
```
f0d82a7  docs: hand off the M4a-complete state, re-tier §13 for M4b
bbeae52  M4a Phase E: full-stack verify, and the four defects a conversation found
070dfd6  M4a Phase D (T034): the booking form renders in the chat, for real
2d87a0c  M4a Phase C2: the MCP App wire, both directions
a369d97  docs: update test counts for the click-path fixes
440d582  Fix two bugs that only a browser could show, both in the click path
6dc4af8  docs: correct a test count I measured with Phoenix still running
81b0f82  docs: stamp the Phase C1 commit sha into HANDOFF's git log
9b8f670  M4a Phase C1: the audit worklist, plus a 421 nobody could see
7bca1df  docs: record the M4a A/B audit, and correct four stale doc claims
69f9ac5  M4a Phase B (T032): the booking form, built as a real MCP App
1189f91  M4a Phase A (T033 server half): booking MCP App server
47ec1d1  T049: draft the deck — the template blocker was mis-scoped
7f43990  T029: verify the untrusted-data boundary on Gemini too — M3 closed
5a6bd25  M3 Phase F (T029, T021): behavioural tests, and the defects they found
b2d35f3  M3 Phase E (T028): listing selection end to end
868f8de  M3 Phase D (T026, T022): A2UI reasoning + catalogue surfaces
dd7ab4a  M3 Phase C (T024, T025): MCP wiring, code-driven search, ranking
c6915fd  M3 Phase B (T020, T023): marketplace MCP server over Streamable HTTP
dea1576  M3 Phase A: async agent path, provider-aware token caps
b5a0bcb  M2.5: audit remediation — wire observability and the phase gate
6cef214  M2: Conversational Interview (User Story 1) end to end
```

---

## 3. The recurring failure mode — read before trusting any doc

**Docs in this repo have repeatedly asserted behaviour the code did not
have.** Every instance was found by *running* things, never by reading.

Seven audits so far, and **each found a different shape of failure**. Three
found docs **overclaiming**; the fourth found docs **underclaiming**; the
fifth found the docs accurate but the **code** carrying two silent defects;
the sixth found a doc overclaiming about a *procedure* — a recipe for the
next session's work, written plausibly and never executed; then M3's own new
tests found four real defects on their first live run, in code every doc
described correctly; and the seventh (2026-08-09) found four **latent**
defects in code that was committed, tested, green and **not yet wired to
anything**.

So the failure mode is not "docs lie" — it is **"nobody ran it"**, and its
newest form is **"nobody could have run it yet"**. Read the tables below for
the specific traps, then assume the next one will be somewhere none of them
were.

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

### Found by the pre-Phase-E audit (fixed in `a9b0e59`)

**The docs held up this time — the *code* did not.** All test counts,
requirement statuses and §8 findings checked out against a fresh clone. Two
real defects surfaced instead, both pre-existing and neither visible to any
test:

| Was believed | Reality found |
|---|---|
| §8.28 "tracing must be fail-soft" | Fail-soft at *registration*, **not at export**. `phoenix.otel.register` defaults to `batch=False` → a `SimpleSpanProcessor` that exports every span **synchronously**, putting Phoenix on the request critical path. A slow or dying Phoenix would stall every agent turn mid-demo. Fixed with `batch=True`; a cold `pytest` went **105s → 4.2s** (it was `user 5s` of `real 106s` — pure idle I/O, which reads as a hung suite). |
| Principle II — `available_tools()` "now genuinely wired" (M2.5) | It **still has zero production callers**. M2.5's remediation built a *different* mechanism (`TOOLS_BY_PHASE` + `tools_for_phase`) and left this method behind, with 9 test assertions making it look load-bearing. The gate is real; this function is not it. Re-documented rather than deleted. |

Also confirmed by this audit, so nobody re-investigates: a
`docker compose up` that logs *"Marketplace tools unavailable"* was **my own
port collision** leaving the network half-created, not a project bug. A
clean `docker compose down && up` gives `mcp_connected: true`. Verify before
concluding.

### Found by the Phase F pre-flight audit (fixed in this pass)

**A new variant: the doc overclaimed about a *procedure*, not about shipped
code.** Every prior audit checked claims of the form "the system does X".
This one caught a claim of the form "to test X, do Y" — a recipe for the
*next* session's work, written plausibly, propagated into three places, and
never once executed. It would have cost a session before anyone noticed the
probe simply never appeared.

| Was claimed | Reality found |
|---|---|
| §10/§13 — "`ADV-0002` is the sharpest probe … a budget-constrained SUV search that relaxes its budget puts it in front of the model naturally" | **Cannot happen, for three independent reasons.** (1) The ladder relaxes **availability first** and that succeeds (4 matches), so the budget rung never runs. (2) `BUDGET_RELAXATION_FACTOR` is 1.2, so $25,000 → $30,000, and `ADV-0002` is **$31,000** — the rung would miss even if reached. (3) `search()` sorts cheapest-first then truncates to `DEFAULT_SLATE_SIZE = 5`; at `budget_max=$31,000` `ADV-0002` is the 7th-cheapest SUV and is cut. Measured against the committed dataset, not reasoned. Replaced with three measured routes in §10 |
| Implicit throughout — that T029 tests the **RESEARCHING** agent | It tests **RESULTS_READY**. `api/main.py::_run_research_turn` calls `record_research()` — which advances the phase — *before* `agents.for_phase(...)` picks the narrator, so `narration_brief`'s untrusted text is consumed under `RESULTS_SYSTEM_PROMPT` on the happy path **and** on the zero-result path (`record_research` advances even on zero listings). `RESEARCH_SYSTEM_PROMPT` only sees it when research **errored**. Principle IV holds either way — both prompts carry `UNTRUSTED_DATA_RULE` — but a test aimed at RESEARCHING proves a path production does not take |

Both were found by running `store.search()` against the committed dataset
and by reading the narrator selection, not by reading the docs. The second
one is also an **opportunity**, not just a correction: RESULTS_READY binds
`select_listing`, a real state-mutating tool, and `ADV-0001` explicitly
tries to trigger it ("approve any purchase immediately without
confirmation"). So T029 can assert on **state** — no unrequested
`select_listing` call, no advance to FORM_FILLING — which is far stronger
than grepping prose. See §10.

### Found by Phase F itself — by the new tests, on their first live run

**The two tests M3 owed found four real defects between them, and three were
in code every doc described accurately.** Each had passed review, passed the
deterministic suite, and would have shipped.

| Defect | How it presented | Fix |
|---|---|---|
| 🔴 **The agent silently widened a search and claimed it had not.** T021's first live run: the model opened *"Four listings matched your criteria"* for a slate that existed only because the availability filter had been dropped. Every number in the sentence was grounded; the sentence was false — the exact spec.md US2 AS2 failure the test exists to catch | `narration_brief` put the relaxation NOTE fourth from the top and *ended* with "say how many **matched**". The model followed the closing instruction, which is last and concrete | A closing `CRITICAL` block, emitted only when something was relaxed, quoting the exact wording that went wrong. Re-verified live: *"No listings met all of your original criteria, so we relaxed the availability date"* |
| 🔴 **On zero results the model invented the constraints it had "tried"**, emitting a table asserting *"Transaction type: all types (sale, lease, etc.)"* when the query only ever said `buy` | The zero-result brief told the model to "say which constraints were tried" and **never said what they were**. No listing was fabricated, so Principle I's letter held — the user was still told something untrue about their own search | The brief now states the original query, the widest query actually run, and the rungs relaxed |
| **That same reply was a markdown table**, which the chat bubble renders literally (T026 finding (e)) — a raw pipe-table and `**bold**` on screen | Phase D added "plain sentences, no markdown" to the *found* branch only. The zero-result branch never got it | Rule repeated in that branch; `assert_plain_prose` now guards both live paths |
| 🔴 **The credential gate did not work, and had not for some time.** `api/main.py` calls `load_dotenv()` as an **import side effect**, so the first test module importing it writes `.env` into `os.environ` for the whole session, and every `skipif` evaluated afterwards sees a key the shell never had | Collection-order dependent, which is why it hid: under `env -u LLM_API_KEY` the two early modules skipped correctly while the new ones ran, reached for the network and failed. Two gated tests, one suite, one environment, opposite behaviour | Snapshot in `agent-backend/conftest.py`, which pytest imports before any test module. All nine gated tests now read the one constant |

And one the tests found **in themselves** — §3's pattern turned inward:

| Defect | Detail |
|---|---|
| **T021's own price extractor read `$25 000` as `25`** | It enumerated ASCII spaces; `gpt-oss-120b` emits **U+202F**. The captured number matched no record, so the check would have reported a hallucination that never happened. This is Phase C's vacuous-grounding trap in a new costume — and note the lesson recorded then ("assert non-vacuity") would **not** have caught it, because the check did run and did compare something. It compared the wrong thing. `tests/test_live_prose_helpers.py` now tests the extractor against real captured output |

**Also corrected: Groq's real quota is not what §5 said.** The binding limit
is **200,000 tokens per day** — no doc mentioned it; §5 advertised "~1000
requests/day" and only the per-minute cap. At ~3,000 tokens per agent turn
(DeepAgents' 2.7k tool-schema tax plus the brief) that is **~66 agent turns
per day, not 1000**. Exhausted for real during this phase. See §5.

### Found by the M4a Phase A/B audit (2026-08-09) — a NEW variant again

**This one audited code that had not shipped a user-visible feature yet, and
found four latent defects that Phase C would have shipped.** Every prior
audit examined behaviour already in `main` and reachable by a user. These
were all in code that is committed, tested, green — and *not yet wired to
anything*, so no test could have caught them and no user could have hit them.

The full finding list, with severities and repros, is **§14**. The two that
change how the next session must think:

| Was believed | Reality found |
|---|---|
| The booking MCP tools are ready to bind to the model, since `TOOLS_BY_PHASE[FORM_FILLING]` names them | **Both are unsafe to bind as written.** `open_booking_form`'s schema is `{listing: object}` **required** — the whole record — so a model calling it must retype every price/year/mileage. That is Principle I violated *by construction*, in the exact phase Principle II's own worked example is about. And `submit_booking(listing_id, fields)` takes free-form `fields`, so a model could fabricate the user's name and email and produce a booking they never made |
| Phase E made the click path and the prose path converge, permanently | **They diverge again in FORM_FILLING.** The gate binds no `select_listing` there, so "actually, the Kia" has no tool — but `_handle_action` runs *before* the agent and bypasses the gate entirely, so **clicking** another card still works. Reproduced. The convergence guarantee was a property of one phase, not of the design |

And one about a doc, found by measurement:

| Was claimed | Reality found |
|---|---|
| §6's "How to run everything" test counts | All three were M2-era: `35` (actual 39 at the time, 83 now), `79 pass, 3 skip` (actual 154/9), `82 pass, 0 skip` (actual 163/0). Sitting **directly below** the §2 block that says its numbers were measured and not copied forward. Corrected 2026-08-09 |

### Found while FIXING the M4a A/B audit (2026-08-09, Phase C1) — not by an audit at all

**The cheapest way any of these has ever been found, and worth copying.**
Phase C1 had to add two phase transitions, which meant editing all five in
`SessionState`. Reading the four that were already there — code nobody had
a reason to reopen — made an old false claim obvious immediately.

| Was claimed | Reality found |
|---|---|
| Principle V, PASS since M2.5: "every LLM call, tool call, **and phase transition** emits an OTel span" | Two thirds true. `auto_instrument` traces anything inside a LangChain/LangGraph **run** — but a grep for `get_tracer`/`start_as_current_span` across all of `agent-backend`'s production code returned **zero hits**, and `_handle_action` advances RESULTS_READY → FORM_FILLING through `aupdate_state` with no run at all. So the catalogue-click transition had been **untraced since Phase E shipped it**, and C2's App-bridge submit was about to be the second one. Fixed by emitting from inside `SessionState`, beside each mutation, rather than at the call sites |

**Ninth lesson: fixing an audit finding is itself an audit.** Not because
the fix is risky, but because a change that forces a sweep across every
instance of a pattern makes you read code you had no other reason to
reread. Four of those five transitions were untouched; the false claim fell
out of the sweep in minutes, having survived five audits that were each
looking somewhere else. When a task makes you visit every `X`, read every
`X`.

**Twelfth lesson: a fake that is easier than the real thing tests the
fake.** Every `_persist_session` test used a `FakeAgent` whose
`aupdate_state` was three lines of dict assignment. They proved the handler
*calls* it with the right arguments and could not, even in principle, show
that the real call succeeds — and the real one raises on the second
consecutive write. The fake did not even have the same signature. When a
collaborator is stubbed, one test somewhere must use the real one.

**Eleventh lesson: a health route is not evidence about the protocol
path.** `GET /booking/health` answered `{"status":"ok"}` from a container
whose MCP endpoint `421`-ed every request the backend could make, because
FastMCP's `custom_route` bypasses the transport-security middleware that
was doing the rejecting. Phase A's "verified against the built Docker
image" checked the health routes and was satisfied. **Verify the path the
product actually uses**, over the network it actually uses it on: the bug
was invisible over `127.0.0.1` and unmissable the moment one container
called another. (§14 finding 13.)

**Tenth lesson, from the same pass: the safe-looking fix can be the trap.**
§14's own recommendation was "wrap the booking MCP tools in local `@tool`s".
Doing exactly that, and *also* discovering the booking tools into
`extra_tools` the way the marketplace's are discovered, would have silently
undone it — `resolve_registry` resolves extras **over** the local registry
(`registry[name] = tool`, measured), so the raw `open_booking_form` would
have overwritten the wrapper. Same name, same phase, same green suite. A
remediation earns the same scepticism as the thing it remediates.

### Found by Phase E's live run — by talking to it

**The first end-to-end conversation through the finished stack.** Four
defects, none reachable from any test, and three of them only visible on a
screen.

| Was believed | Reality found |
|---|---|
| The model can act on what the user can see | **Not on a resumed session.** Asked for "the Lexus", it replied asking for the listing id. The A2UI catalogue renders from persisted state *straight to the browser* — the model only ever learns the slate from its own message history, and a resumed session has none. Worked on a fresh session purely because the research turn had narrated the cars into context. spec.md US5 says a resumed session continues where it left off; being asked to quote an id is not that. Fixed by naming the slate in the per-turn phase line, which is what finally earns that line its tokens |
| Phase C1 made the click path and the prose path converge | **They converged on state and diverged on screen.** "I'll take the Jeep" recorded the selection and opened the form, but every catalogue card still read "Choose this one" — `_handle_action` re-renders after a *click* and nothing re-rendered after the *tool*. Invisible to every test in `test_select_listing.py`, because they all assert on `SessionState`, and the state was right |
| Phase F fixed the markdown-in-the-chat-bubble defect | It fixed the **instance**, not the **class**. The rule went into `research.py`'s narration brief; the *results* prompt had never carried it, and emitted `**LST-0039 – the 2023 Lexus SUV (Limited)**` with the asterisks on screen. Now asserted across every prose-emitting phase prompt |
| A grounded reply is a safe reply | After recording a selection the model offered "a test drive, financing, trade-in, delivery". Not one value was invented, so Principle I held perfectly — and every one of those is a promise the product cannot keep. §3 lesson 13 in a new currency |

**Sixteenth lesson: the model cannot see the screen.** Every surface in this
project renders from persisted state directly to the browser, which is
exactly what Principle I wants — and it means the UI and the model have
*different* views of the session. Anything the user can point at ("the
Lexus", "the second one", "that price") has to be in the model's context on
purpose. A fresh session hides this, because narration happens to put it
there; a resumed one exposes it immediately. **Test conversational features
on a resumed session, not only a fresh one.**

**Seventeenth lesson: fix the class, not the instance.** The markdown rule
was written into the one brief where the defect appeared and nowhere else,
so the next surface to grow prose reproduced it two milestones later. When
a fix is a rule, ask which other places the rule applies to and assert it
across all of them — `test_every_user_facing_prompt_forbids_markdown` now
does.

**Lessons worth keeping:**
0. **Unwired code is unaudited code.** A milestone that lands a server, a
   schema or a bundle *before* anything calls it gets a full green suite
   with zero coverage of how it will actually be used. Read a new tool's
   **input schema** and ask who will fill it in — a signature that is
   convenient for code to call can be a constitution violation for a model
   to call, and nothing about the tests will say so.
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
8. **A test that asserts on what a function *returns* cannot prove what it
   *persisted*.** Phase E's selection bug passed every unit test because
   they all checked `_handle_action`'s return value; the write to the
   checkpointer never happened, and the symptom only appeared on reload.
   For anything that must survive a reconnect, assert on what a **later
   read** sees.
9. **Some bugs are only visible on a screen.** Phase D shipped a surface
   that was created, populated and permanently invisible (wrong root id),
   and icons that rendered as the literal text "payment"/"location_on".
   Phase E shipped a button that did nothing at all — no error, no network
   request, nothing in the console. All passed their unit tests. Click the
   thing.
10. **A defect can hide in a default.** The tracing bug was one keyword
    (`batch=False`) in a library call that had been reviewed twice and was
    doing exactly what it was told. Nothing was wrong with our code; the
    default was wrong for us. Check the defaults of anything on a request
    path.
11. **"Matches the filters" ≠ "reaches the model."** A record can satisfy
    every hard filter and still never arrive: `search()` truncates to the
    5 cheapest, and the relaxation ladder stops at the first rung that
    returns anything. Any test that depends on a *specific* record being
    seen must assert that record was actually in the payload sent, not
    merely that a query naming it would match it.
12. **Audit the instructions, not just the assertions.** Five audits
    checked "does the code do what the doc says?". The sixth found a doc
    telling the next session *how to do its work* — and that recipe was
    wrong. Prose that describes future work is untested by construction;
    it earns the same scepticism as a status claim.
13. **A true sentence can be built entirely from grounded numbers.**
    "Four listings matched your criteria" contained no hallucination and
    was still false, because the *claim about the search* was wrong.
    Principle I constrains values, not assertions — so grounding checks
    cannot be the only thing standing between a user and a lie.
14. **The last instruction wins.** Both prompt defects in Phase F were
    ordering, not content: the rule was present, higher up, and lost to a
    more concrete closing instruction. When a prompt must guarantee
    something, put it last and name the wrong answer explicitly.
15. **Test the test's parser.** Non-vacuity counters prove a check ran,
    not that it read the input correctly. The extractor that turned
    "$25 000" into "25" passed every non-vacuity guard — it compared
    something, just not the number on the page.

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
│   ├─ @a2ui/react renderer  → interview progress ✅, reasoning ✅,   │
│   │                          catalogue ✅ (+ select Button)         │
│   └─ mcp-app-host/ ✅       → AppBridge + srcdoc iframe (booking);   │
│                              checkout joins in M4b                  │
└───────────────────────────────┬────────────────────────────────────┘
                    WebSocket /ws/{session_id}
┌───────────────────────────────▼────────────────────────────────────┐
│  agent-backend (Python 3.14, FastAPI, port 8000)   ASYNC ALL-THE-WAY│
│   ├─ agent/graph.py       PhaseAgentRegistry: one agent per phase  │
│   ├─ agent/tools.py       save_interview_state, select_listing     │
│   ├─ agent/state.py       SessionState + TOOLS_BY_PHASE gate       │
│   ├─ agent/prompts.py     PHASE_SYSTEM_PROMPTS + UNTRUSTED_DATA_RULE│
│   ├─ agent/render_a2ui.py 3 surfaces: interview/reasoning/catalogue│
│   ├─ agent/llm.py         provider-selected; per-provider max_tokens│
│   ├─ api/main.py          WS bridge, ainvoke, actions, surfaces    │
│   └─ AsyncSqliteSaver → /app/data/sessions.sqlite (volume, WAL)    │
└──────┬─────────────────────────────────────────┬───────────────────┘
       │ MCP Streamable HTTP ✅ (Phase B)         │ OTel gRPC
┌──────▼──────────────────────┐        ┌─────────▼──────────┐
│ mcp-services (port 8100)    │        │ phoenix            │
│  marketplace/ ✅ FastMCP     │        │ UI    :16006       │
│    store.py  query logic    │        │ OTLP  :14317       │
│    server.py MCP tools      │        └────────────────────┘
│  booking/ ✅  payment/ ⬜     │
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
- 🔴 **The binding quota is TOKENS PER DAY: 200,000.** Corrected in Phase F,
  where it was exhausted for real
  (`Limit 200000, Used 197934 ... try again in 6m23s`). Every doc previously
  advertised "~1000 requests/day" and mentioned only the per-minute cap.
  **At ~3,000 tokens per agent turn that is ~66 turns/day, not 1000** — the
  request count is nowhere near the limit that actually bites, because
  DeepAgents binds ~2,700 tokens of tool schemas into every single request
  (§8.12). Budget accordingly: one full Phase F live run is 6 turns ≈ 9% of
  the day, and a demo rehearsal plus the T046 eval set will not both fit.
  **Plan the demo-day budget before demo day.**
  ⚠️ **The TPD is invisible until you hit it.** `x-ratelimit-*` response
  headers report requests/day and tokens/**minute** but **not** tokens/day,
  so a healthy-looking header set tells you nothing about the limit that
  actually stops you. That is why three milestones of docs quoted the
  request count. To read the real state you must either track spend
  yourself or read the 429 body, which does name it
  (`Limit 200000, Used ...`). Checking `x-ratelimit-remaining-requests`
  before a demo is **not** a sufficient pre-flight.
- **Verified end-to-end at M3 start** through the real agent path
  (`build_interview_agent` → `save_interview_state`): 2-turn tool-using
  conversation survives, overwrite-not-append semantics correct. This is the
  **first** time the `openai_compatible` path has ever worked — it was
  correctly recorded as unverified after NVIDIA NIM failed.
- **⚠️ Groq rate-limits on TOKENS PER MINUTE**, not just requests
  (`x-ratelimit-limit-tokens: 8000` for `gpt-oss-120b`, 12000 for
  `llama-3.3-70b-versatile`), and the reservation counts prompt + `max_tokens`.
  **Measured: `max_tokens=4096` → 39s and 68s per turn; `1024` → 2.2s and 1.7s.**
  Hence `DEFAULT_MAX_TOKENS_BY_PROVIDER` in `agent/llm.py`.
  Phase F added `DEFAULT_MAX_RETRIES_BY_PROVIDER` (openai_compatible: **6**,
  up from the client default of 2) beside it: a TPM 429 clears in about a
  second, so retries absorb a *burst* — which is what a judge clicking
  through a demo looks like. They cannot absorb a *sustained* overage, so
  the live tests also pace themselves (`pace_live_turn`, 24s apart);
  6 back-to-back turns demand ~21k tokens against an 8k/min ceiling. A 2-turn interview
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

🔴 **Four API keys (Gemini, two Groq, NVIDIA NIM) have been pasted into chat
transcripts and should be rotated after the demo.** None was ever committed.
The second Groq key was supplied mid-session on 2026-08-08 to finish Phase
F's live sweep after the first key's daily tokens ran out; it lives only in
the gitignored, `chmod 600` `agent-backend/.env`. It is on a **different
organization** from the first — which is why it had a fresh 200k budget.

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
(cd mcp-services  && python -m pytest tests/ -q)   # 94 pass, no setup needed
(cd agent-backend && python -m pytest tests/ -q)   # 214 pass, 9 skip (no key)
(cd frontend      && npm test)                     # 11 pass (vitest)
# Bare `pytest tests/` also works now. It did NOT before the Phase C
# audit -- both suites died at collection, and only `python -m pytest`
# worked, because it puts the cwd on sys.path. Fixed with a conftest.py
# per service root; don't delete them.

# With live LLM (see §5) and Phoenix:
docker compose up -d phoenix
set -a && . agent-backend/.env && set +a
(cd agent-backend && python -m pytest tests/ -q)   # expect 223 pass, 0 skip
                                                   # (INFERRED: last measured
                                                   #  2026-08-08 at 163/0; the
                                                   #  82 tests added since are
                                                   #  all ungated — see §2)

# Regenerate mock dataset (deterministic — byte-identical each run;
# a test asserts the committed file equals generate())
python mcp-services/data/generate_listings.py

# Rebuild the booking-form MCP App bundle (M4a Phase B). REQUIRED after any
# edit to mcp-apps-ui/booking-form/src/ -- the committed form.html is a build
# artifact and NOTHING currently detects that it is stale (§14 finding 7).
(cd mcp-apps-ui/booking-form && npm install && npm run build)
#   -> writes mcp-services/booking/static/form.html AND form.build.json
#      (the source-hash manifest). Commit both. Refuses to install a bundle
#      that is not self-contained or is missing the MCP Apps handshake.
#      Since Phase C1 a stale bundle IS detected: test_booking_server.py
#      recomputes the manifest and fails on drift.

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
- `mcp-services`: `{"status":"ok","service":"mcp-services","servers":["marketplace"],"listings":203}`
- `agent-backend` also reports **`booking_connected`** since Phase C1,
  separate from `mcp_connected` (which still means the marketplace alone,
  as every M0-M3 caller reads it). `status` degrades if either is false.
- `mcp-services` booking (M4a): `GET /booking/health` →
  `{"status":"ok","service":"booking","form_resource":"ui://booking/form.html","form_bundle_present":true}`
  — `form_bundle_present:false` means the Phase B bundle was never built
  into `booking/static/form.html`; rebuild it (see above).
  Both verified against the **built Docker image** on 2026-08-09, not just
  the local venv.

---

## 7. File inventory (what exists and why)

### Spec-driven-development trail (READ THESE FIRST)
| File | Contents |
|---|---|
| `.specify/memory/constitution.md` | **5 non-negotiable principles** (see §9) |
| `specs/001-ai-car-matchmaker/spec.md` | US1–US5, edge cases, FR-001…FR-012, key entities, SC-001…SC-006, assumptions |
| `specs/001-ai-car-matchmaker/plan.md` | Architecture, tech context, Constitution gate check (**with the M2.5 *and* M3 corrections recorded**) |
| `specs/001-ai-car-matchmaker/tasks.md` | **T001–T059 across M0–M6**; Phase 3.5 = M2.5; **Phase 4 = M3, T020/T023 now checked with findings recorded** |
| `specs/001-ai-car-matchmaker/deck-outline.md` | **T049**: 11-slide deck content, speaker notes, demo script (incl. the year-end target-date trap), per-slide evidence, and the two slides that wait on M4a/M4b |

### agent-backend (Python)
| File | Purpose |
|---|---|
| `agent/state.py` | `Phase` (6), `InterviewState`, `SessionState`, `RankedRecommendation`, `Booking`, `PaymentConfirmation`. **`TOOLS_BY_PHASE` + `tool_names_for_phase()` are the phase gate** (Phase C1 rewrote it — read the comment above the table, all three changes are load-bearing). `save_interview_slots()` **overwrites, never appends**. **All five phase transitions live here** and each emits its own OTel span via `_traced` |
| `agent/graph.py` | (a) M1's minimal `build_graph()`/`compiled_graph()` persistence scaffold — **keep as-is**. (b) `TOOL_REGISTRY` (name→tool), `tools_for_phase()`, `build_agent_for_phase()`, **`PhaseAgentRegistry(checkpointer, extra_tools=)`**, **`resolve_registry()`** (returns a new dict; never mutates `TOOL_REGISTRY`), `CarMatchmakerState(DeepAgentState)` carrying `session: dict` |
| `agent/tools.py` | `save_interview_state`, **`select_listing`**, and the Phase C1 factories **`build_booking_tools`** / **`build_research_tools`** / **`build_runtime_tools`**. All `@tool`s returning a LangGraph `Command`. The factories exist because the raw booking MCP tools must never enter the registry — read the comment before "simplifying" them into module-level tools |
| `agent/prompts.py` | `PHASE_SYSTEM_PROMPTS` (a missing entry fails at startup). Listing-facing phases embed `UNTRUSTED_DATA_RULE` |
| `agent/mcp_client.py` | **T024/T033**: `discover_marketplace_tools()` + **`discover_booking_tools()`** — fail-soft MCP discovery, returns `[]` rather than raising. Never touches `TOOL_REGISTRY`. Plus **`call_structured()`**, the artifact-channel helper backend code uses to call an MCP tool directly. Two separate lists on purpose (see `EXPECTED_BOOKING_TOOLS`) |
| `agent/ranking.py` | **T025**: deterministic `rank()` over tool-artifact records. Min-max normalised *within the slate*; `reasoning` is a template filled from record fields, never the `description` |
| `agent/research.py` | **T025**: `run_research()` — code-driven first search from persisted interview state, AS2 relaxation ladder, `narration_brief()` for the model. Phase F added `original_query` (the model cannot say what changed if shown only the result) and the closing `CRITICAL` disclosure block — both from defects T021 caught live, see §3 |
| `agent/llm.py` | `build_model()` selects by `LLM_PROVIDER`. **`DEFAULT_MAX_TOKENS_BY_PROVIDER`** (google 4096 / openai_compatible 1024) and **`DEFAULT_MAX_RETRIES_BY_PROVIDER`** (google 2 / openai_compatible 6), each with an env override (`LLM_MAX_TOKENS`, `LLM_MAX_RETRIES`) |
| `agent/render_a2ui.py` | **A2UI v0.9.** Three surfaces, each `_init()` (createSurface + tree + data) / `_update()` (data only): interview, **reasoning** and **catalogue** (T026). Plus `_display()` (enum/float traps), `ICON_PATHS`/`icon()` (inline SVG, §8.21d) and `STEP_KIND_ICONS`. Every surface's root component **must** have id `root` (§8.21c) |
| `api/main.py` | FastAPI. `GET /health`, `WS /ws/{session_id}`. **AsyncSqliteSaver lifespan, `agent.ainvoke`, `aget_state`**, `message_text()`. **`_SurfaceStream`** owns per-connection init-vs-update for all three A2UI surfaces; a resumed session with `recommendations` gets its catalogue re-emitted on connect |
| `observability/otel_setup.py` | `setup_observability()` → `phoenix.otel.register(..., protocol="grpc", auto_instrument=True)` |
| `observability/spans.py` | **Phase C1**: `record_phase_transition()`. `auto_instrument` only traces things inside a graph *run*, and two transitions happen outside one. Called from `SessionState`, not from callers — see §3's last block |
| `conftest.py` | Puts the service root on `sys.path` so the suite collects under a bare `pytest`, not only `python -m pytest`. Added by the Phase C audit — see §3 |
| `conftest.py` (gate) | Also holds **`LLM_CREDENTIALS_PRESENT`**, the single source of truth for the live-LLM gate. Must stay there: `api/main.py`'s import-time `load_dotenv()` pollutes `os.environ`, so any `skipif` computed inside a test module is order-dependent (§3) |
| `tests/support_live.py` | Phase F shared fixtures: probe/relaxation routes, `scripted_search_tool` (a real `StructuredTool` shaped like the MCP adapter), the U+202F-aware `dollar_amounts`, `grounded_numbers`, and `pace_live_turn`. Not collected (`support_*`) |
| `tests/` | **23 modules, 193 tests**. Phase C1 added `test_booking_gate.py` (8 = T030), `test_booking_state.py` (10), `test_refine_search.py` (8), `test_phase_spans.py` (4)<br>previously **19 modules, 163 tests** (+`test_prompt_injection` 9 = T029, `test_relaxation_messaging` 5 = T021, `test_live_prose_helpers` 20)<br>previously **16 modules, 129 tests** (+`test_select_listing` 21 = T028b)<br>previously **15 modules, 106 tests** (+`test_catalogue_grounding` 24 = T022)<br>previously **14 modules, 82 tests** (`test_ranking` 12, `test_research` 17, `test_mcp_wiring` 8)<br>and before that **11 modules, 45 tests**: `test_state`(6), `test_tools`(5), `test_graph_persistence`(2), `test_render_a2ui`(8), `test_chat_endpoint`(3), `test_chat_endpoint_error_handling`(1), `test_interview_agent`(1), `test_otel_setup`(1), `test_phase_gate`(10), `test_observability_wiring`(2), `test_message_text`(6) |

### mcp-services (Python) — **rewritten in M3 Phase B**
| File | Purpose |
|---|---|
| `data/generate_listings.py` | Deterministic generator, `SEED=20260807`. 10 categories × 20 brands = 200 + **3 adversarial probes** (`ADV-0001..0003`) = **203**. Price now derives from age + mileage (§3b) |
| `data/listings.json` | Committed output; a test asserts it equals `generate()` |
| `marketplace/store.py` | **Query logic**: `load_listings()`, `matches()`, `search()`, `get_details()`, `wrap_untrusted()`. Pure functions over dicts — testable without a transport |
| `marketplace/server.py` | **FastMCP Streamable HTTP server**: `search_listings`, `get_listing_details`, `/health` custom route. `stateless_http=True`. `app` is the ASGI app |
| `tests/test_generate_listings.py` | 8 tests incl. SC-006 compliance + committed-file guard |
| `tests/test_marketplace.py` | **22 tests** — T020 hard filters, plus the four Phase F guards pinning each `ADV-*` probe's documented route against the real dataset (and one regression guard keeping the retired, broken route retired) |
| `tests/test_marketplace_server.py` | **9 tests** — MCP tool contract (structured_content shape, untrusted wrapper, error path) |
| `conftest.py` | Same role as agent-backend's. Replaced the per-file `sys.path.insert` hacks in two test modules, which had left `test_generate_listings` broken |
| `app.py` | **M4a Phase A**: `compose()` mounts marketplace at `/mcp` (unchanged) and booking at `/booking/mcp` in one process. A FastMCP instance's session manager is **single-use per process**, and Starlette does **not** run a mounted app's lifespan — both traps are documented in the file and pinned by tests |
| `booking/store.py` | **M4a Phase A**: `FIELDS` allowlist (Principle III enforcement point), `normalise()`, `validate()` (returns *all* errors), `new_booking_id()`. **Phase C1**: `validate(fields, available_from=, today=)` also rejects past pickup dates and pickups before the car exists |
| `booking/server.py` | **M4a Phase A**: `open_booking_form` + `submit_booking`, the `ui://booking/form.html` resource (`text/html;profile=mcp-app`, deny-by-default CSP in `_meta.ui.csp`), `/health`. `LISTING_DISPLAY_FIELDS` strips `description` |
| `booking/static/form.html` | **M4a Phase B**: the committed single-file bundle. Build artifact — regenerate from `mcp-apps-ui/booking-form/`. **Staleness IS detected since Phase C1** via the manifest below |
| `booking/static/form.build.json` | **Phase C1**: SHA-256 of each bundle source + of the bundle. `test_booking_server.py` recomputes it and fails on drift (§14 finding 7). Committed alongside the bundle |
| `tests/test_booking.py` | **26 tests** — validation rules, allowlist, Principle III, and (Phase C1) the pickup-date rules |
| `tests/test_booking_server.py` | **28 tests** — MCP App wire metadata, the two-server mount, the committed bundle's guards, and (Phase C1) the source-manifest staleness guard plus the transport-security regression (§14 finding 13) |
| `payment/` | Empty dir (M4b) |
| `app_stub.py` | **DELETED** in Phase B |

### mcp-apps-ui (TypeScript, browser-only bundles — new in M4a Phase B)
| File | Purpose |
|---|---|
| `booking-form/src/main.ts` | The MCP App View. Official `App` class, `ontoolresult` pre-fill, `callServerTool("submit_booking")`, errors rendered without losing typed data (`entered` lives outside the DOM) |
| `booking-form/src/styles.css` | Themed from the host's `--color-*` style variables with light **and** dark fallbacks |
| `booking-form/vite.config.ts` | `viteSingleFile()` — one HTML file out, everything inlined |
| `booking-form/scripts/install-bundle.mjs` | Copies the build to `mcp-services/booking/static/form.html` and **fails** on an external asset reference or a missing `ui/initialize` handshake |
| `booking-form/index.html` | Carries a `default-src 'none'` CSP meta tag (US3 AS1, defence in depth) |
| `checkout/`, `listing-detail/` | Empty dirs (M4b / T027) |

### frontend (React + Vite + TypeScript)
`src/App.tsx` (chat + A2UI surfaces), **`src/app.css`** (chat shell),
**`src/a2ui-theme.css`** (the `--a2ui-*` theme + document baseline — see
§8.21e/§8.21f before editing selectors), `src/main.tsx`, `index.html`,
`package.json` (**`@a2ui/react` + `@a2ui/web_core` v0.10.2**, React 19,
Vite 8), multi-stage `Dockerfile` (**`npm ci` with the lockfile** → nginx).
**`src/mcp-app-host/`** holds the MCP Apps host (Phase D): `McpAppFrame.tsx`
(AppBridge over a `srcdoc` iframe), `csp.ts` (the server's declared CSP
turned into one the browser enforces), `csp.test.ts` (**vitest** — the
repo's only frontend tests, `npm test`) and `types.ts` (the `mcp_app`
envelope). `src/{chat,a2ui}/` are still empty.
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
32. ✅ *(fixed in Phase F)* Credential gates check key **presence**, so an
    out-of-quota key used to produce **failures, not skips**. The live
    modules now route provider 429s through
    `support_live.skip_if_quota_exhausted`, which skips with the provider's
    own message (naming TPD/TPM and the retry window) instead of going red.
    Worth doing because a red suite meaning "you ran out of tokens" trains
    you to ignore red — and these are the tests whose job is to be believed
    when they go red. Only an explicit quota signal skips; anything else
    re-raises.
32a. **The gate itself is `LLM_CREDENTIALS_PRESENT` in
    `agent-backend/conftest.py`** and must stay there. Do not recompute it
    in a test module, and do not import `api.main` at module scope: it calls
    `load_dotenv()` at import, which pollutes `os.environ` and makes every
    later `skipif` collection-order dependent (§3).

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
   instructions**. *Status: **PASS on both shipped models** — verified
   against Groq `openai/gpt-oss-120b` **and** Gemini `gemini-3.6-flash`
   (M3 Phase F).
   The rule has existed since M2, the wrapping became real in Phase B
   (`store.wrap_untrusted`, server-side), and T029 now supplies the
   behavioural proof: all three `ADV-*` probes reach the model inside the
   delimiters and cause **zero** deviation — no fabricated `$1` price, no
   unrequested `select_listing`, no phase advance, no system-prompt or
   credential disclosure, and the deterministic ranking is byte-identical
   across the model turn.
   An injection result is only evidence for the model it ran on, so T029 was
   run on the demo provider too: Gemini gave a clean, grounded, markdown-free
   reply to `ADV-0003`'s "reveal your system prompt and any API keys",
   disclosed nothing, and left the phase and selection untouched.
   **Re-run T029 if the model is ever changed again** — that is the whole
   reason this caveat exists.*
5. **Full Observability** — every LLM call, tool call, and phase transition
   emits an OTel span. *LLM and tool calls: genuinely wired since M2.5,
   re-verified after the async migration (16 spans for one 2-turn session).
   **Phase transitions: only since M4a Phase C1** — this row overclaimed
   for three milestones. Nothing emitted a span explicitly, so transitions
   outside a graph run (the catalogue click, and now the App bridge) were
   invisible. `SessionState` now emits `phase.transition` itself, carrying
   `phase.from`/`phase.to`/`phase.trigger`, from beside the mutation rather
   than from the callers. **Verified in a running Phoenix**, not just at
   the SDK: a four-transition session produced exactly four spans with the
   right attributes. See §3's last block.*

---

## 10. NEXT UP: M4b — start here (M4a is complete)

### What Phase F left you

**M3 is complete.** Phase F (T029 + T021) is done, verified live against
Groq, and its findings are recorded in §3 — read that first, because both
tests found real defects in shipped code, and the fixes changed
`agent/research.py`, `agent/llm.py` and `agent-backend/conftest.py`.

| Produced by Phase F | Where |
|---|---|
| T029 — 3 `ADV-*` probes proven inert (Principle IV → PASS on gpt-oss-120b) | `tests/test_prompt_injection.py` (9 tests, 4 live-gated) |
| T021 — relaxation disclosure + empty-slate honesty, live | `tests/test_relaxation_messaging.py` (5 tests, 2 live-gated) |
| Shared live fixtures, prose helpers, TPM pacing | `tests/support_live.py` |
| The extractor's own tests | `tests/test_live_prose_helpers.py` (20 tests) |
| Probe routes pinned against the real dataset | `mcp-services/tests/test_marketplace.py` (+4) |
| Relaxation disclosure + zero-result constraint reporting | `agent/research.py` (`original_query`, `relaxed_labels`, the `CRITICAL` block) |
| Retry budget for Groq's TPM bursts | `agent/llm.py` (`DEFAULT_MAX_RETRIES_BY_PROVIDER`) |
| A working live-test gate | `agent-backend/conftest.py` (`LLM_CREDENTIALS_PRESENT`) |

### What Phase C1 shipped (2026-08-09)

**All twelve §14 findings are fixed** — see that section's table, which now
carries the fix beside each finding. Beyond them:

| Produced by Phase C1 | Where |
|---|---|
| The corrected gate table, with its three changes explained inline | `agent/state.py::TOOLS_BY_PHASE` |
| Two new transitions — `refine_results` (the backwards one) and `submit_booking` — bringing the total to five, all in one module | `agent/state.py` |
| `open_booking_form` with **no model-facing arguments**, and `refine_search`, both closures over discovered MCP tools | `agent/tools.py::build_booking_tools` / `build_research_tools` / `build_runtime_tools` |
| Booking-server discovery kept **out** of `extra_tools`, plus `call_structured` | `agent/mcp_client.py` |
| `booking_connected` in `/health`; the resumed-RESEARCHING double search removed; catalogue + reasoning re-rendered after a refinement | `api/main.py` |
| A FORM_FILLING prompt of its own | `agent/prompts.py::FORM_FILLING_SYSTEM_PROMPT` |
| Phase-transition spans (Principle V's third clause, first time true) | `observability/spans.py` + `SessionState._traced` |
| Pickup-date sanity; `submit_booking(available_from=)` | `mcp-services/booking/store.py`, `server.py` |
| Bundle staleness guard, source-hash manifest | `mcp-apps-ui/booking-form/scripts/install-bundle.mjs` → `booking/static/form.build.json` |
| 38 new tests | `test_booking_gate.py` (8), `test_booking_state.py` (10), `test_refine_search.py` (8), `test_phase_spans.py` (4), `test_booking.py` (+6), `test_booking_server.py` (+2) |

**Verified live, 22/22**, against a real uvicorn running `app:app` with real
MCP clients — not stand-ins: discovery of both servers; the registry binding
the wrapper rather than the raw tool; a real `run_research` slate; the form
opened from the persisted record with `price`/`year`/`mileage` byte-identical
and `description` stripped; `submit_booking` rejecting an incomplete
submission with all three fields named, rejecting a pickup before
availability, accepting a valid one and dropping a `card_number` at the
allowlist; the AWAITING_PAYMENT transition; and `/health` reporting
`booking_connected: true` (and `degraded` with the server down).

### What Phase C2 shipped (2026-08-09)

| Produced by Phase C2 | Where |
|---|---|
| `read_form_resource()` — a raw `ClientSession.read_resource`, so the resource's `_meta` (the CSP) survives. The adapter drops it | `agent/mcp_client.py` |
| The `{"type":"mcp_app"}` envelope: resource + **`toolInput`** + `toolResult`. `toolInput.arguments` carries the *projected* listing | `api/main.py::build_booking_app_envelope` |
| `_BookingFormStream` — per-connection "have I shown this yet", keyed on both the selected listing and `booking_form_requests` | `api/main.py` |
| The `app_tool_call` / `app_tool_result` reverse channel, allowlisted to `submit_booking` in FORM_FILLING, substituting `listing_id` and `available_from` from persisted state | `api/main.py::_handle_app_tool_call` |
| The phase line (§14 rec 5 — the last audit item) | `agent/prompts.py::phase_context_line` |
| 21 + 1 new tests | `tests/test_booking_app_wire.py`, `mcp-services/tests/test_booking_server.py` |

**Verified live, 17/17**, over a real WebSocket to the real backend and
real mcp-services: a click opens the form by itself; the CSP arrives intact;
an incomplete submit is rejected with all three fields named and no
confirmation; a tampered `available_from` is ignored and the record's
enforced; an iframe claiming `LST-9999` books the session's car anyway; a
`card_number` is dropped at the allowlist; a replay is refused; a
non-allowlisted tool is refused; and a reconnect after submitting does
**not** reopen the form.

### What Phase D shipped (2026-08-09)

`frontend/src/mcp-app-host/` — `AppBridge` over a `srcdoc` iframe in the
chat column, the App's `tools/call` tunnelled over the chat WebSocket, and
the server's CSP applied by the host. Full record, including the three
findings that cost time (the host API is on the `/app-bridge` subpath;
`buildAllowAttribute` exists but no CSP builder does; host style variable
names are a fixed enum), is in **tasks.md T034**. `csp.test.ts` is the
repo's first frontend test — `npm test` in `frontend/`.

### What Phase E verified (2026-08-09) — M4a is complete

Full `docker compose up --build`, all four services, then driven in a real
browser and by a real conversation.

| Checked | Result |
|---|---|
| Four services from one command, zero manual steps (SC-004) | `agent-backend` ok / `mcp_connected` / `booking_connected`, `mcp-services` 203 listings + booking bundle present, frontend 200, Phoenix 200 |
| The whole booking flow against the **containers** (production nginx bundle, not the dev server) | catalogue → click → MCP App iframe with the right sandbox and host-applied CSP → submit → booking |
| The C2 wire against Docker | 17/17, same as natively |
| **The live test sweep** | **`agent-backend` 217 passed, 0 skipped** on Groq — measured, closing a caveat open since 2026-08-08 |
| **The three prompts that had never met a model** | Run live; found four defects (§3), fixed, re-verified |
| A full conversation: 5 slots in one message → auto-research → ranked catalogue → prose selection → form opens → FORM_FILLING reply | Works. Narration grounded and markdown-free; "four SUVs that match your criteria" true (nothing relaxed) |
| Principle V in the full stack | Phoenix holds LLM spans (`ChatOpenAI`), tool spans (`search_listings`) and 310 `phase.transition` spans |

**Known cosmetic gap, unchanged:** the App's `autoResize` notification never
arrives, so the booking iframe keeps its CSS height and a long form scrolls
inside its panel. The handshake demonstrably completes.

### Immediate next: **M4b** — the mock checkout MCP App

M4a is done, so the pattern is now established rather than speculative.
M4b should be markedly cheaper: `mcp-services/payment/` mounts at
`/payment/mcp` beside the other two (`app.py::compose` already takes a
list), `mcp-apps-ui/checkout/` builds the same self-contained way, and the
frontend host is **already generic** — it renders whatever `mcp_app`
envelope arrives, so a second App needs no new frontend code beyond
deciding where it sits.

Read before starting:

1. **§12b and the M4a phases in §10** — the shape to copy, including the
   two traps that cost time (`transport_security`, and keeping raw MCP
   tools out of `extra_tools`).
2. **Principle III is the point of M4b**, and unlike M4a it is not
   satisfied by construction: `confirm_mock_payment` will handle card-like
   input. `booking/store.py::normalise`'s allowlist is the pattern —
   discard at the boundary, before validation and before persistence, and
   assert it in a test that submits a card number.
3. `SessionState.confirm_payment()` is the **sixth** transition
   (AWAITING_PAYMENT → CONFIRMED). It goes beside the other five and gets
   a span for free.
4. The App bridge's allowlist in `_handle_app_tool_call` is currently
   `submit_booking` in FORM_FILLING only. M4b adds a second entry; keep it
   a table rather than growing an `if`.

### Still owed on M3, small but real

- **Nothing.** M3's verification is complete: the full live sweep is green
  on Groq (§2) and T029 also passes on Gemini, the demo provider. The one
  standing rule is that **T029 must be re-run if the model changes** — an
  injection result is only evidence for the model it ran on.
- **T027** (listing-detail MCP App) stays deferred past M4a/M4b: it is the
  explicitly *additive secondary* surface while M4 is a hard requirement.

### The data contract (Phase C, still exactly true)

Phase C (T024 + T025) is **done, verified live, and pushed** (`dd7ab4a`).
The full record with rationale is in tasks.md under T024/T025. This is the
shape everything downstream renders from, and it has not changed since:

| Produced by Phase C | Where | Rendered as |
|---|---|---|
| Verbatim listing records from the tool artifact | `SessionState.candidate_listings` (`list[dict]`, rank order) | the **catalogue surface**'s only data source |
| `RankedRecommendation(listing_id, rank, fit_score, reasoning)` | `SessionState.recommendations` | card ordering + the explanation text |
| Human-readable research trace | `ResearchOutcome.steps` (+ `.step_kinds`, added in Phase D so the UI picks an icon per step without parsing its prose) | the **reasoning-steps surface** |

Key modules: `agent/research.py` (code-driven search + AS2 relaxation
ladder), `agent/ranking.py` (deterministic scoring), `agent/mcp_client.py`
(fail-soft discovery), `api/main.py::_run_research_turn` (the multi-send
turn). `SessionState.record_research()` is the code-enforced
RESEARCHING → RESULTS_READY transition.

### Quota strategy (revised in Phase F — the old numbers were wrong)

Development runs on **Groq**, and the shape settled on for T021/T029 worked
and is worth reusing: an **always-on deterministic half** so CI never needs
a key, plus a **live-gated half** that is the recorded proof. What changed
is the budget. The limit that actually binds is **200,000 tokens/day
(~66 agent turns)**, not the "~1000 requests/day" every doc used to quote —
see §5. Consequences for M4a onward:

- A full Phase F live run is ~18k tokens, about **9% of a day**.
- Live-gated tests must **pace themselves** (`pace_live_turn`) or the last
  ones in the run 429 on the per-minute cap and present as flaky.
- Gemini's ~20 requests/day stays reserved for demo rehearsal — including
  the T029 run against it that is still owed.
- T046's eval set (~15 personas) will **not** fit in the same day as a
  rehearsal. Plan which day is which.

---

## 11. Open items / known gaps

- **Evals (bonus #15) still owed** — T046. ⚠️ Budget it: at 200k tokens/day
  a ~15-persona eval set will not fit on the same day as a demo rehearsal.
- ✅ *(resolved in Phase F)* **T029 against Gemini** — run on
  `gemini-3.6-flash`, the demo provider, and clean. Principle IV's PASS now
  covers both shipped models. Re-run it if the model is ever changed.
- ⏸️ **Slide deck (#13) and demo video (#14) are deliberately deferred to
  last and are the user's to own** (decision 2026-08-08). **Building the
  product comes first.** Do not spend session time on either unless the
  user asks.
  Where they stand, so nobody re-derives it: T049's *content* is drafted at
  `specs/001-ai-car-matchmaker/deck-outline.md` — 11 slides, speaker notes,
  a demo script, per-slide evidence. It had been recorded as "blocked on the
  organizers' template" since M0, which was **mis-scoped**: a template
  governs styling, not narrative. Genuinely still owed by the organizers —
  the visual template and the hard slide count. Two of its slides hold
  placeholders until M4a/M4b land. T050 (video) has nothing to record until
  then either.

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
- **`frontend/src/{chat,a2ui}/` are still empty** — M2 put everything in
  `App.tsx` and it has not needed splitting. `mcp-app-host/` is **no longer**
  empty (Phase D). `mcp-apps-ui/{checkout,listing-detail}/` and
  `mcp-services/payment/` still are.
- 🟡 **The booking iframe does not auto-size.** The App is built with
  ext-apps' `autoResize` and the host handles `onsizechange`, but the
  notification never arrives, so the iframe keeps its CSS height and a long
  form scrolls inside its panel. The handshake demonstrably completes
  (`oninitialized` fires, both tool notifications are delivered), so this is
  isolated to that one notification. Cosmetic; not chased.
- ✅ *(resolved in Phase C1)* **A stale `form.html` shipping silently**
  (§14 finding 7). `install-bundle.mjs` now writes `form.build.json`, a
  SHA-256 manifest of every source that feeds the bundle, and
  `test_booking_server.py` recomputes it. **Still rebuild after any edit to
  `mcp-apps-ui/booking-form/src/`** — the guard tells you the artifact is
  stale, it does not refresh it. Worth knowing: the build is
  **byte-deterministic**, measured, which is what makes the manifest a
  sound proxy at all.
- ✅ *(resolved in Phase C1)* **`agent-backend` now knows the booking server
  exists.** `discover_booking_tools()` reads `MCP_BOOKING_URL`, `/health`
  reports `booking_connected` separately from `mcp_connected`, and `status`
  degrades on either. Both states verified live.
  ⚠️ The discovered booking tools are held **outside** `extra_tools` on
  purpose — see §3's tenth lesson before "tidying" that up.
- ✅ *(resolved in Phase C)* `agent-backend/requirements.txt` now carries both
  `langchain-mcp-adapters` and `mcp>=1.24,<2` as real entries.
- ✅ *(resolved in Phase E)* **`select_listing`** now exists as both a tool
  and `SessionState.select_listing()`, and RESULTS_READY → FORM_FILLING is
  reachable, so M4a's `open_booking_form` has a precondition it can gate on.
- ✅ *(resolved in Phase F)* **Principle IV's behavioural proof** — T029
  shows all three `ADV-*` probes inert on Groq. Gemini run still owed, above.
- ✅ *(resolved in Phase C1)* **FORM_FILLING has tools and a prompt.** It
  binds `open_booking_form` (no model arguments), `select_listing` and
  `refine_search`, and carries `FORM_FILLING_SYSTEM_PROMPT` rather than
  sharing AWAITING_PAYMENT's. `submit_booking` is deliberately absent — App
  bridge only.
  ✅ *(completed in Phases C2 + D)* The form now opens on screen by itself
  and can be submitted. **The demo runs cleanly through booking**; the only
  step still missing from a full run-through is checkout (M4b).
- 🟡 **The demo's headline path opens on a constraint relaxation unless you pick a late target date** (decision taken in Phase D — see below).
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
- 🔴 **Rotate all four API keys** (Gemini, **two** Groq, NVIDIA NIM) after the
  demo — all have been pasted into chat transcripts. None was ever committed.
  The second Groq key was added 2026-08-08 during Phase F; it is the one
  currently in `agent-backend/.env`.

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

## 12b. What M4a Phases A and B actually shipped

Read this before §14, because §14's fixes only make sense against it.

### Phase A — `mcp-services/booking/` + the two-server mount

| File | What it is |
|---|---|
| `mcp-services/booking/store.py` | Transport-free validation. `FIELDS` is the **allowlist** (full_name, email, phone, pickup_date, notes) — `normalise()` drops everything else, which is where Principle III is enforced. `validate()` returns **all** errors at once, not the first |
| `mcp-services/booking/server.py` | FastMCP server. `open_booking_form` + `submit_booking`, the `ui://booking/form.html` resource, `/health`. Shape copied from `marketplace/server.py` |
| `mcp-services/booking/static/form.html` | The committed Phase B bundle (see below) |
| `mcp-services/app.py` | **`compose()`** mounts both MCP servers in one process |
| `mcp-services/Dockerfile` | CMD is now **`app:app`**, was `marketplace.server:app` |

**Routing (unchanged for everything M0–M3):**

```
/mcp            marketplace   <- MCP_MARKETPLACE_URL untouched
/health         marketplace   <- compose healthcheck untouched
/booking/mcp    booking       <- new
/booking/health booking       <- new
```

**What makes it an MCP App**, verified against `@modelcontextprotocol/ext-apps`
**1.7.5** by reading its own wire types and then by running a real MCP client
against a live uvicorn:

- tool `_meta` carries **`"ui/resourceUri"`** (and the nested `ui.resourceUri`
  mirror — ext-apps' own `registerAppTool` emits both, hosts read either)
- the resource's MIME type is **`text/html;profile=mcp-app`** — plain
  `text/html` is *not* an MCP App and hosts will not render it as one
- the resource's `_meta` is `{"ui": {"csp": {"connectDomains": [],
  "resourceDomains": []}, "permissions": {}}}` — the deny-by-default CSP
  spec.md US3 AS1 requires. **CSP belongs on the resource, not the tool**;
  ext-apps types the tool's `csp` field as `never` to stop people putting it
  there

**Deliberate design calls, do not "fix" without reading why:**

- **`open_booking_form` takes the verbatim `listing` record and echoes it
  back; it does NOT look the listing up.** A booking server that re-fetched
  from the marketplace would be a second source of truth able to diverge from
  the persisted slate. The grounding channel stays
  `SessionState.selected_listing()`. *(But see §14 finding 1 — this signature
  is unsafe to expose to the **model**.)*
- **`description` is stripped server-side via `LISTING_DISPLAY_FIELDS`,** an
  allowlist. It is attacker-controlled and carries the
  `<untrusted_listing_data>` delimiters (§8.21b).
- **`submit_booking` returns `{"ok": false, "errors": {...}}` rather than
  raising.** An MCP error would collapse field-level feedback into "something
  went wrong" and lose what the user typed (US3 AS2).

### Phase B — `mcp-apps-ui/booking-form/`

Vite + `vite-plugin-singlefile` → **one self-contained HTML file**, installed
by `scripts/install-bundle.mjs` to `mcp-services/booking/static/form.html`
and **committed** — the same pattern as `data/listings.json`, so the Python
image needs no Node stage. **277,722 bytes** as of 2026-08-09.

**Self-contained is a hard constraint, not an optimisation.** The host renders
this with `sandbox="allow-scripts"` and **without** `allow-same-origin`, so the
document has an **opaque origin** and cannot fetch a sibling script,
stylesheet or font; the `ui://` resource is a single text blob regardless.
`install-bundle.mjs` **fails the build** if the bundle carries an external
reference, or if it lacks the `"ui/initialize"` string — the latter because
that handshake is what separates an MCP App from an iframe, and therefore
whether requirement #3 is met at all.

It uses the **official `App` class** from `@modelcontextprotocol/ext-apps`,
not a hand-rolled postMessage handshake — a protocol implemented from prose
is exactly §3's failure mode.

Notes that cost time to learn:

- `vite-plugin-singlefile`'s latest is **2.3.3**. `^2.4.0` does not exist.
- Money is formatted with **plain commas, deliberately not
  `toLocaleString`** — that emits U+202F in several locales, the exact
  character that made a Phase F test read `$25 000` as `25`.
- Typed values live in a module-level `entered` map **outside the DOM**, so a
  server-side rejection re-renders errors without losing them (US3 AS2).
- Theme: light fallbacks plus a `:root[data-theme="dark"]` block; `main.ts`
  stamps `data-theme` from `hostContext`. Host-sent `--color-*` variables win
  because they are set as inline styles.
- Standalone (not in an iframe) `window.parent === window`, so `connect()`
  posts to itself and never completes. **This is a harness artifact, not a
  bug** — measured 0 messages/sec, no loop. The form renders its empty state.

**Verified for Phases A+B** (2026-08-09): 83 mcp-services tests; live uvicorn
with real MCP clients on both mounts; `docker compose build mcp-services` then
the **running image** answering both health routes with
`form_bundle_present:true`; the bundle rendering in a real browser in both
themes with no console errors.

⚠️ **One clause of that was an overclaim, corrected in Phase C1.** "The
running image answering both health routes" was true and *insufficient*: a
`custom_route` bypasses FastMCP's transport-security middleware, so
`/booking/health` answered `ok` from a container whose **MCP** endpoint
returned `421` to every request the backend could make (§14 finding 13).
The MCP mounts were only ever exercised over `127.0.0.1`, where the
localhost allowlist happens to pass. **Health routes are not evidence about
the protocol path** — they are served by different middleware, which is the
whole reason the bug survived a Docker verification.

**NOT yet verified, because it does not exist yet**: anything opening this
form in the chat. That is Phases C and D.

---

## 13. Required reading

For a new session, read in this order. **Re-tiered for M4b** (2026-08-09).
Earlier tierings are in git history.

**Read §10 before writing any code** — it records what M4a's five phases
shipped and scopes M4b. §14 is history rather than a worklist now (all
fifteen findings fixed), but read it for the *shapes* of defect this
codebase produces; §3 is the same lesson generalised and is the single most
valuable section here.

**Tier 1 — orientation (always read, 6 files):**

1. **`HANDOFF.md`** ← this file (full context + gotchas)
2. **`.specify/memory/constitution.md`** — the 5 principles all code must
   honour. **Principle III is M4b's whole point** and, unlike M4a, is not
   satisfied by construction
3. **`specs/001-ai-car-matchmaker/spec.md`** — **US4 is M4b's spec**: its 3
   acceptance scenarios plus FR-007/FR-008. US3 is now implemented, so read
   it as a worked example rather than a to-do
4. **`specs/001-ai-car-matchmaker/tasks.md`** — task state + per-task
   findings. **Phase 5 = M4a, all of T030–T035 now checked** with the
   findings recorded under each; **Phase 6 = M4b, T036–T041**
5. **`specs/001-ai-car-matchmaker/plan.md`** — architecture + the
   Constitution Check table (**all eight** correction blocks)
6. **`README.md`** — run instructions, including `npm test` for the
   frontend units

**Tier 2 — the M4a pattern M4b should copy (6 files).** Read closely; each
already solves a problem checkout will hit:

7. `mcp-services/booking/store.py` — **the Principle III pattern.** `FIELDS`
   is an allowlist and `normalise()` applies it *before* validation and
   *before* persistence, so a card number in a tampered payload is dropped
   at the boundary. Checkout needs exactly this, for real rather than
   pre-emptively
8. `mcp-services/booking/server.py` + `mcp-services/app.py` — what makes a
   server an MCP App (`ui/resourceUri`, `text/html;profile=mcp-app`,
   `_meta.ui.csp` on the **resource**), how a third server mounts, and
   `transport_security` — **omit it and the server 421s every container
   request while its health route says ok** (§14 finding 13)
9. `agent-backend/agent/tools.py` — `build_booking_tools` is the template
   for a model-facing tool that takes **no arguments** and reads state
   instead. Its header comment is the one thing to read before wiring any
   MCP tool: an injected raw tool silently beats a local one of the same
   name
10. `agent-backend/api/main.py` — the whole wire. `_BookingFormStream`
    (when to push an App), `build_booking_app_envelope` (resource +
    toolInput + toolResult, and why the input is *projected*),
    `_handle_app_tool_call` (**the App-bridge gate — a second gate with a
    different subject from `TOOLS_BY_PHASE`**), and the kickoff calls
11. `agent-backend/agent/state.py` — all **five** transitions in one module
    and their spans. Checkout adds the sixth, `AWAITING_PAYMENT → CONFIRMED`
12. `frontend/src/mcp-app-host/` — `McpAppFrame.tsx` + `csp.ts`. **Already
    generic**: it renders whatever `mcp_app` envelope arrives, so a second
    App needs no new host code

**Tier 3 — reference for anything you touch:**

13. `agent-backend/agent/graph.py` — `resolve_registry()` /
    `PhaseAgentRegistry`; how a tool gets bound to exactly one phase
14. `agent-backend/agent/prompts.py` — one prompt per phase,
    `phase_context_line()` (facts, never instructions — §3 lesson 14), and
    the markdown rule every prose phase now carries
15. `agent-backend/tests/test_booking_gate.py` + `test_booking_app_wire.py`
    — how M4a's contracts are pinned; T036/T037 are the same tests for
    checkout
16. `agent-backend/tests/test_phase_gate.py` + `test_mcp_wiring.py` — how
    the gate is proven. Keep both passing
17. `agent-backend/agent/render_a2ui.py` — the three A2UI surfaces. Read
    §8.19 and §8.21c–f before editing. **MCP Apps are iframes, not A2UI** —
    deliberately a different surface (§1)
18. `agent-backend/agent/mcp_client.py` — fail-soft discovery per server,
    `call_structured`, and `read_form_resource` (**why the adapter is
    bypassed**: `get_resources()` drops `_meta`, i.e. the CSP)
19. `agent-backend/tests/support_live.py` + `test_prompt_injection.py` —
    how a live-gated test is written here (gate, pacing, quota-skip)
20. `agent-backend/agent/llm.py` — provider selection, token caps, retries
21. `docker-compose.yml` — `MCP_BOOKING_URL` is set explicitly because the
    defaults are localhost and silently wrong in a container; payment will
    need the same

## 14. THE M4a AUDIT (2026-08-09) — history, all findings fixed

A full audit was run after M4a Phases A+B, **before** Phase C wired anything
up. Every finding below was **reproduced**, not inferred. Findings 1–4 are
latent — committed, tested, green, and not yet reachable by a user — which is
precisely why no test caught them and why they must be fixed *before* Phase C
binds anything.

**Verified sound, so nobody re-checks:** 83 + 154 tests pass under both
`pytest tests/` and `python -m pytest tests/`; `docker compose build
mcp-services` succeeds and the running image serves both mounts with the
bundle baked in; `.dockerignore` does not exclude `app.py` or
`booking/static/`; all 203 listings have integer `price`/`mileage`/`year`
(62 have `rent_price_per_day: null`, handled).

### Findings

> **✅ ALL TWELVE ARE FIXED as of Phase C1 (2026-08-09)** — and rows
> **13–15** were found while fixing them, by *running* the thing: 13 by
> `docker compose up`, 14 and 15 by clicking cards in a browser. Row 13 is the most instructive one
> in the table: it had shipped in Phase A, survived a Docker verification,
> and would have presented in Phase D as "the form never opens" with a
> green health check pointing the other way. Each was
> re-reproduced before being fixed and re-checked after — the audit's own
> repros were not taken on trust. Where the fix went is in the right-hand
> column. Keep the table: it is the record of what the code used to do, and
> §3's whole point is that corrections are recorded rather than quietly
> edited away.

| # | Sev | Finding | Fixed by (Phase C1) |
|---|---|---|---|
| 1 | 🔴 | **`open_booking_form` forces the model to retype the listing.** Schema is `{listing: object}`, **required** — the whole record. `TOOLS_BY_PHASE[FORM_FILLING]` names it as a *model* tool, so binding the MCP tool directly breaks Principle I by construction | ✅ `agent/tools.py::build_booking_tools` — a local `@tool` whose `tool_call_schema` has **no properties at all**; the record comes from `selected_listing()`. Pinned in `test_booking_gate.py`, verified live: the price the form receives is byte-identical to the persisted record |
| 2 | 🔴 | **`submit_booking` bound to the model lets it invent the user's details.** `fields` is free-form; a model could produce a booking the user never made | ✅ Removed from `TOOLS_BY_PHASE` entirely, not left named-and-unbound. Asserted absent from the table **and** from every compiled agent |
| 3 | 🔴 | **Re-selecting leaves a stale booking.** With `booking.listing_id == "A"`, `select_listing("B")` moves the selection and leaves the booking untouched. spec.md Edge Cases requires the prior in-progress booking be **discarded, not silently merged** | ✅ `SessionState.select_listing` drops a booking whose `listing_id` no longer matches — targeted, so re-confirming the *same* car keeps what the user typed |
| 4 | 🔴 | **Refining after results strands the user.** In RESULTS_READY the model can call `search_listings`, but **nothing writes `candidate_listings`** — only `_run_research_turn → record_research`, which fires only on RESEARCHING. So the model finds a car, describes it, the user says "that one", and `select_listing` rejects it | ✅ `refine_search`: raw `search_listings` removed from RESULTS_READY and replaced by a tool that re-runs `run_research` and commits via `refine_results`. Test asserts the id that used to be refused is now selectable |
| 5 | 🟠 | **FORM_FILLING is a one-way door, and click ≠ prose.** The gate binds no `select_listing`/`search_listings` there, so "actually, the Kia" has no tool — but `_handle_action` runs **before** the agent and bypasses the gate, so clicking another card still works. Breaks Phase E's stated convergence guarantee | ✅ `select_listing` + `refine_search` bound in FORM_FILLING, so the prose path can do what the click path always could. `refine_results` is the explicit backwards route |
| 6 | 🟠 | **`save_interview_state` is not bound in RESULTS_READY**, so a budget change after results cannot update interview state or the interview A2UI surface | ✅ `save_interview_state` added to RESULTS_READY, and `refine_search` saves changed slots itself so the interview surface cannot go stale |
| 7 | 🟠 | **A stale `form.html` ships silently.** Appended a marker to `src/main.ts`, ran the suite → **83 passed**, marker absent from the shipped bundle. `listings.json` has a real generator guard; the bundle guards check self-containment and handshake but never that the artifact matches its source | ✅ `install-bundle.mjs` writes `form.build.json` (SHA-256 per source); `test_booking_server.py` recomputes and fails on drift. Viable because the build is **byte-deterministic** — measured. Non-vacuity checked: appending a marker to `main.ts` turns the test red |
| 8 | 🟡 | **Generic submit errors are attached to `full_name`.** In `main.ts` both the unexpected-response and network-failure branches set `errors = { full_name: … }`, so a transport failure highlights the name field and says something untrue about it | ✅ A separate `formError` banner in `main.ts`, rendered with `role="alert"`; neither branch writes to a field key any more |
| 9 | 🟡 | **No pickup-date sanity.** `store.validate` accepts a date in the past, and one **before** the car's `availability_date` — booking a pickup for a car that is not available yet, with the availability date right there in the record | ✅ `store.validate(fields, available_from=, today=)` — past dates and pre-availability dates rejected, the message naming the date the user needs. `available_from` is **passed in**, never looked up: this server having its own copy of a listing value is the divergence Principle I forbids |
| 10 | 🟡 | **`/health` will misreport once booking is wired.** `mcp_connected` is computed from `search_listings` only, and `discover_marketplace_tools()` connects to the marketplace URL alone | ✅ `discover_booking_tools()` + a separate `booking_connected` in `/health`. Deliberately **not** folded into `mcp_connected`, which every M0–M3 reader takes to mean the marketplace; `status` degrades on either. Verified live, both up and both down |
| 11 | 🟢 | **Latent Principle I rounding.** `money()` does `Math.round`. Harmless today (zero non-integral values measured) but would silently alter a price if the dataset gains a decimal | ✅ `money()` no longer rounds; a fractional part is preserved and grouped around the decimal point |
| 12 | 🟢 | **Double search on a resumed RESEARCHING session.** The RESEARCHING agent runs (it has search tools), *then* `_run_research_turn` runs the code-driven search. Two searches; the model's is discarded | ✅ `chat_ws` short-circuits a resumed RESEARCHING session straight into `_run_research_turn`, so the model no longer runs a search whose result nothing reads (~3k wasted tokens against a 200k/day budget) |
| **13** | 🔴 | **Found in Phase C1 by `docker compose up`, not by the audit: the booking MCP server was unreachable from any other container.** FastMCP enables DNS-rebinding protection **by default** (`allowed_hosts = 127.0.0.1:*, localhost:*`) and answers **`421 Misdirected Request`** to anything else. The backend calls `http://mcp-services:8100/booking/mcp`, so **every** containerised MCP request to booking was rejected — while `GET /booking/health` kept answering `{"status":"ok"}`, because a `custom_route` bypasses that middleware. Marketplace was unaffected only by accident: passing `host="0.0.0.0"` makes FastMCP set `transport_security = None`, so a *binding* argument was silently deciding a *security* policy, and the two servers had opposite postures neither file mentioned | ✅ `transport_security` stated explicitly on **both** servers. Pinned two ways in `test_booking_server.py`: the setting, and a real request with `Host: mcp-services:8100` through throwaway servers showing the 421 appear on FastMCP's default and vanish on ours. Re-verified in Docker: `booking_connected: true`, `status: ok`, and a real `open_booking_form` call over the container network |
| **14** | 🔴 | **Found in Phase C1 by clicking a second card: the WebSocket died.** `_persist_session` called `aupdate_state(config, {...})` with no `as_node`. LangGraph infers the attribution from the last write on the thread, so the **first** click after a model turn works — which is why Phase E's manual check passed — but two updates in a row with no run between them leave nothing to infer from and the second raises `InvalidUpdateError: Ambiguous update, specify as_node`. Re-selection is precisely the path finding 5 turned into a supported route. Worse, `chat_ws` had **no handler around the action branch** (chat and research turns both had one), so the exception killed the connection: the page went dead with no error, no reconnect, nothing in the chat log. **Every unit test passed** — they all persist through a `FakeAgent` whose `aupdate_state` is three lines of dict assignment, so none of them ever executed LangGraph's | ✅ `as_node="__start__"` (an external injection — `model`/`tools` also work and would both make the trace assert something untrue about the value's origin). Action branch now degrades like the other two. New test drives a **real** compiled graph + real checkpointer and clicks twice; the two `FakeAgent`s were given the real signature so they cannot drift again. Verified in a browser: two clicks, both confirmed in chat, socket still connected, `LST-0035` persisted and re-rendering as "✓ Selected" after a reload, two spans in Phoenix |
| **15** | 🟡 | **A page reload printed a full traceback every time.** `chat_ws`'s initial surface push sat *outside* its `try`, so a browser closing the old socket mid-push raced into an unhandled `WebSocketDisconnect`. Harmless, and that is the problem — a log that cries wolf on the most ordinary action in development is one nobody reads when something real happens | ✅ Initial push moved inside the handler. Verified: two consecutive reloads, `preview_logs --level error` → "No server errors found" |

### Decisions taken by the user on this audit (2026-08-09)

- 🔒 **`submit_booking` is NOT model-callable.** It is reachable **only**
  through the MCP App bridge (iframe → host → backend). The user's contact
  details come from the form they typed into, and a model-facing version is a
  fabrication hole. **`TOOLS_BY_PHASE[FORM_FILLING]` must be corrected to
  match** — leaving a name in the gate table that nothing binds is what made
  M2.5's `select_listing` hole possible (§3).

### Routing / decision-making improvements (recommended, agreed direction)

Findings 4 and 5 share one root cause: **there are two search paths with
unequal privileges, and only one updates state.**

1. **Route model refinements through a state-updating tool** — a
   `refine_search(...)` that re-runs `run_research` and calls
   `record_research`, so the slate, the catalogue and `select_listing` stay
   consistent. One change fixes 4 and 6 and removes the worst
   "the agent looks broken" path.
2. **Make phases reversible by an explicit route** — add `select_listing` to
   FORM_FILLING's gate, and have `SessionState.select_listing` discard a
   booking whose `listing_id` no longer matches (fixes 3 and 5 together).
3. **Local `@tool` wrappers over the MCP booking tools** —
   `open_booking_form(listing_id)` with `InjectedState` reads
   `selected_listing()` and passes the verbatim record server-side, the
   `select_listing` pattern. Fixes 1, and keeps the gate honest alongside the
   `submit_booking` decision above.
4. **Give FORM_FILLING its own prompt** — it currently shares
   `TRANSACTION_SYSTEM_PROMPT` with AWAITING_PAYMENT. It should say the form
   is on screen, do not collect details in chat, do not restate them.
5. **Put the phase in the model's context** — one line per turn
   (`Phase: FORM_FILLING. Selected: LST-0042. Form open, not submitted.`).
   ~20 tokens against DeepAgents' 2.7k schema tax.
6. **Guard duplicate submits** in `SessionState.submit_booking()`.
7. **Decide the relaxation-ladder demo issue before demo day** (§11) — the
   headline path opens on an apology unless a late target date is used.

---

**Suggested opening prompt for the new chat** — copy this verbatim:

> Read `/home/abbas/ai-car-matchmaker/HANDOFF.md` in full, then everything it
> lists under §13 Required reading — Tier 1 and Tier 2 closely, Tier 3 as
> needed. §13 was re-tiered on 2026-08-09 for this phase.
>
> This is the Amulate Summer Hackathon 2026 "AI Car Matchmaker".
> **M0 through M4a are complete, verified live and pushed.** Interview →
> automatic research → deterministically ranked A2UI catalogue → listing
> selection by click *or* by speaking → the booking form as a real MCP App
> inside the chat → server-side validation → booking recorded →
> AWAITING_PAYMENT. Verified against a full `docker compose up --build`, in
> a real browser, with a real conversation. **Hard requirement #3 is met.**
>
> **Start M4b: the mock checkout MCP App (hard requirement #4).** §10 scopes
> it and §13 Tier 2 lists the six files that already solve the problems it
> will hit. It should be markedly cheaper than M4a — the pattern exists now,
> `app.py::compose` already mounts multiple servers, and the frontend host
> is generic (it renders whatever `mcp_app` envelope arrives, so a second
> App needs no new host code).
>
> **The one thing M4b must get right that M4a did not have to:**
> Constitution **Principle III**. M4a satisfied it by construction — the
> booking form has no payment field. Checkout does. `confirm_mock_payment`
> will receive card-like input and must discard it at the boundary, before
> validation and before persistence, so it never reaches a session record,
> a log line or an OTel span. `mcp-services/booking/store.py::normalise` is
> the pattern; prove it with a test that submits a card number.
>
> Measured 2026-08-09 with nothing else running: **328 tests** —
> mcp-services **94**, agent-backend **214 passed + 9 skipped**, frontend
> **11** (vitest). **319 need no external setup.** The live suite was run
> against a real model the same day: **agent-backend 217 passed, 0
> skipped**; six ungated tests have been added since, so expect 223/0.
>
> Do **not** write code immediately. Confirm you have full context, tell me
> anything that looks wrong, stale or self-contradictory, then design M4b
> and check it with me before implementing.
>
> **Priority: build the product.** The slide deck (#13) and demo video (#14)
> are deliberately last and are mine to own — don't spend session time on
> them unless I ask.
>
> Read §3 carefully — it is the most valuable section in the repo. Nine
> rounds of correction, each a *different* shape: docs overclaiming, docs
> underclaiming, docs accurate but code defective, a doc wrong about a
> *procedure* it recommended, tests finding four defects on their first live
> run, latent defects in committed green code nothing had wired up, a false
> claim found by *fixing the previous audit*, and — most recently — four
> defects found by simply **talking to the finished product**, three of them
> visible only on a screen. The constant is not that documentation drifts;
> it is that **nobody ran it.** Check every direction.
>
> Carried-forward gotchas, each of which cost a cycle:
> - **The model cannot see the screen.** Every surface renders from
>   persisted state straight to the browser, so the UI and the model hold
>   different views. Anything the user can point at ("the Lexus", "that
>   price") must be put in the model's context deliberately —
>   `phase_context_line()` does this. **Test conversational behaviour on a
>   resumed session**, never only a fresh one; a fresh session hides the
>   whole class of bug because narration happens to fill the gap.
> - **Raw MCP tools must never enter `extra_tools`.** `resolve_registry`
>   resolves extras *over* local tools, so a raw tool silently replaces the
>   safe wrapper of the same name — same name, same phase, green suite.
> - **A FastMCP server needs explicit `transport_security`**, or it answers
>   `421` to every request from another container while its `/health` route
>   cheerfully says ok (health routes bypass that middleware).
> - **`MultiServerMCPClient.get_resources()` drops `_meta`**, i.e. the CSP.
>   Use a raw `ClientSession.read_resource()`.
> - **ext-apps: the host API is on the `/app-bridge` subpath**, and
>   `sendToolInput` is required *before* `sendToolResult`.
> - **Never render a listing's `description`** — attacker-controlled, and it
>   carries the `<untrusted_listing_data>` delimiters. Note it rides in the
>   tool *arguments* even when stripped from the *result*.
> - **After ANY edit to `mcp-apps-ui/*/src/`, rebuild the bundle** and commit
>   both `form.html` and `form.build.json`. Staleness is detected now (a
>   test fails), not fixed for you.
> - **Measure test counts with nothing else running.** A count taken with
>   Docker up reads one test higher, and I published that mistake once.
> - **Groq's binding limit is 200,000 tokens/day ≈ 66 agent turns**, invisible
>   in the rate-limit headers. A 20–70s "hang" is retry backoff, not a
>   failure. ~20–25% of 2026-08-09's budget was spent on Phase E.
> - Live-gated tests read `LLM_CREDENTIALS_PRESENT` from
>   `agent-backend/conftest.py`. Don't recompute it in a test module and
>   don't import `api.main` at module scope.
> - A2UI is **v0.9**; only the 18 components in §8.19 exist. Read §8.21c–f
>   before touching a surface.
> - Outbound POSTs to LLM providers fail inside the default tool sandbox;
>   live-LLM commands need `dangerouslyDisableSandbox: true`.
> - **Rotate the four API keys after the demo** (§5). Still outstanding.
