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
recommendations, User Story 2) is in progress** — the marketplace MCP server
is built, the agent runs fully async against it, and interview → automatic
research → deterministically ranked, explained recommendations now works end
to end and **renders live as A2UI surfaces**: an interview checklist, a
reasoning-steps trace of how the search ran, and a catalogue of ranked cards.
Listing selection works too — each catalogue card has a button that records
the choice and advances the phase. The in-chat MCP Apps (booking form, mock
checkout) are the remaining M4 work.

**164 automated tests**, of which **161 run with no external setup at all**
(35 `mcp-services` + 126 `agent-backend`); the remaining 3 need a live LLM key
and/or a running Phoenix and auto-skip without them. Plus live end-to-end
verification against a real Docker Compose build. See
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
 └─ MCP-Apps host (iframes, M4)  LangGraph +                    booking / payment (M4)
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
> per model** — a smoke test, not a live demo. Groq's free tier allows
> ~1000/day and works end-to-end with tool calling, so it is the default
> for development; see `.env.example` for both configurations.
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
| MCP services (health) | http://localhost:8100/health |
| MCP services (protocol) | http://localhost:8100/mcp |
| Phoenix (traces UI) | http://localhost:16006 |

`mcp-services` now runs a real MCP server over Streamable HTTP exposing
`search_listings` and `get_listing_details` over the 203-listing mock
dataset; the booking and payment servers land in M4. The agent discovers
those tools at startup, so `agent-backend`'s `/health` reports
`mcp_connected` alongside `llm_configured` — `status` is `degraded` if
either is missing.

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

Note that the skip is on key *presence*. With a key set but out of
quota/credit, those tests **fail** rather than skip — that is a real
failure, but check the provider account before assuming a code bug.

## Tech stack

- **Agent harness**: [LangChain DeepAgents](https://docs.langchain.com/labs/deep-agents/overview) (LangGraph)
- **LLM provider**: config, not code. `LLM_PROVIDER=google` uses [Google Gemini](https://ai.google.dev/) via the native `langchain-google-genai` client (default `gemini-3.6-flash`); `LLM_PROVIDER=openai_compatible` uses any OpenAI-compatible API. Development runs on [Groq](https://groq.com/) (`openai/gpt-oss-120b`) because its free tier allows ~1000 requests/day against Gemini's ~20, keeping the scarce Gemini quota for demo rehearsal
- **Tool protocol**: [MCP](https://modelcontextprotocol.io/) (Python SDK, Streamable HTTP) — marketplace server live; booking/payment in M4
- **In-chat transactional UI**: [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) — booking form + mock checkout (sandboxed iframes) — M4
- **Generative UI**: [A2UI](https://a2ui.org/) v0.9 protocol via the real [`@a2ui/react`](https://www.npmjs.com/package/@a2ui/react) renderer — car catalogue + live agent progress/reasoning
- **Observability**: [Arize Phoenix](https://arize.com/docs/phoenix) via OpenTelemetry
- **Spec process**: [spec-kit](https://github.com/github/spec-kit)

## No real payments

The checkout flow is fully mocked. No real payment gateway, no BMW Group
APIs, no persistence of payment-instrument data anywhere in the system —
see Constitution Principle III.
