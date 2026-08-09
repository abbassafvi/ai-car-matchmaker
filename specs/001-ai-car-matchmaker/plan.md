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
  `LLM_MODEL=openai/gpt-oss-120b`), which is what made M3's behavioural
  tests (T021, T029) affordable rather than deferred. **Corrected in Phase
  F**: the binding quota is **200,000 tokens/day**, not the "~1000
  requests/day" recorded here through M3 — about 66 agent turns, because
  DeepAgents binds ~2,700 tokens of tool schemas into every request. A full
  Phase F live run costs ~9% of a day, and T046's eval set will not fit
  alongside a demo rehearsal.
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
| I. Grounded Recommendations | UI values sourced only from tool-call records, never LLM-retyped | **PASS at the A2UI surfaces (M3 Phase D) and at the booking MCP App (M4a).** The App is the stronger case: `open_booking_form` is bound to the model with **no arguments at all**, so the listing reaches the form from `SessionState.selected_listing()` and there is no channel through which a retyped price could enter — grounding made structural rather than prompt-enforced. Verified live end to end: the price, year and mileage the form renders are byte-identical to the persisted search record. One residual remains, noted below. The catalogue renders from `SessionState.candidate_listings` + `.recommendations` only; `test_catalogue_grounding.py` compares every rendered value back to its source record and asserts its own non-vacuity, and a live run confirmed all 16 catalogue values byte-identical to `listings.json`. **Residual**: the chat narration is still model-authored prose, and while `narration_brief` forbids any number not printed in the brief, that constraint is prompt-enforced rather than structural — the *grounded* channel is the catalogue. T029/T046 measure the prose. Previously recorded as: PARTIAL (materially advanced in M3 Phase C) — listing data now reaches the user, and it is grounded end to end: the search query is built from persisted interview state rather than from the model (`agent/research.py`), ranking is deterministic Python over the tool artifact (`agent/ranking.py`), and the verbatim records are persisted in `SessionState.candidate_listings`. Verified live: four recommended listings byte-identical to `listings.json` on price/year/mileage/category, and all 11 numbers in the model's narration traceable to the slate. Still PARTIAL because the **A2UI surface** is the part the principle names and that is T026/T022 (Phase D) — today the values reach the user as chat prose |
| II. Explicit Phase Gating | Transactional tools unavailable outside their phase | PASS (since M2.5, completed M3 Phase E) — `TOOLS_BY_PHASE` in `agent/state.py` is the single gate definition and `agent/graph.py` builds one agent per phase from it. **All three phase transitions are now code paths in `SessionState`** (`save_interview_slots`, `record_research`, `select_listing`), none of them a model decision. Phase E closed the last hole: `select_listing` had been *named* by the gate since M2.5 with nothing implementing it, so Principle II's own worked example — `open_booking_form` gated on a listing being selected — had no precondition anything could satisfy. Covered by `test_phase_gate.py`, `test_mcp_wiring.py`, `test_select_listing.py`. **Caveat**: `FORM_FILLING` is now reachable but its tools land in M4a |
| III. Mock-Only Transactions | No real payment path exists | **PENDING — and M4b is where it stops being free.** M4a satisfies it by construction (the booking form has no payment field), so nothing has yet been *tested against an actual card-like input arriving*. `confirm_mock_payment` will receive one. Enforced ahead of time so far (M4a Phase A): The booking form has no payment field at all, and `booking/store.py`'s `FIELDS` is an allowlist that `normalise()` applies *before* validation and persistence, so a card number submitted into a tampered form is discarded at the boundary rather than filtered later. Tests assert both the schema property and the runtime drop. `confirm_mock_payment` and the real enforcement point still land in M4b |
| IV. Untrusted Data Boundary | Listing/user text never treated as instructions | **PASS on `openai/gpt-oss-120b` (since M3 Phase F)**, with one caveat below. The rule is in every listing-facing prompt, `store.wrap_untrusted()` genuinely emits the delimiters server-side, and **T029 now supplies the behavioural proof**: all three `ADV-*` probes reach the model inside the delimiters and cause zero deviation — no fabricated `$1` price, no unrequested `select_listing` call, no phase advance, no system-prompt or credential disclosure, and the deterministic ranking byte-identical across the model turn. A fourth test asserts the probes do not derail the turn either, since a boundary enforced by refusing to answer is not a win. Run against **both** shipped models: Groq `openai/gpt-oss-120b` and Gemini `gemini-3.6-flash`, clean on each. An injection result is only evidence for the model it ran on, so re-run T029 whenever the model changes. Previously recorded as: PARTIAL (improved in M3 Phase B) — the *rule* is in every listing-facing prompt (`agent/prompts.py`), and the delimiters it refers to are now genuinely emitted: `store.wrap_untrusted()` wraps each `description` server-side, at the tool-output boundary, before it can reach the model. Confirmed live that the `ADV-0001` payload arrives inside the delimiters via `langchain-mcp-adapters`. Still PARTIAL because what remains is the **behavioural** proof — T029 must show the three `ADV-*` probes cause zero deviation. A wrapper the model ignores is not a boundary |
| V. Full Observability | Every call/transition traced | **PASS since M4a Phase C1 — previously overstated.** LLM calls and tool calls have been traced since M2.5 via `setup_observability(auto_instrument=True)`, which patches LangChain. **Phase transitions were not**, and the row said they were: a grep for `get_tracer`/`start_as_current_span` across production code returned nothing, so every span was a by-product of a graph *run* — while `_handle_action` advances RESULTS_READY → FORM_FILLING through `aupdate_state`, outside any run, and the MCP App bridge will do the same on submit. `SessionState` now emits a `phase.transition` span itself, from beside the mutation rather than from each caller, carrying `phase.from`/`phase.to`/`phase.trigger`. Fail-soft (§8.28). **Verified against a running Phoenix**, not only at the SDK: a four-transition session produced four `phase.transition` spans, each carrying the right `phase.from`/`phase.to`/`phase.trigger`/`session.id` (§3 lesson 4). Covered by `test_phase_spans.py` (the span is real) and `test_booking_state.py` (every transition emits one) — split deliberately, since "the mechanism exists" and "the mechanism is called" are exactly the two things M2.5 found failing independently |

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

