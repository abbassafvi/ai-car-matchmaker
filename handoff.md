# Handoff — AI Car Matchmaker

**Last updated:** 2026-08-09
**Branch:** `dev` (all work happens here, never touch `main`)
**Repo:** `https://github.com/abbassafvi/ai-car-matchmaker.git`

---

## Quick Start (natively, not Docker)

```bash
# Terminal 1 — MCP services (port 8100)
cd mcp-services && source ../.venv/bin/activate && python -m uvicorn mcp.run:app --host 0.0.0.0 --port 8100

# Terminal 2 — Agent backend (port 8000)
cd agent-backend && source ../.venv/bin/activate && python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 3 — Frontend (port 3000)
cd frontend && npm run dev

# Phoenix traces: http://localhost:16006
```

## LLM Configuration (`.env`)

| Var | Value | Notes |
|-----|-------|-------|
| `LLM_PROVIDER` | `openai_compatible` | Groq via OpenAI-compat |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Primary |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | |
| `LLM_FALLBACK_PROVIDER` | `openai_compatible` | Different Groq model |
| `LLM_FALLBACK_MODEL` | `llama-3.3-70b-versatile` | Separate per-model TPD |
| `LLM_FALLBACK_BASE_URL` | `https://api.groq.com/openai/v1` | Same Groq endpoint |
| `LLM_FALLBACK_API_KEY` | (same as primary) | Same Groq key |

The `FallbackModel` class (`agent/llm.py`) wraps primary + fallback and retries on 429/403. Both models are `openai_compatible` so `bind_tools` works identically. Different Groq models have separate per-model quotas (200k TPD each).

**To switch to Gemini-only for demo:**
```env
LLM_PROVIDER=google
LLM_MODEL=gemini-3.6-flash
LLM_API_KEY=<see agent-backend/.env>
```

---

## Architecture

```
frontend (React 19 + Vite, port 3000)
    ↓ WebSocket
agent-backend (Python/FastAPI/LangGraph/DeepAgents, port 8000)
    ↓ MCP protocol
mcp-services (3 MCP servers via Starlette, port 8100)
    ├── marketplace (search_listings, get_listing_details)
    ├── booking (open_booking_form, submit_booking)
    └── payment (open_mock_checkout, confirm_mock_payment)
phoenix (OTel traces, port 16006)
```

---

## Phase State Machine

```
INTERVIEWING → RESEARCHING → RESULTS_READY → FORM_FILLING → AWAITING_PAYMENT → CONFIRMED
```

Each phase has a dedicated agent with only that phase's tools (Constitution Principle II). Transitions happen in `SessionState` (`agent/state.py`), never by LLM announcement.

---

## Key Files

| File | Purpose |
|------|---------|
| `agent-backend/api/main.py` | WebSocket handler, all turn logic, MCP App bridge |
| `agent-backend/agent/state.py` | `SessionState`, `Phase` enum, all transitions |
| `agent-backend/agent/graph.py` | `PhaseAgentRegistry`, `build_agent_for_phase` |
| `agent-backend/agent/llm.py` | `FallbackModel`, `build_model` |
| `agent-backend/agent/research.py` | `run_research`, `narration_brief` |
| `agent-backend/agent/render_a2ui.py` | A2UI surface builders, `SELECT_LISTING_ACTION` |
| `agent-backend/agent/tools.py` | `save_interview_state`, `select_listing`, `refine_search` |
| `agent-backend/agent/mcp_client.py` | MCP URL defaults, tool discovery |
| `frontend/src/App.tsx` | Main React app — chat, drawer, McpAppFrame |
| `frontend/src/app.css` | All styles — chat, drawer, typing indicator, chips |
| `frontend/src/mcp-app-host/McpAppFrame.tsx` | MCP App host with cancel button |
| `mcp-apps-ui/booking-form/` | Booking form MCP App |
| `mcp-apps-ui/checkout/` | Checkout MCP App |
| `mcp-services/*/server.py` | Individual MCP server implementations |

---

## What Was Done (commit history on `dev`)

### Bug Fixes
- **`5e8c3cb`** — `McpAppFrame` key forces React remount on re-selection
- **`e7e822f`** — Checkout MCP App opens after `submit_booking` (was missing `maybe_open` call)
- **`ce75b59`** — Added `PaymentConfirmation` to imports (was crashing with `NameError`)
- **`540c893`** — Skip duplicate `_run_research_turn` when `refine_search` already ran (saves ~5-8s per preference change)
- **`8677f89`** — Chat text before cards (catalogue timing fix)

### UI/UX
- **`8677f89`** — Slide-out drawer (replaces permanent sidebar), hide interview checkboxes, chat-before-cards timing
- **`6a4377d`** — Cancel button on booking form and checkout card (resets to RESULTS_READY)
- **`8aa69cb`** — Auto-open drawer on refined search after cancel
- **`9588dde`** — Typing indicator (bouncing dots), drawer badge, escape key, quick-start chips, smooth scroll, send arrow icon

### Features
- **`ce75b59`** — Full M4b: dual-tool handler (`submit_booking` + `confirm_mock_payment`), `_CheckoutStream`, checkout wired in `chat_ws`
- **`ce75b59`** — M4c: Frontend auto-reconnect with exponential backoff
- **`ce75b59`** — LLM Fallback: `FallbackModel` class, retries on 429/403
- **`ce75b59`** — Playwright E2E tests
- **`ce75b59`** — Eval set (15 synthetic personas, SC-001/SC-002 scoring)
- **`9588dde`** — Groq→Gemini fallback configured in `.env`

---

## Test Counts

| Suite | Count | Notes |
|-------|-------|-------|
| agent-backend | 269 | 8 skip without LLM key/Phoenix |
| mcp-services | 146 | |
| **Total** | **415** | |

Run all: `source .venv/bin/activate && make test`

The two suites must be separate invocations — both roots have a top-level
`conftest.py`, so pointing one pytest run at both fails at collection.
See `pytest.ini` for the detail.

---

## Known Issues / TODO

1. **Groq quota** — 200k TPD per model. Fallback to Gemini configured but unverified. Wait ~17min for quota reset, or switch to Gemini-only for demo.
2. **Gemini fallback deprecated** — Gemini's `bind_tools` doesn't work with LangGraph (`NotImplementedError`). Fallback now uses `llama-3.3-70b-versatile` (different Groq model, separate quota).
3. **No `onSurfaceUpdated`** in A2UI processor — Drawer auto-open tracks fingerprint (surface IDs + component counts) as a workaround.
4. **T027 (multi-session load test)** — Deferred, optional.
5. **T050 (owner-owned)** — Deferred.

---

## Constitution (5 Principles)

1. **Grounded Recommendations (I)** — Every listing comes from a tool call, never invented.
2. **Explicit Phase Gating (II)** — State machine drives flow; LLM cannot skip phases.
3. **Mock-Only Transactions (III)** — All payments are mock; no real money movement.
4. **Untrusted Data Boundary (IV)** — Listing descriptions are never trusted as instructions.
5. **Full Observability (V)** — Every phase transition emits an OTel span.
