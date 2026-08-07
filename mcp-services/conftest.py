"""Makes `marketplace`/`data` importable from the test suite.

Same reason as agent-backend/conftest.py: without it the suite only
collects under `python -m pytest`, and `pytest tests/` dies at collection.
Two of the three test modules used to paper over this with their own
`sys.path.insert`, which fixed those files and left `test_generate_listings`
broken -- one mechanism at the service root covers all of them.
"""
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
