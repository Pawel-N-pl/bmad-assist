"""Tests for CLI IPC socket management commands.

Story 29.6: `bmad-assist ipc cleanup` and `bmad-assist ipc list` commands.
Story 29.8: `bmad-assist ipc status` and `bmad-assist ipc list --probe` commands.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist.commands.ipc import ipc_app

runner = CliRunner()


@pytest.fixture
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory for CLI tests."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", d)
    monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", d)
    monkeypatch.setattr("bmad_assist.commands.ipc.SOCKET_DIR", d, raising=False)
    return d


# =============================================================================
# Test: ipc cleanup command (AC #6)
# =============================================================================


class TestCleanupCommand:
    """Test `bmad-assist ipc cleanup` command."""

    def test_cleanup_removes_orphaned_sockets(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup command removes orphaned sockets."""
        # Create orphaned socket (no lock file)
        orphan = sock_dir / "orphan.sock"
        orphan.touch()

        result = runner.invoke(ipc_app, ["cleanup"])
        assert result.exit_code == 0
        assert not orphan.exists()

    def test_cleanup_dry_run_lists_without_removing(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup --dry-run lists orphans but does not remove."""
        orphan = sock_dir / "orphan.sock"
        orphan.touch()

        result = runner.invoke(ipc_app, ["cleanup", "--dry-run"])
        assert result.exit_code == 0
        assert orphan.exists()  # Still there
        assert "dry-run" in result.output.lower()

    def test_cleanup_no_orphans(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup when no orphans exist."""
        result = runner.invoke(ipc_app, ["cleanup"])
        assert result.exit_code == 0
        assert "no orphaned" in result.output.lower()

    def test_cleanup_no_socket_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup when socket directory doesn't exist."""
        monkeypatch.setattr(
            "bmad_assist.ipc.protocol.SOCKET_DIR",
            tmp_path / "nonexistent",
        )
        result = runner.invoke(ipc_app, ["cleanup"])
        assert result.exit_code == 0


# =============================================================================
# Test: ipc list command (AC #6)
# =============================================================================


class TestListCommand:
    """Test `bmad-assist ipc list` command."""

    def test_list_shows_sockets(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List command shows socket files with status."""
        # Create active socket with lock
        sock = sock_dir / "active.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            result = runner.invoke(ipc_app, ["list"])

        assert result.exit_code == 0
        assert "active" in result.output.lower()

    def test_list_shows_stale_sockets(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List command shows stale sockets."""
        # Create stale socket (no lock file)
        sock = sock_dir / "stale.sock"
        sock.touch()

        result = runner.invoke(ipc_app, ["list"])
        assert result.exit_code == 0
        assert "stale" in result.output.lower()

    def test_list_empty_dir(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List with no socket files."""
        result = runner.invoke(ipc_app, ["list"])
        assert result.exit_code == 0
        assert "no socket" in result.output.lower()

    def test_list_no_socket_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List when socket directory doesn't exist."""
        monkeypatch.setattr(
            "bmad_assist.ipc.protocol.SOCKET_DIR",
            tmp_path / "nonexistent",
        )
        result = runner.invoke(ipc_app, ["list"])
        assert result.exit_code == 0

    def test_list_mixed_active_and_stale(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List shows both active and stale sockets."""
        # Active socket
        active = sock_dir / "active.sock"
        active.touch()
        active_lock = Path(f"{active}.lock")
        active_lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        # Stale socket
        stale = sock_dir / "stale.sock"
        stale.touch()

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            result = runner.invoke(ipc_app, ["list"])

        assert result.exit_code == 0
        # Both should appear
        assert "active" in result.output.lower()
        assert "stale" in result.output.lower()


# =============================================================================
# Test: ipc status command (AC #4, Story 29.8)
# =============================================================================


class TestStatusCommand:
    """Test `bmad-assist ipc status` command."""

    def test_status_no_instances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status with no running instances shows informational message, exits 0."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)

        result = runner.invoke(ipc_app, ["status"])
        assert result.exit_code == 0
        assert "no running" in result.output.lower()

    def test_status_project_socket_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status --project with socket found shows detail output."""
        # Set up socket directory without triggering get_socket_dir() mkdir
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)

        # Create a fake socket file at the expected path
        from bmad_assist.ipc.protocol import compute_project_hash

        project = tmp_path / "myproject"
        project.mkdir()
        phash = compute_project_hash(project)
        sock_path = sock_dir / f"{phash}.sock"
        sock_path.touch()

        mock_state = {
            "state": "running",
            "running": True,
            "paused": False,
            "current_epic": 29,
            "current_story": "29.8",
            "current_phase": "dev_story",
            "elapsed_seconds": 125.5,
            "llm_sessions": 3,
            "error": None,
        }

        with patch(
            "bmad_assist.ipc.discovery.probe_instance",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            result = runner.invoke(
                ipc_app, ["status", "--project", str(project)]
            )

        assert result.exit_code == 0
        assert "running" in result.output.lower()
        assert "29.8" in result.output
        assert "dev_story" in result.output

    def test_status_project_socket_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status --project with no socket shows warning, exits 0."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)

        project = tmp_path / "noproject"
        project.mkdir()

        result = runner.invoke(
            ipc_app, ["status", "--project", str(project)]
        )
        assert result.exit_code == 0
        assert "no socket" in result.output.lower()

    def test_status_project_socket_exists_but_unresponsive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status --project when socket exists but runner not responding shows warning."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)

        from bmad_assist.ipc.protocol import compute_project_hash

        project = tmp_path / "myproject"
        project.mkdir()
        phash = compute_project_hash(project)
        sock_path = sock_dir / f"{phash}.sock"
        sock_path.touch()

        # Probe returns None = socket exists but runner not responding
        with patch(
            "bmad_assist.ipc.discovery.probe_instance",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = runner.invoke(
                ipc_app, ["status", "--project", str(project)]
            )

        assert result.exit_code == 0
        assert "not responding" in result.output.lower()

    def test_status_all_instances_partial_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status all-instances mode handles partial/missing state fields."""
        from datetime import UTC, datetime

        from bmad_assist.ipc.discovery import DiscoveredInstance

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)

        # Create actual socket files so _status_all_instances sees them
        sock1 = sock_dir / ("a" * 32 + ".sock")
        sock2 = sock_dir / ("b" * 32 + ".sock")
        sock1.touch()
        sock2.touch()
        # Create lock files with PIDs
        Path(f"{sock1}.lock").write_text(f"1234\n2026-02-19T00:00:00+00:00\n")
        Path(f"{sock2}.lock").write_text(f"5678\n2026-02-19T00:00:00+00:00\n")

        # Mock discover_instances to return instances with partial state
        instances = [
            DiscoveredInstance(
                socket_path=sock1,
                project_hash="a" * 32,
                pid=1234,
                state={"state": "running"},  # Minimal state, missing many fields
                discovered_at=datetime.now(UTC),
            ),
            DiscoveredInstance(
                socket_path=sock2,
                project_hash="b" * 32,
                pid=None,
                state={},  # Empty state (AC #2: ping OK, get_state failed)
                discovered_at=datetime.now(UTC),
            ),
        ]

        with patch(
            "bmad_assist.ipc.discovery.discover_instances",
            return_value=instances,
        ):
            result = runner.invoke(ipc_app, ["status"])

        assert result.exit_code == 0
        # First instance has state "running" — must appear
        assert "running" in result.output.lower()
        # Second instance has empty state {} — state should show "?"
        assert "?" in result.output
        # Second instance has pid=None — should show "N/A"
        assert "N/A" in result.output


# =============================================================================
# Test: ipc list --probe (AC #7, Story 29.8)
# =============================================================================


class TestListProbeCommand:
    """Test `bmad-assist ipc list --probe` flag."""

    def test_list_probe_shows_state(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List --probe shows State column with runner state on success."""
        from datetime import UTC, datetime

        from bmad_assist.ipc.discovery import DiscoveredInstance

        # Create active socket with lock
        sock = sock_dir / "active.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        # Mock discover_instances_async to return a probed instance
        mock_instance = DiscoveredInstance(
            socket_path=sock,
            project_hash="active",
            pid=os.getpid(),
            state={"state": "running"},
            discovered_at=datetime.now(UTC),
        )

        with (
            patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True),
            patch(
                "bmad_assist.ipc.discovery.discover_instances_async",
                new_callable=AsyncMock,
                return_value=[mock_instance],
            ),
        ):
            result = runner.invoke(ipc_app, ["list", "--probe"])

        assert result.exit_code == 0
        assert "state" in result.output.lower()
        assert "running" in result.output.lower()

    def test_list_probe_shows_question_mark_on_failure(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List --probe shows '?' for sockets that fail probe."""
        # Create active socket with lock
        sock = sock_dir / "failing.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        # Mock discover_instances_async to return empty (probe failures)
        with (
            patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True),
            patch(
                "bmad_assist.ipc.discovery.discover_instances_async",
                new_callable=AsyncMock,
                return_value=[],  # No instances discovered = probe failed
            ),
        ):
            result = runner.invoke(ipc_app, ["list", "--probe"])

        assert result.exit_code == 0
        # Table still shows the socket, State should show "?"
        assert "?" in result.output

    def test_list_without_probe_shows_dash(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List without --probe shows '–' in State column."""
        # Create active socket with lock
        sock = sock_dir / "active.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            result = runner.invoke(ipc_app, ["list"])

        assert result.exit_code == 0
        # State column exists and shows "–" for unprobed sockets
        assert "State" in result.output
        assert "–" in result.output


# =============================================================================
# Story 29.9: Project identity in status display
# =============================================================================


class TestStatusProjectIdentity:
    """Story 29.9 AC #6: Status command displays project identity."""

    def test_status_project_displays_project_name_and_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ipc status --project shows 'Project' and 'Path' rows when available."""
        from bmad_assist.ipc.protocol import compute_project_hash

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)

        project = tmp_path / "my-project"
        project.mkdir()
        phash = compute_project_hash(project)
        sock_path = sock_dir / f"{phash}.sock"
        sock_path.touch()

        mock_state = {
            "state": "running",
            "running": True,
            "paused": False,
            "current_epic": 29,
            "current_story": "29.9",
            "current_phase": "dev_story",
            "elapsed_seconds": 60.0,
            "llm_sessions": 2,
            "error": None,
            "project_name": "my-project",
            "project_path": str(project),
        }

        with patch(
            "bmad_assist.ipc.discovery.probe_instance",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            result = runner.invoke(
                ipc_app, ["status", "--project", str(project)]
            )

        assert result.exit_code == 0
        assert "Project" in result.output
        assert "my-project" in result.output
        assert "Path" in result.output
        assert str(project) in result.output

    def test_status_project_no_project_fields_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ipc status --project handles missing project fields (older runner)."""
        from bmad_assist.ipc.protocol import compute_project_hash

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)

        project = tmp_path / "legacy-project"
        project.mkdir()
        phash = compute_project_hash(project)
        sock_path = sock_dir / f"{phash}.sock"
        sock_path.touch()

        # State without project_name/project_path (older runner)
        mock_state = {
            "state": "idle",
            "running": False,
            "paused": False,
        }

        with patch(
            "bmad_assist.ipc.discovery.probe_instance",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            result = runner.invoke(
                ipc_app, ["status", "--project", str(project)]
            )

        assert result.exit_code == 0
        # "Project" row should NOT appear if project_name is missing
        # The state/running rows should still appear
        assert "idle" in result.output.lower()

    def test_status_all_instances_shows_project_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ipc status all-instances table shows 'Project' column with project name."""
        from datetime import UTC, datetime

        from bmad_assist.ipc.discovery import DiscoveredInstance

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)

        sock1 = sock_dir / ("a" * 32 + ".sock")
        sock1.touch()
        Path(f"{sock1}.lock").write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        instances = [
            DiscoveredInstance(
                socket_path=sock1,
                project_hash="a" * 32,
                pid=os.getpid(),
                state={
                    "state": "running",
                    "project_name": "cool-project",
                    "project_path": "/home/user/cool-project",
                },
                discovered_at=datetime.now(UTC),
            ),
        ]

        with patch(
            "bmad_assist.ipc.discovery.discover_instances",
            return_value=instances,
        ):
            result = runner.invoke(ipc_app, ["status"])

        assert result.exit_code == 0
        assert "Project" in result.output
        assert "cool-project" in result.output

    def test_status_all_instances_fallback_to_hash_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ipc status all-instances falls back to hash prefix when project_name missing."""
        from datetime import UTC, datetime

        from bmad_assist.ipc.discovery import DiscoveredInstance

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.protocol.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)

        sock1 = sock_dir / ("abcdef1234567890abcdef1234567890.sock")
        sock1.touch()
        Path(f"{sock1}.lock").write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        # Instance without project_name in state (older runner)
        instances = [
            DiscoveredInstance(
                socket_path=sock1,
                project_hash="abcdef1234567890abcdef1234567890",
                pid=os.getpid(),
                state={"state": "idle"},  # No project_name
                discovered_at=datetime.now(UTC),
            ),
        ]

        with patch(
            "bmad_assist.ipc.discovery.discover_instances",
            return_value=instances,
        ):
            result = runner.invoke(ipc_app, ["status"])

        assert result.exit_code == 0
        # Should show hash prefix as fallback (not a project name)
        # Hash prefix "abcdef123456" appears in output (may be truncated by Rich)
        assert "abcdef" in result.output
