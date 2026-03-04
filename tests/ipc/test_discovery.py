"""Tests for IPC instance discovery module.

Story 29.8: Tests for discover_instances(), discover_instances_async(),
and DiscoveredInstance dataclass.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bmad_assist.ipc.discovery import (
    DiscoveredInstance,
    discover_instances,
    discover_instances_async,
    probe_instance,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory for discovery tests."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", d)
    monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", d)
    return d


def _create_socket_with_lock(
    sock_dir: Path, name: str, pid: int | None = None
) -> Path:
    """Create a .sock file with optional .lock file containing PID."""
    sock = sock_dir / f"{name}.sock"
    sock.touch()
    if pid is not None:
        lock = Path(f"{sock}.lock")
        lock.write_text(f"{pid}\n2026-02-19T00:00:00+00:00\n")
    return sock


# =============================================================================
# Test: DiscoveredInstance dataclass (AC #2)
# =============================================================================


class TestDiscoveredInstance:
    """Test DiscoveredInstance frozen dataclass."""

    def test_creates_with_fields(self) -> None:
        """DiscoveredInstance stores all required fields."""
        now = datetime.now(UTC)
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=12345,
            state={"state": "running"},
            discovered_at=now,
        )
        assert inst.socket_path == Path("/tmp/test.sock")
        assert inst.project_hash == "a" * 32
        assert inst.pid == 12345
        assert inst.state == {"state": "running"}
        assert inst.discovered_at == now

    def test_frozen_immutable(self) -> None:
        """DiscoveredInstance is immutable (frozen dataclass)."""
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=12345,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            inst.pid = 99999  # type: ignore[misc]

    def test_default_state_is_empty_dict(self) -> None:
        """state defaults to empty dict."""
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
        )
        assert inst.state == {}

    def test_default_discovered_at_is_utc_now(self) -> None:
        """discovered_at defaults to approximately now."""
        before = datetime.now(UTC)
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
        )
        after = datetime.now(UTC)
        assert before <= inst.discovered_at <= after

    def test_pid_none_when_lock_missing(self) -> None:
        """pid can be None."""
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="abc123",
            pid=None,
        )
        assert inst.pid is None

    def test_project_hash_matches_socket_stem(self) -> None:
        """project_hash should match socket filename stem."""
        path = Path("/tmp/sockets/abcdef1234567890abcdef1234567890.sock")
        inst = DiscoveredInstance(
            socket_path=path,
            project_hash=path.stem,
            pid=1000,
        )
        assert inst.project_hash == "abcdef1234567890abcdef1234567890"

    def test_last_seen_defaults_to_utc_now(self) -> None:
        """last_seen defaults to approximately now (UTC)."""
        before = datetime.now(UTC)
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
        )
        after = datetime.now(UTC)
        assert before <= inst.last_seen <= after

    def test_last_seen_equals_discovered_at_by_default(self) -> None:
        """For one-shot callers, last_seen and discovered_at are both ~now."""
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
        )
        # Both default to datetime.now(UTC) — they may differ by microseconds
        # but should be very close
        delta = abs((inst.last_seen - inst.discovered_at).total_seconds())
        assert delta < 0.1

    def test_last_seen_explicit_value(self) -> None:
        """last_seen can be set explicitly."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 1, 2, tzinfo=UTC)
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
            discovered_at=t1,
            last_seen=t2,
        )
        assert inst.discovered_at == t1
        assert inst.last_seen == t2

    def test_last_seen_immutable(self) -> None:
        """last_seen cannot be mutated on frozen dataclass."""
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            inst.last_seen = datetime.now(UTC)  # type: ignore[misc]

    def test_last_seen_updated_via_replace(self) -> None:
        """last_seen can be updated via dataclasses.replace()."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        inst = DiscoveredInstance(
            socket_path=Path("/tmp/test.sock"),
            project_hash="a" * 32,
            pid=None,
            discovered_at=t1,
            last_seen=t1,
        )
        t2 = datetime(2026, 1, 2, tzinfo=UTC)
        updated = dataclasses.replace(inst, last_seen=t2)
        assert updated.last_seen == t2
        assert updated.discovered_at == t1  # preserved
        assert inst.last_seen == t1  # original unchanged


# =============================================================================
# Test: discover_instances() with no socket directory (AC #3)
# =============================================================================


class TestDiscoverNoSocketDir:
    """Test discover_instances() when socket directory doesn't exist."""

    def test_returns_empty_list_no_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty list when socket directory doesn't exist."""
        monkeypatch.setattr(
            "bmad_assist.ipc.discovery.SOCKET_DIR",
            tmp_path / "nonexistent",
        )
        result = discover_instances()
        assert result == []


# =============================================================================
# Test: discover_instances() with stale sockets only (AC #3)
# =============================================================================