### Correction (M3 Phase E / pre-Phase-E audit)

A fifth audit, run before Phase E. **This one found the docs accurate and
the code defective** — the inverse of every prior round, and worth recording
because a reader primed to distrust the docs would have looked in the wrong
place.

- **Tracing was on the request critical path.** `phoenix.otel.register`
  defaults to `batch=False`, i.e. a `SimpleSpanProcessor` that exports every
  span synchronously. Principle V's row said tracing was wired and fail-soft,
  and it was — at *registration*. At *export* it blocked the agent turn until
  the collector answered, so a slow Phoenix would have stalled the demo. One
  keyword (`batch=True`) fixed it; a cold `pytest` went 105s → 4.2s. Nothing
  was wrong with the project's code; the library default was wrong for it.
- **Row II's remediation left a decoy behind.** `SessionState.available_tools()`
  still has zero production callers. M2.5 fixed the *principle* by building
  `TOOLS_BY_PHASE` + `tools_for_phase`, but the method that the M2.5 finding
  actually named was never wired up and is still tested by 9 assertions,
  which makes it read as load-bearing. Re-documented, not deleted.

Fifth lesson: **a defect can hide in a default**, and "the docs are wrong" is
only one of the failure modes. The constant across all five audits is not
that documentation drifts — it is that **nobody ran the thing**.

### Correction (M3 Phase F / pre-Phase-F audit)

A sixth audit, run before Phase F. It found a **new variant**: the docs were
accurate about shipped code, but wrong about a *procedure* — a recipe for how
the next session should do its work. HANDOFF §10 and §13 had recommended,
across two milestones, that T029 surface the `ADV-0002` probe via "a
budget-constrained SUV search that relaxes its budget". Measured against the
committed dataset, that route fails three ways independently: the relaxation
ladder tries availability first and succeeds there, so the budget rung never
runs; the 1.2 factor lifts $25,000 only to $30,000 while the probe costs
$31,000; and the 5-item slate truncation would drop it regardless, since it
is the 7th-cheapest match. Three measured replacement routes are now recorded
in tasks.md T029 and HANDOFF §10.

