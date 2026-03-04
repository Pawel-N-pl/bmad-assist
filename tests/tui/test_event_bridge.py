"""Tests for EventBridge — IPC event to TUI Renderer Protocol mapping."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmad_assist.ipc.client import SocketClient
from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.event_bridge import EventBridge
from bmad_assist.tui.interactive import InteractiveRenderer
from bmad_assist.tui.status_bar import StatusBar
from tests.tui.conftest import (
    FakeEventSource,
    make_error_event,
    make_goodbye_event,
    make_log_event,
    make_metrics_event,
    make_phase_completed_event,
    make_phase_started_event,
    make_state_changed_event,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_renderer() -> MagicMock:
    """Create a mock InteractiveRenderer."""
    return MagicMock(spec=InteractiveRenderer)


@pytest.fixture
def mock_status_bar() -> MagicMock:
    """Create a mock StatusBar."""
    return MagicMock(spec=StatusBar)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock SocketClient."""
    mock = MagicMock(spec=SocketClient)
    mock.disconnect = AsyncMock()
    mock.get_state = AsyncMock()
    return mock


@pytest.fixture
def clock() -> MagicMock:
    """Create a mock clock starting at 100.0."""
    c = MagicMock()
    c.return_value = 100.0
    return c


@pytest.fixture
def bridge(
    mock_renderer: MagicMock,
    mock_status_bar: MagicMock,
    mock_client: MagicMock,
    clock: MagicMock,
) -> EventBridge:
    """Create an EventBridge with mocked dependencies."""
    return EventBridge(mock_renderer, mock_status_bar, mock_client, clock=clock)


@pytest.fixture
def bridge_no_status_bar(
    mock_renderer: MagicMock,
    mock_client: MagicMock,
    clock: MagicMock,
) -> EventBridge:
    """Create an EventBridge with no status bar (None)."""
    return EventBridge(mock_renderer, None, mock_client, clock=clock)


# ---------------------------------------------------------------------------
# Log event dispatch
# ---------------------------------------------------------------------------


