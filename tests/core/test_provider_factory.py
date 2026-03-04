"""Tests for create_provider factory function.

Tests that the factory correctly wraps providers with FallbackProvider
when fallbacks are configured, and returns raw providers otherwise.
"""

from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config.models.providers import (
    HelperProviderConfig,
    MasterProviderConfig,
    MultiProviderConfig,
)
from bmad_assist.core.provider_factory import create_provider
from bmad_assist.providers.base import BaseProvider
from bmad_assist.providers.fallback import ConfiguredProvider, FallbackProvider


@pytest.fixture
def mock_get_provider():
    """Mock the provider registry to return fresh MagicMock providers."""
    providers: dict[str, MagicMock] = {}

    def _get(name: str) -> MagicMock:
        if name not in providers:
            p = MagicMock(spec=BaseProvider)
            p.provider_name = name
            providers[name] = p
        return providers[name]

    with patch("bmad_assist.core.provider_factory.get_provider", side_effect=_get) as mock:
        mock.providers = providers  # type: ignore[attr-defined]
        yield mock


class TestCreateProviderNoFallbacks:
    """Without fallbacks, create_provider returns the raw provider."""

    def test_master_no_fallbacks(self, mock_get_provider):
        """Master config without fallbacks returns raw provider."""
        config = MasterProviderConfig(provider="claude", model="opus")
        result = create_provider(config)
        assert not isinstance(result, FallbackProvider)
        mock_get_provider.assert_called_once_with("claude")

    def test_multi_no_fallbacks(self, mock_get_provider):
        """Multi config without fallbacks returns raw provider."""
        config = MultiProviderConfig(provider="gemini", model="flash")
        result = create_provider(config)
        assert not isinstance(result, FallbackProvider)

    def test_helper_no_fallbacks(self, mock_get_provider):
        """Helper config without fallbacks returns raw provider."""
        config = HelperProviderConfig(provider="claude", model="haiku")
        result = create_provider(config)
        assert not isinstance(result, FallbackProvider)


class TestCreateProviderWithFallbacks:
    """With fallbacks, create_provider returns a FallbackProvider."""

    def test_returns_fallback_provider(self, mock_get_provider):
        """Config with fallbacks returns a FallbackProvider wrapper."""
        config = MasterProviderConfig(
            provider="claude",
            model="opus",
            fallbacks=[
                MasterProviderConfig(provider="gemini", model="pro"),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)
        assert result.primary.provider_name == "claude"
        assert len(result.fallbacks) == 1

    def test_multiple_fallbacks(self, mock_get_provider):
        """Multiple fallbacks are all registered in the FallbackProvider."""
        config = MasterProviderConfig(
            provider="claude",
            model="opus",
            fallbacks=[
                MasterProviderConfig(provider="gemini", model="pro"),
                MasterProviderConfig(provider="deepseek", model="chat"),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)
        assert len(result.fallbacks) == 2

    def test_fallback_model_bound(self, mock_get_provider):
        """Fallback model is bound in the ConfiguredProvider."""
        config = MasterProviderConfig(
            provider="claude",
            model="opus",
            fallbacks=[
                MasterProviderConfig(provider="gemini", model="pro"),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)
        fb = result.fallbacks[0]
        assert isinstance(fb, ConfiguredProvider)
        assert fb.model == "pro"

    def test_fallback_settings_bound(self, mock_get_provider):
        """Fallback settings file is bound in the ConfiguredProvider."""
        config = MasterProviderConfig(
            provider="claude",
            model="opus",
            fallbacks=[
                MasterProviderConfig(
                    provider="claude",
                    model="sonnet",
                    settings="/tmp/test.json",
                ),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)
        fb = result.fallbacks[0]
        assert fb.settings_file is not None

    def test_multi_with_fallbacks(self, mock_get_provider):
        """Multi config with fallbacks returns a FallbackProvider."""
        config = MultiProviderConfig(
            provider="gemini",
            model="pro",
            fallbacks=[
                MultiProviderConfig(provider="gemini", model="flash"),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)

    def test_helper_with_fallbacks(self, mock_get_provider):
        """Helper config with fallbacks returns a FallbackProvider."""
        config = HelperProviderConfig(
            provider="claude",
            model="haiku",
            fallbacks=[
                HelperProviderConfig(provider="gemini", model="flash"),
            ],
        )
        result = create_provider(config)
        assert isinstance(result, FallbackProvider)
