"""Tests for time formatting utilities."""

import time

from bmad_assist.core.project_tree.time_format import format_relative_time


class TestFormatRelativeTime:
    """Test cases for format_relative_time function."""

    def test_seconds_range(self) -> None:
        """Test formatting for <60 seconds."""
        now = time.time()

        assert format_relative_time(now - 45, now) == "(45s ago)"
        assert format_relative_time(now - 1, now) == "(1s ago)"
        assert format_relative_time(now - 59, now) == "(59s ago)"

    def test_minutes_range(self) -> None:
        """Test formatting for <60 minutes."""
        now = time.time()

        assert format_relative_time(now - 60, now) == "(1m ago)"
        assert format_relative_time(now - 90, now) == "(1m 30s ago)"
        assert format_relative_time(now - 300, now) == "(5m ago)"
        assert format_relative_time(now - 330, now) == "(5m 30s ago)"
        assert format_relative_time(now - 3599, now) == "(59m 59s ago)"

    def test_hours_range(self) -> None:
        """Test formatting for <24 hours."""
        now = time.time()

        assert format_relative_time(now - 3600, now) == "(1h ago)"
        assert format_relative_time(now - 7200, now) == "(2h ago)"
        assert format_relative_time(now - 8100, now) == "(2h 15m ago)"
        assert format_relative_time(now - 86399, now) == "(23h 59m ago)"

    def test_days_range(self) -> None:
        """Test formatting for <30 days."""
        now = time.time()

        assert format_relative_time(now - 86400, now) == "(1d ago)"
        assert format_relative_time(now - 172800, now) == "(2d ago)"
        assert format_relative_time(now - 2592000, now) == "(30d ago)"

    def test_years_range(self) -> None:
        """Test formatting for >=365 days."""
        now = time.time()

        assert format_relative_time(now - 31536000, now) == "(1y ago)"
        assert format_relative_time(now - 63072000, now) == "(2y ago)"
        assert format_relative_time(now - 315360000, now) == "(10y ago)"

    def test_future_timestamp(self) -> None:
        """Test handling of future timestamp."""
        now = time.time()

        assert format_relative_time(now + 100, now) == "(just now)"
        assert format_relative_time(now + 1, now) == "(just now)"

    def test_epoch_zero(self) -> None:
        """Test handling of timestamp = 0 (epoch)."""
        assert format_relative_time(0) == "(unknown)"

    def test_very_old_file(self, tmp_path) -> None:
        """Test handling of very old file (>10 years)."""
        now = time.time()
        ten_years_ago = now - (10 * 365 * 24 * 3600)

        result = format_relative_time(ten_years_ago, now)
        assert result.startswith("(")
        assert result.endswith("y ago)")

    def test_no_now_provided(self) -> None:
        """Test that function works without explicit 'now' parameter."""
        # Just verify it doesn't crash
        result = format_relative_time(time.time() - 60)
        assert "ago)" in result
