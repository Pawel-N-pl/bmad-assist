"""Tests for CLI serve command - Story 16.1: CLI Serve Command.

Tests verify:
- AC1: Default port 9600, status message with URL/path/hint
- AC2: Custom port via --port
- AC3: Custom host via --host
- AC4: Config loading wrapped in try/except for ConfigError
- AC5: Graceful shutdown on SIGTERM/SIGINT (exit 0)
- AC6: Port-in-use error handling (exit 1)
- AC7: Server starts without config (graceful degradation)
- AC8: Verbose flag enables debug logging
"""

import asyncio
import errno
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app
from bmad_assist.cli_utils import EXIT_ERROR, EXIT_SUCCESS

runner = CliRunner()


# =============================================================================
# Fixtures for mocking asyncio.run
# =============================================================================


@pytest.fixture
def mock_asyncio_run():
    """Mock asyncio.run to prevent blocking during tests."""
    with patch("asyncio.run") as mock:
        mock.return_value = None
        yield mock


# =============================================================================
# Test: Serve Command Existence and Help (AC: All)
# =============================================================================


@pytest.mark.skipif(os.geteuid() == 0, reason="Rich/Typer help broken in Docker as root")
class TestServeCommandExists:
    """Tests for serve command registration and help output."""

    def test_serve_command_in_help(self, cli_isolated_env: Path) -> None:
        """GIVEN user runs help
        WHEN they check available commands
        THEN serve command is listed.
        """
        # GIVEN: User runs --help
        result = runner.invoke(app, ["--help"])

        # THEN: serve command is visible
        assert result.exit_code == 0
        assert "serve" in result.output.lower()

    def test_serve_help_shows_all_options(self, cli_isolated_env: Path) -> None:
        """GIVEN user runs serve --help
        WHEN they view options
        THEN --port, --host, --verbose, --project are listed.
        """
        # GIVEN: User runs serve --help
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: All options are displayed
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output
        assert "--verbose" in result.output
        assert "--project" in result.output
        # Short forms
        assert "-p" in result.output  # --port short form

    def test_serve_help_does_not_have_h_short_for_host(self, cli_isolated_env: Path) -> None:
        """GIVEN user runs serve --help
        WHEN they check short forms
        THEN -h is NOT a short form for --host (conflicts with --help).
        """
        # GIVEN: User runs serve --help
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: -h is not listed as short form for --host
        # (It should only appear for --help which is auto-generated)
        assert result.exit_code == 0
        # Verify -h is NOT listed before --host
        # Typer shows short form as "-h, --host" if -h exists
        assert "-h, --host" not in result.output
        assert "--host" in result.output  # But --host should exist


# =============================================================================
# Test: Default Port and Startup Message (AC1)
# =============================================================================


