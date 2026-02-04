"""Token bucket rate limiter for LLM API calls.

This module provides rate limiting to prevent API quota exhaustion during
parallel verification method execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from bmad_assist.deep_verify.infrastructure.types import RateLimitStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiter Implementation
# =============================================================================


@dataclass
class TokenBucketConfig:
    """Configuration for token bucket rate limiter.

    Attributes:
        tokens_per_minute: Maximum tokens per minute allowed.
        burst_size: Maximum tokens that can be consumed at once (bucket capacity).
                    Defaults to tokens_per_minute (allow full burst).

    """

    tokens_per_minute: int
    burst_size: int | None = None

    def __post_init__(self) -> None:
        """Set burst_size to tokens_per_minute if not specified."""
        if self.burst_size is None:
            self.burst_size = self.tokens_per_minute


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls.

    Maintains a bucket of tokens that refills at a constant rate.
    Each API call consumes tokens based on input + output token count.

    The token bucket algorithm:
    1. Calculate tokens to add based on time elapsed since last call
    2. Cap tokens at bucket capacity
    3. If request_tokens <= available_tokens: allow and deduct
    4. If request_tokens > available_tokens: wait for tokens to refill

    This implementation is async-safe using asyncio.Lock.

    Example:
        >>> limiter = TokenBucketRateLimiter(tokens_per_minute=100000)
        >>> # Acquire 1000 tokens (will wait if not available)
        >>> wait_time = await limiter.acquire(1000)
        >>> if wait_time > 0:
        ...     print(f"Rate limited, waited {wait_time:.2f}s")

    """

    def __init__(self, tokens_per_minute: int):
        """Initialize the rate limiter.

        Args:
            tokens_per_minute: Maximum tokens per minute allowed.

        """
        self._capacity = tokens_per_minute
        self._refill_rate = tokens_per_minute / 60.0  # tokens per second
        self._tokens = float(tokens_per_minute)  # Start with full bucket
        self._last_refill = time.monotonic()
        # Lazy lock initialization - created on first use in current event loop
        # This prevents "Lock bound to different event loop" errors when used
        # across multiple loops (e.g., via run_async_in_thread())
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

        logger.debug(
            "TokenBucketRateLimiter initialized: capacity=%d, refill_rate=%.2f tokens/sec",
            self._capacity,
            self._refill_rate,
        )

    def _get_lock(self) -> asyncio.Lock:
        """Get or create lock for current event loop.

        Creates a new lock if called from a different event loop than before.
        This handles cases where the rate limiter is used across multiple
        event loops (e.g., via run_async_in_thread()).
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - create lock anyway, will work when loop starts
            if self._lock is None:
                self._lock = asyncio.Lock()
            return self._lock

        if self._lock is None or self._lock_loop is not current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop

        return self._lock

    def _refill(self) -> None:
        """Refill tokens based on elapsed time.

        This method is NOT thread-safe and should only be called
        while holding the lock.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self._refill_rate

        self._tokens = min(self._capacity, self._tokens + tokens_to_add)
        self._last_refill = now

        logger.debug(
            "Token bucket refilled: +%.2f tokens, current=%.2f/%d",
            tokens_to_add,
            self._tokens,
            self._capacity,
        )

    async def acquire(self, tokens_needed: int) -> float:
        """Acquire tokens, waiting if necessary.

        Args:
            tokens_needed: Number of tokens to acquire.

        Returns:
            Time waited in seconds.

        Note:
            This method will block (async wait) until the required
            tokens are available. It does not raise an error if rate
            limit is exceeded.

        """
        if tokens_needed <= 0:
            return 0.0

        async with self._get_lock():
            self._refill()

            if tokens_needed <= self._tokens:
                # Sufficient tokens available
                self._tokens -= tokens_needed
                logger.debug(
                    "Tokens acquired immediately: needed=%d, remaining=%.2f",
                    tokens_needed,
                    self._tokens,
                )
                return 0.0

            # Need to wait for tokens to refill
            deficit = tokens_needed - self._tokens
            wait_time = deficit / self._refill_rate

            logger.info(
                "Rate limit reached: need %d tokens, have %.2f, deficit=%.2f, wait=%.2fs",
                tokens_needed,
                self._tokens,
                deficit,
                wait_time,
            )

        # Release lock while sleeping
        await asyncio.sleep(wait_time)

        # Re-acquire lock and deduct tokens
        async with self._get_lock():
            self._refill()
            self._tokens -= tokens_needed
            remaining = self._tokens

        logger.info(
            "Tokens acquired after wait: waited=%.2fs, needed=%d, remaining=%.2f",
            wait_time,
            tokens_needed,
            remaining,
        )

        return wait_time

    async def try_acquire(self, tokens_needed: int) -> bool:
        """Try to acquire tokens without waiting.

        Args:
            tokens_needed: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False if not enough available.

        """
        if tokens_needed <= 0:
            return True

        async with self._get_lock():
            self._refill()

            if tokens_needed <= self._tokens:
                self._tokens -= tokens_needed
                return True

            return False

    def get_status(self) -> RateLimitStatus:
        """Get current rate limiter status.

        Returns:
            RateLimitStatus with current token counts.

        """
        # Note: This is a best-effort snapshot without locking
        elapsed = time.monotonic() - self._last_refill
        tokens_available = min(self._capacity, self._tokens + elapsed * self._refill_rate)

        return RateLimitStatus(
            tokens_available=tokens_available,
            tokens_capacity=self._capacity,
            refill_rate_per_second=self._refill_rate,
            last_refill_timestamp=self._last_refill,
        )

    async def reset(self) -> None:
        """Reset the token bucket to full capacity."""
        async with self._get_lock():
            self._tokens = float(self._capacity)
            self._last_refill = time.monotonic()
            logger.debug("Token bucket reset to full capacity: %d tokens", self._capacity)


class NoOpRateLimiter:
    """No-op rate limiter that always allows requests.

    Use this when rate limiting is disabled but you still need
    the same interface.
    """

    async def acquire(self, tokens_needed: int) -> float:
        """Always returns immediately with 0 wait time."""
        return 0.0

    async def try_acquire(self, tokens_needed: int) -> bool:
        """Always returns True."""
        return True

    def get_status(self) -> RateLimitStatus:
        """Returns status with unlimited capacity."""
        return RateLimitStatus(
            tokens_available=float("inf"),
            tokens_capacity=0,
            refill_rate_per_second=float("inf"),
            last_refill_timestamp=time.monotonic(),
        )

    async def reset(self) -> None:
        """No-op."""
        pass


# =============================================================================
# Factory Function
# =============================================================================


def create_rate_limiter(tokens_per_minute: int | None) -> TokenBucketRateLimiter | NoOpRateLimiter:
    """Create appropriate rate limiter based on configuration.

    Args:
        tokens_per_minute: Tokens per minute limit, or None to disable.

    Returns:
        TokenBucketRateLimiter if tokens_per_minute is set,
        NoOpRateLimiter otherwise.

    Example:
        >>> limiter = create_rate_limiter(tokens_per_minute=100000)
        >>> limiter = create_rate_limiter(tokens_per_minute=None)  # No-op

    """
    if tokens_per_minute is None or tokens_per_minute <= 0:
        logger.debug("Rate limiting disabled (no token limit configured)")
        return NoOpRateLimiter()

    logger.debug("Rate limiting enabled: %d tokens/minute", tokens_per_minute)
    return TokenBucketRateLimiter(tokens_per_minute)
