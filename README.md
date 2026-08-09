# AI Car Matchmaker

A multistep AI agent that interviews a user about the car they want to buy
or rent, researches a marketplace on their behalf, and presents ranked,
explained recommendations — with in-chat booking and mock checkout via
[MCP Apps](https://apps.extensions.modelcontextprotocol.io/), and a live
catalogue/progress UI driven by [A2UI](https://a2ui.org/).

Built for the Amulate Summer Hackathon 2026.

## Status

**All 5 user stories complete.** M0–M4c delivered:

- **M0–M1**: Scaffolding, foundational (checkpointer, MCP wiring, observability)
- **M2 (US1)**: Conversational interview — the agent asks questions, extracts structured slots
- **M3 (US2)**: Research & ranked recommendations — marketplace search, deterministic ranking, A2UI catalogue
- **M4a (US3)**: In-chat booking — MCP App form, phase transitions, WebSocket bridge
- **M4b (US4)**: Mock checkout — payment MCP App, Principle III enforcement, synthetic confirmations
- **M4c (US5)**: Session resume — auto-reconnect, SQLite persistence, concurrent session isolation

**261 automated tests** (agent-backend) + **146** (mcp-services) + **11** (frontend) = **418 total**.
9 tests skip without a live LLM key or Phoenix; the rest run with no external setup.

LLM provider fallback: when the primary provider (Groq or Vertex AI) hits a
rate limit or quota error, the agent automatically retries on a configured
fallback provider — critical for demos where quota is有限.

See [`specs/001-ai-car-matchmaker/`](specs/001-ai-car-matchmaker/) for the full
spec-driven-development trail:

- [`spec.md`](specs/001-ai-car-matchmaker/spec.md) — user stories, requirements, success criteria
- [`plan.md`](specs/001-ai-car-matchmaker/plan.md) — architecture, tech stack, constitution gates
- [`tasks.md`](specs/001-ai-car-matchmaker/tasks.md) — milestone-by-milestone task breakdown, including bugs found during live verification
- [`.specify/memory/constitution.md`](.specify/memory/constitution.md) — non-negotiable project principles

## Architecture

```
frontend (React + Vite)          agent-backend (Python)         mcp-services (Python)
 ├─ A2UI renderer (@a2ui/react)  LangChain DeepAgents    ◄──►   marketplace ✅
 └─ MCP-Apps host (iframes)      LangGraph +                    booking ✅
        │                        AsyncSqliteSaver               payment ✅
        │ WebSocket                     │                       MCP over Streamable HTTP
        └──────────────────►    Arize Phoenix (OTel traces)
                                LLM Fallback (Groq ↔ Vertex AI)
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
| MCP services — payment (health) | http://localhost:8100/payment/health |
| MCP services — payment (protocol) | http://localhost:8100/payment/mcp |
| Phoenix (traces UI) | http://localhost:16006 |

`mcp-services` runs **three** MCP servers over Streamable HTTP in one process:
**marketplace** at `/mcp` (`search_listings`, `get_listing_details` over the
203-listing mock dataset), **booking** at `/booking/mcp`
(`open_booking_form`, `submit_booking`, plus the `ui://booking/form.html`
MCP App resource), and **payment** at `/payment/mcp`
(`open_mock_checkout`, `confirm_mock_payment`, plus the
`ui://payment/checkout.html` MCP App resource). The agent discovers all
three servers at startup, so `agent-backend`'s `/health` reports
`mcp_connected` (marketplace), `booking_connected`, and `payment_connected`
alongside `llm_configured` — `status` is `degraded` if any is missing.
Discovery is fail-soft in both directions: an unreachable server degrades
that step rather than stopping the backend.

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

# Frontend units (vitest) — the MCP App host's CSP derivation
(cd frontend && npm install && npm test)
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

### Rebuilding the checkout form (MCP App)

`mcp-services/payment/static/checkout.html` is a **committed build artifact**
from `mcp-apps-ui/checkout/`. After editing anything under
`mcp-apps-ui/checkout/src/`:

```bash
(cd mcp-apps-ui/checkout && npm install && npm run build)
```

The build writes `checkout.html` **and** `checkout.build.json`. Commit both.
The checkout bundle carries card inputs (for Principle III testing) but
**never sends them** — `confirm_mock_payment` is called with no arguments.

The gate itself is on key *presence*, but an out-of-quota key no longer
reads as a bug: a provider 429 that names a quota is routed through
`skip_if_quota_exhausted`, so those tests **skip** with the provider's own
message rather than going red. Anything that is not an explicit quota signal
still re-raises.

## Tech stack

- **Agent harness**: [LangChain DeepAgents](https://docs.langchain.com/labs/deep-agents/overview) (LangGraph)
- **LLM provider**: config, not code. `LLM_PROVIDER=google` uses [Google Gemini](https://ai.google.dev/) via the native `langchain-google-genai` client (default `gemini-3.6-flash`); `LLM_PROVIDER=openai_compatible` uses any OpenAI-compatible API. Development runs on [Groq](https://groq.com/) (`openai/gpt-oss-120b`). **Fallback**: configure `LLM_FALLBACK_PROVIDER` to automatically retry on rate limits (429) or quota errors (403) — e.g., primary Groq, fallback Vertex AI
- **Tool protocol**: [MCP](https://modelcontextprotocol.io/) (Python SDK, Streamable HTTP) — marketplace, booking, and payment servers
- **In-chat transactional UI**: [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) (`@modelcontextprotocol/ext-apps`) — booking form and mock checkout, both rendered in the chat
- **Generative UI**: [A2UI](https://a2ui.org/) v0.9 protocol via the real [`@a2ui/react`](https://www.npmjs.com/package/@a2ui/react) renderer — car catalogue + live agent progress/reasoning
- **Observability**: [Arize Phoenix](https://arize.com/docs/phoenix) via OpenTelemetry
- **Spec process**: [spec-kit](https://github.com/github/spec-kit)

## No real payments

The checkout flow is fully mocked. No real payment gateway, no BMW Group
APIs, no persistence of payment-instrument data anywhere in the system —
see Constitution Principle III.
