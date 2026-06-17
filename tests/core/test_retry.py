"""Tests for invoke_with_timeout_retry retry mechanics and fallback timeout."""

import pytest

from bmad_assist.core.exceptions import ProviderTimeoutError
from bmad_assist.core.retry import invoke_with_timeout_retry


class TestRetryBasicBehavior:
    """Test basic retry mechanics."""

    def test_no_retry_when_none(self) -> None:
        """timeout_retries=None raises immediately on timeout."""

        def fail(**kw):
            raise ProviderTimeoutError("timeout")

        with pytest.raises(ProviderTimeoutError):
            invoke_with_timeout_retry(fail, timeout_retries=None, phase_name="test")

    def test_success_on_first_try(self) -> None:
        """Successful invocation returns result directly."""

        def succeed(**kw):
            return "ok"

        result = invoke_with_timeout_retry(
            succeed, timeout_retries=2, phase_name="test"
        )
        assert result == "ok"

    def test_retry_once_then_succeed(self) -> None:
        """Primary fails once, succeeds on retry."""
        call_count = 0

        def flaky(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ProviderTimeoutError("timeout")
            return "recovered"

        result = invoke_with_timeout_retry(
            flaky, timeout_retries=2, phase_name="test"
        )
        assert result == "recovered"
        assert call_count == 2

    def test_retry_exhausted_raises(self) -> None:
        """After N retries with no fallback, raises ProviderTimeoutError."""

        def always_fail(**kw):
            raise ProviderTimeoutError("timeout")

        with pytest.raises(ProviderTimeoutError):
            invoke_with_timeout_retry(
                always_fail, timeout_retries=2, phase_name="test"
            )

    def test_retry_exhausted_calls_fallback(self) -> None:
        """Primary fails N times, fallback is invoked."""

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary timeout")

        def fallback_succeed(**kw):
            return "fallback_ok"

        result = invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_succeed,
        )
        assert result == "fallback_ok"

    def test_kwargs_passed_to_invoke_fn(self) -> None:
        """Verify kwargs flow to invoke function."""
        received = {}

        def capture(**kw):
            received.update(kw)
            return "ok"

        invoke_with_timeout_retry(
            capture,
            timeout_retries=1,
            phase_name="test",
            prompt="hello",
            timeout=600,
            model="opus",
        )
        assert received["prompt"] == "hello"
        assert received["timeout"] == 600
        assert received["model"] == "opus"


class TestFallbackTimeout:
    """Test fallback timeout override (Fix #1)."""

    def test_fallback_uses_explicit_timeout(self) -> None:
        """When fallback_timeout=900, fallback receives timeout=900."""
        received_timeout = None

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary timeout")

        def fallback_capture(**kw):
            nonlocal received_timeout
            received_timeout = kw.get("timeout")
            return "ok"

        invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_capture,
            fallback_timeout=900,
            timeout=600,
        )
        assert received_timeout == 900

    def test_fallback_uses_1_5x_multiplier_when_no_explicit(self) -> None:
        """Without explicit fallback_timeout, uses 1.5x primary timeout."""
        received_timeout = None

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary timeout")

        def fallback_capture(**kw):
            nonlocal received_timeout
            received_timeout = kw.get("timeout")
            return "ok"

        invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_capture,
            timeout=600,
        )
        assert received_timeout == 900  # 600 * 1.5

    def test_fallback_multiplier_with_different_timeout(self) -> None:
        """1.5x multiplier works with various base timeouts."""
        received_timeout = None

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary timeout")

        def fallback_capture(**kw):
            nonlocal received_timeout
            received_timeout = kw.get("timeout")
            return "ok"

        invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_capture,
            timeout=1000,
        )
        assert received_timeout == 1500  # 1000 * 1.5

    def test_fallback_default_timeout_when_no_timeout_in_kwargs(self) -> None:
        """When no timeout in kwargs, fallback gets int(3600 * 1.5) = 5400."""
        received_timeout = None

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary timeout")

        def fallback_capture(**kw):
            nonlocal received_timeout
            received_timeout = kw.get("timeout")
            return "ok"

        invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_capture,
        )
        assert received_timeout == 5400  # 3600 * 1.5

    def test_primary_timeout_unchanged(self) -> None:
        """Primary always uses original timeout, not fallback timeout."""
        primary_timeouts = []
        call_count = 0

        def primary_track(**kw):
            nonlocal call_count
            call_count += 1
            primary_timeouts.append(kw.get("timeout"))
            if call_count <= 2:
                raise ProviderTimeoutError("timeout")
            return "ok"

        invoke_with_timeout_retry(
            primary_track,
            timeout_retries=3,
            phase_name="test",
            fallback_timeout=9999,
            timeout=600,
        )
        # All primary attempts should use 600
        assert all(t == 600 for t in primary_timeouts)

    def test_fallback_kwargs_are_independent_copy(self) -> None:
        """Verify original kwargs dict is not mutated by fallback."""
        original_kwargs = {"timeout": 600, "prompt": "test"}

        def primary_fail(**kw):
            raise ProviderTimeoutError("timeout")

        def fallback_ok(**kw):
            return "ok"

        invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_ok,
            fallback_timeout=900,
            **original_kwargs,
        )
        # Original dict should not be mutated
        assert original_kwargs["timeout"] == 600

    def test_fallback_timeout_retries_independent(self) -> None:
        """Fallback uses its own retry count."""
        fallback_calls = 0

        def primary_fail(**kw):
            raise ProviderTimeoutError("primary")

        def fallback_track(**kw):
            nonlocal fallback_calls
            fallback_calls += 1
            if fallback_calls < 3:
                raise ProviderTimeoutError("fallback timeout")
            return "ok"

        result = invoke_with_timeout_retry(
            primary_fail,
            timeout_retries=1,
            phase_name="test",
            fallback_invoke_fn=fallback_track,
            fallback_timeout_retries=3,
            timeout=600,
        )
        assert result == "ok"
        assert fallback_calls == 3
