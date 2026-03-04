"""Tests for FallbackProvider and ConfiguredProvider.

Tests the fallback failover chain, transient error detection,
ConfiguredProvider kwargs override, and delegation to primary provider.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import BaseProvider, ExitStatus, ProviderResult
from bmad_assist.providers.fallback import ConfiguredProvider, FallbackProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(stdout: str = "ok") -> ProviderResult:
    """Create a simple successful ProviderResult."""
    return ProviderResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        duration_ms=100,
        model="test-model",
        command=("test",),
    )


def _make_provider(name: str = "mock") -> MagicMock:
    """Create a mock BaseProvider."""
    provider = MagicMock(spec=BaseProvider)
    provider.provider_name = name
    provider.default_model = None
    provider.supports_model.return_value = True
    provider.parse_output.side_effect = lambda r: r.stdout
    return provider


def _transient_exit_error(stderr: str = "rate limit exceeded") -> ProviderExitCodeError:
    """Create a transient ProviderExitCodeError (rate limit)."""
    return ProviderExitCodeError(
        message=f"Process exited with code 1: {stderr}",
        exit_code=1,
        stderr=stderr,
        exit_status=ExitStatus.ERROR,
        command=("test",),
    )


def _nontransient_exit_error(stderr: str = "invalid api key") -> ProviderExitCodeError:
    """Create a non-transient ProviderExitCodeError (auth failure)."""
    return ProviderExitCodeError(
        message=f"Process exited with code 1: {stderr}",
        exit_code=1,
        stderr=stderr,
        exit_status=ExitStatus.ERROR,
        command=("test",),
    )


# ---------------------------------------------------------------------------
# FallbackProvider Tests
# ---------------------------------------------------------------------------


class TestFallbackProviderPrimarySucceeds:
    """When the primary provider succeeds, fallbacks are never invoked."""

    def test_returns_primary_result(self):
        """Primary result is returned when invocation succeeds."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")
        expected = _make_result("primary-output")
        primary.invoke.return_value = expected

        provider = FallbackProvider(primary, [ConfiguredProvider(fb, model="fb-model")])
        result = provider.invoke("prompt")

        assert result is expected
        fb.invoke.assert_not_called()

    def test_fallbacks_never_touched(self):
        """Fallback providers are never invoked on primary success."""
        primary = _make_provider("primary")
        fb1 = _make_provider("fb1")
        fb2 = _make_provider("fb2")
        primary.invoke.return_value = _make_result()

        provider = FallbackProvider(
            primary,
            [ConfiguredProvider(fb1), ConfiguredProvider(fb2)],
        )
        provider.invoke("prompt")

        fb1.invoke.assert_not_called()
        fb2.invoke.assert_not_called()


class TestFallbackProviderTransientFallover:
    """When the primary fails with a transient error, fallbacks are tried."""

    def test_fallback_succeeds_after_primary_transient(self):
        """First fallback is used when primary fails transiently."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")

        primary.invoke.side_effect = _transient_exit_error()
        expected = _make_result("fallback-output")
        fb.invoke.return_value = expected

        provider = FallbackProvider(primary, [ConfiguredProvider(fb, model="fb-model")])
        result = provider.invoke("prompt")

        assert result is expected

    def test_second_fallback_after_first_fails(self):
        """Second fallback is used when first also fails transiently."""
        primary = _make_provider("primary")
        fb1 = _make_provider("fb1")
        fb2 = _make_provider("fb2")

        primary.invoke.side_effect = _transient_exit_error()
        fb1.invoke.side_effect = _transient_exit_error("503 service overloaded")
        expected = _make_result("fb2-output")
        fb2.invoke.return_value = expected

        provider = FallbackProvider(
            primary,
            [ConfiguredProvider(fb1, model="m1"), ConfiguredProvider(fb2, model="m2")],
        )
        result = provider.invoke("prompt")

        assert result is expected

    def test_timeout_error_is_transient(self):
        """ProviderTimeoutError triggers fallback (treated as transient)."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")

        primary.invoke.side_effect = ProviderTimeoutError(
            message="Timed out after 60s"
        )
        expected = _make_result("fallback-output")
        fb.invoke.return_value = expected

        provider = FallbackProvider(primary, [ConfiguredProvider(fb)])
        result = provider.invoke("prompt")

        assert result is expected


