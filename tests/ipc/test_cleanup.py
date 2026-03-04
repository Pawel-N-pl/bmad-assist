"""Tests for IPC socket cleanup utilities.

Story 29.6: Socket cleanup on crash — defense-in-depth cleanup strategy.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.ipc.cleanup import (
    read_socket_pid,
    cleanup_orphaned_sockets,
    cleanup_socket,
    cleanup_stale_sockets_on_startup,
    clear_active_socket,
    find_orphaned_sockets,
    get_active_socket,
    is_socket_stale,
    set_active_socket,
    signal_safe_cleanup,
)
from bmad_assist.ipc.protocol import SOCKET_DIR, compute_project_hash


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", d)
    return d


@pytest.fixture
def sock_file(sock_dir: Path) -> Path:
    """Create a socket file in the test socket directory."""
    p = sock_dir / "test1234.sock"
    p.touch()
    return p


@pytest.fixture
def lock_file(sock_file: Path) -> Path:
    """Create a lock file with current PID for the socket file."""
    lock = Path(f"{sock_file}.lock")
    lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")
    return lock


@pytest.fixture(autouse=True)
def reset_active_socket():
    """Ensure active socket is cleared between tests."""
    clear_active_socket()
    yield
    clear_active_socket()


# =============================================================================
# Test: read_socket_pid
# =============================================================================


class TestReadSocketPid:
    """Test lock file PID reading."""

    def test_reads_valid_pid(self, tmp_path: Path) -> None:
        lock = tmp_path / "test.sock.lock"
        lock.write_text("12345\n2026-02-19T00:00:00+00:00\n")
        assert read_socket_pid(lock) == 12345

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "nonexistent.sock.lock"
        assert read_socket_pid(lock) is None

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "empty.sock.lock"
        lock.write_text("")
        assert read_socket_pid(lock) is None

    def test_returns_none_for_invalid_content(self, tmp_path: Path) -> None:
        lock = tmp_path / "invalid.sock.lock"
        lock.write_text("not-a-number\n")
        assert read_socket_pid(lock) is None


# =============================================================================
# Test: is_socket_stale (AC #1)
# =============================================================================


class TestIsSocketStale:
    """Test stale socket detection."""

    def test_stale_when_no_lock_file(self, sock_file: Path) -> None:
        """Socket with no lock file is stale."""
        assert is_socket_stale(sock_file) is True

    def test_stale_when_pid_dead(self, sock_file: Path) -> None:
        """Socket with dead PID lock is stale."""
        lock = Path(f"{sock_file}.lock")
        lock.write_text("999999999\n2026-02-19T00:00:00+00:00\n")
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=False):
            assert is_socket_stale(sock_file) is True

    def test_not_stale_when_pid_alive(self, sock_file: Path, lock_file: Path) -> None:
        """Socket with live PID is not stale."""
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            assert is_socket_stale(sock_file) is False

    def test_stale_when_invalid_lock_content(self, sock_file: Path) -> None:
        """Socket with invalid lock content is stale."""
        lock = Path(f"{sock_file}.lock")
        lock.write_text("garbage\ndata\n")
        assert is_socket_stale(sock_file) is True

    def test_probe_returns_stale_on_connect_failure(
        self, sock_file: Path, lock_file: Path
    ) -> None:
        """With probe=True, socket that fails connect is stale."""
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            with patch("bmad_assist.ipc.cleanup._run_probe_sync", return_value=False):
                assert is_socket_stale(sock_file, probe=True) is True

    def test_probe_returns_active_on_successful_ping(
        self, sock_file: Path, lock_file: Path
    ) -> None:
        """With probe=True, socket that responds to ping is active."""
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            with patch("bmad_assist.ipc.cleanup._run_probe_sync", return_value=True):
                assert is_socket_stale(sock_file, probe=True) is False


# =============================================================================
# Test: find_orphaned_sockets (AC #1)
# =============================================================================


class TestFindOrphanedSockets:
    """Test orphaned socket scanning."""

    def test_empty_dir(self, sock_dir: Path) -> None:
        """Empty socket directory returns empty list."""
        assert find_orphaned_sockets() == []

    def test_finds_socket_without_lock(self, sock_file: Path) -> None:
        """Socket without lock file is orphaned."""
        orphans = find_orphaned_sockets()
        assert len(orphans) == 1
        assert orphans[0][0] == sock_file
        assert orphans[0][1] is None
        assert orphans[0][2] == "no_lock_file"

    def test_finds_socket_with_dead_pid(self, sock_file: Path) -> None:
        """Socket with dead PID is orphaned."""
        lock = Path(f"{sock_file}.lock")
        lock.write_text("999999999\n2026-02-19T00:00:00+00:00\n")
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=False):
            orphans = find_orphaned_sockets()
        assert len(orphans) == 1
        assert orphans[0][1] == 999999999
        assert orphans[0][2] == "process_dead"

    def test_skips_active_socket(self, sock_file: Path, lock_file: Path) -> None:
        """Socket with live PID is not orphaned."""
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            orphans = find_orphaned_sockets()
        assert len(orphans) == 0

    def test_handles_nonexistent_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nonexistent socket directory returns empty list."""
        monkeypatch.setattr(
            "bmad_assist.ipc.cleanup.SOCKET_DIR",
            tmp_path / "nonexistent",
        )
        assert find_orphaned_sockets() == []

    def test_multiple_sockets_mixed(self, sock_dir: Path) -> None:
        """Multiple sockets with mixed states."""
        # Active socket
        active = sock_dir / "active.sock"
        active.touch()
        active_lock = Path(f"{active}.lock")
        active_lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        # Orphaned socket (no lock)
        orphan = sock_dir / "orphan.sock"
        orphan.touch()

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            orphans = find_orphaned_sockets()

        assert len(orphans) == 1
        assert orphans[0][0] == orphan


