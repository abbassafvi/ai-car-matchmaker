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
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
