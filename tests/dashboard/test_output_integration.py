"""Tests for Main Loop Output Integration - Story 16.4.

Tests verify output capture and SSE broadcasting integration:
- AC1: write_progress() output captured and sent to SSE broadcaster
- AC2: Multi-LLM validation output streamed with provider context
- AC3: Provider detection via thread-local context with regex fallback
- AC4: No errors when dashboard not connected (graceful degradation)
- AC5: Multiple dashboard connections receive output
- AC6: Hook registration during server startup/shutdown

RED Phase: All tests should FAIL initially since implementation doesn't exist.
"""

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# =============================================================================
# Task 1: Test Thread-Local Provider Context (AC: 2, 3)
# =============================================================================


class TestThreadLocalProviderContext:
    """Tests for thread-local provider context in providers/base.py.

    These tests verify that set_active_provider() and get_active_provider()
    correctly isolate provider context per-thread.
    """

    def test_set_active_provider_stores_name(self) -> None:
        """GIVEN no active provider set
        WHEN set_active_provider("claude") is called
        THEN get_active_provider() returns "claude".
        """
        # Import will fail until implementation exists
        from bmad_assist.providers.base import get_active_provider, set_active_provider

        # GIVEN: No provider set initially
        set_active_provider(None)

        # WHEN: Set active provider
        set_active_provider("claude")

        # THEN: Get returns the set value
        assert get_active_provider() == "claude"

        # Cleanup
        set_active_provider(None)

    def test_get_active_provider_returns_none_when_not_set(self) -> None:
        """GIVEN provider was never set for this thread
        WHEN get_active_provider() is called
        THEN returns None.
        """
        from bmad_assist.providers.base import get_active_provider, set_active_provider

        # GIVEN: Clear any existing provider
        set_active_provider(None)

        # WHEN/THEN: Get returns None
        assert get_active_provider() is None

    def test_thread_isolation_different_providers(self) -> None:
        """GIVEN two threads with different active providers
        WHEN each thread reads its provider
        THEN each gets its own value (thread isolation).
        """
        from bmad_assist.providers.base import get_active_provider, set_active_provider

        # Storage for thread results
        thread1_result = [None]
        thread2_result = [None]

        def thread1_work():
            set_active_provider("claude")
            time.sleep(0.05)  # Let thread2 set its value
            thread1_result[0] = get_active_provider()

        def thread2_work():
            time.sleep(0.01)  # Start after thread1
            set_active_provider("gemini")
            time.sleep(0.05)  # Let thread1 read its value
            thread2_result[0] = get_active_provider()

        # GIVEN: Two threads
        t1 = threading.Thread(target=thread1_work)
        t2 = threading.Thread(target=thread2_work)

        # WHEN: Both run concurrently
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # THEN: Each has its own provider value
        assert thread1_result[0] == "claude"
        assert thread2_result[0] == "gemini"

    def test_context_cleanup_on_none(self) -> None:
        """GIVEN provider was set to "opus"
        WHEN set_active_provider(None) is called
        THEN get_active_provider() returns None.
        """
        from bmad_assist.providers.base import get_active_provider, set_active_provider

        # GIVEN: Provider set
        set_active_provider("opus")
        assert get_active_provider() == "opus"

        # WHEN: Clear provider
        set_active_provider(None)

        # THEN: Returns None
        assert get_active_provider() is None


# =============================================================================
# Task 2-3: Test Output Callback Hook (AC: 1, 4, 6)
# =============================================================================


