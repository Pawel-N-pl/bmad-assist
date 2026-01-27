"""
UI Journey Tests for webhook-relay

NOTE: webhook-relay has NO UI (per PRD "Out of Scope: Web UI dashboard").
This file is a placeholder showing how UI tests would be structured.

For fixtures with UI, copy experiments/testing-framework/templates/test_ui_template.py
and customize for the specific UI.
"""

import pytest

# Skip all tests - fixture has no UI
pytestmark = pytest.mark.skip(reason="webhook-relay has no UI (out of scope per PRD)")


class TestPlaceholder:
    """Placeholder tests - fixture has no UI."""

    def test_no_ui(self):
        """This fixture has no UI to test."""
        assert True, "No UI tests needed for this fixture"
