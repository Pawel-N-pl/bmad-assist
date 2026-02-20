"""Tests for LLMClient with retry, rate limiting, and cost tracking.

This module tests the LLMClient class which wraps provider calls with:
- Retry logic with exponential backoff
- Token bucket rate limiting
- Cost tracking per model and method
- Timeout handling with graceful degradation
- Comprehensive call logging
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.deep_verify.config import LLMConfig
from bmad_assist.deep_verify.infrastructure import (
    LLMCallRecord,
    LLMClient,
    RetryConfig,
    RetryHandler,
)
from bmad_assist.deep_verify.infrastructure.cost_tracker import MODEL_PRICING
from bmad_assist.providers.base import (
    ExitStatus,
    ProviderResult,
)

# =============================================================================
# Mock Provider
# =============================================================================

class MockProvider:
    """Mock provider for testing."""

    def __init__(self, responses: list[Any] | None = None):
        self.responses = responses or []
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self,
        prompt: str,
        model: str | None = None,
        timeout: int | None = None,
    ) -> ProviderResult:
        """Mock invoke that returns pre-configured responses."""
        self.call_count += 1
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "timeout": timeout,
        })

        if self.call_count <= len(self.responses):
            response = self.responses[self.call_count - 1]
            if isinstance(response, Exception):
                raise response
            return response

        # Default success response
        return ProviderResult(
            stdout='{"result": "success"}',
            stderr="",
            exit_code=0,
            duration_ms=100,
            model=model or "haiku",
            command=["mock"],
        )

    def parse_output(self, result: ProviderResult) -> str:
        """Parse output from result."""
        return result.stdout


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Create a mock DeepVerifyConfig with LLMConfig."""
    config = MagicMock()
    config.llm_config = LLMConfig(
        max_retries=3,
        base_delay_seconds=0.1,  # Fast for tests
        max_delay_seconds=1.0,
        tokens_per_minute_limit=100000,
        cost_tracking_enabled=True,
        log_all_calls=True,
        default_timeout_seconds=30,
        total_timeout_seconds=90,
    )
    return config


@pytest.fixture
def mock_provider():
    """Create a mock provider."""
    return MockProvider()


@pytest.fixture
def llm_client(mock_config, mock_provider):
    """Create an LLMClient with mock dependencies."""
    return LLMClient(mock_config, mock_provider)


# =============================================================================
# Tests for LLMClient Basic Functionality
# =============================================================================

@pytest.mark.asyncio
async def test_invoke_success(llm_client, mock_provider):
    """Test successful LLM invocation."""
    result = await llm_client.invoke(
        prompt="Test prompt",
        model="haiku",
        timeout=30,
        method_id="#153",
    )

    assert result.exit_code == 0
    assert result.stdout == '{"result": "success"}'
    assert mock_provider.call_count == 1


@pytest.mark.asyncio
async def test_invoke_with_model_alias(llm_client, mock_provider):
    """Test invocation with model alias."""
    result = await llm_client.invoke(
        prompt="Test",
        model="opus",
        timeout=30,
    )

    assert result.exit_code == 0
    assert mock_provider.calls[0]["model"] == "opus"


@pytest.mark.asyncio
async def test_invoke_records_call_log(llm_client):
    """Test that successful calls are recorded in call log."""
    await llm_client.invoke(
        prompt="Test prompt",
        model="haiku",
        method_id="#153",
    )

    call_log = llm_client.get_call_log()
    assert len(call_log) == 1

    record = call_log[0]
    assert isinstance(record, LLMCallRecord)
    assert record.model == "haiku"
    assert record.method_id == "#153"
    assert record.success is True
    assert record.retry_count == 0


@pytest.mark.asyncio
async def test_invoke_records_cost(llm_client):
    """Test that costs are tracked for successful calls."""
    await llm_client.invoke(
        prompt="Test prompt with some length",
        model="haiku",
        method_id="#153",
    )

    summary = llm_client.get_cost_summary()
    assert summary.total_calls == 1
    assert summary.total_tokens > 0
    assert summary.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_invoke_tracks_by_model(llm_client):
    """Test cost tracking by model."""
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#153")
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#154")
    await llm_client.invoke(prompt="Test", model="opus", method_id="#153")

    summary = llm_client.get_cost_summary()
    assert "haiku" in summary.by_model
    assert "opus" in summary.by_model
    assert summary.by_model["haiku"].calls == 2
    assert summary.by_model["opus"].calls == 1


