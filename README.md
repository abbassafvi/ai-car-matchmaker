# AI Car Matchmaker

A multistep AI agent that interviews a user about the car they want to buy
or rent, researches a marketplace on their behalf, and presents ranked,
explained recommendations — with in-chat booking and mock checkout via
[MCP Apps](https://apps.extensions.modelcontextprotocol.io/), and a live
catalogue/progress UI driven by [A2UI](https://a2ui.org/).

Built for the Amulate Summer Hackathon 2026.

## Status

M0 (scaffolding) + M1 (foundational) + M2 (conversational interview, User
Story 1) + M2.5 (audit remediation) complete — **47 automated tests**
(39 `agent-backend` + 8 `mcp-services`, excluding credential- and
Phoenix-gated ones), plus live end-to-end verification in a real browser
against a real Docker Compose build. See
[`specs/001-ai-car-matchmaker/`](specs/001-ai-car-matchmaker/) for the full
spec-driven-development trail:

- [`spec.md`](specs/001-ai-car-matchmaker/spec.md) — user stories, requirements, success criteria
- [`plan.md`](specs/001-ai-car-matchmaker/plan.md) — architecture, tech stack, constitution gates
- [`tasks.md`](specs/001-ai-car-matchmaker/tasks.md) — milestone-by-milestone task breakdown, including bugs found during live verification
- [`.specify/memory/constitution.md`](.specify/memory/constitution.md) — non-negotiable project principles

## Architecture

```
frontend (React + Vite)          agent-backend (Python)         mcp-services (Python)
 ├─ A2UI renderer (@a2ui/react)  LangChain DeepAgents    ◄──►   marketplace / booking / payment
 └─ MCP-Apps host (iframes, M4)  LangGraph + SqliteSaver        MCP servers over Streamable HTTP
        │                               │                              (M3+)
        │ WebSocket                     ▼
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
> per model**. That covers a smoke test, not a live demo. Use a billed key
> for anything real, or switch `LLM_MODEL` to spread load.

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Agent backend (health) | http://localhost:8000/health |
| Agent backend (chat) | ws://localhost:8000/ws/{session_id} |
| MCP services (health, M0 stub) | http://localhost:8100 |
| Phoenix (traces UI) | http://localhost:16006 |

`mcp-services` is still an M0 health-check stub — real marketplace/booking/
payment MCP servers land in M3/M4. Everything else is real: the frontend is
a production Vite build served by nginx, `agent-backend` runs the actual
FastAPI + DeepAgents interview agent.

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
- **LLM provider**: [Google Gemini](https://ai.google.dev/) via the native `langchain-google-genai` client (default `gemini-3.6-flash`). `LLM_PROVIDER=openai_compatible` swaps to any OpenAI-compatible API (OpenRouter, NVIDIA NIM) — provider and model are config, not code
- **Tool protocol**: [MCP](https://modelcontextprotocol.io/) (Python SDK, Streamable HTTP) — M3+
- **In-chat transactional UI**: [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) — booking form + mock checkout (sandboxed iframes) — M4
- **Generative UI**: [A2UI](https://a2ui.org/) v0.9 protocol via the real [`@a2ui/react`](https://www.npmjs.com/package/@a2ui/react) renderer — car catalogue + live agent progress/reasoning
- **Observability**: [Arize Phoenix](https://arize.com/docs/phoenix) via OpenTelemetry
- **Spec process**: [spec-kit](https://github.com/github/spec-kit)

## No real payments

The checkout flow is fully mocked. No real payment gateway, no BMW Group
APIs, no persistence of payment-instrument data anywhere in the system —
see Constitution Principle III.
