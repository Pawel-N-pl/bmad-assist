"""Tests for MultiProviderConfig fallback_models field."""

from bmad_assist.core.config.models.providers import MultiProviderConfig


class TestMultiProviderConfigFallbackModels:
    """Test fallback_models field on MultiProviderConfig."""

    def test_default_empty_list(self) -> None:
        """fallback_models defaults to empty list."""
        config = MultiProviderConfig(provider="gemini", model="gemini-3-pro")
        assert config.fallback_models == []

    def test_explicit_fallback_models(self) -> None:
        """fallback_models can be set explicitly."""
        config = MultiProviderConfig(
            provider="gemini",
            model="gemini-3-pro-preview",
            fallback_models=["gemini-2.5-flash"],
        )
        assert config.fallback_models == ["gemini-2.5-flash"]

    def test_multiple_fallback_models(self) -> None:
        """fallback_models supports multiple models."""
        config = MultiProviderConfig(
            provider="gemini",
            model="gemini-3-pro-preview",
            fallback_models=["gemini-2.5-flash", "gemini-2.5-pro"],
        )
        assert config.fallback_models == ["gemini-2.5-flash", "gemini-2.5-pro"]

    def test_backward_compatible_without_field(self) -> None:
        """Config without fallback_models still works (backward compatible)."""
        # Simulates existing YAML without the new field
        config = MultiProviderConfig(**{"provider": "gemini", "model": "gemini-2.5-flash"})
        assert config.fallback_models == []

    def test_frozen_model(self) -> None:
        """MultiProviderConfig is frozen (immutable)."""
        config = MultiProviderConfig(
            provider="gemini",
            model="gemini-3-pro",
            fallback_models=["gemini-2.5-flash"],
        )
        # Verify frozen by checking model_config
        assert config.model_config.get("frozen") is True
