.PHONY: test test-backend test-mcp test-e2e

# Two invocations, not one: agent-backend and mcp-services each own a
# top-level conftest.py and cannot share a pytest run (see pytest.ini).
test: test-backend test-mcp

test-backend:
	cd agent-backend && python -m pytest tests/ -q

test-mcp:
	cd mcp-services && python -m pytest tests/ -q

test-e2e:
	npx playwright test