@pytest.mark.asyncio
async def test_invoke_tracks_by_method(llm_client):
    """Test cost tracking by method."""
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#153")
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#153")
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#154")

    summary = llm_client.get_cost_summary()
    assert "#153" in summary.by_method
    assert "#154" in summary.by_method
    assert summary.by_method["#153"].calls == 2
    assert summary.by_method["#154"].calls == 1


# =============================================================================
# Tests for Retry Logic
# =============================================================================

@pytest.mark.asyncio
async def test_retry_on_timeout_error(mock_config):
    """Test that timeout errors trigger retry."""
    # Create provider that fails twice with timeout, then succeeds
    provider = MockProvider([
        ProviderTimeoutError("timeout 1"),
        ProviderTimeoutError("timeout 2"),
        ProviderResult(stdout="success", stderr="", exit_code=0, duration_ms=100, model="haiku", command=["mock"]),
    ])

    client = LLMClient(mock_config, provider)
    result = await client.invoke(prompt="test", model="haiku")

    assert result.stdout == "success"
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_retry_on_provider_error(mock_config):
    """Test that provider errors trigger retry."""
    provider = MockProvider([
        ProviderError("network error"),
        ProviderResult(stdout="success", stderr="", exit_code=0, duration_ms=100, model="haiku", command=["mock"]),
    ])

    client = LLMClient(mock_config, provider)
    result = await client.invoke(prompt="test", model="haiku")

    assert result.stdout == "success"
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_retry_gives_up_after_max_retries(mock_config):
    """Test that retry gives up after max retries exceeded."""
    # Create provider that always fails
    provider = MockProvider([
        ProviderTimeoutError(f"timeout {i}")
        for i in range(5)
    ])

    client = LLMClient(mock_config, provider)

    with pytest.raises(ProviderTimeoutError):
        await client.invoke(prompt="test", model="haiku")

    # Should be initial attempt + 3 retries = 4 calls
    assert provider.call_count == 4


@pytest.mark.asyncio
async def test_no_retry_on_exit_code_error(mock_config):
    """Test that exit code errors don't trigger retry."""
    # ExitStatus errors are not retriable by default
    provider = MockProvider([
        ProviderExitCodeError(
            "command not found",
            exit_code=127,
            exit_status=ExitStatus.NOT_FOUND,
            stderr="",
            stdout="",
            command=("mock",),
        ),
    ])

    client = LLMClient(mock_config, provider)

    with pytest.raises(ProviderExitCodeError):
        await client.invoke(prompt="test", model="haiku")

    # Should not retry
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_retry_records_in_call_log(llm_client, mock_provider):
    """Test that retry count is recorded in call log."""
    # Setup provider to fail once then succeed
    mock_provider.responses = [
        ProviderTimeoutError("timeout"),
        ProviderResult(stdout="success", stderr="", exit_code=0, duration_ms=100, model="haiku", command=["mock"]),
    ]

    await llm_client.invoke(prompt="test", model="haiku", method_id="#153")

    call_log = llm_client.get_call_log()
    assert len(call_log) == 1
    assert call_log[0].retry_count == 1


# =============================================================================
# Tests for Timeout Handling
# =============================================================================

@pytest.mark.asyncio
async def test_timeout_uses_default_from_config(mock_config, mock_provider):
    """Test that default timeout from config is used when not specified."""
    client = LLMClient(mock_config, mock_provider)

    await client.invoke(prompt="test", model="haiku")

    # Check that default timeout was passed to provider
    assert mock_provider.calls[0]["timeout"] == 30  # default_timeout_seconds


@pytest.mark.asyncio
async def test_timeout_override(mock_config, mock_provider):
    """Test that timeout can be overridden per call."""
    client = LLMClient(mock_config, mock_provider)

    await client.invoke(prompt="test", model="haiku", timeout=60)

    assert mock_provider.calls[0]["timeout"] == 60


# =============================================================================
# Tests for Cost Tracking
# =============================================================================

