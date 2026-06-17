"""Tests for extraction with termination_reason (Fix #4)."""

import logging

from bmad_assist.core.extraction import (
    ReportMarkers,
    extract_report,
)

_TEST_MARKERS = ReportMarkers(
    start_marker="<!-- TEST_START -->",
    end_marker="<!-- TEST_END -->",
    fallback_patterns=[r"^## Report"],
    name="test-report",
)


class TestExtractionTerminationReason:
    """Test termination_reason parameter in extract_report."""

    def test_guard_terminated_logs_distinct_warning(self, caplog) -> None:
        """Guard-terminated extraction logs ToolCallGuard-specific warning."""
        raw = "some incomplete output without markers"
        with caplog.at_level(logging.WARNING):
            result = extract_report(
                raw,
                _TEST_MARKERS,
                termination_reason="guard:file_interaction_cap:foo.md(would_be_26/25)",
            )
        assert result == raw.strip()
        assert "ToolCallGuard terminated" in caplog.text
        assert "guard:file_interaction_cap" in caplog.text

    def test_no_termination_reason_logs_generic_warning(self, caplog) -> None:
        """Without termination_reason, logs generic extraction warning."""
        raw = "some output without markers"
        with caplog.at_level(logging.WARNING):
            result = extract_report(raw, _TEST_MARKERS)
        assert result == raw.strip()
        assert "Could not extract structured" in caplog.text
        assert "ToolCallGuard" not in caplog.text

    def test_markers_present_ignores_termination_reason(self, caplog) -> None:
        """When markers found, termination_reason is irrelevant."""
        raw = (
            "preamble\n<!-- TEST_START -->\nReport content\n"
            "<!-- TEST_END -->\npostamble"
        )
        with caplog.at_level(logging.WARNING):
            result = extract_report(
                raw,
                _TEST_MARKERS,
                termination_reason="guard:file_interaction_cap:foo(26/25)",
            )
        assert result == "Report content"
        assert "ToolCallGuard" not in caplog.text
        assert "Could not extract" not in caplog.text

    def test_fallback_pattern_ignores_termination_reason(self, caplog) -> None:
        """When fallback pattern matches, termination_reason is irrelevant."""
        raw = "some text\n## Report\nReport body here"
        with caplog.at_level(logging.WARNING):
            result = extract_report(
                raw,
                _TEST_MARKERS,
                termination_reason="guard:budget_exceeded",
            )
        assert "Report body here" in result
        assert "ToolCallGuard" not in caplog.text

    def test_termination_reason_none_default(self, caplog) -> None:
        """Default termination_reason=None behaves like pre-fix behavior."""
        raw = "raw output"
        with caplog.at_level(logging.WARNING):
            result = extract_report(raw, _TEST_MARKERS, termination_reason=None)
        assert result == raw.strip()
        assert "Could not extract structured" in caplog.text

    def test_non_guard_termination_reason_uses_generic(self, caplog) -> None:
        """Non-guard termination reasons use generic warning."""
        raw = "output without markers"
        with caplog.at_level(logging.WARNING):
            extract_report(
                raw,
                _TEST_MARKERS,
                termination_reason="some_other_reason",
            )
        assert "Could not extract structured" in caplog.text
        assert "ToolCallGuard" not in caplog.text