# =============================================================================
# Test: cleanup_socket (AC #1)
# =============================================================================


class TestCleanupSocket:
    """Test individual socket cleanup."""

    def test_removes_sock_and_lock(self, sock_file: Path, lock_file: Path) -> None:
        """Removes both .sock and .lock files."""
        assert cleanup_socket(sock_file) is True
        assert not sock_file.exists()
        assert not lock_file.exists()

    def test_returns_false_when_nothing_exists(self, sock_dir: Path) -> None:
        """Returns False when neither file exists."""
        nonexistent = sock_dir / "ghost.sock"
        assert cleanup_socket(nonexistent) is False

    def test_removes_sock_without_lock(self, sock_file: Path) -> None:
        """Removes socket even without lock file."""
        assert cleanup_socket(sock_file) is True
        assert not sock_file.exists()

    def test_removes_lock_without_sock(self, sock_dir: Path) -> None:
        """Removes lock file even without socket file."""
        lock = sock_dir / "orphan.sock.lock"
        lock.write_text("1234\n")
        sock = sock_dir / "orphan.sock"
        assert cleanup_socket(sock) is True
        assert not lock.exists()


# =============================================================================
# Test: cleanup_orphaned_sockets (AC #1)
# =============================================================================


class TestCleanupOrphanedSockets:
    """Test batch orphaned socket cleanup."""

    def test_removes_stale_sockets(self, sock_dir: Path) -> None:
        """Removes all stale sockets."""
        # Create orphaned socket (no lock file)
        orphan = sock_dir / "orphan.sock"
        orphan.touch()

        cleaned = cleanup_orphaned_sockets()
        assert len(cleaned) == 1
        assert cleaned[0] == orphan
        assert not orphan.exists()

    def test_preserves_active_sockets(self, sock_file: Path, lock_file: Path) -> None:
        """Does not remove active sockets."""
        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            cleaned = cleanup_orphaned_sockets()
        assert len(cleaned) == 0
        assert sock_file.exists()
        assert lock_file.exists()

    def test_force_probes_and_removes_connect_failed(self, sock_dir: Path) -> None:
        """Force mode probes live-PID sockets and removes failed ones."""
        sock = sock_dir / "zombie.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            with patch("bmad_assist.ipc.cleanup._run_probe_sync", return_value=False):
                cleaned = cleanup_orphaned_sockets(force=True)

        assert len(cleaned) == 1
        assert not sock.exists()

    def test_empty_returns_empty_list(self, sock_dir: Path) -> None:
        """No sockets to clean returns empty list."""
        cleaned = cleanup_orphaned_sockets()
        assert cleaned == []