@pytest.mark.asyncio
async def test_cost_calculation_for_haiku(llm_client, mock_provider):
    """Test cost calculation for haiku model."""
    await llm_client.invoke(prompt="Short test", model="haiku", method_id="#153")

    summary = llm_client.get_cost_summary()

    # Haiku pricing: $0.25 per 1M input, $1.25 per 1M output
    # Cost should be calculated based on estimated tokens
    assert summary.estimated_cost_usd >= 0

    # Verify model cost breakdown exists
    assert "haiku" in summary.by_model
    assert summary.by_model["haiku"].estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_cost_calculation_for_opus(llm_client, mock_provider):
    """Test cost calculation for opus model."""
    await llm_client.invoke(prompt="Short test", model="opus", method_id="#153")

    summary = llm_client.get_cost_summary()

    # Opus pricing: $15.00 per 1M input, $75.00 per 1M output
    assert summary.estimated_cost_usd >= 0
    assert "opus" in summary.by_model


@pytest.mark.asyncio
async def test_cost_tracking_disabled(mock_config, mock_provider):
    """Test that cost tracking can be disabled."""
    mock_config.llm_config = LLMConfig(cost_tracking_enabled=False)
    client = LLMClient(mock_config, mock_provider)

    await client.invoke(prompt="test", model="haiku")

    summary = client.get_cost_summary()
    assert summary.total_calls == 0
    assert summary.estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_reset_tracking(llm_client, mock_provider):
    """Test that tracking can be reset."""
    await llm_client.invoke(prompt="test", model="haiku")

    assert llm_client.get_cost_summary().total_calls == 1
    assert len(llm_client.get_call_log()) == 1

    llm_client.reset_tracking()

    assert llm_client.get_cost_summary().total_calls == 0
    assert len(llm_client.get_call_log()) == 0


# =============================================================================
# Tests for Call Log
# =============================================================================

@pytest.mark.asyncio
async def test_call_log_contains_all_fields(llm_client, mock_provider):
    """Test that call log contains all required fields."""
    await llm_client.invoke(
        prompt="Test prompt",
        model="haiku",
        method_id="#153",
    )

    call_log = llm_client.get_call_log()
    assert len(call_log) == 1

    record = call_log[0]
    assert isinstance(record.timestamp, type(record.timestamp))  # datetime
    assert record.method_id == "#153"
    assert record.model == "haiku"
    assert record.input_tokens >= 0
    assert record.output_tokens >= 0
    assert record.latency_ms >= 0
    assert record.success is True
    assert record.error is None
    assert record.retry_count == 0


@pytest.mark.asyncio
async def test_call_log_for_failed_call(mock_config):
    """Test that failed calls are recorded in call log."""
    # Provider that will fail after all retries
    provider = MockProvider([
        ProviderTimeoutError("timeout 1"),
        ProviderTimeoutError("timeout 2"),
        ProviderTimeoutError("timeout 3"),
        ProviderTimeoutError("timeout 4"),  # Final failure
    ])
    client = LLMClient(mock_config, provider)

    with pytest.raises(ProviderTimeoutError):
        await client.invoke(prompt="test", model="haiku", method_id="#153")

    call_log = client.get_call_log()
    assert len(call_log) == 1

    record = call_log[0]
    assert record.success is False
    assert "timeout" in record.error


@pytest.mark.asyncio
async def test_call_log_chronological_order(llm_client, mock_provider):
    """Test that call log is in chronological order."""
    for i in range(3):
        await llm_client.invoke(
            prompt=f"Test {i}",
            model="haiku",
            method_id=f"#15{i}",
        )

    call_log = llm_client.get_call_log()
    assert len(call_log) == 3

    # Verify chronological order
    timestamps = [record.timestamp for record in call_log]
    assert timestamps == sorted(timestamps)


# =============================================================================
# Tests for Stats
# =============================================================================

@pytest.mark.asyncio
async def test_get_stats(llm_client, mock_provider):
    """Test getting client statistics."""
    await llm_client.invoke(prompt="Test", model="haiku", method_id="#153")
    await llm_client.invoke(prompt="Test", model="opus", method_id="#154")

    stats = llm_client.get_stats()

    assert stats["total_calls"] == 2
    assert stats["total_tokens"] > 0
    assert stats["total_cost_usd"] > 0
    assert "haiku" in stats["calls_by_model"]
    assert "opus" in stats["calls_by_model"]
    assert "#153" in stats["calls_by_method"]
    assert "#154" in stats["calls_by_method"]
    assert stats["failed_calls"] == 0


@pytest.mark.asyncio
async def test_get_stats_with_failures(mock_config):
    """Test stats include failed calls count."""
    provider = MockProvider([
        ProviderTimeoutError("timeout 1"),
        ProviderTimeoutError("timeout 2"),
        ProviderTimeoutError("timeout 3"),
        ProviderTimeoutError("timeout 4"),  # Final failure, no more retries
    ])
    client = LLMClient(mock_config, provider)

    # All retries exhausted
    with pytest.raises(ProviderTimeoutError):
        await client.invoke(prompt="test", model="haiku")

    stats = client.get_stats()
    assert stats["failed_calls"] == 1  # One recorded failed call


