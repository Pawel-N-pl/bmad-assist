"""
Common test infrastructure for fixture behavioral testing.

This package provides:
- App discovery and startup strategies (strategies.py)
- Pytest fixtures for running fixture apps (conftest.py)
- Reusable assertion helpers (assertions.py)
- Automated quality scoring (scorecard.py)
"""

# Use relative imports to avoid package installation requirement
from .assertions import (
    assert_json_response,
    assert_response_ok,
    assert_status_code,
)
from .strategies import (
    AppStrategy,
    GoStrategy,
    NodeStrategy,
    PythonStrategy,
    discover_strategy,
)

__all__ = [
    # Strategies
    "AppStrategy",
    "discover_strategy",
    "GoStrategy",
    "NodeStrategy",
    "PythonStrategy",
    # Assertions
    "assert_response_ok",
    "assert_status_code",
    "assert_json_response",
]
