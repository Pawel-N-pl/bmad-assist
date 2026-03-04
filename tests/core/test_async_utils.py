"""Tests for bmad_assist.core.async_utils module."""

import asyncio
import logging
import threading

import pytest

from bmad_assist.core.async_utils import (
    _run_coro_in_new_loop,
    run_async_in_thread,
    run_async_with_timeout,
)


# --- Helpers ---


async def async_return(value):
    """Simple coroutine that returns a value."""
    return value


async def async_add(a, b):
    """Coroutine that adds two numbers."""
    return a + b


async def async_raise(exc):
    """Coroutine that raises an exception."""
    raise exc


async def async_get_thread_id():
    """Coroutine that returns the current thread ID."""
    return threading.current_thread().ident


# --- Tests for _run_coro_in_new_loop ---


class TestRunCoroInNewLoop:
    """Tests for the internal _run_coro_in_new_loop helper."""

    def test_returns_coroutine_result(self):
        result = _run_coro_in_new_loop(async_return(42))
        assert result == 42

    def test_propagates_exception(self):
        with pytest.raises(ValueError, match="test error"):
            _run_coro_in_new_loop(async_raise(ValueError("test error")))

    def test_cleans_up_event_loop(self):
        """After running, no event loop should be set for this thread."""
        _run_coro_in_new_loop(async_return(1))
        # Should raise RuntimeError because no loop is set
        with pytest.raises(RuntimeError):
            asyncio.get_event_loop()


# --- Tests for run_async_in_thread ---


class TestRunAsyncInThread:
    """Tests for run_async_in_thread."""

    def test_returns_result_no_running_loop(self):
        """Works when no event loop is running (normal case)."""
        result = run_async_in_thread(async_return("hello"))
        assert result == "hello"

    def test_propagates_exception_no_running_loop(self):
        with pytest.raises(RuntimeError, match="boom"):
            run_async_in_thread(async_raise(RuntimeError("boom")))

    def test_works_inside_running_event_loop(self):
        """The nested-loop case: calling from sync code within an async function."""

        async def outer():
            # Simulate sync code called from async context
            def sync_bridge():
                return run_async_in_thread(async_return(99))

            return sync_bridge()

        result = asyncio.run(outer())
        assert result == 99

    def test_nested_loop_runs_in_different_thread(self):
        """When nested, the coroutine should run in a separate thread."""
        main_thread_id = threading.current_thread().ident

        async def outer():
            def sync_bridge():
                return run_async_in_thread(async_get_thread_id())

            return sync_bridge()

        coro_thread_id = asyncio.run(outer())
        assert coro_thread_id != main_thread_id

    def test_nested_loop_propagates_exception(self):
        """Exceptions from the nested-loop path should propagate correctly."""

        async def outer():
            def sync_bridge():
                return run_async_in_thread(async_raise(ValueError("nested error")))

            return sync_bridge()

        with pytest.raises(ValueError, match="nested error"):
            asyncio.run(outer())

    def test_nested_loop_logs_debug_message(self, caplog):
        """Should log a debug message when detecting a running loop."""

        async def outer():
            def sync_bridge():
                return run_async_in_thread(async_return(1))

            return sync_bridge()

        with caplog.at_level(logging.DEBUG, logger="bmad_assist.core.async_utils"):
            asyncio.run(outer())

        assert any("running loop detected" in r.message for r in caplog.records)

    def test_works_from_asyncio_to_thread(self):
        """The intended use case: called from within asyncio.to_thread()."""

        async def main():
            def sync_fn():
                return run_async_in_thread(async_add(3, 4))

            return await asyncio.to_thread(sync_fn)

        result = asyncio.run(main())
        assert result == 7


# --- Tests for run_async_with_timeout ---


class TestRunAsyncWithTimeout:
    """Tests for run_async_with_timeout."""

    def test_returns_result(self):
        result = run_async_with_timeout(async_return("ok"))
        assert result == "ok"

    def test_propagates_exception(self):
        with pytest.raises(TypeError, match="type error"):
            run_async_with_timeout(async_raise(TypeError("type error")))
