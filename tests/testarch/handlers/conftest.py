"""Fixtures for testarch handler tests."""

from pathlib import Path

import pytest


@pytest.fixture
def evidence_fixtures_dir() -> Path:
    """Return the path to evidence test fixtures."""
    return Path(__file__).parent.parent.parent / "fixtures" / "evidence"