The same audit found an unrecorded fact that changes what T029 must target:
**the probes reach the RESULTS_READY agent, not the RESEARCHING one.**
`_run_research_turn` advances the phase via `record_research()` before it
selects the narrator, so the untrusted narration brief is consumed under
`RESULTS_SYSTEM_PROMPT`. Row IV below is unaffected — both prompts carry
`UNTRUSTED_DATA_RULE` — but RESULTS_READY additionally binds
`select_listing`, so T029 gains a state-level assertion (no unrequested
selection, no advance to FORM_FILLING) that is stronger than any prose check.

Sixth lesson: **prose describing future work is untested by construction.**
Five audits asked "does the code do what the doc claims?"; none had asked
"does the doc's *instruction* actually work?" A recipe earns the same
scepticism as a status claim, and is more dangerous, because it is read by
someone who has no reason yet to doubt it.

### Correction (M3 Phase F, after the fact)

Recorded because it inverts the sixth lesson's own framing. The audit above
scrutinised the *documentation* and found the code sound. Then the two tests
that audit was clearing the way for ran, and **found four real defects in
that same code** — three of which every doc described accurately, because
the docs described what the code was *meant* to do and nobody had watched it
do it. In order of seriousness:

1. **The agent silently widened a search and said it had not** — "Four
   listings matched your criteria" for a slate produced by dropping the
   availability filter. Every number grounded, the claim false. This is the
   spec.md US2 AS2 failure T021 exists to catch, and it was live in `main`.
2. **On zero results the model invented the constraints it had tried**,
   because the brief asked it to name them without stating them.
3. **The live-test credential gate had stopped working** — `load_dotenv()`
   at import time in `api/main.py` polluted `os.environ`, so `skipif`
   results depended on collection order.
4. **The tests' own number extractor misread real model output**, which
   would have reported a hallucination that never happened.

Seventh lesson, and it is the one this project keeps paying for in a new
currency each milestone: **Principle I constrains values, not claims.** A
sentence can be assembled entirely from grounded numbers and still be false,
because the falsehood is in what it asserts *about* the search. Grounding
checks cannot be the last line of defence between a user and a lie — and
"the docs are accurate" is not evidence that anything works.

### Correction (M4a Phases A+B / the 2026-08-09 audit)

A seventh audit, run after M4a's server and form bundle shipped but **before**
Phase C wired them to the agent. It found a **new variant** again: every prior
audit examined behaviour already reachable by a user. This one examined code
that was committed, tested, green — and **not yet called by anything** — and
found four latent defects that Phase C would have shipped. No test could have
caught them, because there was nothing to test against yet.

The two that bear on this table:

- **Principle I would have been violated by construction in FORM_FILLING.**
  `open_booking_form`'s MCP schema is `{listing: object}`, **required** — the
  whole record. `TOOLS_BY_PHASE[FORM_FILLING]` names it as a *model* tool, so
  binding it directly means the model retypes every price, year and mileage
  as tool arguments. In the exact phase Principle II's own worked example is
  about. Fix: local `@tool` wrappers with `InjectedState` that read
  `SessionState.selected_listing()` and pass the verbatim record server-side.
- **Principle II's gate table was about to acquire a second lie.**
  `submit_booking` takes free-form `fields`, so a model-facing version could
  fabricate the user's name and email into a booking they never made. Decided
  2026-08-09: **`submit_booking` is not model-callable**, reachable only
  through the MCP App bridge, and the gate table is corrected to match — a
  name in that table that nothing binds is exactly the hole M2.5 left with
  `select_listing`.