# =============================================================================
# Test: cleanup_stale_sockets_on_startup (AC #9)
# =============================================================================


class TestCleanupStaleSocketsOnStartup:
    """Test project-specific startup cleanup."""

    def test_removes_stale_for_project(self, sock_dir: Path, tmp_path: Path) -> None:
        """Removes stale socket matching project hash."""
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        project_hash = compute_project_hash(project_root)

        sock = sock_dir / f"{project_hash}.sock"
        sock.touch()
        # No lock file → stale

        with patch("bmad_assist.ipc.cleanup.compute_project_hash", return_value=project_hash):
            cleanup_stale_sockets_on_startup(project_root)

        assert not sock.exists()

    def test_preserves_other_project_sockets(
        self, sock_dir: Path, tmp_path: Path
    ) -> None:
        """Does not touch sockets from other projects."""
        project_root = tmp_path / "my-project"
        project_root.mkdir()

        other_sock = sock_dir / "other_project_hash.sock"
        other_sock.touch()

        cleanup_stale_sockets_on_startup(project_root)
        assert other_sock.exists()

    def test_noop_when_no_socket_exists(
        self, sock_dir: Path, tmp_path: Path
    ) -> None:
        """No-op when project socket doesn't exist."""
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        # Should not raise
        cleanup_stale_sockets_on_startup(project_root)

    def test_noop_when_socket_active(
        self, sock_dir: Path, tmp_path: Path
    ) -> None:
        """Does not remove active socket for project."""
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        project_hash = compute_project_hash(project_root)

        sock = sock_dir / f"{project_hash}.sock"
        sock.touch()
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

        with patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True):
            with patch("bmad_assist.ipc.cleanup.compute_project_hash", return_value=project_hash):
                cleanup_stale_sockets_on_startup(project_root)

        assert sock.exists()
        assert lock.exists()

    def test_noop_when_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No-op when socket directory doesn't exist."""
        monkeypatch.setattr(
            "bmad_assist.ipc.cleanup.SOCKET_DIR",
            tmp_path / "nonexistent",
        )
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        # Should not raise
        cleanup_stale_sockets_on_startup(project_root)


# =============================================================================
# Test: Module-level socket tracking (AC #10)
# =============================================================================


class TestActiveSocketTracking:
    """Test module-level socket path tracking."""

    def test_initially_none(self) -> None:
        assert get_active_socket() is None

    def test_set_and_get(self, tmp_path: Path) -> None:
        path = tmp_path / "test.sock"
        set_active_socket(path)
        assert get_active_socket() == path

    def test_clear(self, tmp_path: Path) -> None:
        path = tmp_path / "test.sock"
        set_active_socket(path)
        clear_active_socket()
        assert get_active_socket() is None


# =============================================================================
# Test: signal_safe_cleanup (AC #3)
# =============================================================================


class TestSignalSafeCleanup:
    """Test signal-safe cleanup function."""

    def test_removes_socket_and_lock(self, tmp_path: Path) -> None:
        """Removes socket and lock files when active."""
        sock = tmp_path / "test.sock"
        lock = tmp_path / "test.sock.lock"
        sock.touch()
        lock.touch()

        set_active_socket(sock)
        signal_safe_cleanup()

        assert not sock.exists()
        assert not lock.exists()

    def test_noop_when_no_active_socket(self) -> None:
        """No-op when no active socket is set."""
        # Should not raise
        signal_safe_cleanup()

    def test_handles_missing_files(self, tmp_path: Path) -> None:
        """Handles case where files don't exist."""
        sock = tmp_path / "ghost.sock"
        set_active_socket(sock)
        # Should not raise
        signal_safe_cleanup()

    def test_only_uses_os_unlink(self, tmp_path: Path) -> None:
        """Verify implementation uses os.unlink, not pathlib."""
        sock = tmp_path / "test.sock"
        sock.touch()
        set_active_socket(sock)

        with patch("bmad_assist.ipc.cleanup.os.unlink") as mock_unlink:
            signal_safe_cleanup()
            assert mock_unlink.call_count == 2
            mock_unlink.assert_any_call(str(sock))
            mock_unlink.assert_any_call(str(sock) + ".lock")