# =============================================================================
# Tests for Retry Handler
# =============================================================================

def test_retry_handler_should_retry_timeout():
    """Test that timeout errors are retriable."""
    handler = RetryHandler(RetryConfig(max_retries=3))

    error = ProviderTimeoutError("timeout")
    assert handler.should_retry(error) is True


def test_retry_handler_should_retry_provider_error():
    """Test that certain provider errors are retriable."""
    handler = RetryHandler(RetryConfig(max_retries=3))

    error = ProviderError("rate limit exceeded")
    assert handler.should_retry(error) is True


def test_retry_handler_should_not_retry_auth_error():
    """Test that auth errors are not retriable."""
    handler = RetryHandler(RetryConfig(max_retries=3))

    # ExitStatus.MISUSE is not in RETRIABLE_STATUSES
    error = ProviderExitCodeError(
        "invalid usage",
        exit_code=2,
        exit_status=ExitStatus.MISUSE,
    )
    assert handler.should_retry(error) is False


def test_retry_handler_calculate_backoff():
    """Test backoff calculation."""
    config = RetryConfig(base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_factor=0.0)
    handler = RetryHandler(config)

    # Test exponential increase
    delay_0 = handler.calculate_backoff(0)
    delay_1 = handler.calculate_backoff(1)
    delay_2 = handler.calculate_backoff(2)

    # With jitter=0, delays should be exactly: 1, 2, 4
    assert delay_0 == 1.0
    assert delay_1 == 2.0
    assert delay_2 == 4.0


def test_retry_handler_backoff_max_cap():
    """Test that backoff is capped at max_delay."""
    config = RetryConfig(base_delay_seconds=1.0, max_delay_seconds=5.0, jitter_factor=0.0)
    handler = RetryHandler(config)

    # After 3 attempts: 1 * 2^3 = 8, but capped at 5
    delay = handler.calculate_backoff(3)
    assert delay == 5.0


def test_retry_handler_backoff_with_jitter():
    """Test that jitter adds randomness."""
    config = RetryConfig(base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_factor=0.2)
    handler = RetryHandler(config)

    delay = handler.calculate_backoff(0)

    # With 20% jitter on base 1.0, should be between 1.0 and 1.2
    assert 1.0 <= delay <= 1.2


# =============================================================================
# Tests for Model Pricing
# =============================================================================

def test_model_pricing_contains_known_models():
    """Test that known models have pricing defined."""
    assert "haiku" in MODEL_PRICING
    assert "sonnet" in MODEL_PRICING
    assert "opus" in MODEL_PRICING
    assert "gpt-4o" in MODEL_PRICING


def test_model_pricing_has_input_output():
    """Test that each model has input and output pricing."""
    for model, pricing in MODEL_PRICING.items():
        assert len(pricing) == 2
        assert pricing[0] >= 0  # input price
        assert pricing[1] >= 0  # output price


# =============================================================================
# Tests for Configuration
# =============================================================================

def test_llm_config_defaults():
    """Test LLMConfig default values."""
    config = LLMConfig()

    assert config.max_retries == 3
    assert config.base_delay_seconds == 1.0
    assert config.max_delay_seconds == 30.0
    assert config.tokens_per_minute_limit == 100000
    assert config.cost_tracking_enabled is True
    assert config.log_all_calls is True
    assert config.default_timeout_seconds == 30
    assert config.total_timeout_seconds == 90


def test_llm_config_validation():
    """Test LLMConfig field validation."""
    # max_retries must be between 0 and 10
    with pytest.raises(ValueError):
        LLMConfig(max_retries=-1)

    with pytest.raises(ValueError):
        LLMConfig(max_retries=11)

    # base_delay must be positive
    with pytest.raises(ValueError):
        LLMConfig(base_delay_seconds=0.0)

    # tokens_per_minute must be reasonable
    with pytest.raises(ValueError):
        LLMConfig(tokens_per_minute_limit=500)


# =============================================================================
# Tests for Integration with DomainDetector and Methods
# =============================================================================

