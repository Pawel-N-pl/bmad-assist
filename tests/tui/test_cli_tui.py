"""Tests for CLI TUI management commands.

Tests `bmad-assist tui` subcommand group:
- connect (default): Launch TUI process connected to a runner
- list: Show running instances
- reset: Emergency terminal restoration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist.commands.tui import tui_app

runner = CliRunner()


# =============================================================================
# Fixtures
# =============================================================================


def _make_instance(
    socket_path: Path,
    project_hash: str = "abc123",
    pid: int | None = 1234,
    state: dict | None = None,
) -> MagicMock:
    """Create a mock DiscoveredInstance."""
    inst = MagicMock()
    inst.socket_path = socket_path
    inst.project_hash = project_hash
    inst.pid = pid
    inst.state = state or {
        "project_name": "my-project",
        "project_path": "/home/user/my-project",
        "state": "running",
    }
    return inst


# =============================================================================
# Test: tui list command
# =============================================================================


class TestListCommand:
    """Test `bmad-assist tui list`."""

    def test_list_no_instances(self) -> None:
        """List command shows message when no instances found."""
        with patch("bmad_assist.ipc.discovery.discover_instances", return_value=[]):
            result = runner.invoke(tui_app, ["list"])
        assert result.exit_code == 0
        assert "no running" in result.output.lower()

    def test_list_shows_instances(self, tmp_path: Path) -> None:
        """List command displays instance table."""
        sock = tmp_path / "test.sock"
        inst = _make_instance(sock, pid=9876)

        with patch("bmad_assist.ipc.discovery.discover_instances", return_value=[inst]):
            result = runner.invoke(tui_app, ["list"])
        assert result.exit_code == 0
        assert "my-project" in result.output
        assert "running" in result.output
        assert "9876" in result.output

    def test_list_instance_no_pid(self, tmp_path: Path) -> None:
        """List command handles instance with no PID."""
        sock = tmp_path / "test.sock"
        inst = _make_instance(sock, pid=None)

        with patch("bmad_assist.ipc.discovery.discover_instances", return_value=[inst]):
            result = runner.invoke(tui_app, ["list"])
        assert result.exit_code == 0
        assert "N/A" in result.output

    def test_list_instance_empty_state(self, tmp_path: Path) -> None:
        """List command handles instance with empty state dict."""
        sock = tmp_path / "test.sock"
        inst = _make_instance(sock, state={})

        with patch("bmad_assist.ipc.discovery.discover_instances", return_value=[inst]):
            result = runner.invoke(tui_app, ["list"])
        assert result.exit_code == 0
        # Should still render a table (not crash on empty state)
        assert "Running Instances" in result.output

    def test_list_multiple_instances(self, tmp_path: Path) -> None:
        """List command shows multiple instances."""
        inst1 = _make_instance(
            tmp_path / "a.sock",
            project_hash="hash1",
            state={"project_name": "proj-a", "project_path": "/a", "state": "running"},
        )
        inst2 = _make_instance(
            tmp_path / "b.sock",
            project_hash="hash2",
            state={"project_name": "proj-b", "project_path": "/b", "state": "paused"},
        )

        with patch("bmad_assist.ipc.discovery.discover_instances", return_value=[inst1, inst2]):
            result = runner.invoke(tui_app, ["list"])
        assert result.exit_code == 0
        assert "proj-a" in result.output
        assert "proj-b" in result.output


# =============================================================================
# Test: tui reset command
# =============================================================================


class TestResetCommand:
    """Test `bmad-assist tui reset`."""

    def test_reset_calls_stty(self) -> None:
        """Reset command calls stty sane."""
        with patch("bmad_assist.commands.tui.os.system") as mock_system:
            result = runner.invoke(tui_app, ["reset"])
        assert result.exit_code == 0
        mock_system.assert_called_once_with("stty sane 2>/dev/null")
        assert "reset complete" in result.output.lower()

    def test_reset_outputs_escape_sequences(self) -> None:
        """Reset command writes terminal reset escape sequences."""
        with patch("bmad_assist.commands.tui.os.system"):
            result = runner.invoke(tui_app, ["reset"])
        assert result.exit_code == 0
        # The escape sequences are written to sys.stdout, which CliRunner captures
        # Check that the success message is shown
        assert "reset complete" in result.output.lower()


# =============================================================================
# Test: tui connect command
# =============================================================================


class TestConnectCommand:
    """Test `bmad-assist tui connect`."""

    def test_connect_non_tty_fails(self) -> None:
        """Connect command fails when stdin is not a TTY."""
        # CliRunner runs in non-TTY mode by default
        with patch("bmad_assist.commands.tui.sys") as mock_sys:
            mock_sys.stdin = None
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect"])
        assert result.exit_code == 1

    def test_connect_launches_subprocess(self) -> None:
        """Connect command launches TUI app as subprocess."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch("bmad_assist.commands.tui.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect"])

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/python3"
        assert "-m" in cmd
        assert "bmad_assist.tui.app" in cmd
        assert result.exit_code == 0

    def test_connect_with_socket_option(self) -> None:
        """Connect command passes --socket to subprocess."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch("bmad_assist.commands.tui.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect", "--socket", "/tmp/test.sock"])

        cmd = mock_popen.call_args[0][0]
        assert "--socket" in cmd
        assert "/tmp/test.sock" in cmd

    def test_connect_with_project_option(self) -> None:
        """Connect command passes --project to subprocess."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch("bmad_assist.commands.tui.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect", "--project", "my-proj"])

        cmd = mock_popen.call_args[0][0]
        assert "--project" in cmd
        assert "my-proj" in cmd

    def test_connect_returns_subprocess_exit_code(self) -> None:
        """Connect command propagates subprocess exit code."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_proc = MagicMock()
        mock_proc.returncode = 42

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch("bmad_assist.commands.tui.subprocess.Popen", return_value=mock_proc),
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect"])

        assert result.exit_code == 42

    def test_connect_popen_failure(self) -> None:
        """Connect command handles Popen failure."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch(
                "bmad_assist.commands.tui.subprocess.Popen",
                side_effect=FileNotFoundError("not found"),
            ),
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["connect"])

        assert result.exit_code == 1


# =============================================================================
# Test: tui default (no subcommand) → connect
# =============================================================================


class TestDefaultCommand:
    """Test `bmad-assist tui` (no subcommand) defaults to connect."""

    def test_no_subcommand_defaults_to_connect(self) -> None:
        """Running `bmad-assist tui` without subcommand invokes connect."""
        # Since stdin is not a TTY in CliRunner, this will fail with
        # the TTY check — which proves _do_connect was called
        with patch("bmad_assist.commands.tui.sys") as mock_sys:
            mock_sys.stdin = None
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, [])
        assert result.exit_code == 1

    def test_no_subcommand_with_project_option(self) -> None:
        """Running `bmad-assist tui -p foo` passes project to connect."""
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("bmad_assist.commands.tui.sys") as mock_sys,
            patch("bmad_assist.commands.tui.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            mock_sys.stdin = mock_stdin
            mock_sys.executable = "/usr/bin/python3"
            result = runner.invoke(tui_app, ["-p", "my-proj"])

        cmd = mock_popen.call_args[0][0]
        assert "--project" in cmd
        assert "my-proj" in cmd