Also found, and material to Principle II: **the click path and the prose path
diverge again in FORM_FILLING.** The gate binds no `select_listing` there, so
"actually, the Kia" has no tool — but `_handle_action` runs *before* the gate
and bypasses it, so clicking another card still works. Phase E's convergence
guarantee turned out to be a property of one phase, not of the design. And
re-selecting leaves a **stale booking** attached to the previous listing,
which spec.md's Edge Cases explicitly forbid.

Full finding list, severities and repros: HANDOFF §14.

Eighth lesson: **unwired code is unaudited code.** A milestone that lands a
server, a schema or a bundle before anything calls it gets a fully green suite
with zero coverage of how it will actually be used. Read a new tool's *input
schema* and ask who fills it in — a signature that is convenient for code to
call can be a constitution violation for a model to call, and nothing in the
tests will say so.

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

### Correction (M4a Phase C1) — Principle V had never been fully true

Not an audit this time: the eighth correction was found while *fixing* the
seventh audit's findings, which is worth recording because it is the
cheapest way any of these has ever been found. Touching all five phase
transitions to add the two M4a needed made it obvious that the row above
claimed something no code did.

- **Row V said "every LLM call, tool call, and phase transition emits an
  OTel span" and had said so since M2.5.** Two thirds of that was real.
  The third was not: nothing in `agent-backend` emitted a span explicitly,
  so every span came from `auto_instrument` patching a LangChain *run* —
  and `_handle_action` advances a phase through `aupdate_state` with no run
  at all. The catalogue-click path, shipped in Phase E, had been silently
  untraced ever since, and the MCP App bridge was about to add a second
  one. Fixed by emitting from inside `SessionState`, next to each
  transition, rather than at the call sites — the M2.5 lesson applied:
  a mechanism every caller must remember to invoke is one forgotten call
  site away from decorative.

Rows I, II and III also strengthened, all through §14's findings:

- **I.** `open_booking_form` is bound to the model with **no arguments at
  all** (`tool_call_schema` has no properties), so the listing record
  reaches the booking server from `SessionState.selected_listing()` and
  cannot be retyped by the model. Grounding at this boundary is now
  structural, not prompt-enforced. Verified live against the running
  server: the price and year the form receives are byte-identical to the
  persisted search record.
- **II.** `submit_booking` removed from the gate table entirely rather
  than left named-and-unbound; `select_listing` and `refine_search` added
  to FORM_FILLING so the phase is reversible by an explicit route instead
  of only by the UI accident of `_handle_action` running ahead of the gate;
  raw `search_listings` removed from RESULTS_READY, because a search that
  cannot update the slate produces recommendations `select_listing` then
  refuses.
- **III.** Verified live rather than only in unit tests: a `card_number`
  submitted through the real MCP `submit_booking` is dropped by
  `store.normalise`'s allowlist and never appears in the returned booking.

And one defect found not by reading anything but by bringing the stack up:
**the booking MCP server had never been reachable from another container.**
FastMCP enables DNS-rebinding protection by default and answers `421` to any
`Host` outside `localhost`, so every MCP call the backend made to
`http://mcp-services:8100/booking/mcp` was rejected — while
`GET /booking/health` answered `ok`, because a `custom_route` bypasses that
middleware. Phase A's Docker verification checked the health routes.
Marketplace was fine only because `host="0.0.0.0"` makes FastMCP drop the
setting, so a binding argument was deciding a security policy. Both servers
now say so explicitly.

Tenth lesson: **a health route is not evidence about the protocol path.**
They are served by different middleware, and the one that answers first is
the one least likely to be broken.

Ninth lesson, and it is a cheerful one for once: **fixing an audit finding
is itself an audit.** Four of the five transitions were untouched code that
nobody had reason to reread; the fifth required editing all of them, and
the false claim fell out immediately. When a change forces a sweep across
every instance of some pattern, read what is already there — that sweep is
the audit you are not otherwise going to run.

### Correction (M4a Phase E) — found by talking to it, not by auditing it

The ninth round, and the second that came from no audit at all. M4a's five
phases were complete and every suite was green; the defects turned up in the
first real conversation through the finished stack. Three were visible only
on a screen, and none was reachable from any test.

