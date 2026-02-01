"""Async utility functions shared across modules."""

import asyncio
from typing import Any, Coroutine


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