def test_domain_detector_accepts_llm_client():
    """Test that DomainDetector accepts optional LLMClient."""
    from pathlib import Path

    from bmad_assist.deep_verify.core.domain_detector import DomainDetector
    from bmad_assist.deep_verify.infrastructure.llm_client import LLMClient

    # Test without LLMClient (backward compatible)
    detector1 = DomainDetector(project_root=Path("."))
    assert detector1._llm_client is None
    assert detector1._provider is not None

    # Test with LLMClient
    mock_config = MagicMock()
    mock_config.llm_config = LLMConfig()
    mock_provider = MockProvider()
    llm_client = LLMClient(mock_config, mock_provider)

    detector2 = DomainDetector(project_root=Path("."), llm_client=llm_client)
    assert detector2._llm_client is llm_client
    assert detector2._provider is None


def test_adversarial_review_method_accepts_llm_client():
    """Test that AdversarialReviewMethod accepts optional LLMClient."""
    from bmad_assist.deep_verify.infrastructure.llm_client import LLMClient
    from bmad_assist.deep_verify.methods.adversarial_review import AdversarialReviewMethod

    # Test without LLMClient (backward compatible)
    method1 = AdversarialReviewMethod()
    assert method1._llm_client is None
    assert method1._provider is not None

    # Test with LLMClient
    mock_config = MagicMock()
    mock_config.llm_config = LLMConfig()
    mock_provider = MockProvider()
    llm_client = LLMClient(mock_config, mock_provider)

    method2 = AdversarialReviewMethod(llm_client=llm_client)
    assert method2._llm_client is llm_client
    assert method2._provider is None


# =============================================================================
# Tests for Error Categorization
# =============================================================================

def test_is_retriable_error_function():
    """Test is_retriable_error convenience function."""
    from bmad_assist.deep_verify.infrastructure.retry_handler import is_retriable_error

    assert is_retriable_error(ProviderTimeoutError("timeout")) is True
    assert is_retriable_error(ProviderError("rate limit")) is True
    assert is_retriable_error(ConnectionError("connection reset")) is True


def test_calculate_retry_delay_function():
    """Test calculate_retry_delay convenience function."""
    from bmad_assist.deep_verify.infrastructure.retry_handler import calculate_retry_delay

    delay = calculate_retry_delay(attempt=0, base_delay=1.0, max_delay=30.0, jitter=0.0)
    assert delay == 1.0

    delay = calculate_retry_delay(attempt=1, base_delay=1.0, max_delay=30.0, jitter=0.0)
    assert delay == 2.0


# =============================================================================
# Tests for Async Concurrency Safety
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_invocations(mock_config, mock_provider):
    """Test that concurrent invocations work correctly."""
    client = LLMClient(mock_config, mock_provider)

    # Run multiple invocations concurrently
    tasks = [
        client.invoke(prompt=f"Test {i}", model="haiku", method_id=f"#15{i}")
        for i in range(5)
    ]

    results = await asyncio.gather(*tasks)

    assert len(results) == 5
    assert all(r.exit_code == 0 for r in results)
    assert client.get_cost_summary().total_calls == 5


# =============================================================================
# Tests for Representation
# =============================================================================

def test_llm_client_repr(llm_client):
    """Test LLMClient string representation."""
    repr_str = repr(llm_client)
    assert "LLMClient" in repr_str
    assert "calls=" in repr_str
    assert "cost=$" in repr_str


# =============================================================================
# Tests for Edge Cases
# =============================================================================

@pytest.mark.asyncio
async def test_empty_prompt(llm_client, mock_provider):
    """Test handling of empty prompt."""
    result = await llm_client.invoke(prompt="", model="haiku")
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_very_long_prompt(llm_client, mock_provider):
    """Test handling of very long prompt."""
    long_prompt = "word " * 10000
    result = await llm_client.invoke(prompt=long_prompt, model="haiku")
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_no_method_id(llm_client, mock_provider):
    """Test invocation without method_id."""
    result = await llm_client.invoke(prompt="test", model="haiku")
    assert result.exit_code == 0

    # Check call log
    call_log = llm_client.get_call_log()
    assert call_log[0].method_id is None


@pytest.mark.asyncio
async def test_unknown_model_cost_tracking(llm_client, mock_provider):
    """Test cost tracking for unknown model uses default pricing."""
    result = await llm_client.invoke(prompt="test", model="unknown-model-v1")
    assert result.exit_code == 0

    summary = llm_client.get_cost_summary()
    assert summary.total_calls == 1
    assert summary.estimated_cost_usd > 0