# =============================================================================
# Test: Crash simulation (AC #7)
# =============================================================================


class TestCrashSimulation:
    """Test that stale socket detection works after SIGKILL."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Unix-only: signals and sockets",
    )
    def test_sigkill_leaves_socket_and_new_start_cleans(
        self, sock_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SIGKILL a process → socket remains → new start detects stale and cleans."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_hash = compute_project_hash(project_root)
        sock_path = sock_dir / f"{project_hash}.sock"

        # Simulate: create socket and lock with a dead PID
        # We use a subprocess that exits immediately to get a dead PID
        proc = subprocess.Popen(
            [sys.executable, "-c", "import os; print(os.getpid())"],
            stdout=subprocess.PIPE,
        )
        proc.wait()
        dead_pid = int(proc.stdout.read().strip())

        sock_path.touch()
        lock_path = Path(f"{sock_path}.lock")
        lock_path.write_text(f"{dead_pid}\n2026-02-19T00:00:00+00:00\n")

        # Verify files exist
        assert sock_path.exists()
        assert lock_path.exists()

        # Verify stale detection works
        assert is_socket_stale(sock_path) is True

        # Cleanup on startup removes stale socket
        with patch("bmad_assist.ipc.cleanup.compute_project_hash", return_value=project_hash):
            cleanup_stale_sockets_on_startup(project_root)

        assert not sock_path.exists()
        assert not lock_path.exists()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Unix-only: signals and sockets",
    )
    def test_lock_file_remains_after_sigkill(
        self, sock_dir: Path, tmp_path: Path
    ) -> None:
        """Verify lock file remains after process SIGKILL (expected behavior)."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_hash = compute_project_hash(project_root)
        sock_path = sock_dir / f"{project_hash}.sock"

        # Simulate dead process
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE,
        )
        dead_pid = proc.pid
        sock_path.touch()
        lock_path = Path(f"{sock_path}.lock")
        lock_path.write_text(f"{dead_pid}\n2026-02-19T00:00:00+00:00\n")

        # Kill the process
        try:
            os.kill(dead_pid, signal.SIGKILL)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()

        # Files should remain (SIGKILL bypasses all cleanup)
        assert sock_path.exists()
        assert lock_path.exists()

        # But they should be detected as stale
        assert is_socket_stale(sock_path) is True


# =============================================================================
# Test: Stress test (AC #8)
# =============================================================================


class TestStressStartStop:
    """Stress test: no orphan sockets after rapid start/stop cycles."""

    def test_no_orphans_after_rapid_cycles(self, tmp_path: Path) -> None:
        """20 rapid start/stop cycles leave no orphan sockets."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)

        for i in range(20):
            # Simulate start: create socket + lock
            sock = sock_dir / f"cycle_{i}.sock"
            lock = Path(f"{sock}.lock")
            sock.touch()
            lock.write_text(f"{os.getpid()}\n2026-02-19T00:00:00+00:00\n")

            # Simulate stop: cleanup
            assert cleanup_socket(sock) is True
            assert not sock.exists()
            assert not lock.exists()

        # Verify no leftover files
        remaining_socks = list(sock_dir.glob("*.sock"))
        remaining_locks = list(sock_dir.glob("*.sock.lock"))
        assert remaining_socks == []
        assert remaining_locks == []

    def test_concurrent_stale_detection(self, sock_dir: Path) -> None:
        """Multiple stale sockets detected correctly."""
        # Create 10 stale sockets (no lock files)
        for i in range(10):
            (sock_dir / f"stale_{i}.sock").touch()

        orphans = find_orphaned_sockets()
        assert len(orphans) == 10

        cleaned = cleanup_orphaned_sockets()
        assert len(cleaned) == 10

        # Verify all cleaned
        remaining = list(sock_dir.glob("*.sock"))
        assert remaining == []
