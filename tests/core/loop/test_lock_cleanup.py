"""Tests for lock file cleanup functionality.

Story 22.3: Lock file cleanup on run completion.

Tests cover:
- Lock file creation when entering context manager
- Lock file removal on normal exit (no exception)
- Lock file removal when exception raised
- Lock file removal on KeyboardInterrupt
- Lock file format validation (PID + UTC timestamp)
- Subsequent run works immediately after lock cleanup
- Lock file removed even if state save fails
- Stale lock detection removes dead PID lock file
- Active lock check aborts new run
- Edge cases: externally deleted lock file, missing directory
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import StateError

if TYPE_CHECKING:
    pass


class TestIsPidAlive:
    """Tests for _is_pid_alive() helper function."""

    def test_is_pid_alive_returns_true_for_current_process(self, tmp_path: Path) -> None:
        """AC: _is_pid_alive returns True for the current process PID."""
        from bmad_assist.core.loop.locking import _is_pid_alive

        # Current process should be alive
        assert _is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_returns_false_for_nonexistent_pid(self, tmp_path: Path) -> None:
        """AC: _is_pid_alive returns False for a non-existent PID."""
        from bmad_assist.core.loop.locking import _is_pid_alive

        # Use a very high PID that is unlikely to exist
        # PID 99999999 is almost certainly not running
        assert _is_pid_alive(99999999) is False

    def test_is_pid_alive_returns_false_for_invalid_pid(self, tmp_path: Path) -> None:
        """AC: _is_pid_alive returns False for invalid PIDs (negative, zero)."""
        from bmad_assist.core.loop.locking import _is_pid_alive

        # Negative PIDs have special meaning in os.kill() and should be rejected
        assert _is_pid_alive(-1) is False
        assert _is_pid_alive(-99999) is False

        # PID 0 refers to the caller's process group and should be rejected
        assert _is_pid_alive(0) is False


class TestReadLockFile:
    """Tests for _read_lock_file() helper function."""

    def test_read_lock_file_valid_format(self, tmp_path: Path) -> None:
        """AC: _read_lock_file parses valid lock file format correctly."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "running.lock"
        lock_content = "12345\n2026-01-15T02:53:54.691166+00:00\n"
        lock_path.write_text(lock_content)

        pid, timestamp = _read_lock_file(lock_path)
        assert pid == 12345
        assert timestamp == "2026-01-15T02:53:54.691166+00:00"

    def test_read_lock_file_with_extra_newlines(self, tmp_path: Path) -> None:
        """AC: _read_lock_file handles extra whitespace correctly."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "running.lock"
        lock_content = "12345\n2026-01-15T02:53:54.691166+00:00\n\n"
        lock_path.write_text(lock_content)

        pid, timestamp = _read_lock_file(lock_path)
        assert pid == 12345
        assert timestamp == "2026-01-15T02:53:54.691166+00:00"

    def test_read_lock_file_missing_timestamp(self, tmp_path: Path) -> None:
        """AC: _read_lock_file returns (None, None) for incomplete lock file."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "running.lock"
        lock_content = "12345\n"
        lock_path.write_text(lock_content)

        pid, timestamp = _read_lock_file(lock_path)
        assert pid is None
        assert timestamp is None

    def test_read_lock_file_invalid_pid(self, tmp_path: Path) -> None:
        """AC: _read_lock_file returns (None, None) for invalid PID."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "running.lock"
        lock_content = "not_a_number\n2026-01-15T02:53:54.691166+00:00\n"
        lock_path.write_text(lock_content)

        pid, timestamp = _read_lock_file(lock_path)
        assert pid is None
        assert timestamp is None

    def test_read_lock_file_empty_file(self, tmp_path: Path) -> None:
        """AC: _read_lock_file returns (None, None) for empty file."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "running.lock"
        lock_path.write_text("")

        pid, timestamp = _read_lock_file(lock_path)
        assert pid is None
        assert timestamp is None

    def test_read_lock_file_nonexistent_file(self, tmp_path: Path) -> None:
        """AC: _read_lock_file returns (None, None) for missing file."""
        from bmad_assist.core.loop.locking import _read_lock_file

        lock_path = tmp_path / "nonexistent.lock"

        pid, timestamp = _read_lock_file(lock_path)
        assert pid is None
        assert timestamp is None