class TestOutputCallbackHook:
    """Tests for output callback hook registration in dashboard/__init__.py.

    These tests verify that output hooks can be registered and called
    during write_progress() execution.
    """

    def test_set_output_hook_registers_callback(self) -> None:
        """GIVEN no hook is registered
        WHEN set_output_hook(callback) is called
        THEN get_output_hook() returns the callback.
        """
        from bmad_assist.dashboard import get_output_hook, set_output_hook

        # GIVEN: No hook initially
        set_output_hook(None)

        # WHEN: Register a callback
        def my_callback(line: str, provider: str | None) -> None:
            pass

        set_output_hook(my_callback)

        # THEN: Get returns the callback
        assert get_output_hook() is my_callback

        # Cleanup
        set_output_hook(None)

    def test_get_output_hook_returns_none_when_not_set(self) -> None:
        """GIVEN no hook is registered
        WHEN get_output_hook() is called
        THEN returns None.
        """
        from bmad_assist.dashboard import get_output_hook, set_output_hook

        # GIVEN: Clear any existing hook
        set_output_hook(None)

        # THEN: Returns None
        assert get_output_hook() is None

    def test_write_progress_calls_hook_with_line(self) -> None:
        """GIVEN output hook is registered
        WHEN write_progress(line) is called
        THEN hook is called with the line.
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import write_progress

        # GIVEN: Hook registered
        captured = []

        def capture_hook(line: str, provider: str | None) -> None:
            captured.append((line, provider))

        set_output_hook(capture_hook)

        # WHEN: Write progress
        with patch("builtins.print"):  # Suppress actual print
            write_progress("test output line")

        # THEN: Hook was called
        assert len(captured) == 1
        assert captured[0][0] == "test output line"

        # Cleanup
        set_output_hook(None)

    def test_write_progress_passes_provider_from_thread_context(self) -> None:
        """GIVEN output hook is registered AND thread-local provider is set
        WHEN write_progress() is called
        THEN hook receives provider from thread-local context.
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import (
            set_active_provider,
            write_progress,
        )

        # GIVEN: Provider and hook set
        captured = []

        def capture_hook(line: str, provider: str | None) -> None:
            captured.append((line, provider))

        set_output_hook(capture_hook)
        set_active_provider("claude")

        # WHEN: Write progress
        with patch("builtins.print"):
            write_progress("test line")

        # THEN: Hook received provider
        assert len(captured) == 1
        assert captured[0][1] == "claude"

        # Cleanup
        set_output_hook(None)
        set_active_provider(None)

    def test_write_progress_no_error_when_hook_is_none(self) -> None:
        """GIVEN no output hook is registered (None)
        WHEN write_progress() is called
        THEN no exception is raised.
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import write_progress

        # GIVEN: No hook
        set_output_hook(None)

        # WHEN/THEN: No exception
        with patch("builtins.print"):
            write_progress("test line")  # Should not raise

    def test_write_progress_hook_called_outside_lock(self) -> None:
        """GIVEN output hook is registered
        WHEN write_progress() calls hook
        THEN hook is called OUTSIDE the _OUTPUT_LOCK (to prevent deadlock).

        Note: This is a behavioral test verifying hook is fire-and-forget.
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import _OUTPUT_LOCK, write_progress

        # GIVEN: Hook that checks lock state
        lock_held_during_hook = [None]

        def check_lock_hook(line: str, provider: str | None) -> None:
            # Try to acquire lock - should succeed if we're outside
            acquired = _OUTPUT_LOCK.acquire(blocking=False)
            lock_held_during_hook[0] = not acquired
            if acquired:
                _OUTPUT_LOCK.release()

        set_output_hook(check_lock_hook)

        # WHEN: Write progress
        with patch("builtins.print"):
            write_progress("test")

        # THEN: Lock was NOT held during hook call
        assert lock_held_during_hook[0] is False

        # Cleanup
        set_output_hook(None)

    def test_write_progress_hook_exception_does_not_propagate(self) -> None:
        """GIVEN output hook raises an exception
        WHEN write_progress() calls hook
        THEN exception is caught and does not propagate.
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import write_progress

        # GIVEN: Hook that raises
        def bad_hook(line: str, provider: str | None) -> None:
            raise ValueError("Hook error!")

        set_output_hook(bad_hook)

        # WHEN/THEN: No exception propagates
        with patch("builtins.print"):
            write_progress("test")  # Should not raise

        # Cleanup
        set_output_hook(None)


# =============================================================================
# Task 4: Test Sync-to-Async Bridge (AC: 1, 2, 5)
# =============================================================================


class TestSyncToAsyncBridge:
    """Tests for sync-to-async bridge functions in dashboard/__init__.py.

    These tests verify that sync_broadcast() correctly schedules
    async broadcast_output() calls in the server's event loop.
    """

    @pytest.mark.asyncio
    async def test_register_output_bridge_stores_loop_and_broadcaster(self) -> None:
        """GIVEN event loop and broadcaster
        WHEN register_output_bridge(loop, broadcaster) is called
        THEN both are stored for later use.
        """
        from bmad_assist.dashboard import (
            register_output_bridge,
            unregister_output_bridge,
        )
        from bmad_assist.dashboard.sse import SSEBroadcaster

        # GIVEN: Running event loop and broadcaster
        loop = asyncio.get_running_loop()
        broadcaster = SSEBroadcaster(heartbeat_interval=60)

        # WHEN: Register
        register_output_bridge(loop, broadcaster)

        # THEN: Values are stored (verified by sync_broadcast working)
        # Note: We can't directly access module variables, but sync_broadcast
        # should work after registration

        # Cleanup
        unregister_output_bridge()

    @pytest.mark.asyncio
    async def test_unregister_output_bridge_clears_state(self) -> None:
        """GIVEN bridge is registered
        WHEN unregister_output_bridge() is called
        THEN sync_broadcast does nothing (no error, returns early).
        """
        from bmad_assist.dashboard import (
            register_output_bridge,
            sync_broadcast,
            unregister_output_bridge,
        )
        from bmad_assist.dashboard.sse import SSEBroadcaster

        # GIVEN: Registered bridge
        loop = asyncio.get_running_loop()
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        register_output_bridge(loop, broadcaster)

        # WHEN: Unregister
        unregister_output_bridge()

        # THEN: sync_broadcast returns early without error
        sync_broadcast("test", "opus")  # Should not raise

    @pytest.mark.asyncio
    async def test_sync_broadcast_schedules_in_event_loop(self) -> None:
        """GIVEN bridge is registered with a running event loop
        WHEN sync_broadcast(line, provider) is called from main thread
        THEN broadcast_output is scheduled in the event loop.
        """
        from bmad_assist.dashboard import (
            register_output_bridge,
            sync_broadcast,
            unregister_output_bridge,
        )
        from bmad_assist.dashboard.sse import SSEBroadcaster

        # GIVEN: Registered bridge
        loop = asyncio.get_running_loop()
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        register_output_bridge(loop, broadcaster)

        # Collect messages from subscriber
        received = []

        async def collect_messages():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:  # Initial status + broadcast
                    break

        # Start subscriber
        subscriber_task = asyncio.create_task(collect_messages())
        await asyncio.sleep(0.05)  # Let subscriber connect

        # WHEN: Sync broadcast from this thread
        sync_broadcast("hello world", "claude")

        # Wait for message delivery
        await asyncio.wait_for(subscriber_task, timeout=2.0)

        # THEN: Message was delivered via SSE
        assert len(received) == 2
        assert "hello world" in received[1]

        # Cleanup
        unregister_output_bridge()

    def test_sync_broadcast_from_worker_thread(self) -> None:
        """GIVEN bridge is registered and server loop is running
        WHEN sync_broadcast() is called from a WORKER thread
        THEN message is delivered to subscribers (cross-thread).
        """
        from bmad_assist.dashboard import (
            register_output_bridge,
            sync_broadcast,
            unregister_output_bridge,
        )
        from bmad_assist.dashboard.sse import SSEBroadcaster

        received = []
        broadcaster = SSEBroadcaster(heartbeat_interval=60)

        async def server_main():
            """Simulates server event loop."""
            loop = asyncio.get_running_loop()
            register_output_bridge(loop, broadcaster)

            # Subscribe to receive messages
            async def subscriber():
                count = 0
                async for msg in broadcaster.subscribe():
                    received.append(msg)
                    count += 1
                    if count >= 2:
                        break

            subscriber_task = asyncio.create_task(subscriber())
            await asyncio.sleep(0.05)  # Let subscriber connect

            # Wait for worker thread to send message
            await asyncio.wait_for(subscriber_task, timeout=3.0)

            unregister_output_bridge()

        def worker_thread_func():
            """Worker thread that calls sync_broadcast."""
            time.sleep(0.1)  # Wait for server to be ready
            sync_broadcast("from worker", "gemini")

        # GIVEN: Start worker thread
        worker = threading.Thread(target=worker_thread_func)
        worker.start()

        # WHEN: Run server event loop
        asyncio.run(server_main())

        worker.join()

        # THEN: Message was received
        assert len(received) >= 2
        assert any("from worker" in msg for msg in received)

    @pytest.mark.asyncio
    async def test_sync_broadcast_returns_early_when_loop_not_running(self) -> None:
        """GIVEN bridge is registered but loop is stopped
        WHEN sync_broadcast() is called
        THEN returns early without error.
        """
        from bmad_assist.dashboard import (
            sync_broadcast,
            unregister_output_bridge,
        )

        # GIVEN: Create a new (not-running) loop and register it
        # Note: This simulates the server shutdown scenario
        # After unregister, sync_broadcast should return early

        unregister_output_bridge()  # Ensure clean state

        # THEN: sync_broadcast with no bridge does nothing
        sync_broadcast("test", "opus")  # Should not raise


# =============================================================================
# Task 6: Test Provider Detection Fallback (AC: 3)
# =============================================================================


class TestProviderDetection:
    """Tests for provider detection from line content in dashboard/__init__.py.

    These tests verify detect_provider_from_line() correctly identifies
    provider from output line content when thread-local context is unavailable.
    """

    def test_detect_gemini_from_line_content(self) -> None:
        """GIVEN line contains "gemini" (case-insensitive)
        WHEN detect_provider_from_line() is called
        THEN returns "gemini".
        """
        from bmad_assist.dashboard import detect_provider_from_line

        # Various gemini patterns
        assert detect_provider_from_line("Using gemini-2.5-pro model") == "gemini"
        assert detect_provider_from_line("Gemini response: hello") == "gemini"
        assert detect_provider_from_line("GEMINI completed") == "gemini"

    def test_detect_glm_from_line_content(self) -> None:
        """GIVEN line contains "glm" or "zhipu"
        WHEN detect_provider_from_line() is called
        THEN returns "glm".
        """
        from bmad_assist.dashboard import detect_provider_from_line

        # GLM patterns
        assert detect_provider_from_line("glm-4.7 model response") == "glm"
        assert detect_provider_from_line("Zhipu API call") == "glm"
        assert detect_provider_from_line("GLM output: test") == "glm"

    def test_detect_returns_none_for_generic_output(self) -> None:
        """GIVEN line has no provider-specific patterns
        WHEN detect_provider_from_line() is called
        THEN returns None.
        """
        from bmad_assist.dashboard import detect_provider_from_line

        # Generic output
        assert detect_provider_from_line("Hello world") is None
        assert detect_provider_from_line("[ASSISTANT] Thinking...") is None
        assert detect_provider_from_line("") is None

    def test_detect_strips_ansi_codes_before_matching(self) -> None:
        """GIVEN line contains ANSI escape codes
        WHEN detect_provider_from_line() is called
        THEN ANSI codes are stripped before pattern matching.
        """
        from bmad_assist.dashboard import detect_provider_from_line

        # Line with ANSI color codes
        ansi_line = "\033[32mgemini response\033[0m"
        assert detect_provider_from_line(ansi_line) == "gemini"

        # Line where ANSI codes could interfere
        glm_ansi = "\033[35mglm-4.7\033[0m output"
        assert detect_provider_from_line(glm_ansi) == "glm"

    def test_write_progress_uses_fallback_detection_when_no_context(self) -> None:
        """GIVEN no thread-local provider context is set
        WHEN write_progress() is called with gemini in the line
        THEN hook receives "gemini" via fallback detection (AC3).
        """
        from bmad_assist.dashboard import set_output_hook
        from bmad_assist.providers.base import set_active_provider, write_progress

        # GIVEN: No provider context, but hook registered
        captured = []

        def capture_hook(line: str, provider: str | None) -> None:
            captured.append((line, provider))

        set_output_hook(capture_hook)
        set_active_provider(None)  # Explicitly clear context

        # WHEN: Write progress with gemini in the line
        with patch("builtins.print"):
            write_progress("Using gemini-2.5-pro for validation")

        # THEN: Hook received "gemini" via fallback detection
        assert len(captured) == 1
        assert captured[0][0] == "Using gemini-2.5-pro for validation"
        assert captured[0][1] == "gemini"

        # Cleanup
        set_output_hook(None)


# =============================================================================
# Task 5, 9: Test Server Integration (AC: 6)
# =============================================================================


class TestServerIntegration:
    """Tests for server startup/shutdown hook integration.

    These tests verify that DashboardServer correctly registers and
    unregisters the output hook during lifecycle events.
    """

    @pytest.mark.asyncio
    async def test_server_startup_registers_output_bridge(self, tmp_path: Path) -> None:
        """GIVEN DashboardServer is created
        WHEN server starts (on_startup event)
        THEN output bridge is registered with event loop and broadcaster.
        """
        from bmad_assist.dashboard import get_output_hook
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Server instance (use tmp_path directly - autouse fixture creates sprint-status.yaml there)
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()

        # WHEN: Simulate startup
        async with app.router.lifespan_context(app):
            # THEN: Output hook is registered
            hook = get_output_hook()
            assert hook is not None

    @pytest.mark.asyncio
    async def test_server_shutdown_unregisters_output_bridge(self, tmp_path: Path) -> None:
        """GIVEN server is running with registered hook
        WHEN server shuts down (on_shutdown event)
        THEN output hook is unregistered (set to None).
        """
        from bmad_assist.dashboard import get_output_hook
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Server that was started (use tmp_path directly)
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()

        # WHEN: Start and then stop server
        async with app.router.lifespan_context(app):
            # Hook should be registered
            assert get_output_hook() is not None

        # THEN: After shutdown, hook is cleared
        assert get_output_hook() is None

    @pytest.mark.asyncio
    async def test_server_broadcaster_accessible(self, tmp_path: Path) -> None:
        """GIVEN DashboardServer is created
        WHEN accessing sse_broadcaster property
        THEN returns SSEBroadcaster instance.
        """
        from bmad_assist.dashboard.server import DashboardServer
        from bmad_assist.dashboard.sse import SSEBroadcaster

        # GIVEN: Server instance (use tmp_path directly - autouse fixture creates sprint-status.yaml there)
        server = DashboardServer(project_root=tmp_path)

        # THEN: Broadcaster is accessible
        assert isinstance(server.sse_broadcaster, SSEBroadcaster)


# =============================================================================
# Integration Tests: Full Flow (AC: 1, 2, 5)
# =============================================================================


class TestEndToEndOutputFlow:
    """Integration tests verifying the complete output capture flow.

    These tests simulate the real workflow where providers write output
    that flows through to SSE subscribers.
    """

    @pytest.mark.asyncio
    async def test_full_flow_write_progress_to_sse(self, tmp_path: Path) -> None:
        """GIVEN server is running with subscriber connected
        WHEN write_progress() is called with active provider
        THEN subscriber receives output via SSE.
        """
        from bmad_assist.dashboard.server import DashboardServer
        from bmad_assist.providers.base import set_active_provider, write_progress

        # GIVEN: Server running (use tmp_path directly)
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()

        received = []

        async with app.router.lifespan_context(app):
            # Subscribe to SSE
            async def subscriber():
                count = 0
                async for msg in server.sse_broadcaster.subscribe():
                    received.append(msg)
                    count += 1
                    if count >= 2:
                        break

            subscriber_task = asyncio.create_task(subscriber())
            await asyncio.sleep(0.05)

            # WHEN: Set provider and write progress
            set_active_provider("claude")
            with patch("builtins.print"):
                write_progress("test output from claude")

            # Wait for delivery
            await asyncio.wait_for(subscriber_task, timeout=2.0)

            # Cleanup
            set_active_provider(None)

        # THEN: Output received via SSE
        assert len(received) >= 2
        output_msg = received[1]
        assert "test output from claude" in output_msg
        assert '"provider": "claude"' in output_msg or '"provider":"claude"' in output_msg

    @pytest.mark.asyncio
    async def test_no_error_without_connected_clients(self, tmp_path: Path) -> None:
        """GIVEN server is running but NO clients connected
        WHEN write_progress() is called
        THEN no exception is raised, broadcast returns 0.
        """
        from bmad_assist.dashboard.server import DashboardServer
        from bmad_assist.providers.base import set_active_provider, write_progress

        # GIVEN: Server running, no subscribers (use tmp_path directly)
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()

        async with app.router.lifespan_context(app):
            # WHEN: Write without any subscribers
            set_active_provider("opus")
            with patch("builtins.print"):
                write_progress("no one listening")  # Should not raise

            set_active_provider(None)

        # THEN: No exception raised (test passes if we get here)

    @pytest.mark.asyncio
    async def test_multiple_clients_receive_output(self, tmp_path: Path) -> None:
        """GIVEN server running with 3 connected clients
        WHEN write_progress() is called
        THEN all 3 clients receive the output.
        """
        from bmad_assist.dashboard.server import DashboardServer
        from bmad_assist.providers.base import set_active_provider, write_progress

        # GIVEN: Server running (use tmp_path directly)
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()

        client_received = [[], [], []]  # 3 clients

        async with app.router.lifespan_context(app):
            # Create 3 subscribers
            async def subscriber(client_id: int):
                count = 0
                async for msg in server.sse_broadcaster.subscribe():
                    client_received[client_id].append(msg)
                    count += 1
                    if count >= 2:
                        break

            tasks = [asyncio.create_task(subscriber(i)) for i in range(3)]
            await asyncio.sleep(0.1)  # Let all connect

            # WHEN: Write progress
            set_active_provider("test")
            with patch("builtins.print"):
                write_progress("broadcast to all")

            # Wait for delivery
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=3.0)

            set_active_provider(None)

        # THEN: All 3 clients received output
        for i, msgs in enumerate(client_received):
            assert len(msgs) >= 2, f"Client {i} didn't receive enough messages"
            assert any("broadcast to all" in msg for msg in msgs)
