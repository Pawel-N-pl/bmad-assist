"""Tests for antipattern extractor debug logging (Fix #9)."""

import logging
from unittest.mock import MagicMock

from bmad_assist.antipatterns.extractor import extract_antipatterns


def _make_config(enabled: bool = True) -> MagicMock:
    """Create a mock config with antipatterns settings."""
    config = MagicMock()
    config.antipatterns.enabled = enabled
    return config


class TestZeroAntipatternDebugLogging:
    """Test debug logging when Issues Verified section found but 0 items."""

    def test_section_found_zero_items_logs_debug(self, caplog) -> None:
        """Section present but no parseable items logs debug message."""
        content = """## Summary
Some summary.

## Issues Verified (by severity)

No issues found in this review.

## Changes Applied
Some changes.
"""
        with caplog.at_level(logging.DEBUG):
            result = extract_antipatterns(content, 10, "10-3", _make_config())
        assert len(result) == 0
        assert "0 items extracted" in caplog.text
        assert "10-3" in caplog.text

    def test_no_section_logs_different_debug(self, caplog) -> None:
        """Content without Issues Verified section logs 'not found'."""
        content = "## Summary\nSome content without issues section."
        with caplog.at_level(logging.DEBUG):
            result = extract_antipatterns(content, 10, "10-4", _make_config())
        assert len(result) == 0
        assert "No 'Issues Verified' section found" in caplog.text

    def test_section_with_items_no_zero_warning(self, caplog) -> None:
        """Section with valid items does NOT log '0 items extracted'."""
        content = """## Issues Verified (by severity)

### Critical
- **Issue**: Missing auth check | **Fix**: Added middleware

## Changes Applied
"""
        with caplog.at_level(logging.DEBUG):
            result = extract_antipatterns(content, 10, "10-5", _make_config())
        assert len(result) > 0
        assert "0 items extracted" not in caplog.text

    def test_debug_log_includes_section_length(self, caplog) -> None:
        """Debug message includes section character count."""
        content = """## Issues Verified (by severity)

Nothing actionable here.

## Next Section
"""
        with caplog.at_level(logging.DEBUG):
            extract_antipatterns(content, 10, "10-6", _make_config())
        assert "section length:" in caplog.text