class TestDiscoverStaleOnly:
    """Test discover_instances() with only stale sockets present."""

    def test_returns_empty_list_stale_only(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty list when only stale sockets exist (no lock files)."""
        # Create socket without lock file → stale
        _create_socket_with_lock(sock_dir, "stale1")
        _create_socket_with_lock(sock_dir, "stale2")

        result = discover_instances()
        assert result == []

    def test_returns_empty_list_dead_pid(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty list when sockets have dead PIDs."""
        _create_socket_with_lock(sock_dir, "dead", pid=99999999)

        with patch(
            "bmad_assist.ipc.cleanup._is_pid_alive", return_value=False
        ):
            result = discover_instances()

        assert result == []


# =============================================================================
# Test: discover_instances() with live server (AC #3, integration)
# =============================================================================


class TestDiscoverWithLiveServer:
    """Test discover_instances() with a real SocketServer."""

    @pytest.mark.asyncio
    async def test_discovers_live_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discovers a live SocketServer and returns populated state."""
        from bmad_assist.ipc.server import SocketServer
        from bmad_assist.ipc.types import RunnerState

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        sock_path = sock_dir / "testhash1234567890abcdef12345678.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={"current_epic": 29, "current_story": "29.8"},
        )

        await server.start()
        try:
            instances = await discover_instances_async(probe_timeout=5.0)
            assert len(instances) == 1

            inst = instances[0]
            assert inst.socket_path == sock_path
            assert inst.project_hash == sock_path.stem
            assert inst.pid is not None
            assert inst.state.get("state") == "running"
            assert inst.state.get("current_epic") == 29
            assert inst.state.get("current_story") == "29.8"
            assert isinstance(inst.discovered_at, datetime)
        finally:
            await server.stop()


# =============================================================================
# Test: discover_instances() graceful error handling (AC #3)
# =============================================================================


class TestDiscoverGracefulErrors:
    """Test discover_instances() handles per-socket failures."""

    def test_handles_one_socket_failing(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One failing socket doesn't abort discovery of others.

        Tests mixed success/failure: one socket returns valid state,
        the other fails probe. The successful discovery must still appear.
        """
        _create_socket_with_lock(sock_dir, "good", pid=os.getpid())
        _create_socket_with_lock(sock_dir, "bad", pid=os.getpid())

        good_state: dict[str, Any] = {"state": "running", "current_phase": "dev_story"}

        async def mock_probe(socket_path: Path, timeout: float) -> dict[str, Any] | None:
            """Return state for 'good' socket, None for 'bad'."""
            if "good" in socket_path.name:
                return good_state
            return None  # Simulate probe failure

        with (
            patch("bmad_assist.ipc.cleanup._is_pid_alive", return_value=True),
            patch("bmad_assist.ipc.discovery.probe_instance", side_effect=mock_probe),
        ):
            result = discover_instances(probe_timeout=0.5)

        # One succeeded, one failed — should get exactly one result
        assert len(result) == 1
        assert result[0].project_hash == "good"
        assert result[0].state == good_state

    def test_all_probes_fail_returns_empty_list(
        self, sock_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All probes failing returns empty list without exception."""
        _create_socket_with_lock(sock_dir, "fail1", pid=os.getpid())
        _create_socket_with_lock(sock_dir, "fail2", pid=os.getpid())

        with patch(
            "bmad_assist.ipc.cleanup._is_pid_alive", return_value=True
        ):
            # Both sockets look alive but neither has a real server
            result = discover_instances(probe_timeout=0.5)

        assert isinstance(result, list)
        assert len(result) == 0


# =============================================================================
# Test: discover_instances() sorting (AC #3)
# =============================================================================


# =============================================================================
# Story 29.9: Project identity in discovered instance state
# =============================================================================


class TestDiscoverProjectIdentity:
    """Story 29.9 AC #1-2: Discovered instance state contains project identity."""

    @pytest.mark.asyncio
    async def test_discovered_state_contains_project_name_and_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Probing a real server returns project_name and project_path in state."""
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        project = tmp_path / "my-test-project"
        project.mkdir()
        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=project)

        await server.start()
        try:
            state = await probe_instance(sock_path, timeout=5.0)
            assert state is not None
            assert state.get("project_name") == "my-test-project"
            assert state.get("project_path") == str(project)
        finally:
            await server.stop()


# =============================================================================
# Test: last_seen field in discover_instances_async (AC #5)
# =============================================================================


class TestLastSeenInDiscovery:
    """Story 29.11 AC #5: last_seen set identical to discovered_at in scans."""

    @pytest.mark.asyncio
    async def test_discover_sets_last_seen_equal_to_discovered_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """discover_instances_async sets last_seen == discovered_at from same timestamp."""
        from bmad_assist.ipc.server import SocketServer
        from bmad_assist.ipc.types import RunnerState

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        server.update_runner_state(state=RunnerState.IDLE)

        await server.start()
        try:
            instances = await discover_instances_async(probe_timeout=5.0)
            assert len(instances) == 1
            inst = instances[0]
            # Both must be identical — set from same datetime.now(UTC) call
            assert inst.discovered_at == inst.last_seen
        finally:
            await server.stop()


class TestDiscoverSorting:
    """Test discover_instances() result is sorted by socket_path."""

    @pytest.mark.asyncio
    async def test_results_sorted_by_socket_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Results are sorted by socket_path."""
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        # Create two servers with names that would sort differently
        # Use short names to stay under 107-byte sun_path limit
        sock_path_z = sock_dir / "zzzz.sock"
        sock_path_a = sock_dir / "aaaa.sock"

        server_z = SocketServer(socket_path=sock_path_z, project_root=tmp_path)
        server_a = SocketServer(
            socket_path=sock_path_a, project_root=tmp_path / "other"
        )

        await server_z.start()
        await server_a.start()
        try:
            instances = await discover_instances_async(probe_timeout=5.0)
            assert len(instances) == 2
            assert instances[0].socket_path < instances[1].socket_path
            assert instances[0].project_hash == "aaaa"
            assert instances[1].project_hash == "zzzz"
        finally:
            await server_z.stop()
            await server_a.stop()


# =============================================================================
# Story 29.11: DiscoveryService tests (AC #1, #2, #3, #4, #5, #12)
# =============================================================================


class TestDiscoveryServiceLifecycle:
    """Story 29.11 AC #1: DiscoveryService starts and stops cleanly."""

    def test_start_and_stop(self) -> None:
        """Service starts and stops without error."""
        from bmad_assist.ipc.discovery import DiscoveryService

        service = DiscoveryService(poll_interval=1.0)
        service.start()
        try:
            assert service._thread is not None
            assert service._thread.is_alive()
        finally:
            service.stop()
        assert service._thread is None

    def test_context_manager(self) -> None:
        """Service works as context manager."""
        from bmad_assist.ipc.discovery import DiscoveryService

        with DiscoveryService(poll_interval=1.0) as service:
            assert service._thread is not None
            assert service._thread.is_alive()
        # After exit, thread should be stopped
        assert service._thread is None

    def test_get_instances_empty_initially(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_instances() returns empty list initially."""
        from bmad_assist.ipc.discovery import DiscoveryService

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)

        with DiscoveryService(poll_interval=1.0) as service:
            instances = service.get_instances()
            assert instances == []

    def test_invalid_poll_interval_raises(self) -> None:
        """poll_interval <= 0 raises ValueError."""
        from bmad_assist.ipc.discovery import DiscoveryService

        with pytest.raises(ValueError, match="poll_interval must be positive"):
            DiscoveryService(poll_interval=0)
        with pytest.raises(ValueError, match="poll_interval must be positive"):
            DiscoveryService(poll_interval=-1.0)

    def test_invalid_probe_timeout_raises(self) -> None:
        """probe_timeout <= 0 raises ValueError."""
        from bmad_assist.ipc.discovery import DiscoveryService

        with pytest.raises(ValueError, match="probe_timeout must be positive"):
            DiscoveryService(probe_timeout=0)

    def test_double_start_is_safe(self) -> None:
        """Calling start() twice is a no-op."""
        from bmad_assist.ipc.discovery import DiscoveryService

        service = DiscoveryService(poll_interval=1.0)
        service.start()
        try:
            thread1 = service._thread
            service.start()  # Should not create a new thread
            assert service._thread is thread1
        finally:
            service.stop()


class TestDiscoveryServiceCallbacks:
    """Story 29.11 AC #2: Change-detection callbacks."""

    @pytest.mark.asyncio
    async def test_on_instance_added_callback_fires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """on_added callback fires when a new server starts."""
        import asyncio

        from bmad_assist.ipc.discovery import DiscoveryService
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        added: list[DiscoveredInstance] = []

        def on_added(inst: DiscoveredInstance) -> None:
            added.append(inst)

        service = DiscoveryService(poll_interval=0.2, probe_timeout=2.0)
        service.on_added(on_added)
        service.start()

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        await server.start()

        try:
            # Wait for discovery to detect the new server.
            # Use asyncio.sleep to yield control so the server can handle
            # probe connections from the discovery thread.
            for _ in range(50):
                if added:
                    break
                await asyncio.sleep(0.1)

            assert len(added) >= 1
            assert added[0].socket_path == sock_path
        finally:
            await server.stop()
            service.stop()

    @pytest.mark.asyncio
    async def test_on_instance_removed_callback_fires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """on_removed callback fires when a server stops."""
        import asyncio

        from bmad_assist.ipc.discovery import DiscoveryService
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        added: list[DiscoveredInstance] = []
        removed: list[Path] = []

        service = DiscoveryService(poll_interval=0.2, probe_timeout=2.0)
        service.on_added(lambda inst: added.append(inst))
        service.on_removed(lambda path: removed.append(path))

        # Start server first, then start service
        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        await server.start()

        service.start()

        try:
            # Wait for discovery to detect the server.
            # Use asyncio.sleep to yield control so the server can handle probes.
            for _ in range(50):
                if added:
                    break
                await asyncio.sleep(0.1)
            assert len(added) >= 1

            # Now stop the server
            await server.stop()

            # Wait for discovery to detect the removal
            for _ in range(50):
                if removed:
                    break
                await asyncio.sleep(0.1)

            assert len(removed) >= 1
            assert removed[0] == sock_path
        finally:
            service.stop()
            # Server may already be stopped, but ensure cleanup
            try:
                await server.stop()
            except (OSError, RuntimeError):
                pass


class TestDiscoveryServiceRefresh:
    """Story 29.11 AC #4: Manual refresh triggers immediate scan."""

    @pytest.mark.asyncio
    async def test_refresh_returns_instances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """refresh() triggers scan and returns results."""
        import asyncio

        from bmad_assist.ipc.discovery import DiscoveryService
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        await server.start()

        # Use long poll_interval so only refresh triggers scan
        service = DiscoveryService(poll_interval=60.0, probe_timeout=2.0)
        service.start()
        try:
            # Run refresh() in a thread so the event loop stays free
            # to handle probe connections from the discovery thread.
            instances = await asyncio.to_thread(service.refresh)
            assert len(instances) >= 1
            assert any(i.socket_path == sock_path for i in instances)
        finally:
            service.stop()
            await server.stop()

    def test_refresh_raises_when_not_running(self) -> None:
        """refresh() raises RuntimeError when service is not running."""
        from bmad_assist.ipc.discovery import DiscoveryService

        service = DiscoveryService(poll_interval=1.0)
        with pytest.raises(RuntimeError, match="not running"):
            service.refresh()


class TestDiscoveryServiceLastSeen:
    """Story 29.11 AC #5: last_seen updates on re-scan."""

    @pytest.mark.asyncio
    async def test_last_seen_updates_on_rescan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """last_seen is updated on each re-confirmation scan."""
        import asyncio

        from bmad_assist.ipc.discovery import DiscoveryService
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        await server.start()

        service = DiscoveryService(poll_interval=0.3, probe_timeout=2.0)
        service.start()

        try:
            # Wait for first scan — yield to event loop so server handles probes
            for _ in range(50):
                if service.get_instances():
                    break
                await asyncio.sleep(0.1)

            first_instances = service.get_instances()
            assert len(first_instances) >= 1
            first_last_seen = first_instances[0].last_seen
            first_discovered_at = first_instances[0].discovered_at

            # Wait for at least one more scan cycle — yield to event loop
            await asyncio.sleep(0.5)

            second_instances = service.get_instances()
            assert len(second_instances) >= 1

            # last_seen should have advanced (re-scan updates timestamp)
            assert second_instances[0].last_seen > first_last_seen
            # discovered_at should be preserved
            assert second_instances[0].discovered_at == first_discovered_at
        finally:
            service.stop()
            await server.stop()


class TestDiscoveryServiceErrorResilience:
    """Story 29.11 AC #2: Callback exceptions don't crash polling thread."""

    @pytest.mark.asyncio
    async def test_callback_exception_doesnt_crash_service(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception in on_added callback doesn't stop the service."""
        import asyncio

        from bmad_assist.ipc.discovery import DiscoveryService
        from bmad_assist.ipc.server import SocketServer

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir
        )

        call_count = 0

        def bad_callback(inst: DiscoveredInstance) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Intentional test error")

        service = DiscoveryService(poll_interval=0.2, probe_timeout=2.0)
        service.on_added(bad_callback)
        service.start()

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        await server.start()

        try:
            # Wait for discovery to fire the callback.
            # Use asyncio.sleep to yield control so the server can handle probes.
            for _ in range(50):
                if call_count > 0:
                    break
                await asyncio.sleep(0.1)

            assert call_count >= 1
            # Service should still be running despite callback error
            assert service._thread is not None
            assert service._thread.is_alive()

            # get_instances should still work
            instances = service.get_instances()
            assert len(instances) >= 1
        finally:
            await server.stop()
            service.stop()

    def test_thread_safety_concurrent_get_instances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_instances() is thread-safe under concurrent access."""
        import threading as th

        from bmad_assist.ipc.discovery import DiscoveryService

        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", sock_dir)
        monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)

        service = DiscoveryService(poll_interval=0.5)
        service.start()

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    result = service.get_instances()
                    assert isinstance(result, list)
            except Exception as e:
                errors.append(e)

        threads = [th.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        service.stop()
        assert len(errors) == 0
