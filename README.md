# AI Car Matchmaker

A multistep AI agent that interviews a user about the car they want to buy
or rent, researches a marketplace on their behalf, and presents ranked,
explained recommendations — with in-chat booking and mock checkout via
[MCP Apps](https://apps.extensions.modelcontextprotocol.io/), and a live
catalogue/progress UI driven by [A2UI](https://a2ui.org/).

Built for the Amulate Summer Hackathon 2026.

## Status

Early scaffolding (M0). See [`specs/001-ai-car-matchmaker/`](specs/001-ai-car-matchmaker/)
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
| Phoenix (traces UI) | http://localhost:6006 |

Currently all services are M0 health-check stubs — real functionality
lands milestone by milestone per `tasks.md`. This section will be updated
as each milestone ships.

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