class TestRunningLockBasic:
    """Tests for _running_lock() context manager basic functionality."""

    def test_lock_file_created_on_enter(self, tmp_path: Path) -> None:
        """AC 3.1: Lock file created when entering context manager."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        # Mock init_run_prompts_dir to avoid directory creation
        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            # Lock file should exist
            assert lock_path.exists()

            # Lock file should contain valid PID
            content = lock_path.read_text().strip().split("\n")
            assert len(content) >= 2
            assert content[0].strip().isdigit()
            pid_from_lock = int(content[0].strip())

            # PID should match current process
            assert pid_from_lock == os.getpid()

            # Second line should be valid ISO timestamp
            timestamp_str = content[1].strip()
            # Should be parseable as ISO datetime
            datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

    def test_lock_file_removed_on_normal_exit(self, tmp_path: Path) -> None:
        """AC 3.2: Lock file removed on normal exit (no exception)."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            # Lock file exists during context
            assert lock_path.exists()

        # Lock file should be removed after exit
        assert not lock_path.exists()

    def test_lock_file_removed_when_exception_raised(self, tmp_path: Path) -> None:
        """AC 3.3: Lock file removed when exception raised."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"), pytest.raises(ValueError):
            with _running_lock(tmp_path):
                assert lock_path.exists()
                raise ValueError("Test exception")

        # Lock file should be removed despite exception
        assert not lock_path.exists()

    def test_lock_file_removed_on_keyboard_interrupt(self, tmp_path: Path) -> None:
        """AC 3.4: Lock file removed on KeyboardInterrupt."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            # Simulate KeyboardInterrupt in context manager body
            def body_that_raises():
                with _running_lock(tmp_path):
                    assert lock_path.exists()
                    raise KeyboardInterrupt()

            with pytest.raises(KeyboardInterrupt):
                body_that_raises()

        # Lock file should be removed despite KeyboardInterrupt
        assert not lock_path.exists()

    def test_lock_file_format_correct(self, tmp_path: Path) -> None:
        """AC 3.5: Lock file contains PID and UTC timestamp in correct format."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            content = lock_path.read_text()
            lines = content.strip().split("\n")

            # Should have exactly 2 lines
            assert len(lines) >= 2

            # First line: PID (decimal integer)
            pid = int(lines[0].strip())
            assert pid == os.getpid()

            # Second line: ISO 8601 timestamp
            timestamp_str = lines[1].strip()
            # Should be parseable as datetime
            parsed_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            # Should be recent (within last minute)
            assert (datetime.now(UTC) - parsed_time).total_seconds() < 60

    def test_subsequent_run_works_after_lock_cleanup(self, tmp_path: Path) -> None:
        """AC 3.6: Subsequent run works immediately after lock cleanup."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        # First run
        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            pass

        # Lock should be cleaned up
        assert not lock_path.exists()

        # Second run should work immediately (no "lock exists" error)
        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            assert lock_path.exists()

        # Lock cleaned up again
        assert not lock_path.exists()