- **The model cannot see the screen, and a resumed session exposes it.**
  Every surface in this project renders from persisted state *straight to
  the browser* — which is exactly what Principle I asks for, and it means
  the UI and the model hold different views of the session. Asked for "the
  Lexus", the agent replied asking for a listing id: it only ever learns the
  slate through its own message history, and a resumed session has none. A
  *fresh* session hides this completely, because the research turn happens
  to narrate the cars into context. spec.md US5 says a resumed session
  continues where it left off; being asked to quote an id is not that.
- **Row II's convergence held on state and broke on screen.** A spoken
  selection recorded the choice and opened the booking form while every
  catalogue card still read "Choose this one" — `_handle_action` re-renders
  after a click and nothing re-rendered after the tool. Invisible to every
  test, all of which assert on `SessionState`, and the state was correct.
- **A fix written as a rule was applied to one instance.** Phase F put the
  no-markdown rule in `research.py`'s narration brief; the *results* prompt
  had never carried it and emitted `**LST-0039 ...**` literally two
  milestones later.
- **A perfectly grounded reply promised things that do not exist** — a test
  drive, financing, a trade-in, delivery. Principle I held perfectly: not one
  value was invented. Lesson 13 again, in a new currency.

Ninth lesson: **test conversational behaviour on a resumed session.** A
fresh session is the easy case and it conceals an entire class of bug — one
that Principle I's own architecture creates, by design, every time a surface
renders from state rather than through the model.

Tenth lesson: **when a fix is a rule, fix the class.** Ask which other
places the rule applies to and assert it across all of them, or the next
surface to grow the same shape will reproduce the defect.

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
│   └── mcp-app-host/               # ✅ M4a Phase D: AppBridge host —
│                                   #   postMessage bridge (adapted from
│                                   #   ext-apps/examples/basic-host)
└── tests/

docker-compose.yml                  # frontend, agent-backend, mcp-services, phoenix
```

**Structure Decision**: Multi-service web application (Option 2 variant),
extended from 2 services (backend/frontend) to 4 logical units because MCP
servers must be independently network-addressable (Streamable HTTP) from the
agent backend — collapsing them into the agent-backend process would break
that addressability. `mcp-apps-ui` is deliberately not a running service:
it produces a static asset committed into `mcp-services` and served as the
`ui://` resource.

**Corrected 2026-08-09 (M4a).** This paragraph previously also said the
**frontend's** MCP-Apps host fetches `ui://` resources directly from
`mcp-services`. That was never built and is not the design taken: it would
put a second MCP client in the browser (plus CORS), and — worse — a form
submitted straight to `mcp-services` would bypass agent-backend entirely,
while the `FORM_FILLING → AWAITING_PAYMENT` transition and the `Booking`
record live in the backend's checkpointer. **The backend reads the `ui://`
resource over MCP and pushes the HTML to the frontend over the existing
WebSocket**, and the host tunnels the App's `tools/call` back the same way
(`AppBridge` accepts a null MCP client; `oncalltool` is a public setter).
One wire contract, one source of session truth.

**Also corrected**: `mcp-services` is described above as "3 MCP servers, one
process". Until M4a that was aspirational — the container ran a single app
(`marketplace.server:app`). As of M4a Phase A it is real: `mcp-services/app.py`
mounts marketplace at `/mcp` (unchanged) and booking at `/booking/mcp`, and
the Dockerfile runs `app:app`. Payment joins at `/payment/mcp` in M4b.

**And a third correction (M4a Phase C1)**: each mounted FastMCP server must
declare `transport_security` explicitly. The default enables DNS-rebinding
protection with a localhost-only allowlist, so booking answered `421` to
every request from another container while `GET /booking/health` — a
`custom_route`, which bypasses that middleware — kept reporting `ok`.
Marketplace was unaffected only because passing `host="0.0.0.0"` makes
FastMCP drop the setting entirely, i.e. a binding argument was silently
deciding a security policy. Payment must state it too.

## Complexity Tracking

*(empty — no constitution violations to justify)*
