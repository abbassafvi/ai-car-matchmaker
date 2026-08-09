# Setup Guide — AI Car Matchmaker

## Quick Start (Docker)

### Prerequisites
- Docker Desktop installed
- An LLM API key (see below)

### Step 1: Get an API Key

**Option A: Groq (Recommended — Fast, Free Tier)**
1. Go to https://console.groq.com/keys
2. Create a free account
3. Generate an API key (starts with `gsk_`)

**Option B: Google Gemini (Alternative)**
1. Go to https://aistudio.google.com/apikey
2. Create a free account
3. Generate an API key (starts with `AIza`)

### Step 2: Configure Environment

```bash
# Clone the repo
git clone https://github.com/abbassafvi/ai-car-matchmaker.git
cd ai-car-matchmaker

# Copy the example env file
cp agent-backend/.env.example agent-backend/.env

# Edit with your API key
# For Groq (recommended):
cat > agent-backend/.env << 'EOF'
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
LLM_API_KEY=YOUR_GROQ_KEY_HERE
EOF

# OR for Gemini:
cat > agent-backend/.env << 'EOF'
LLM_PROVIDER=google
LLM_MODEL=gemini-3.6-flash
LLM_API_KEY=YOUR_GEMINI_KEY_HERE
EOF
```

### Step 3: Run the Stack

```bash
docker compose up --build
```

Wait for all services to start (about 2-3 minutes first time).

### Step 4: Access the App

Open http://localhost:3000 in your browser.

## What You'll See

1. **Chat Interface**: AI agent interviews you about your car preferences
2. **Marketplace Search**: Agent searches a 203-listing mock database
3. **Ranked Results**: You see 5 top recommendations with explanations
4. **In-Chat Booking**: Click "Book" to fill a form without leaving the chat
5. **Mock Checkout**: Complete a simulated payment (no real money involved)

## Services Running

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend | http://localhost:3000 | Chat UI |
| Agent Backend | http://localhost:8000 | AI agent |
| MCP Services | http://localhost:8100 | Marketplace, booking, payment |
| Phoenix Traces | http://localhost:16006 | Debug/observability |

## Troubleshooting

### "Status: degraded" in health check
- Missing API key — check `agent-backend/.env`
- MCP services not connected — wait a moment and refresh

### Agent not responding
- Check Docker logs: `docker compose logs agent-backend`
- Verify API key is valid
- Check quota limits (Groq free tier: ~200k tokens/day)

### Frontend won't load
- Ensure port 3000 is not in use
- Check `docker compose logs frontend`

## No API Key? (Demo Mode)

The stack runs without an API key, but the agent will respond with:
> "No LLM API key configured. Please set LLM_API_KEY in agent-backend/.env"

You can still see the UI and architecture, just no AI responses.

## Test Suite

```bash
# Run all tests (429 tests)
make test

# Or run individually:
cd agent-backend && python -m pytest tests/ -v
cd mcp-services && python -m pytest tests/ -v
```

9 tests require a live LLM key and will skip without it.

## Architecture Notes

- **No real payments**: Checkout is fully mocked (Constitution Principle III)
- **Grounded recommendations**: Agent searches marketplace, never invents data
- **Session persistence**: Conversations survive page refreshes (SQLite)
- **Auto-reconnect**: WebSocket reconnects automatically if connection drops

## Need Help?

- Health check: http://localhost:8000/health
- Logs: `docker compose logs -f`
- Stop: `docker compose down`