class TestFallbackProviderNonTransient:
    """Non-transient errors on primary raise immediately."""

    def test_primary_nontransient_raises(self):
        """Non-transient primary error raises without trying fallbacks."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")

        error = _nontransient_exit_error()
        primary.invoke.side_effect = error

        provider = FallbackProvider(primary, [ConfiguredProvider(fb)])

        with pytest.raises(ProviderExitCodeError):
            provider.invoke("prompt")

        fb.invoke.assert_not_called()

    def test_fallback_nontransient_continues_to_next(self):
        """Non-transient fallback errors continue to next fallback (resilient behavior)."""
        primary = _make_provider("primary")
        fb1 = _make_provider("fb1")
        fb2 = _make_provider("fb2")

        primary.invoke.side_effect = _transient_exit_error()
        fb1.invoke.side_effect = _nontransient_exit_error()
        expected = _make_result("fb2-output")
        fb2.invoke.return_value = expected

        provider = FallbackProvider(
            primary,
            [ConfiguredProvider(fb1, model="m1"), ConfiguredProvider(fb2, model="m2")],
        )
        result = provider.invoke("prompt")

        assert result is expected


class TestFallbackProviderAllFail:
    """When all providers fail, the last error is raised."""

    def test_raises_last_error(self):
        """Last error is raised when all providers fail."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")

        primary.invoke.side_effect = _transient_exit_error("rate limit exceeded")
        last_err = _transient_exit_error("503 service unavailable")
        fb.invoke.side_effect = last_err

        provider = FallbackProvider(primary, [ConfiguredProvider(fb)])

        with pytest.raises(ProviderExitCodeError) as exc_info:
            provider.invoke("prompt")

        assert exc_info.value is last_err

    def test_raises_provider_error_when_no_last_error(self):
        """Edge case: empty fallback list + primary operational error -> last_error raised."""
        primary = _make_provider("primary")
        err = ProviderError("oops")
        primary.invoke.side_effect = err

        provider = FallbackProvider(primary, [])

        with pytest.raises(ProviderError):
            provider.invoke("prompt")


class TestFallbackProviderDelegation:
    """Properties and methods delegate to the primary provider."""

    def test_provider_name_proxies(self):
        """Provider name is proxied from the primary."""
        primary = _make_provider("claude")
        provider = FallbackProvider(primary, [])
        assert provider.provider_name == "claude"

    def test_default_model_proxies(self):
        """Default model is proxied from the primary."""
        primary = _make_provider("claude")
        primary.default_model = "opus"
        provider = FallbackProvider(primary, [])
        assert provider.default_model == "opus"

    def test_supports_model_proxies(self):
        """Supports-model check is proxied from the primary."""
        primary = _make_provider("claude")
        primary.supports_model.return_value = False
        provider = FallbackProvider(primary, [])
        assert provider.supports_model("unknown") is False

    def test_parse_output_delegates_to_primary(self):
        """Parse-output delegates to the primary provider."""
        primary = _make_provider("claude")
        primary.parse_output.side_effect = None  # Remove side_effect
        primary.parse_output.return_value = "parsed"
        provider = FallbackProvider(primary, [])
        result = _make_result("raw")
        assert provider.parse_output(result) == "parsed"

    def test_cancel_propagates_to_all(self):
        """Cancel propagates to primary and all fallbacks."""
        primary = _make_provider("primary")
        fb1 = _make_provider("fb1")
        fb2 = _make_provider("fb2")

        provider = FallbackProvider(
            primary,
            [ConfiguredProvider(fb1), ConfiguredProvider(fb2)],
        )
        provider.cancel()

        primary.cancel.assert_called_once()
        fb1.cancel.assert_called_once()
        fb2.cancel.assert_called_once()


class TestFallbackProviderLogging:
    """Success logging is emitted when a fallback succeeds."""

    def test_success_log_emitted(self, caplog):
        """Info log is emitted when a fallback provider succeeds."""
        primary = _make_provider("primary")
        fb = _make_provider("fallback")

        primary.invoke.side_effect = _transient_exit_error()
        fb.invoke.return_value = _make_result("ok")

        provider = FallbackProvider(primary, [ConfiguredProvider(fb, model="fb-model")])

        import logging
        with caplog.at_level(logging.INFO):
            provider.invoke("prompt")

        assert any("succeeded" in msg for msg in caplog.messages)
        assert any("fallback" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# ConfiguredProvider Tests
# ---------------------------------------------------------------------------


class TestConfiguredProvider:
    """ConfiguredProvider overrides model and settings_file in kwargs."""

    def test_overrides_model(self):
        """Model kwarg is overridden by ConfiguredProvider."""
        inner = _make_provider("inner")
        inner.invoke.return_value = _make_result()

        cp = ConfiguredProvider(inner, model="custom-model")
        cp.invoke("prompt", model="original-model")

        _, kwargs = inner.invoke.call_args
        assert kwargs["model"] == "custom-model"

    def test_overrides_settings_file(self, tmp_path):
        """Settings-file kwarg is overridden by ConfiguredProvider."""
        inner = _make_provider("inner")
        inner.invoke.return_value = _make_result()
        settings = tmp_path / "settings.json"

        cp = ConfiguredProvider(inner, settings_file=settings)
        cp.invoke("prompt", settings_file=None)

        _, kwargs = inner.invoke.call_args
        assert kwargs["settings_file"] == settings

    def test_passes_through_other_kwargs(self):
        """Non-overridden kwargs are passed through to the inner provider."""
        inner = _make_provider("inner")
        inner.invoke.return_value = _make_result()

        cp = ConfiguredProvider(inner, model="m")
        cp.invoke("prompt", timeout=300, cwd=Path("/tmp"))

        _, kwargs = inner.invoke.call_args
        assert kwargs["timeout"] == 300
        assert kwargs["cwd"] == Path("/tmp")

    def test_no_override_when_none(self):
        """Kwargs are not overridden when ConfiguredProvider has no overrides."""
        inner = _make_provider("inner")
        inner.invoke.return_value = _make_result()

        cp = ConfiguredProvider(inner)  # No model/settings
        cp.invoke("prompt", model="keep-this")

        _, kwargs = inner.invoke.call_args
        assert kwargs["model"] == "keep-this"
