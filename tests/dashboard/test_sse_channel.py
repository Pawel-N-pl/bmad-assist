"""Tests for SSE channel and event parser.

Tests per-project SSE streaming, backpressure, and event parsing.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from bmad_assist.dashboard.sse_channel.channel import (
    SSEChannel,
    SSEChannelManager,
    SSEEvent,
)
from bmad_assist.dashboard.sse_channel.event_parser import (
    DASHBOARD_EVENT_PREFIX,
    ParsedEvent,
    parse_line,
    parse_lines,
    parse_log_level,
)


class TestSSEEvent:
    """Tests for SSEEvent formatting."""

    def test_format_basic_event(self):
        """Format produces valid SSE string."""
        event = SSEEvent(
            event="test",
            data={"message": "Hello"},
        )

        formatted = event.format()

        assert "event: test" in formatted
        assert 'data: {"message": "Hello"}' in formatted
        assert formatted.endswith("\n\n")

    def test_format_with_id(self):
        """Format includes ID when provided."""
        event = SSEEvent(
            event="test",
            data={"x": 1},
            id="123",
        )

        formatted = event.format()

        assert "id: 123" in formatted

    def test_format_with_retry(self):
        """Format includes retry when provided."""
        event = SSEEvent(
            event="test",
            data={"x": 1},
            retry=3000,
        )

        formatted = event.format()

        assert "retry: 3000" in formatted


class TestSSEChannel:
    """Tests for SSEChannel."""

    @pytest.fixture
    def channel(self):
        """Create test channel."""
        return SSEChannel(
            project_uuid="test-uuid-1234",
            max_queue_size=10,
            heartbeat_interval=60,  # Long heartbeat for testing
        )

    def test_init(self, channel):
        """Channel initializes with correct settings."""
        assert channel.project_uuid == "test-uuid-1234"
        assert channel.max_queue_size == 10
        assert channel.subscriber_count == 0

    async def test_broadcast_increments_counter(self, channel):
        """broadcast() increments message counter."""
        await channel.broadcast("test", {"data": 1})
        await channel.broadcast("test", {"data": 2})

        assert channel._message_counter == 2

    async def test_broadcast_output(self, channel):
        """broadcast_output() sends output event."""
        count = await channel.broadcast_output("Test line", level="info")

        # No subscribers, so count is 0
        assert count == 0

    async def test_broadcast_phase_changed(self, channel):
        """broadcast_phase_changed() sends phase event."""
        count = await channel.broadcast_phase_changed(
            from_phase="dev_story",
            to_phase="code_review",
            story_id="5.2",
        )

        assert count == 0

    async def test_broadcast_loop_status(self, channel):
        """broadcast_loop_status() sends status event."""
        count = await channel.broadcast_loop_status("running")

        assert count == 0

    async def test_broadcast_error(self, channel):
        """broadcast_error() sends error event."""
        count = await channel.broadcast_error("Something failed", code="test_error")

        assert count == 0


class TestSSEChannelManager:
    """Tests for SSEChannelManager."""

    def test_get_or_create_new(self):
        """get_or_create() creates new channel."""
        manager = SSEChannelManager()

        channel = manager.get_or_create("test-uuid")

        assert channel is not None
        assert channel.project_uuid == "test-uuid"

    def test_get_or_create_existing(self):
        """get_or_create() returns existing channel."""
        manager = SSEChannelManager()

        channel1 = manager.get_or_create("test-uuid")
        channel2 = manager.get_or_create("test-uuid")

        assert channel1 is channel2

    def test_get_nonexistent(self):
        """get() returns None for nonexistent channel."""
        manager = SSEChannelManager()

        result = manager.get("unknown-uuid")

        assert result is None

    def test_remove(self):
        """remove() deletes channel."""
        manager = SSEChannelManager()
        manager.get_or_create("test-uuid")

        result = manager.remove("test-uuid")

        assert result is True
        assert manager.get("test-uuid") is None

    def test_remove_nonexistent(self):
        """remove() returns False for nonexistent channel."""
        manager = SSEChannelManager()

        result = manager.remove("unknown-uuid")

        assert result is False

    async def test_shutdown(self):
        """shutdown() clears all channels."""
        manager = SSEChannelManager()
        manager.get_or_create("uuid-1")
        manager.get_or_create("uuid-2")

        await manager.shutdown()

        assert len(manager._channels) == 0


class TestEventParser:
    """Tests for DASHBOARD_EVENT parsing."""

    def test_parse_log_level_info(self):
        """parse_log_level() extracts INFO level."""
        level = parse_log_level("[INFO] Some message")

        assert level == "info"

    def test_parse_log_level_error(self):
        """parse_log_level() extracts ERROR level."""
        level = parse_log_level("[ERROR] Something failed")

        assert level == "error"

    def test_parse_log_level_warning(self):
        """parse_log_level() extracts WARNING level."""
        level = parse_log_level("[WARNING] Be careful")

        assert level == "warn"

    def test_parse_log_level_warn(self):
        """parse_log_level() extracts WARN level."""
        level = parse_log_level("[WARN] Be careful")

        assert level == "warn"

    def test_parse_log_level_debug(self):
        """parse_log_level() extracts DEBUG level."""
        level = parse_log_level("[DEBUG] Details")

        assert level == "debug"

    def test_parse_log_level_default(self):
        """parse_log_level() defaults to info."""
        level = parse_log_level("Plain message without level")

        assert level == "info"


class TestParseLine:
    """Tests for parse_line() function."""

    def test_parse_raw_output_line(self):
        """parse_line() handles raw output."""
        result = parse_line("[INFO] Starting validation...")

        assert result.event_type == "output"
        assert result.data["line"] == "[INFO] Starting validation..."
        assert result.data["level"] == "info"
        assert result.is_structured is False

    def test_parse_dashboard_event_marker(self):
        """parse_line() parses DASHBOARD_EVENT marker."""
        line = f'{DASHBOARD_EVENT_PREFIX}{{"type":"phase_changed","from":"dev","to":"review"}}'

        result = parse_line(line)

        assert result.event_type == "phase_changed"
        assert result.data["from"] == "dev"
        assert result.data["to"] == "review"
        assert result.is_structured is True

    def test_parse_invalid_json_falls_back(self):
        """parse_line() falls back to output for invalid JSON."""
        line = f"{DASHBOARD_EVENT_PREFIX}not-valid-json"

        result = parse_line(line)

        assert result.event_type == "output"
        assert result.is_structured is False

    def test_parse_lines_multiple(self):
        """parse_lines() handles multiple lines."""
        lines = [
            "[INFO] Line 1",
            "[ERROR] Line 2",
        ]

        results = parse_lines(lines)

        assert len(results) == 2
        assert results[0].data["level"] == "info"
        assert results[1].data["level"] == "error"
