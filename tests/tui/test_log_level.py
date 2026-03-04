"""Tests for tui/log_level.py LogLevelToggle component."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.status_bar import StatusBar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_status_bar() -> MagicMock:
    """Create a mock StatusBar."""
    return MagicMock(spec=StatusBar)


@pytest.fixture()
def mock_layout() -> MagicMock:
    """Create a mock LayoutManager."""
    return MagicMock(spec=LayoutManager)


@pytest.fixture()
def toggle(mock_status_bar: MagicMock, mock_layout: MagicMock) -> "LogLevelToggle":
    """Create a LogLevelToggle with mock dependencies."""
    from bmad_assist.tui.log_level import LogLevelToggle

    return LogLevelToggle(mock_status_bar, mock_layout)


# Import after fixtures to avoid import errors during collection
# (actual import happens at test runtime via fixture)


# ---------------------------------------------------------------------------
# LOG_LEVEL_CYCLE constant (AC #1, #12)
# ---------------------------------------------------------------------------


class TestLogLevelCycleConstant:
    def test_cycle_is_tuple(self) -> None:
        """LOG_LEVEL_CYCLE is a tuple."""
        from bmad_assist.tui.log_level import LOG_LEVEL_CYCLE

        assert isinstance(LOG_LEVEL_CYCLE, tuple)

    def test_cycle_contains_three_levels(self) -> None:
        """LOG_LEVEL_CYCLE contains exactly 3 levels."""
        from bmad_assist.tui.log_level import LOG_LEVEL_CYCLE

        assert LOG_LEVEL_CYCLE == ("WARNING", "INFO", "DEBUG")


# ---------------------------------------------------------------------------
# __init__() tests (AC #1)
# ---------------------------------------------------------------------------


class TestLogLevelToggleInit:
    def test_stores_references(
        self, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """LogLevelToggle stores StatusBar and LayoutManager references."""
        from bmad_assist.tui.log_level import LogLevelToggle

        toggle = LogLevelToggle(mock_status_bar, mock_layout)
        assert toggle._status_bar is mock_status_bar
        assert toggle._layout is mock_layout

    def test_default_level_is_warning(
        self, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """Default _current_level is 'WARNING'."""
        from bmad_assist.tui.log_level import LogLevelToggle

        toggle = LogLevelToggle(mock_status_bar, mock_layout)
        assert toggle._current_level == "WARNING"

    def test_ipc_callback_is_none(
        self, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """Default _ipc_callback is None."""
        from bmad_assist.tui.log_level import LogLevelToggle

        toggle = LogLevelToggle(mock_status_bar, mock_layout)
        assert toggle._ipc_callback is None


# ---------------------------------------------------------------------------
# get_level() tests (AC #6)
# ---------------------------------------------------------------------------


class TestGetLevel:
    def test_returns_current_level(self, toggle: "LogLevelToggle") -> None:
        """get_level() returns current level string."""
        assert toggle.get_level() == "WARNING"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_reflects_set_level(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """get_level() reflects changes from set_level()."""
        toggle.set_level("DEBUG")
        assert toggle.get_level() == "DEBUG"


# ---------------------------------------------------------------------------
# set_level() tests (AC #5)
# ---------------------------------------------------------------------------


class TestSetLevel:
    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_updates_current_level(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """set_level() updates _current_level."""
        toggle.set_level("INFO")
        assert toggle._current_level == "INFO"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_calls_status_bar_set_log_level(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_status_bar: MagicMock,
    ) -> None:
        """set_level() calls status_bar.set_log_level() with new level."""
        toggle.set_level("DEBUG")
        mock_status_bar.set_log_level.assert_called_with("DEBUG")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_calls_update_log_level(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """set_level() calls update_log_level() from cli_utils."""
        toggle.set_level("INFO")
        mock_update.assert_called_with("INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_does_not_call_ipc_callback(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """set_level() does NOT call _ipc_callback (avoids echo loop)."""
        cb = MagicMock()
        toggle.set_ipc_callback(cb)
        toggle.set_level("DEBUG")
        cb.assert_not_called()

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_does_not_write_log(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_layout: MagicMock,
    ) -> None:
        """set_level() does NOT write a log message (avoids feedback loop)."""
        toggle.set_level("INFO")
        mock_layout.write_log.assert_not_called()

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_invalid_level_is_noop(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_status_bar: MagicMock,
    ) -> None:
        """set_level() with invalid level is a no-op."""
        toggle.set_level("ERROR")
        assert toggle._current_level == "WARNING"  # unchanged
        mock_status_bar.set_log_level.assert_not_called()
        mock_update.assert_not_called()

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_invalid_level_critical_is_noop(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_status_bar: MagicMock,
    ) -> None:
        """set_level('CRITICAL') is silently ignored."""
        toggle.set_level("CRITICAL")
        assert toggle._current_level == "WARNING"
        mock_status_bar.set_log_level.assert_not_called()

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_case_insensitive(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """set_level() is case-insensitive ('debug' → 'DEBUG')."""
        toggle.set_level("debug")
        assert toggle._current_level == "DEBUG"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_case_insensitive_info(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """set_level('Info') → 'INFO'."""
        toggle.set_level("Info")
        assert toggle._current_level == "INFO"


# ---------------------------------------------------------------------------
# set_ipc_callback() tests (AC #4)
# ---------------------------------------------------------------------------


class TestSetIpcCallback:
    def test_stores_callback(self, toggle: "LogLevelToggle") -> None:
        """set_ipc_callback() stores the callback."""
        cb = MagicMock()
        toggle.set_ipc_callback(cb)
        assert toggle._ipc_callback is cb


# ---------------------------------------------------------------------------
# on_log_level_key() tests (AC #2)
# ---------------------------------------------------------------------------


class TestOnLogLevelKey:
    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_cycles_warning_to_info(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() cycles WARNING → INFO."""
        assert toggle.get_level() == "WARNING"
        toggle.on_log_level_key()
        assert toggle.get_level() == "INFO"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_cycles_info_to_debug(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() cycles INFO → DEBUG."""
        toggle.on_log_level_key()  # WARNING → INFO
        toggle.on_log_level_key()  # INFO → DEBUG
        assert toggle.get_level() == "DEBUG"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_cycles_debug_to_warning(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() cycles DEBUG → WARNING (wrapping)."""
        toggle.on_log_level_key()  # WARNING → INFO
        toggle.on_log_level_key()  # INFO → DEBUG
        toggle.on_log_level_key()  # DEBUG → WARNING
        assert toggle.get_level() == "WARNING"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_full_cycle(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """Full cycle: WARNING → INFO → DEBUG → WARNING."""
        assert toggle.get_level() == "WARNING"
        toggle.on_log_level_key()
        assert toggle.get_level() == "INFO"
        toggle.on_log_level_key()
        assert toggle.get_level() == "DEBUG"
        toggle.on_log_level_key()
        assert toggle.get_level() == "WARNING"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_calls_status_bar_set_log_level(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_status_bar: MagicMock,
    ) -> None:
        """on_log_level_key() calls status_bar.set_log_level() with new level."""
        toggle.on_log_level_key()
        mock_status_bar.set_log_level.assert_called_with("INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_calls_update_log_level(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() calls update_log_level() from cli_utils."""
        toggle.on_log_level_key()
        mock_update.assert_called_with("INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_calls_ipc_callback_when_set(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() calls _ipc_callback(new_level) when set."""
        cb = MagicMock()
        toggle.set_ipc_callback(cb)
        toggle.on_log_level_key()
        cb.assert_called_once_with("INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_safe_when_ipc_callback_is_none(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_status_bar: MagicMock,
    ) -> None:
        """on_log_level_key() does not crash when _ipc_callback is None."""
        toggle.on_log_level_key()  # Should not raise
        assert toggle.get_level() == "INFO"
        mock_update.assert_called_once_with("INFO")
        mock_status_bar.set_log_level.assert_called_with("INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_ipc_callback_exception_caught(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """on_log_level_key() catches IPC callback exceptions and logs warning."""
        cb = MagicMock(side_effect=RuntimeError("IPC error"))
        toggle.set_ipc_callback(cb)
        with caplog.at_level(logging.WARNING, logger="bmad_assist.tui.log_level"):
            toggle.on_log_level_key()  # Should not raise
        assert toggle.get_level() == "INFO"  # State still updated
        assert any(
            "IPC log-level callback failed" in r.message for r in caplog.records
        )

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_out_of_cycle_level_resets_to_warning(
        self, mock_update: MagicMock, toggle: "LogLevelToggle"
    ) -> None:
        """on_log_level_key() resets to WARNING when _current_level is outside cycle."""
        toggle._current_level = "ERROR"  # Simulate corrupted/external state
        toggle.on_log_level_key()
        assert toggle.get_level() == "WARNING"

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_writes_log_message(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_layout: MagicMock,
    ) -> None:
        """on_log_level_key() writes exact log message to LayoutManager."""
        toggle.on_log_level_key()
        mock_layout.write_log.assert_called_once_with("Log level: INFO")

    @patch("bmad_assist.tui.log_level.update_log_level")
    def test_writes_log_with_correct_level_each_cycle(
        self,
        mock_update: MagicMock,
        toggle: "LogLevelToggle",
        mock_layout: MagicMock,
    ) -> None:
        """Log messages reflect correct level at each cycle step."""
        toggle.on_log_level_key()
        assert mock_layout.write_log.call_args[0][0] == "Log level: INFO"

        toggle.on_log_level_key()
        assert mock_layout.write_log.call_args[0][0] == "Log level: DEBUG"

        toggle.on_log_level_key()
        assert mock_layout.write_log.call_args[0][0] == "Log level: WARNING"
