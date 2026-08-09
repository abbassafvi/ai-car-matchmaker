# AI Car Matchmaker

A multistep AI agent that interviews a user about the car they want to buy
or rent, researches a marketplace on their behalf, and presents ranked,
explained recommendations — with in-chat booking and mock checkout via
[MCP Apps](https://apps.extensions.modelcontextprotocol.io/), and a live
catalogue/progress UI driven by [A2UI](https://a2ui.org/).

Built for the Amulate Summer Hackathon 2026.

## Status

M0 (scaffolding) + M1 (foundational) + M2 (conversational interview, User
Story 1) + M2.5 (audit remediation) complete. **M3 (research & ranked
recommendations, User Story 2) is complete** — the marketplace MCP server
is built, the agent runs fully async against it, and interview → automatic
research → deterministically ranked, explained recommendations now works end
to end and **renders live as A2UI surfaces**: an interview checklist, a
reasoning-steps trace of how the search ran, and a catalogue of ranked cards.
Listing selection works too — each catalogue card has a button that records
the choice and advances the phase. **User Story 2 is complete**, including
its two behavioural guarantees, both proven against a live model: the three
seeded prompt-injection listings cause zero deviation, and a search that
matches nothing is widened *and said so*. The in-chat MCP Apps (booking
form, mock checkout) are the remaining M4 work: the **booking MCP App server
and its form bundle now exist and are verified** (M4a Phases A+B), and the
agent now **opens the form for the car the user picked and records the
booking it comes back with** (Phases C1–C2 — tools, phase transitions,
discovery, and the WebSocket bridge that carries the App and its
`tools/call` both ways). Rendering that form in the browser is the rest of
M4a.

**311 automated tests**, of which **303 run with no external setup at all**
(94 `mcp-services` + 209 `agent-backend`); the remaining 9 need a live LLM key
and/or a running Phoenix and auto-skip without them. The 202 tests that
existed on 2026-08-08 have been run green together against a live model and a
running Phoenix; the 109 added since need no external setup and none is gated.
Plus live end-to-end verification against a real Docker Compose build. See
[`specs/001-ai-car-matchmaker/`](specs/001-ai-car-matchmaker/) for the full
spec-driven-development trail:

- [`spec.md`](specs/001-ai-car-matchmaker/spec.md) — user stories, requirements, success criteria
- [`plan.md`](specs/001-ai-car-matchmaker/plan.md) — architecture, tech stack, constitution gates
- [`tasks.md`](specs/001-ai-car-matchmaker/tasks.md) — milestone-by-milestone task breakdown, including bugs found during live verification
- [`.specify/memory/constitution.md`](.specify/memory/constitution.md) — non-negotiable project principles

## Architecture

```
frontend (React + Vite)          agent-backend (Python)         mcp-services (Python)
 ├─ A2UI renderer (@a2ui/react)  LangChain DeepAgents    ◄──►   marketplace ✅ (live)
 └─ MCP-Apps host (iframes, M4a) LangGraph +                    booking (live) / payment (M4b)
        │                        AsyncSqliteSaver               MCP over Streamable HTTP
        │ WebSocket                     │
        └──────────────────►    Arize Phoenix (OTel traces)
```

## Running locally

1. Copy `agent-backend/.env.example` to `agent-backend/.env` and fill in
   `LLM_API_KEY` (get a Gemini key at
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
2. `docker compose up --build`

Without a key the stack still comes up — `/health` reports
`status: degraded` and the chat replies with what to configure, rather than
the backend dying at startup.

> **Quota note**: Gemini's free tier allows roughly **20 requests per day
> per model** — a smoke test, not a live demo. Groq works end-to-end with
> tool calling and is the default for development; see `.env.example` for
> both configurations. Groq's binding limit is **200,000 tokens per day**
> (~66 agent turns here) plus 8,000 tokens per minute, so a burst of turns
> can be throttled — the client retries, and it is backoff, not a hang.
>
> If you point `LLM_PROVIDER=openai_compatible` at Groq, leave
> `LLM_MAX_TOKENS` alone unless you re-measure: Groq rate-limits on *tokens
> per minute*, and raising the output cap pushes agent turns from ~2s into
> 40–70s of retry backoff.

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Agent backend (health) | http://localhost:8000/health |
| Agent backend (chat) | ws://localhost:8000/ws/{session_id} |
| MCP services — marketplace (health) | http://localhost:8100/health |
| MCP services — marketplace (protocol) | http://localhost:8100/mcp |
| MCP services — booking (health) | http://localhost:8100/booking/health |
| MCP services — booking (protocol) | http://localhost:8100/booking/mcp |
| Phoenix (traces UI) | http://localhost:16006 |

`mcp-services` runs **two** MCP servers over Streamable HTTP in one process:
**marketplace** at `/mcp` (`search_listings`, `get_listing_details` over the
203-listing mock dataset) and **booking** at `/booking/mcp`
(`open_booking_form`, `submit_booking`, plus the `ui://booking/form.html`
MCP App resource). The payment server lands in M4b. The agent discovers
**both** servers at startup, so `agent-backend`'s `/health` reports
`mcp_connected` (marketplace) and `booking_connected` alongside
`llm_configured` — `status` is `degraded` if any is missing. Discovery is
fail-soft in both directions: an unreachable booking server degrades the
booking step rather than stopping the backend.

`submit_booking` is deliberately **not** exposed to the model in any phase.
It takes free-form form values, so a model-callable version could invent
the user's contact details; it is reachable only from the booking form
itself, through the MCP App bridge, with the values the user typed.
`open_booking_form` *is* model-callable but takes **no arguments** — it
reads the chosen listing from session state, so no price can enter through
a tool call the model wrote.

**How recommendations stay grounded**: once the interview is complete the
backend runs the marketplace search itself, building the query from the
saved interview slots rather than asking the model to restate them, and
ranks the results in deterministic Python. The model receives the ranked
records and explains them; it never originates a price, year or mileage.
See [Constitution Principle I](.specify/memory/constitution.md).

The frontend is a production Vite build served by nginx, and `agent-backend`
runs the actual FastAPI + DeepAgents agent.

## Running tests locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r agent-backend/requirements.txt -r mcp-services/requirements.txt

(cd mcp-services && python -m pytest tests/ -v)
(cd agent-backend && python -m pytest tests/ -v)
```

Two test categories auto-skip without extra setup rather than failing:

- Anything needing a live LLM call skips without `LLM_API_KEY` set
  (export it, or `set -a && . agent-backend/.env && set +a` first, to run them)
- The Phoenix tracing test skips unless Phoenix is running:
  `docker compose up -d phoenix`

### Rebuilding the booking form (MCP App)

`mcp-services/booking/static/form.html` is a **committed build artifact** —
one self-contained HTML file produced from `mcp-apps-ui/booking-form/`, so
the Python image needs no Node stage. After editing anything under
`mcp-apps-ui/booking-form/src/`:

```bash
(cd mcp-apps-ui/booking-form && npm install && npm run build)
```

The build writes `form.html` **and** `form.build.json`, a manifest of
SHA-256 hashes of every source that feeds the bundle. Commit both.
`mcp-services/tests/test_booking_server.py` recomputes those hashes and
fails when the committed artifact no longer matches its source, so a stale
bundle is now caught by the ordinary test run rather than by noticing the
form behaves like an older version of itself. (This works because the build
is byte-deterministic: rebuilding an unchanged tree reproduces `form.html`
exactly.) The check skips when the TypeScript sources are absent, e.g.
inside the Python image.

The build also still refuses to install a bundle that references external
assets (a sandboxed, opaque-origin iframe cannot load them) or that is
missing the MCP Apps handshake.

The gate itself is on key *presence*, but an out-of-quota key no longer
reads as a bug: a provider 429 that names a quota is routed through
`skip_if_quota_exhausted`, so those tests **skip** with the provider's own
message rather than going red. Anything that is not an explicit quota signal
still re-raises.

## Tech stack

- **Agent harness**: [LangChain DeepAgents](https://docs.langchain.com/labs/deep-agents/overview) (LangGraph)
- **LLM provider**: config, not code. `LLM_PROVIDER=google` uses [Google Gemini](https://ai.google.dev/) via the native `langchain-google-genai` client (default `gemini-3.6-flash`); `LLM_PROVIDER=openai_compatible` uses any OpenAI-compatible API. Development runs on [Groq](https://groq.com/) (`openai/gpt-oss-120b`), keeping the scarce Gemini quota for demo rehearsal. Groq's free tier is generous on request count but capped at **200,000 tokens/day** — roughly 66 agent turns here, since the DeepAgents harness binds ~2,700 tokens of tool schemas into every request
- **Tool protocol**: [MCP](https://modelcontextprotocol.io/) (Python SDK, Streamable HTTP) — marketplace **and** booking servers live at `/mcp` and `/booking/mcp`; payment in M4b
- **In-chat transactional UI**: [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) (`@modelcontextprotocol/ext-apps` 1.7.5) — the booking form is built and served as a `ui://` resource; rendering it in the chat and the mock checkout are the rest of M4
- **Generative UI**: [A2UI](https://a2ui.org/) v0.9 protocol via the real [`@a2ui/react`](https://www.npmjs.com/package/@a2ui/react) renderer — car catalogue + live agent progress/reasoning
- **Observability**: [Arize Phoenix](https://arize.com/docs/phoenix) via OpenTelemetry
- **Spec process**: [spec-kit](https://github.com/github/spec-kit)

## No real payments

The checkout flow is fully mocked. No real payment gateway, no BMW Group
APIs, no persistence of payment-instrument data anywhere in the system —
see Constitution Principle III.
