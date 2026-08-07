# AI Car Matchmaker

A multistep AI agent that interviews a user about the car they want to buy
or rent, researches a marketplace on their behalf, and presents ranked,
explained recommendations — with in-chat booking and mock checkout via
[MCP Apps](https://apps.extensions.modelcontextprotocol.io/), and a live
catalogue/progress UI driven by [A2UI](https://a2ui.org/).

Built for the Amulate Summer Hackathon 2026.

## Status

M0 (scaffolding) + M1 (foundational: mock dataset generator, session-state
schemas, checkpointer persistence, Phoenix tracing) complete — 16 automated
tests passing. See [`specs/001-ai-car-matchmaker/`](specs/001-ai-car-matchmaker/)
for the full spec-driven-development trail:

- [`spec.md`](specs/001-ai-car-matchmaker/spec.md) — user stories, requirements, success criteria
- [`plan.md`](specs/001-ai-car-matchmaker/plan.md) — architecture, tech stack, constitution gates
- [`tasks.md`](specs/001-ai-car-matchmaker/tasks.md) — milestone-by-milestone task breakdown
- [`.specify/memory/constitution.md`](.specify/memory/constitution.md) — non-negotiable project principles

## Architecture

```
frontend (React + Vite)          agent-backend (Python)         mcp-services (Python)
 ├─ A2UI renderer (Lit)     ◄──►   LangChain DeepAgents    ◄──►   marketplace / booking / payment
 └─ MCP-Apps host (iframes)       LangGraph + SqliteSaver         MCP servers over Streamable HTTP
                                          │
                                          ▼
                                   Arize Phoenix (OTel traces)
```

## Running locally

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Agent backend (health) | http://localhost:8000 |
| MCP services (health) | http://localhost:8100 |
| Phoenix (traces UI) | http://localhost:16006 |

Currently all *services* are M0 health-check stubs — the M1 foundational
modules (dataset generator, state schemas, checkpointer, tracing) exist and
are tested but aren't wired into the running containers yet; that lands in
M2/M3 alongside the real agent and MCP server logic. This section will be
updated as each milestone ships.

## Running tests locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r agent-backend/requirements.txt -r mcp-services/requirements.txt

(cd mcp-services && python -m pytest tests/ -v)
(cd agent-backend && python -m pytest tests/ -v)   # otel test auto-skips
                                                     # unless Phoenix is up:
                                                     #   docker compose up -d phoenix
```

## Tech stack

- **Agent harness**: [LangChain DeepAgents](https://docs.langchain.com/labs/deep-agents/overview) (LangGraph)
- **Tool protocol**: [MCP](https://modelcontextprotocol.io/) (Python SDK, Streamable HTTP)
- **In-chat transactional UI**: [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) — booking form + mock checkout (sandboxed iframes)
- **Generative UI**: [A2UI](https://a2ui.org/) — car catalogue + live agent progress/reasoning
- **Observability**: [Arize Phoenix](https://arize.com/docs/phoenix) via OpenTelemetry
- **Spec process**: [spec-kit](https://github.com/github/spec-kit)

## No real payments

The checkout flow is fully mocked. No real payment gateway, no BMW Group
APIs, no persistence of payment-instrument data anywhere in the system —
see Constitution Principle III.
