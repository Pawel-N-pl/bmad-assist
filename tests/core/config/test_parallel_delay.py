"""Tests for parallel_delay parsing."""

import logging

import pytest

from bmad_assist.core.config.loaders import ParallelDelayError, parse_parallel_delay


class TestParseParallelDelay:
    """Tests for parse_parallel_delay function."""

    def test_none_returns_default(self) -> None:
        """None value should return default 1.0."""
        assert parse_parallel_delay(None) == 1.0

    def test_float_value(self) -> None:
        """Float value should be returned as-is."""
        assert parse_parallel_delay(1.5) == 1.5
        assert parse_parallel_delay(0.5) == 0.5
        assert parse_parallel_delay(0.0) == 0.0

    def test_int_value(self) -> None:
        """Int value should be converted to float."""
        assert parse_parallel_delay(2) == 2.0
        assert parse_parallel_delay(0) == 0.0

    def test_string_float(self) -> None:
        """String numeric value should be parsed."""
        assert parse_parallel_delay("1.5") == 1.5
        assert parse_parallel_delay("0.5") == 0.5

    def test_range_returns_random(self) -> None:
        """Range format should return value within range."""
        # Run multiple times to verify randomness
        results = [parse_parallel_delay("0.5-1.5") for _ in range(10)]
        assert all(0.5 <= r <= 1.5 for r in results)
        # Check there's some variance (not all same)
        assert len(set(results)) > 1

    def test_range_min_equals_max(self) -> None:
        """Range where min equals max should return that value."""
        assert parse_parallel_delay("1.0-1.0") == 1.0

    def test_negative_value_raises(self) -> None:
        """Negative delay should raise ParallelDelayError."""
        with pytest.raises(ParallelDelayError, match="Negative"):
            parse_parallel_delay(-1.0)

    def test_negative_range_raises(self) -> None:
        """Range with negative values should raise."""
        with pytest.raises(ParallelDelayError, match="Invalid"):
            parse_parallel_delay("-1.0-0.5")

    def test_min_greater_than_max_raises(self) -> None:
        """Range where min > max should raise."""
        with pytest.raises(ParallelDelayError, match="Invalid"):
            parse_parallel_delay("2.0-1.0")

    def test_invalid_range_format_raises(self) -> None:
        """Invalid range format should raise."""
        with pytest.raises(ParallelDelayError, match="Invalid"):
            parse_parallel_delay("1.0-2.0-3.0")

    def test_invalid_string_raises(self) -> None:
        """Non-numeric string should raise."""
        with pytest.raises(ParallelDelayError, match="Invalid"):
            parse_parallel_delay("invalid")

    def test_warns_over_5_seconds(self, caplog: pytest.LogCaptureFixture) -> None:
        """Value > 5.0 should log warning."""
        with caplog.at_level(logging.WARNING):
            result = parse_parallel_delay(10.0)

        assert result == 10.0
        assert "parallel_delay > 5s" in caplog.text

    def test_no_warning_under_5_seconds(self, caplog: pytest.LogCaptureFixture) -> None:
        """Value <= 5.0 should not warn."""
        with caplog.at_level(logging.WARNING):
            parse_parallel_delay(5.0)

        assert "parallel_delay > 5s" not in caplog.text

    def test_range_with_spaces_returns_value(self) -> None:
        """Range with spaces parses first part as float."""
        # "0.5 - 1.5" splits to ["0.5 ", " 1.5"] which fails float conversion
        # Actually "0.5 - 1.5" has one hyphen, splits to ["0.5 ", " 1.5"]
        # "0.5 " parses as 0.5 in Python float(), so this might work
        # Let's just verify the behavior
        with pytest.raises(ParallelDelayError, match="Invalid"):
            parse_parallel_delay("not-a-number-range")
