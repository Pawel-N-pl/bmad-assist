"""Tests for Token Bucket Rate Limiter.

This module tests the TokenBucketRateLimiter class which provides
token bucket rate limiting for LLM API calls.
"""

from __future__ import annotations

import asyncio

import pytest

from bmad_assist.deep_verify.infrastructure.rate_limiter import (
    NoOpRateLimiter,
    TokenBucketRateLimiter,
    create_rate_limiter,
)

# =============================================================================
# Tests for TokenBucketRateLimiter
# =============================================================================

class TestTokenBucketRateLimiter:
    """Test suite for TokenBucketRateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_immediate_when_tokens_available(self):
        """Test that acquire returns immediately when tokens available."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        # Acquire 100 tokens (should be immediate with 1000 capacity)
        wait_time = await limiter.acquire(100)

        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_tokens_exhausted(self):
        """Test that acquire waits when tokens are exhausted."""
        # Small bucket that will be exhausted quickly
        limiter = TokenBucketRateLimiter(tokens_per_minute=120)  # 2 tokens/sec

        # Exhaust the bucket
        await limiter.acquire(120)

        # Next acquire should need to wait
        start = asyncio.get_event_loop().time()
        wait_time = await limiter.acquire(2)  # Need 1 second to refill
        elapsed = asyncio.get_event_loop().time() - start

        assert wait_time > 0
        assert elapsed >= 0.9  # Should have waited ~1 second

    @pytest.mark.asyncio
    async def test_acquire_zero_tokens(self):
        """Test that acquiring zero tokens returns immediately."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        wait_time = await limiter.acquire(0)

        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_try_acquire_success(self):
        """Test that try_acquire returns True when tokens available."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        success = await limiter.try_acquire(100)

        assert success is True

    @pytest.mark.asyncio
    async def test_try_acquire_failure(self):
        """Test that try_acquire returns False when not enough tokens."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=100)

        # Exhaust all tokens
        await limiter.acquire(100)

        # Try to acquire more (should fail)
        success = await limiter.try_acquire(10)

        assert success is False

    @pytest.mark.asyncio
    async def test_try_acquire_zero_tokens(self):
        """Test that try_acquire with zero tokens always succeeds."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=100)

        # Exhaust all tokens
        await limiter.acquire(100)

        # Zero tokens should still succeed
        success = await limiter.try_acquire(0)

        assert success is True

    @pytest.mark.asyncio
    async def test_bucket_refills_over_time(self):
        """Test that bucket refills over time."""
        # 60 tokens per minute = 1 token per second
        limiter = TokenBucketRateLimiter(tokens_per_minute=60)

        # Exhaust all tokens
        await limiter.acquire(60)

        # Should fail immediately
        assert await limiter.try_acquire(1) is False

        # Wait for refill
        await asyncio.sleep(1.1)

        # Should succeed now
        assert await limiter.try_acquire(1) is True

    @pytest.mark.asyncio
    async def test_reset_restores_full_capacity(self):
        """Test that reset restores full token capacity."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=100)

        # Exhaust tokens
        await limiter.acquire(100)
        assert await limiter.try_acquire(1) is False

        # Reset
        await limiter.reset()

        # Should have full capacity again
        assert await limiter.try_acquire(100) is True

    def test_get_status(self):
        """Test that get_status returns current status."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        status = limiter.get_status()

        assert status.tokens_capacity == 1000
        assert status.tokens_available == 1000
        assert status.refill_rate_per_second == 1000 / 60.0
        assert status.last_refill_timestamp > 0

    @pytest.mark.asyncio
    async def test_status_updates_after_acquire(self):
        """Test that status updates after token acquisition."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        initial_status = limiter.get_status()
        assert initial_status.tokens_available == 1000

        await limiter.acquire(100)

        updated_status = limiter.get_status()
        # Use approx due to floating point and time-based refill
        assert updated_status.tokens_available == pytest.approx(900, abs=1.0)

    @pytest.mark.asyncio
    async def test_concurrent_acquires(self):
        """Test that concurrent acquires work correctly."""
        limiter = TokenBucketRateLimiter(tokens_per_minute=1000)

        # Run multiple acquires concurrently
        tasks = [limiter.acquire(100) for _ in range(5)]
        wait_times = await asyncio.gather(*tasks)

        # All should succeed immediately (500 tokens from 1000 capacity)
        assert all(w == 0.0 for w in wait_times)

        # Bucket should have approximately 500 left
        status = limiter.get_status()
        assert status.tokens_available == pytest.approx(500, abs=1.0)


# =============================================================================
# Tests for NoOpRateLimiter
# =============================================================================

class TestNoOpRateLimiter:
    """Test suite for NoOpRateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_always_zero(self):
        """Test that acquire always returns 0."""
        limiter = NoOpRateLimiter()

        wait_time = await limiter.acquire(1000000)

        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_try_acquire_always_true(self):
        """Test that try_acquire always returns True."""
        limiter = NoOpRateLimiter()

        success = await limiter.try_acquire(1000000)

        assert success is True

    def test_status_shows_unlimited(self):
        """Test that status shows unlimited capacity."""
        limiter = NoOpRateLimiter()

        status = limiter.get_status()

        assert status.tokens_available == float("inf")
        assert status.tokens_capacity == 0

    @pytest.mark.asyncio
    async def test_reset_does_nothing(self):
        """Test that reset does nothing."""
        limiter = NoOpRateLimiter()

        # Should not raise
        await limiter.reset()


# =============================================================================
# Tests for Factory Function
# =============================================================================

class TestCreateRateLimiter:
    """Test suite for create_rate_limiter factory."""

    def test_create_with_positive_limit(self):
        """Test creating rate limiter with positive limit."""
        limiter = create_rate_limiter(tokens_per_minute=1000)

        assert isinstance(limiter, TokenBucketRateLimiter)

    def test_create_with_none_returns_noop(self):
        """Test that None returns NoOpRateLimiter."""
        limiter = create_rate_limiter(tokens_per_minute=None)

        assert isinstance(limiter, NoOpRateLimiter)

    def test_create_with_zero_returns_noop(self):
        """Test that zero returns NoOpRateLimiter."""
        limiter = create_rate_limiter(tokens_per_minute=0)

        assert isinstance(limiter, NoOpRateLimiter)

    def test_create_with_negative_returns_noop(self):
        """Test that negative returns NoOpRateLimiter."""
        limiter = create_rate_limiter(tokens_per_minute=-100)

        assert isinstance(limiter, NoOpRateLimiter)


# =============================================================================
# Integration Tests
# =============================================================================

@pytest.mark.slow  # Real 5s wait for token refill
@pytest.mark.asyncio
async def test_rate_limiter_integration():
    """Integration test for rate limiter with realistic usage."""
    # 120 tokens per minute = 2 tokens per second
    limiter = TokenBucketRateLimiter(tokens_per_minute=120)

    # First 120 tokens should be immediate
    start = asyncio.get_event_loop().time()
    for _ in range(12):
        await limiter.acquire(10)
    elapsed = asyncio.get_event_loop().time() - start

    # Should complete quickly (no waiting)
    assert elapsed < 1.0

    # 13th acquisition should need to wait for refill
    start = asyncio.get_event_loop().time()
    await limiter.acquire(10)
    elapsed = asyncio.get_event_loop().time() - start

    # Should have waited ~5 seconds for 10 tokens at 2 tokens/sec
    assert elapsed >= 4.0