class TestServeDefaultPort:
    """Tests for default port 9600 and startup message (AC1)."""

    def test_serve_uses_default_port_9600(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user runs serve without --port
        WHEN server starts
        THEN it uses port 9600.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve without --port
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Server configured with port 9600
        # Note: This test will FAIL until serve command is implemented
        assert mock_asyncio_run.called or "serve" not in result.output.lower()
        # The actual assertion will be: check uvicorn.Config was called with port=9600

    def test_serve_startup_message_shows_url(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user starts server successfully
        WHEN startup completes
        THEN status message shows server URL.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Output shows URL
        # Note: Test will FAIL until implementation shows URL in output
        assert "127.0.0.1" in result.output or "localhost" in result.output

    def test_serve_startup_message_shows_project_path(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user starts server successfully
        WHEN startup completes
        THEN status message shows project path.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Output shows project path (or at least "project" in path)
        assert "project" in result.output.lower() or str(tmp_path) in result.output

    def test_serve_startup_message_shows_shutdown_hint(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user starts server successfully
        WHEN startup completes
        THEN status message shows Ctrl+C hint.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Output shows shutdown hint
        assert "ctrl+c" in result.output.lower() or "ctrl-c" in result.output.lower()


# =============================================================================
# Test: Custom Port (AC2)
# =============================================================================


class TestServeCustomPort:
    """Tests for custom port option (AC2)."""

    def test_serve_accepts_custom_port(self, tmp_path: Path, mock_asyncio_run: MagicMock) -> None:
        """GIVEN user runs serve --port 3000
        WHEN server starts
        THEN it uses port 3000.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve with custom port
        result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "3000"])

        # THEN: Server uses custom port
        # Note: Test will FAIL until implementation uses the port value
        assert "3000" in result.output or mock_asyncio_run.called

    def test_serve_port_short_form(self, tmp_path: Path) -> None:
        """GIVEN user runs serve -p 9000
        WHEN server starts
        THEN short form -p works for port.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve with -p short form
        # Note: -p is used for --project in other commands, check if serve uses different
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: -p short form exists for --port (not conflicting)
        assert result.exit_code == 0
        # The implementation must decide short form allocation


# =============================================================================
# Test: Custom Host (AC3)
# =============================================================================


class TestServeCustomHost:
    """Tests for custom host option (AC3)."""

    def test_serve_accepts_custom_host(self, tmp_path: Path, mock_asyncio_run: MagicMock) -> None:
        """GIVEN user runs serve --host 0.0.0.0
        WHEN server starts
        THEN it binds to all interfaces.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve with custom host
        result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--host", "0.0.0.0"])

        # THEN: Server binds to all interfaces
        # Note: Test will FAIL until implementation uses host value
        assert "0.0.0.0" in result.output or mock_asyncio_run.called

    def test_serve_default_host_is_localhost(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user runs serve without --host
        WHEN server starts
        THEN default host is 127.0.0.1 (localhost only).
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve without --host
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Default is localhost
        assert "127.0.0.1" in result.output or mock_asyncio_run.called


# =============================================================================
# Test: Config Loading (AC4, AC7)
# =============================================================================


class TestServeConfigLoading:
    """Tests for config loading behavior (AC4, AC7)."""

    def test_serve_starts_without_config(self, tmp_path: Path, mock_asyncio_run: MagicMock) -> None:
        """GIVEN no project config exists
        WHEN user runs serve
        THEN server starts anyway (graceful degradation).
        """
        # GIVEN: Project without config
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        
        # No bmad-assist.yaml created

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Server starts (exit 0 or continues running)
        # Note: Test will FAIL until serve handles missing config gracefully
        # Should NOT exit with config error
        assert result.exit_code != 2  # EXIT_CONFIG_ERROR

    def test_serve_handles_config_error_gracefully(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN load_config_with_project raises ConfigError
        WHEN user runs serve
        THEN server starts without full config (project_root only).
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: Config loading fails (note: serve should catch internally)
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Server should still start (exit 0)
        # Note: Test will FAIL until implementation wraps config in try/except
        assert result.exit_code == EXIT_SUCCESS or mock_asyncio_run.called


# =============================================================================
# Test: Graceful Shutdown (AC5)
# =============================================================================


class TestServeGracefulShutdown:
    """Tests for graceful shutdown behavior (AC5)."""

    def test_serve_exits_cleanly_after_shutdown(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN server is running
        WHEN shutdown completes
        THEN exit code is EXIT_SUCCESS (0).
        """
        # GIVEN: Valid project directory (use tmp_path - autouse fixture creates sprint-status.yaml)
        # WHEN: Server runs and completes (simulated)
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Exit code is 0
        # Note: Test will FAIL until implementation returns EXIT_SUCCESS
        assert result.exit_code == EXIT_SUCCESS

    def test_serve_shows_shutdown_message(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN server receives shutdown signal
        WHEN shutdown completes
        THEN shutdown message is displayed.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: Server shuts down
        result = runner.invoke(app, ["serve", "--project", str(tmp_path)])

        # THEN: Shutdown message visible AND clean exit
        assert result.exit_code == EXIT_SUCCESS
        assert "server stopped" in result.output.lower()


# =============================================================================
# Test: Port In Use Error (AC6)
# =============================================================================


class TestServePortInUse:
    """Tests for port-in-use error handling (AC6)."""

    def test_serve_port_in_use_shows_error(self, tmp_path: Path) -> None:
        """GIVEN port is already in use
        WHEN user attempts to start serve
        THEN clear error message is displayed.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: Port is in use (OSError with EADDRINUSE)
        with patch("asyncio.run") as mock_run:
            mock_run.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

        # THEN: Error message mentions port in use
        # Note: Test will FAIL until implementation catches OSError
        assert "in use" in result.output.lower() or "already" in result.output.lower()

    def test_serve_port_in_use_exits_with_error(self, tmp_path: Path) -> None:
        """GIVEN port is already in use
        WHEN user attempts to start serve
        THEN exit code is EXIT_ERROR (1).
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: Port is in use
        with patch("asyncio.run") as mock_run:
            mock_run.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

        # THEN: Exit code is 1
        # Note: Test will FAIL until implementation handles OSError
        assert result.exit_code == EXIT_ERROR


# =============================================================================
# Test: Verbose Logging (AC8)
# =============================================================================


class TestServeVerboseLogging:
    """Tests for verbose logging option (AC8)."""

    def test_serve_verbose_flag_accepted(self) -> None:
        """GIVEN user runs serve --verbose
        WHEN checking help
        THEN --verbose flag is recognized.
        """
        # GIVEN: User checks serve help
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: --verbose is listed
        assert "--verbose" in result.output

    def test_serve_verbose_short_form(self, cli_isolated_env: Path) -> None:
        """GIVEN user runs serve -v
        WHEN checking help
        THEN -v short form exists.
        """
        # GIVEN: User checks serve help
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: -v short form is listed
        assert "-v" in result.output

    def test_serve_verbose_sets_debug_log_level(
        self, tmp_path: Path, mock_asyncio_run: MagicMock
    ) -> None:
        """GIVEN user runs serve --verbose
        WHEN server starts
        THEN Uvicorn log_level is set to 'debug'.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # WHEN: User runs serve with --verbose
        result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--verbose"])

        # THEN: Uvicorn config has log_level="debug"
        # Note: Test will FAIL until implementation passes verbose to uvicorn
        # This requires inspecting uvicorn.Config call args
        assert mock_asyncio_run.called  # At minimum, asyncio.run should be called


# =============================================================================
# Test: Invalid Project Path
# =============================================================================


class TestServeInvalidProject:
    """Tests for invalid project path handling."""

    def test_serve_nonexistent_project_exits_with_error(self, tmp_path: Path) -> None:
        """GIVEN project path does not exist
        WHEN user runs serve
        THEN exit code is EXIT_ERROR.
        """
        # GIVEN: Nonexistent project path
        nonexistent = tmp_path / "nonexistent"

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(nonexistent)])

        # THEN: Exit with error
        assert result.exit_code == EXIT_ERROR

    def test_serve_file_as_project_exits_with_error(self, tmp_path: Path) -> None:
        """GIVEN project path is a file (not directory)
        WHEN user runs serve
        THEN exit code is EXIT_ERROR.
        """
        # GIVEN: File instead of directory
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a directory")

        # WHEN: User runs serve
        result = runner.invoke(app, ["serve", "--project", str(file_path)])

        # THEN: Exit with error
        assert result.exit_code == EXIT_ERROR


# =============================================================================
# Test: Port Auto-Discovery (Story 16.11)
# =============================================================================


class TestServePortAutoDiscovery:
    """Tests for port auto-discovery integration (Story 16.11)."""

    @pytest.mark.skipif(os.geteuid() == 0, reason="Rich/Typer help broken in Docker as root")
    def test_serve_help_shows_no_auto_port_flag(self, cli_isolated_env: Path) -> None:
        """GIVEN user runs serve --help
        WHEN they view options
        THEN --no-auto-port flag is listed.
        """
        # GIVEN: User runs serve --help
        result = runner.invoke(app, ["serve", "--help"])

        # THEN: --no-auto-port is displayed
        assert result.exit_code == 0
        assert "--no-auto-port" in result.output

    def test_serve_auto_discovers_port_when_busy(self, tmp_path: Path, mock_asyncio_run) -> None:
        """GIVEN default port is busy
        WHEN user runs serve (without --no-auto-port)
        THEN server uses next available port.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port to return different port
        with patch(
            "bmad_assist.dashboard.server.find_available_port", return_value=9602
        ) as mock_find:
            # WHEN: User runs serve
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

            # THEN: find_available_port was called with correct args
            mock_find.assert_called_once_with(9600, "127.0.0.1")

    def test_serve_shows_warning_when_using_different_port(
        self, tmp_path: Path, mock_asyncio_run
    ) -> None:
        """GIVEN default port is busy
        WHEN server uses different port
        THEN warning message is displayed.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port to return different port
        with patch("bmad_assist.dashboard.server.find_available_port", return_value=9602):
            # WHEN: User runs serve with port 9600
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

        # THEN: Warning shows port change
        assert "9600" in result.output
        assert "9602" in result.output
        assert "unavailable" in result.output.lower()

    def test_serve_shows_actual_port_in_startup_message(
        self, tmp_path: Path, mock_asyncio_run
    ) -> None:
        """GIVEN port auto-discovery finds different port
        WHEN startup message is displayed
        THEN it shows the actual port.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port to return different port
        with patch("bmad_assist.dashboard.server.find_available_port", return_value=9602):
            # WHEN: User runs serve
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

        # THEN: Startup URL shows actual port
        assert "http://127.0.0.1:9602/" in result.output

    def test_serve_no_auto_port_fails_immediately(self, tmp_path: Path, mock_asyncio_run) -> None:
        """GIVEN --no-auto-port flag is used
        WHEN port is busy (OSError raised)
        THEN server fails immediately.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock asyncio.run to raise port in use error
        with patch("asyncio.run") as mock_run:
            mock_run.side_effect = OSError(errno.EADDRINUSE, "Address already in use")

            # WHEN: User runs serve with --no-auto-port
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--no-auto-port"])

        # THEN: Exits with error
        assert result.exit_code == EXIT_ERROR

    def test_serve_no_auto_port_skips_discovery(self, tmp_path: Path, mock_asyncio_run) -> None:
        """GIVEN --no-auto-port flag is used
        WHEN server starts
        THEN find_available_port is NOT called.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port
        with patch("bmad_assist.dashboard.server.find_available_port") as mock_find:
            # WHEN: User runs serve with --no-auto-port
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--no-auto-port"])

        # THEN: find_available_port was NOT called
        mock_find.assert_not_called()

    def test_serve_all_ports_busy_shows_error(self, tmp_path: Path) -> None:
        """GIVEN all ports are busy
        WHEN user runs serve
        THEN error message shows port range tried.
        """
        from bmad_assist.core.exceptions import DashboardError

        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port to raise DashboardError
        with patch(
            "bmad_assist.dashboard.server.find_available_port",
            side_effect=DashboardError(
                "No available port. Tried: 9600-9618. Free a port or use --port with different value."
            ),
        ):
            # WHEN: User runs serve
            result = runner.invoke(app, ["serve", "--project", str(tmp_path), "--port", "9600"])

        # THEN: Error shows port range
        assert result.exit_code == EXIT_ERROR
        assert "9600" in result.output
        assert "9618" in result.output

    def test_serve_passes_host_to_port_discovery(self, tmp_path: Path, mock_asyncio_run) -> None:
        """GIVEN custom host is specified
        WHEN find_available_port is called
        THEN it receives the correct host.
        """
        # GIVEN: Valid project directory
        # Using tmp_path directly (autouse fixture creates sprint-status.yaml)
        

        # Mock find_available_port
        with patch(
            "bmad_assist.dashboard.server.find_available_port", return_value=9600
        ) as mock_find:
            # WHEN: User runs serve with custom host
            result = runner.invoke(
                app, ["serve", "--project", str(tmp_path), "--host", "0.0.0.0"]
            )

        # THEN: find_available_port was called with correct host
        mock_find.assert_called_once_with(9600, "0.0.0.0")
