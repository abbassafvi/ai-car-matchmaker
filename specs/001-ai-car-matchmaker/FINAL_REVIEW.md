# T048 — Final Review Checklist

Walk through every requirement in spec.md and plan.md, verify it is met,
and check off. This is the last gate before demo.

## Constitution Principles

- [x] **I. Grounded Recommendations**: All listing data comes from the
  marketplace MCP server. The model explains records; it never originates
  prices, years, or mileage. Verified in `test_catalogue_grounding.py`.

- [x] **II. Explicit Phase Gating**: Phase transitions are in `state.py`.
  `TOOLS_BY_PHASE` controls tool availability. `test_phase_gate.py` covers
  all transitions.

- [x] **III. Mock-Only Transactions**: `PAYMENT_FIELDS={}`. No payment
  data survives normalisation. Checkout sends no arguments to
  `confirm_mock_payment`. Verified in `test_payment.py` and
  `test_payment_server.py`.

- [x] **IV. Untrusted Data Boundary**: Listing descriptions wrapped in
  delimiters are never rendered raw. `test_prompt_injection.py` proves
  zero deviation from seeded hostile listings.

- [x] **V. Full Observability**: Every LLM call, tool call, and phase
  transition emits an OTel span. `test_phase_spans.py` covers phase
  transitions; `auto_instrument` covers the rest.

## User Stories

- [x] **US1 (Interview)**: Agent extracts 5 structured slots from natural
  conversation. Progress visible via A2UI interview checklist.
  `test_interview_agent.py` verifies slot extraction.

- [x] **US2 (Research)**: Marketplace search runs automatically after
  interview. Results ranked deterministically. A2UI catalogue renders
  ranked cards. `test_ranking.py`, `test_catalogue_grounding.py`.

- [x] **US3 (Booking)**: MCP App form opens in chat. User fills fields
  server validates, booking submitted. Phase transitions to
  AWAITING_PAYMENT. `test_booking_state.py`, `test_booking_gate.py`,
  `test_booking_server.py`.

- [x] **US4 (Checkout)**: Mock checkout MCP App opens. Card inputs
  collected but never sent. Confirmation is synthetic. Phase transitions
  to CONFIRMED. `test_checkout_state.py`, `test_checkout_gate.py`,
  `test_payment.py`, `test_payment_server.py`.

- [x] **US5 (Session Resume)**: SQLite persistence survives backend
  restart. Auto-reconnect with exponential backoff. Concurrent sessions
  isolated. `test_graph_persistence.py`, `test_session_resume.py`.

## Technical Requirements

- [x] **MCP Protocol**: Three servers (marketplace, booking, payment)
  over Streamable HTTP. `test_mcp_wiring.py`, `test_booking_server.py`,
  `test_payment_server.py`.

- [x] **MCP Apps**: Booking form and checkout bundle are self-contained,
  sandboxed, labelled as mock. CSP deny-by-default. Committed build
  artifacts with source manifests.

- [x] **A2UI**: Interview checklist, reasoning steps, catalogue surfaces
  rendered via `@a2ui/react`.

- [x] **WebSocket**: Bi-directional chat with `app_tool_call`/`app_tool_result`
  for MCP Apps. Auto-reconnect on disconnect.

- [x] **LLM Fallback**: `FallbackModel` retries on 429/403. Configurable
  via `LLM_FALLBACK_PROVIDER`.

- [x] **Degraded Mode**: Backend boots without LLM key. `/health` reports
  status. Chat returns error message.

- [x] **Observability**: Phoenix traces for LLM calls, tool calls, phase
  transitions. Custom spans in `observability/spans.py`.

## Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| agent-backend | 261 | ✅ All pass |
| mcp-services | 146 | ✅ All pass |
| frontend | 11 | ✅ All pass |
| **Total** | **418** | ✅ |

9 tests skip without LLM key or Phoenix (expected).

## Demo Readiness

- [x] Full interview→booking→checkout flow works end-to-end
- [x] A2UI surfaces render live (catalogue, progress, reasoning)
- [x] MCP Apps render in-chat (booking form, checkout)
- [x] Session resume works (reconnect preserves state)
- [x] LLM fallback prevents demo failure on quota exhaustion
- [x] Phoenix shows complete traces

## Known Limitations (Accepted)

- Gemini free tier: ~20 requests/day (use Groq for dev, Vertex for demo)
- Groq TPM: 8000 tokens/min (mitigated by fallback + low max_tokens)
- Playwright E2E: requires running Docker Compose stack
- Eval set: synthetic personas, not real user data

## Sign-off

- [x] All constitution principles verified
- [x] All 5 user stories independently functional
- [x] All automated tests pass
- [x] README updated with current status
- [x] `.env.example` documents fallback configuration
