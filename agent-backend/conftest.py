"""Makes `agent`/`api`/`observability` importable from the test suite.

Without this, the suite only collects under `python -m pytest` (which puts
the cwd on `sys.path` as a side effect) and every `from agent.graph import
...` fails under a bare `pytest tests/` with a collection error. That is a
trap for CI and for anyone whose editor runs `pytest` directly, and it made
the documented and the undocumented invocation behave differently.

Placed at the service root rather than inside `tests/` on purpose: pytest
imports the nearest ancestor conftest and prepends *its* directory, which is
the directory the packages actually live in.
"""
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))


# 🔴 The LLM credential gate has to be snapshotted HERE, and nowhere else.
#
# `api/main.py` calls `load_dotenv()` as an import side effect, so the first
# test module that imports it writes `agent-backend/.env` into `os.environ`
# for the rest of the session. Any `skipif` evaluated after that point sees a
# key the shell never had, so the test *runs* -- reaching for the network and
# then failing, on a machine the developer believed had no credentials.
#
# The effect is collection-order dependent, which is why it hid so long:
# under `env -u LLM_API_KEY`, `test_chat_endpoint` and `test_interview_agent`
# collect early and skip correctly, while anything collected after the first
# module-level `api.main` import does not. Two gated tests in one suite, same
# environment, opposite behaviour. Found in Phase F while adding T021/T029.
#
# pytest imports the root conftest before any test module, so reading the
# environment here is the only point guaranteed to see it unpolluted.
# Policy: the *shell* decides. A `.env` file is dev convenience for running
# the app -- which is all api/main.py claims it is for -- not a way to
# silently opt every live test into billing a real account.
#
# Related but distinct: HANDOFF §8.30 warns against *tests* setting env vars
# at module level, for exactly this reason. Here the culprit is production
# code, which no amount of test discipline would have caught.
LLM_CREDENTIALS_PRESENT = bool(os.environ.get("LLM_API_KEY"))

# `test_otel_setup.py` is deliberately left alone: its gate probes a socket
# rather than an env var, so nothing can pollute it.
