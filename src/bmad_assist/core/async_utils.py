"""Async utility functions shared across modules."""

import asyncio
import concurrent.futures
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _run_coro_in_new_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in a fresh event loop on the current thread.

    Internal helper that creates a new event loop, runs the coroutine,
    and cleans up. Does not shutdown any executor (avoids hangs).

    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def run_async_in_thread(coro: Coroutine[Any, Any, T]) -> T:
    """Run async code in a thread without any executor shutdown.

    CRITICAL: Use this instead of asyncio.run() when running async code from
    within a thread spawned by asyncio.to_thread() or run_in_executor().

    Unlike asyncio.run(), this function:
    - Creates a NEW event loop (not reusing any existing loop)
    - Sets the loop as the current loop for this thread
    - Does NOT shutdown any executor (avoids hangs)
    - Just closes the local event loop

    If called from a thread that already has a running event loop (e.g.,
    synchronous code called directly from an async function), this function
    spawns a new thread to avoid the "Cannot run the event loop while another
    loop is running" error.

    This prevents hangs from nested asyncio.run() calls.

    Args:
        coro: Coroutine to execute.

    Returns:
        Result of the coroutine.

    """
    # Check if there's already a running event loop on this thread
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to create one directly on this thread
        return _run_coro_in_new_loop(coro)

    # Already in an event loop - spawn a separate thread to avoid
    # "Cannot run the event loop while another loop is running"
    logger.debug(
        "run_async_in_thread: running loop detected, delegating to new thread"
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_coro_in_new_loop, coro)
        return future.result()


def run_async_with_timeout(coro: Coroutine[Any, Any, T], executor_timeout: float = 10.0) -> T:
    """Run async code like asyncio.run() but with timeout on executor shutdown.

    This is a replacement for asyncio.run() that prevents hanging when
    executor threads don't terminate cleanly. Use this for top-level
    async entry points (handlers) where hanging on shutdown is unacceptable.

    Args:
        coro: Coroutine to execute.
        executor_timeout: Timeout in seconds for executor shutdown. Default 10s.

    Returns:
        Result of the coroutine.

    Raises:
        Same exceptions as the coroutine.

    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        with contextlib.suppress(Exception):
            # Cleanup async generators
            loop.run_until_complete(loop.shutdown_asyncgens())

        try:
            # Shutdown executor with timeout to prevent hanging
            loop.run_until_complete(
                asyncio.wait_for(
                    loop.shutdown_default_executor(),
                    timeout=executor_timeout,
                )
            )
        except TimeoutError:
            logger.warning(
                "Executor shutdown timed out after %.1fs - some threads may still be running",
                executor_timeout,
            )
        except Exception as e:
            logger.debug("Executor shutdown error (ignored): %s", e)

        asyncio.set_event_loop(None)
        loop.close()


async def delayed_invoke(delay: float, coro: Coroutine[Any, Any, Any]) -> Any:
    """Execute coroutine after a delay.

    Used for staggered parallel execution to avoid rate limits.

    Args:
        delay: Seconds to wait before execution.
        coro: Coroutine to execute.

    Returns:
        Result of the coroutine.

    """
    if delay > 0:
        await asyncio.sleep(delay)
    return await coro