class TestLogEventDispatch:
    """Test log event handling and throttling."""

    def test_log_event_renders_via_renderer(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log event is rendered via renderer.render_log()."""
        ts = "2026-02-20T10:30:00+00:00"
        event = make_log_event(seq=1, level="WARNING", message="disk full", timestamp=ts)

        # Clock advanced past flush interval so log flushes immediately
        clock.return_value = 200.0
        bridge.on_event(event)

        mock_renderer.render_log.assert_called_once()
        call_args = mock_renderer.render_log.call_args
        assert call_args[0][0] == "WARNING"
        assert call_args[0][1] == "disk full"
        assert call_args[0][2] == "test.logger"

    def test_log_event_parses_timestamp_from_envelope(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log event extracts timestamp from params envelope, not data."""
        ts = "2026-02-20T10:30:00+00:00"
        event = make_log_event(seq=1, timestamp=ts)

        clock.return_value = 200.0
        bridge.on_event(event)

        call_args = mock_renderer.render_log.call_args
        parsed_ts = call_args[0][3]
        assert isinstance(parsed_ts, datetime)
        assert parsed_ts.hour == 10
        assert parsed_ts.minute == 30

    def test_log_event_missing_timestamp_fallback(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log event with missing timestamp falls back to now()."""
        event = make_log_event(seq=1)
        del event["timestamp"]

        clock.return_value = 200.0
        bridge.on_event(event)

        call_args = mock_renderer.render_log.call_args
        parsed_ts = call_args[0][3]
        assert isinstance(parsed_ts, datetime)

    def test_log_event_invalid_timestamp_fallback(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log event with invalid timestamp falls back to now()."""
        event = make_log_event(seq=1, timestamp="not-a-date")

        clock.return_value = 200.0
        bridge.on_event(event)

        call_args = mock_renderer.render_log.call_args
        parsed_ts = call_args[0][3]
        assert isinstance(parsed_ts, datetime)


# ---------------------------------------------------------------------------
# Phase events
# ---------------------------------------------------------------------------


class TestPhaseEvents:
    """Test phase_started and phase_completed event handling."""

    def test_phase_started_dispatches_to_renderer(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """phase_started calls renderer.render_phase_started()."""
        event = make_phase_started_event(seq=1, phase="dev_story", epic_id=15, story_id="15.3")
        bridge.on_event(event)

        mock_renderer.render_phase_started.assert_called_once_with("dev_story", 15, "15.3")

    def test_phase_started_updates_status_bar(
        self, bridge: EventBridge, mock_status_bar: MagicMock
    ) -> None:
        """phase_started calls status_bar.set_phase_info()."""
        event = make_phase_started_event(seq=1, phase="create_story", epic_id=10, story_id="10.1")
        bridge.on_event(event)

        mock_status_bar.set_phase_info.assert_called_once_with("create_story", 10, "10.1")

    def test_phase_started_with_none_epic_id(
        self, bridge: EventBridge, mock_status_bar: MagicMock
    ) -> None:
        """phase_started with None epic_id passes empty string to status_bar."""
        event = make_phase_started_event(seq=1, epic_id=None, story_id="1.1")
        bridge.on_event(event)

        args = mock_status_bar.set_phase_info.call_args[0]
        assert args[1] == ""  # epic_id coerced to ""

    def test_phase_completed_maps_duration_seconds(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """phase_completed maps data['duration_seconds'] to renderer's duration param."""
        event = make_phase_completed_event(
            seq=2, phase="dev_story", epic_id=15, story_id="15.3", duration_seconds=123.4
        )
        bridge.on_event(event)

        mock_renderer.render_phase_completed.assert_called_once_with("dev_story", 15, "15.3", 123.4)

    def test_phase_started_updates_context_tracking(
        self, bridge: EventBridge
    ) -> None:
        """phase_started updates internal epic_id and story_id context."""
        event = make_phase_started_event(seq=1, epic_id=7, story_id="7.2")
        bridge.on_event(event)

        assert bridge._last_epic_id == 7
        assert bridge._last_story_id == "7.2"

    def test_phase_started_no_status_bar(
        self, bridge_no_status_bar: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """phase_started with no status_bar does not crash."""
        event = make_phase_started_event(seq=1)
        bridge_no_status_bar.on_event(event)

        mock_renderer.render_phase_started.assert_called_once()


# ---------------------------------------------------------------------------
# State changed events (polymorphic dispatch)
# ---------------------------------------------------------------------------


class TestStateChangedEvents:
    """Test polymorphic state_changed event dispatch on data['field']."""

    def test_state_field_calls_update_status(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """state_changed with field='state' calls renderer.update_status()."""
        event = make_state_changed_event(
            seq=1, field="state", old_value="idle", new_value="running"
        )
        bridge.on_event(event)

        mock_renderer.update_status.assert_called_once_with(RunnerState.RUNNING)

    def test_state_field_paused(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """state_changed with new_value='paused' converts to RunnerState.PAUSED."""
        event = make_state_changed_event(
            seq=1, field="state", old_value="running", new_value="paused"
        )
        bridge.on_event(event)

        mock_renderer.update_status.assert_called_once_with(RunnerState.PAUSED)

    def test_state_field_invalid_value(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """state_changed with invalid state value does not crash."""
        event = make_state_changed_event(
            seq=1, field="state", old_value="idle", new_value="INVALID_STATE"
        )
        bridge.on_event(event)

        mock_renderer.update_status.assert_not_called()

    def test_current_phase_field_routes_to_status_bar(
        self, bridge: EventBridge, mock_renderer: MagicMock, mock_status_bar: MagicMock
    ) -> None:
        """state_changed with field='current_phase' routes to StatusBar, NOT update_status()."""
        event = make_state_changed_event(
            seq=1, field="current_phase", old_value="create_story", new_value="dev_story"
        )
        bridge.on_event(event)

        mock_renderer.update_status.assert_not_called()
        mock_status_bar.set_phase_info.assert_called_once()
        args = mock_status_bar.set_phase_info.call_args[0]
        assert args[0] == "dev_story"

    def test_current_story_field_updates_context(
        self, bridge: EventBridge, mock_status_bar: MagicMock
    ) -> None:
        """state_changed with field='current_story' updates context and status bar."""
        event = make_state_changed_event(
            seq=1, field="current_story", old_value="15.1", new_value="15.2"
        )
        bridge.on_event(event)

        assert bridge._last_story_id == "15.2"
        mock_status_bar.set_phase_info.assert_called_once()

    def test_unknown_field_ignored(
        self, bridge: EventBridge, mock_renderer: MagicMock, mock_status_bar: MagicMock
    ) -> None:
        """state_changed with unknown field is silently ignored."""
        event = make_state_changed_event(
            seq=1, field="unknown_field", old_value="a", new_value="b"
        )
        bridge.on_event(event)

        mock_renderer.update_status.assert_not_called()
        mock_status_bar.set_phase_info.assert_not_called()

    def test_current_phase_uses_cached_context(
        self, bridge: EventBridge, mock_status_bar: MagicMock
    ) -> None:
        """current_phase state_changed uses cached epic_id and story_id."""
        # First set context via phase_started
        bridge.on_event(make_phase_started_event(seq=1, epic_id=30, story_id="30.4"))
        mock_status_bar.reset_mock()

        # Now change phase
        event = make_state_changed_event(
            seq=2, field="current_phase", old_value="create_story", new_value="dev_story"
        )
        bridge.on_event(event)

        args = mock_status_bar.set_phase_info.call_args[0]
        assert args[0] == "dev_story"
        assert args[1] == 30  # cached epic_id
        assert args[2] == "30.4"  # cached story_id


# ---------------------------------------------------------------------------
# Metrics events
# ---------------------------------------------------------------------------


class TestMetricsEvents:
    """Test metrics event handling."""

    def test_metrics_updates_llm_sessions(
        self, bridge: EventBridge, mock_status_bar: MagicMock
    ) -> None:
        """Metrics event updates status_bar.set_llm_sessions()."""
        event = make_metrics_event(seq=1, llm_sessions=7)
        bridge.on_event(event)

        mock_status_bar.set_llm_sessions.assert_called_once_with(7)

    def test_metrics_no_status_bar(
        self, bridge_no_status_bar: EventBridge
    ) -> None:
        """Metrics event with no status_bar does not crash."""
        event = make_metrics_event(seq=1)
        bridge_no_status_bar.on_event(event)  # Should not raise


# ---------------------------------------------------------------------------
# Goodbye events
# ---------------------------------------------------------------------------


class TestGoodbyeEvents:
    """Test goodbye-aware reconnection logic (AC-E2)."""

    def test_goodbye_normal_disconnects(
        self, bridge: EventBridge, mock_client: MagicMock
    ) -> None:
        """Goodbye with reason='normal' schedules client.disconnect()."""
        event = make_goodbye_event(seq=1, reason="normal")

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value = MagicMock()
            bridge.on_event(event)

            mock_loop.return_value.create_task.assert_called_once()

    def test_goodbye_stop_command_no_disconnect(
        self, bridge: EventBridge, mock_client: MagicMock
    ) -> None:
        """Goodbye with reason='stop_command' does NOT disconnect."""
        event = make_goodbye_event(seq=1, reason="stop_command")
        bridge.on_event(event)

        mock_client.disconnect.assert_not_called()

    def test_goodbye_error_no_disconnect(
        self, bridge: EventBridge, mock_client: MagicMock
    ) -> None:
        """Goodbye with reason='error' does NOT disconnect."""
        event = make_goodbye_event(seq=1, reason="error", message="Fatal crash")
        bridge.on_event(event)

        mock_client.disconnect.assert_not_called()

    def test_goodbye_normal_no_event_loop(
        self, bridge: EventBridge
    ) -> None:
        """Goodbye with reason='normal' gracefully handles missing event loop."""
        event = make_goodbye_event(seq=1, reason="normal")
        # No event loop running — should not crash
        bridge.on_event(event)


# ---------------------------------------------------------------------------
# Error events
# ---------------------------------------------------------------------------


class TestErrorEvents:
    """Test error event handling."""

    def test_error_renders_as_log(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """Error event renders as ERROR log via renderer."""
        event = make_error_event(seq=1, code=-32000, message="Provider timeout")
        bridge.on_event(event)

        mock_renderer.render_log.assert_called_once()
        args = mock_renderer.render_log.call_args[0]
        assert args[0] == "ERROR"
        assert "[IPC ERROR -32000]" in args[1]
        assert "Provider timeout" in args[1]


# ---------------------------------------------------------------------------
# 30 FPS throttle (AC-E5)
# ---------------------------------------------------------------------------


class TestLogThrottle:
    """Test 30 FPS render throttling for log events."""

    def test_logs_within_flush_interval_queued(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log events within flush interval are queued, not rendered immediately."""
        # Set clock to same time for all calls (within interval)
        clock.return_value = 100.0
        # First event triggers initial flush (since last_flush_time=0.0)
        bridge.on_event(make_log_event(seq=1, message="first"))

        # Now clock is set to 100.0, last_flush_time is 100.0
        # Next event within interval should be queued
        clock.return_value = 100.01  # only 10ms later
        bridge.on_event(make_log_event(seq=2, message="second"))

        # "first" was rendered (initial flush), "second" is queued
        assert mock_renderer.render_log.call_count == 1

    def test_logs_after_flush_interval_flushed(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Log events after flush interval trigger flush."""
        clock.return_value = 100.0
        bridge.on_event(make_log_event(seq=1, message="first"))

        # Advance past flush interval (~33ms)
        clock.return_value = 100.05
        bridge.on_event(make_log_event(seq=2, message="second"))

        assert mock_renderer.render_log.call_count == 2

    def test_essential_events_flush_queued_logs(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Essential events (phase_started) flush queued log events first."""
        clock.return_value = 100.0
        bridge.on_event(make_log_event(seq=1, message="first"))

        # Queue a second log within interval
        clock.return_value = 100.01
        bridge.on_event(make_log_event(seq=2, message="queued"))

        # Now send essential event — should flush queued logs
        bridge.on_event(make_phase_started_event(seq=3))

        # "first" rendered immediately, "queued" flushed by phase_started
        assert mock_renderer.render_log.call_count == 2

    def test_coalesce_over_50_events(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """When >50 events queued, coalesce to summary + latest 5."""
        clock.return_value = 100.0
        # First event triggers flush (initial)
        bridge.on_event(make_log_event(seq=1, message="initial"))
        mock_renderer.reset_mock()

        # Queue 55 events within interval
        clock.return_value = 100.01
        for i in range(55):
            bridge.on_event(make_log_event(seq=i + 2, message=f"msg-{i}"))

        # Force flush
        bridge.flush()

        # Should have: 1 summary + 5 latest = 6 render_log calls
        assert mock_renderer.render_log.call_count == 6
        # First call should be the coalesce summary
        first_call = mock_renderer.render_log.call_args_list[0]
        assert "more log lines" in first_call[0][1]

    def test_force_flush(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """flush() forces all queued events to be rendered."""
        clock.return_value = 100.0
        bridge.on_event(make_log_event(seq=1, message="first"))
        mock_renderer.reset_mock()

        clock.return_value = 100.01
        bridge.on_event(make_log_event(seq=2, message="queued"))

        bridge.flush()
        assert mock_renderer.render_log.call_count == 1
        assert mock_renderer.render_log.call_args[0][1] == "queued"


# ---------------------------------------------------------------------------
# Seq gap detection (AC-E4)
# ---------------------------------------------------------------------------


class TestSeqGapDetection:
    """Test event sequence gap detection and rehydration debounce."""

    def test_contiguous_seq_no_warning(
        self, bridge: EventBridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Contiguous seq numbers do not trigger gap warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            bridge.on_event(make_log_event(seq=1))
            bridge.on_event(make_log_event(seq=2))
            bridge.on_event(make_log_event(seq=3))

        assert not any("sequence gap" in r.message for r in caplog.records)

    def test_seq_gap_triggers_warning(
        self, bridge: EventBridge, caplog: pytest.LogCaptureFixture, clock: MagicMock
    ) -> None:
        """Seq gap triggers warning log."""
        import logging

        clock.return_value = 200.0
        with caplog.at_level(logging.WARNING):
            bridge.on_event(make_log_event(seq=1))
            bridge.on_event(make_log_event(seq=5))  # Gap: expected 2, got 5

        assert any("sequence gap" in r.message for r in caplog.records)

    def test_seq_gap_debounce(
        self, bridge: EventBridge, clock: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Multiple gaps within 5s debounce window only trigger one rehydration."""
        import logging

        clock.return_value = 200.0
        with caplog.at_level(logging.DEBUG):
            bridge.on_event(make_log_event(seq=1))
            bridge.on_event(make_log_event(seq=5))  # Gap 1
            bridge.on_event(make_log_event(seq=10))  # Gap 2 (within debounce)

        rehydration_logs = [r for r in caplog.records if "rehydration" in r.message.lower()]
        # One trigger + one debounce
        trigger_logs = [r for r in rehydration_logs if "Triggering" in r.message]
        debounce_logs = [r for r in rehydration_logs if "debounced" in r.message]
        assert len(trigger_logs) == 1
        assert len(debounce_logs) == 1

    def test_seq_gap_after_debounce_expires(
        self, bridge: EventBridge, clock: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Gap after debounce window triggers new rehydration."""
        import logging

        clock.return_value = 200.0
        with caplog.at_level(logging.INFO):
            bridge.on_event(make_log_event(seq=1))
            bridge.on_event(make_log_event(seq=5))  # Gap 1 -> triggers

            # Advance past debounce window
            clock.return_value = 206.0
            bridge.on_event(make_log_event(seq=10))  # Gap 2 -> triggers again

        trigger_logs = [
            r for r in caplog.records
            if "Triggering" in r.message and "rehydration" in r.message.lower()
        ]
        assert len(trigger_logs) == 2


# ---------------------------------------------------------------------------
# Stop / Reset behavior
# ---------------------------------------------------------------------------


class TestStopReset:
    """Test stop() and reset() lifecycle methods."""

    def test_events_dropped_after_stop(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """Events are silently dropped after stop()."""
        bridge.stop()

        clock.return_value = 200.0
        bridge.on_event(make_log_event(seq=1))
        bridge.on_event(make_phase_started_event(seq=2))

        mock_renderer.render_log.assert_not_called()
        mock_renderer.render_phase_started.assert_not_called()

    def test_stop_flushes_remaining(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """stop() flushes remaining queued log events."""
        clock.return_value = 100.0
        bridge.on_event(make_log_event(seq=1))
        mock_renderer.reset_mock()

        clock.return_value = 100.01
        bridge.on_event(make_log_event(seq=2, message="queued"))

        bridge.stop()
        assert mock_renderer.render_log.call_count == 1

    def test_reset_clears_state(self, bridge: EventBridge) -> None:
        """reset() clears seq tracking, context, and queue."""
        bridge._last_seq = 42
        bridge._last_epic_id = 15
        bridge._last_story_id = "15.3"
        bridge._log_queue.append({})
        bridge._stopped = True

        bridge.reset()

        assert bridge._last_seq is None
        assert bridge._last_epic_id is None
        assert bridge._last_story_id is None
        assert len(bridge._log_queue) == 0
        assert bridge._stopped is False


# ---------------------------------------------------------------------------
# Malformed events
# ---------------------------------------------------------------------------


class TestMalformedEvents:
    """Test graceful handling of malformed events."""

    def test_missing_type_field(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """Event with missing type field does not crash."""
        bridge.on_event({"seq": 1, "data": {}, "timestamp": "2026-02-20T00:00:00Z"})

    def test_missing_data_field(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """Event with missing data field does not crash."""
        bridge.on_event({"seq": 1, "type": "phase_started", "timestamp": "2026-02-20T00:00:00Z"})
        mock_renderer.render_phase_started.assert_called_once()

    def test_empty_event_dict(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """Empty event dict does not crash."""
        bridge.on_event({})

    def test_unknown_event_type(
        self, bridge: EventBridge, mock_renderer: MagicMock
    ) -> None:
        """Unknown event type is silently ignored."""
        bridge.on_event({"seq": 1, "type": "alien_event", "data": {}, "timestamp": "2026-02-20T00:00:00Z"})

        mock_renderer.render_log.assert_not_called()
        mock_renderer.render_phase_started.assert_not_called()


# ---------------------------------------------------------------------------
# FakeEventSource integration
# ---------------------------------------------------------------------------


class TestFakeEventSourceIntegration:
    """Test EventBridge with FakeEventSource for replay scenarios."""

    def test_replay_sync_dispatches_all(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """FakeEventSource.replay_sync dispatches all events."""
        clock.return_value = 200.0
        events = [
            (0, make_phase_started_event(seq=1, phase="create_story")),
            (10, make_log_event(seq=2, message="creating story")),
            (100, make_phase_completed_event(seq=3, phase="create_story", duration_seconds=30.0)),
        ]
        source = FakeEventSource(events)
        count = source.replay_sync(bridge.on_event)

        assert count == 3
        mock_renderer.render_phase_started.assert_called_once()
        mock_renderer.render_phase_completed.assert_called_once()

    def test_replay_sync_abrupt_termination(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """FakeEventSource.replay_sync with terminate_at stops early."""
        clock.return_value = 200.0
        events = [
            (0, make_phase_started_event(seq=1)),
            (10, make_log_event(seq=2)),
            (20, make_log_event(seq=3)),
        ]
        source = FakeEventSource(events)
        count = source.replay_sync(bridge.on_event, terminate_at=2)

        assert count == 2

    @pytest.mark.asyncio
    async def test_replay_async_dispatches_all(
        self, bridge: EventBridge, mock_renderer: MagicMock, clock: MagicMock
    ) -> None:
        """FakeEventSource.replay_async dispatches all events (no delay)."""
        clock.return_value = 200.0
        events = [
            (0, make_phase_started_event(seq=1)),
            (0, make_log_event(seq=2, message="test")),
        ]
        source = FakeEventSource(events)
        count = await source.replay_async(bridge.on_event, time_scale=0.0)

        assert count == 2

    def test_replay_with_seq_gaps(
        self, bridge: EventBridge, clock: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FakeEventSource with non-contiguous seqs triggers gap detection."""
        import logging

        clock.return_value = 200.0
        events = [
            (0, make_log_event(seq=1)),
            (0, make_log_event(seq=5)),  # Gap!
        ]
        source = FakeEventSource(events)
        with caplog.at_level(logging.WARNING):
            source.replay_sync(bridge.on_event)

        assert any("sequence gap" in r.message for r in caplog.records)
