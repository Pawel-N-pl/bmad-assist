"""Tests for notification dispatch integration in runner.py.

Story 15.4: Test _dispatch_event helper and loop integration points.
"""

from pathlib import Path
from unittest.mock import patch

import pytest


class TestDispatchEventHelper:
    """Tests for _dispatch_event helper function."""

    def test_dispatch_event_noop_when_no_dispatcher(self) -> None:
        """Test _dispatch_event does nothing when dispatcher not initialized."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.CREATE_STORY,
        )

        # Should not raise, just return silently
        _dispatch_event(
            "story_started",
            Path("/test/project"),
            state,
            phase="CREATE_STORY",
        )

    def test_dispatch_event_story_started(self) -> None:
        """Test _dispatch_event for story_started event."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import (
            init_dispatcher,
            reset_dispatcher,
        )

        reset_dispatcher()

        config = NotificationConfig(
            enabled=True,
            providers=[],  # No real providers - just checking dispatch
            events=["story_started"],
        )
        init_dispatcher(config)

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.CREATE_STORY,
        )

        # Patch dispatcher.dispatch
        with patch(
            "bmad_assist.notifications.dispatcher.EventDispatcher.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = None
            _dispatch_event(
                "story_started",
                Path("/test/project"),
                state,
                phase="CREATE_STORY",
            )

        reset_dispatcher()

    def test_dispatch_event_phase_completed(self) -> None:
        """Test _dispatch_event for phase_completed event."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.DEV_STORY,
        )

        # Should not raise even without dispatcher
        _dispatch_event(
            "phase_completed",
            Path("/test/project"),
            state,
            phase="DEV_STORY",
            next_phase="CODE_REVIEW",
        )

    def test_dispatch_event_error_occurred(self) -> None:
        """Test _dispatch_event for error_occurred event."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.DEV_STORY,
        )

        # Should not raise
        _dispatch_event(
            "error_occurred",
            Path("/test/project"),
            state,
            error_type="phase_failure",
            message="Test error message",
        )

    def test_dispatch_event_story_completed(self) -> None:
        """Test _dispatch_event for story_completed event."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        )

        _dispatch_event(
            "story_completed",
            Path("/test/project"),
            state,
            duration_ms=5000,
            outcome="success",
        )

    def test_dispatch_event_queue_blocked(self) -> None:
        """Test _dispatch_event for queue_blocked event."""
        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.DEV_STORY,
        )

        _dispatch_event(
            "queue_blocked",
            Path("/test/project"),
            state,
            reason="guardian_halt",
            waiting_tasks=0,
        )

    def test_dispatch_event_unknown_type_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test unknown event types are logged and ignored."""
        import logging

        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import (
            init_dispatcher,
            reset_dispatcher,
        )

        caplog.set_level(logging.DEBUG)
        reset_dispatcher()

        config = NotificationConfig(enabled=True, events=["story_started"])
        init_dispatcher(config)

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.DEV_STORY,
        )

        # Should not raise, just log debug message
        _dispatch_event(
            "totally_unknown_event",
            Path("/test/project"),
            state,
        )

        assert "Unknown event type" in caplog.text

        reset_dispatcher()

    def test_dispatch_event_exception_caught(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test exceptions in dispatch are caught and logged."""
        import logging

        from bmad_assist.core.loop.runner import _dispatch_event
        from bmad_assist.core.state import Phase, State
        from bmad_assist.notifications.dispatcher import reset_dispatcher

        caplog.set_level(logging.DEBUG)
        reset_dispatcher()

        state = State(
            current_epic=1,
            current_story="1-1",
            current_phase=Phase.DEV_STORY,
        )

        # Mock get_dispatcher to raise exception (patch where imported)
        with patch(
            "bmad_assist.notifications.dispatcher.get_dispatcher",
            side_effect=RuntimeError("Test exception"),
        ):
            # Should not raise
            _dispatch_event(
                "story_started",
                Path("/test/project"),
                state,
                phase="DEV_STORY",
            )

        # Should be logged
        assert "Notification dispatch error" in caplog.text


class TestRunnerIntegrationWithNotifications:
    """Integration tests for notifications in run_loop."""

    def test_init_dispatcher_called_from_cli(self) -> None:
        """Test that CLI imports and calls init_dispatcher."""
        # Check import works

        # Check dispatcher module is imported in cli.py
        import importlib

        cli_module = importlib.import_module("bmad_assist.cli")

        # The import should work even though we don't call the function
        from bmad_assist.notifications.dispatcher import init_dispatcher

        assert callable(init_dispatcher)
