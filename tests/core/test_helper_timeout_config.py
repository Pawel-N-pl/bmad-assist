"""Tests for helper provider timeout configuration."""

from bmad_assist.core.config.models.providers import HelperProviderConfig


class TestHelperProviderTimeout:
    """Test configurable timeout for helper LLM provider."""

    def test_default_timeout_is_120(self) -> None:
        """Default helper timeout is 120 seconds."""
        config = HelperProviderConfig()
        assert config.timeout == 120

    def test_custom_timeout_from_config(self) -> None:
        """Custom timeout value can be set."""
        config = HelperProviderConfig(timeout=180)
        assert config.timeout == 180

    def test_minimum_timeout_is_10(self) -> None:
        """Timeout must be at least 10 seconds."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HelperProviderConfig(timeout=5)

    def test_timeout_used_in_provider_config(self) -> None:
        """Verify timeout is accessible alongside model and provider."""
        config = HelperProviderConfig(provider="claude", model="haiku", timeout=90)
        assert config.provider == "claude"
        assert config.model == "haiku"
        assert config.timeout == 90