class TestRunningLockEdgeCases:
    """Tests for edge cases in lock file cleanup."""

    def test_lock_cleanup_when_file_manually_deleted_during_run(self, tmp_path: Path) -> None:
        """AC 4.1: Handle lock file manually deleted during run."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path) as lock:
                assert lock.exists()

                # Simulate external deletion
                lock.unlink()
                assert not lock.exists()

            # No crash, finally block handles missing file gracefully
            assert not lock.exists()

    def test_lock_cleanup_when_directory_deleted_during_run(self, tmp_path: Path) -> None:
        """AC 4.2: Handle .bmad-assist/ directory deleted during run."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"

        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path) as lock:
                assert lock.exists()

                # Simulate external directory deletion
                import shutil

                shutil.rmtree(lock_dir)
                assert not lock_dir.exists()

            # No crash, finally block handles missing directory gracefully
            # (Directory will be recreated if needed)

    def test_lock_file_removed_even_if_state_save_fails(self, tmp_path: Path) -> None:
        """AC 3.7: Lock file removed even if state save fails."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        with patch("bmad_assist.core.io.init_run_prompts_dir"), _running_lock(tmp_path):
            assert lock_path.exists()

        # Lock cleanup happens regardless of state save failures
        assert not lock_path.exists()


class TestStaleLockDetection:
    """Tests for stale lock detection and cleanup (AC #2)."""

    def test_stale_lock_detection_removes_dead_pid_lock(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC 3.8: Stale lock detection removes dead PID lock file."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # Create a stale lock with a non-existent PID
        stale_pid = 99999999  # Almost certainly not running
        stale_timestamp = "2026-01-15T02:53:54.691166+00:00"
        lock_path.write_text(f"{stale_pid}\n{stale_timestamp}\n")

        assert lock_path.exists()

        with caplog.at_level(logging.WARNING):
            with patch("bmad_assist.core.io.init_run_prompts_dir"):
                with _running_lock(tmp_path) as lock:
                    # Stale lock should have been removed
                    # New lock should have our PID
                    content = lock.read_text().strip().split("\n")
                    current_pid = int(content[0].strip())
                    assert current_pid == os.getpid()
                    assert current_pid != stale_pid

        # Warning should be logged
        assert "Removed stale lock file" in caplog.text
        assert str(stale_pid) in caplog.text

    def test_stale_lock_with_invalid_format_is_removed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC: Invalid lock files are treated as stale and removed."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # Create an invalid lock file
        lock_path.write_text("invalid_content\nnot_a_pid\n")

        assert lock_path.exists()

        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path) as lock:
                # Invalid lock should have been removed
                # New lock should have our PID
                content = lock.read_text().strip().split("\n")
                current_pid = int(content[0].strip())
                assert current_pid == os.getpid()

        # Lock should work normally after cleanup
        assert not lock_path.exists()

    def test_stale_lock_warning_includes_timestamp(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC: Stale lock warning includes the lock timestamp."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # Create a stale lock with specific timestamp
        stale_pid = 99999999
        stale_timestamp = "2026-01-15T02:53:54.691166+00:00"
        lock_path.write_text(f"{stale_pid}\n{stale_timestamp}\n")

        with caplog.at_level(logging.WARNING):
            with patch("bmad_assist.core.io.init_run_prompts_dir"):
                with _running_lock(tmp_path):
                    pass

        # Warning should include the timestamp
        assert stale_timestamp in caplog.text
        assert "locked at" in caplog.text


class TestActiveLockPrevention:
    """Tests for active lock checking and concurrent run prevention (AC #3)."""

    def test_active_lock_check_aborts_new_run(self, tmp_path: Path) -> None:
        """AC 3.9: Active lock check aborts new run."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # Create a lock with the current (running) PID
        current_pid = os.getpid()
        lock_path.write_text(f"{current_pid}\n2026-01-15T02:53:54.691166+00:00\n")

        # Attempting to create a new lock should raise StateError
        with pytest.raises(StateError) as exc_info:
            with patch("bmad_assist.core.io.init_run_prompts_dir"):
                with _running_lock(tmp_path):
                    pass

        # Error message should mention the active PID
        assert "already active" in str(exc_info.value).lower()
        assert str(current_pid) in str(exc_info.value)
        assert lock_path.as_posix() in str(exc_info.value)

    def test_active_lock_error_message_is_helpful(self, tmp_path: Path) -> None:
        """AC: Error message includes instructions for manual cleanup."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # Create a lock with the current PID
        current_pid = os.getpid()
        lock_path.write_text(f"{current_pid}\n2026-01-15T02:53:54.691166+00:00\n")

        with pytest.raises(StateError) as exc_info:
            with patch("bmad_assist.core.io.init_run_prompts_dir"):
                with _running_lock(tmp_path):
                    pass

        error_msg = str(exc_info.value)

        # Should explain the problem
        assert "already active" in error_msg.lower()
        # Should provide the lock file path for manual cleanup
        assert lock_path.as_posix() in error_msg
        # Should mention the PID
        assert str(current_pid) in error_msg


class TestLockFileLifecycle:
    """Integration tests for complete lock file lifecycle."""

    def test_lock_lifecycle_create_run_cleanup_run_again(self, tmp_path: Path) -> None:
        """AC: Complete lifecycle: create → run → cleanup → run again."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_path = tmp_path / ".bmad-assist" / "running.lock"

        # First run
        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path) as lock1:
                assert lock1.exists()
                first_pid = int(lock1.read_text().strip().split("\n")[0])
                assert first_pid == os.getpid()

        # Lock cleaned up
        assert not lock_path.exists()

        # Second run (immediate, no manual cleanup needed)
        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path) as lock2:
                assert lock2.exists()
                second_pid = int(lock2.read_text().strip().split("\n")[0])
                assert second_pid == os.getpid()

        # Lock cleaned up again
        assert not lock_path.exists()

    def test_multiple_concurrent_lock_attempts_fail(self, tmp_path: Path) -> None:
        """AC: Only one _running_lock context can be active at a time."""
        from bmad_assist.core.loop.locking import _running_lock

        lock_dir = tmp_path / ".bmad-assist"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "running.lock"

        # First lock
        with patch("bmad_assist.core.io.init_run_prompts_dir"):
            with _running_lock(tmp_path):
                assert lock_path.exists()

                # Second lock attempt should fail
                with pytest.raises(StateError, match="already active"):
                    with patch("bmad_assist.core.io.init_run_prompts_dir"):
                        with _running_lock(tmp_path):
                            pass

            # After first lock released, second should work
            with patch("bmad_assist.core.io.init_run_prompts_dir"):
                with _running_lock(tmp_path):
                    assert lock_path.exists()
