"""Tests for provider registry module.

This module tests the provider registry functionality including:
- Provider lookup by name (AC1, AC2, AC3)
- Provider listing (AC4)
- Provider validation (AC5)
- Custom provider registration (AC6, AC7, AC10)
- Model name normalization (AC8)
- Package exports (AC9)
"""

import pytest

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.providers.base import BaseProvider, ProviderResult


class TestGetProvider:
    """Tests for get_provider() function (AC1, AC2, AC3)."""

    def test_get_provider_claude_returns_claude_sdk_provider(self, reset_registry: None) -> None:
        """AC1: get_provider('claude') returns ClaudeSDKProvider instance."""
        from bmad_assist.providers.registry import get_provider
        from bmad_assist.providers.claude_sdk import ClaudeSDKProvider

        provider = get_provider("claude")

        assert isinstance(provider, ClaudeSDKProvider)
        assert provider.provider_name == "claude"

    def test_get_provider_claude_subprocess_returns_subprocess_provider(
        self, reset_registry: None
    ) -> None:
        """AC1: get_provider('claude-subprocess') returns ClaudeSubprocessProvider."""
        from bmad_assist.providers.registry import get_provider
        from bmad_assist.providers.claude import ClaudeSubprocessProvider

        provider = get_provider("claude-subprocess")

        assert isinstance(provider, ClaudeSubprocessProvider)
        assert provider.provider_name == "claude-subprocess"

    def test_get_provider_codex_returns_codex_provider(self, reset_registry: None) -> None:
        """AC1: get_provider('codex') returns CodexProvider instance."""
        from bmad_assist.providers.registry import get_provider
        from bmad_assist.providers.codex import CodexProvider

        provider = get_provider("codex")

        assert isinstance(provider, CodexProvider)
        assert provider.provider_name == "codex"

    def test_get_provider_gemini_returns_gemini_provider(self, reset_registry: None) -> None:
        """AC1: get_provider('gemini') returns GeminiProvider instance."""
        from bmad_assist.providers.registry import get_provider
        from bmad_assist.providers.gemini import GeminiProvider

        provider = get_provider("gemini")

        assert isinstance(provider, GeminiProvider)
        assert provider.provider_name == "gemini"

    def test_get_provider_unknown_raises_config_error(self, reset_registry: None) -> None:
        """AC2: get_provider('unknown') raises ConfigError with helpful message."""
        from bmad_assist.providers.registry import get_provider

        with pytest.raises(ConfigError) as exc_info:
            get_provider("unknown-provider")

        error_msg = str(exc_info.value)
        assert "Unknown provider: 'unknown-provider'" in error_msg
        # Check available providers are listed in the error message
        assert "Available:" in error_msg
        # Verify expected providers are mentioned (not exact string to be future-proof)
        for expected in ["amp", "claude", "gemini", "opencode", "codex"]:
            assert expected in error_msg

    def test_get_provider_empty_string_raises_config_error(self, reset_registry: None) -> None:
        """get_provider('') raises ConfigError for empty name."""
        from bmad_assist.providers.registry import get_provider

        with pytest.raises(ConfigError) as exc_info:
            get_provider("")

        error_msg = str(exc_info.value)
        assert "Provider name cannot be empty" in error_msg
        assert "Available:" in error_msg

    def test_get_provider_whitespace_only_raises_config_error(self, reset_registry: None) -> None:
        """get_provider('  ') raises ConfigError for whitespace-only name."""
        from bmad_assist.providers.registry import get_provider

        with pytest.raises(ConfigError) as exc_info:
            get_provider("   ")

        error_msg = str(exc_info.value)
        assert "Provider name cannot be empty" in error_msg

    def test_get_provider_creates_new_instance_each_call(self, reset_registry: None) -> None:
        """AC3: Each get_provider() call returns new instance (not same object)."""
        from bmad_assist.providers.registry import get_provider

        provider1 = get_provider("claude")
        provider2 = get_provider("claude")

        assert provider1 is not provider2
        assert id(provider1) != id(provider2)
        # Both are valid ClaudeSDKProvider instances
        assert provider1.provider_name == "claude"
        assert provider2.provider_name == "claude"


class TestListProviders:
    """Tests for list_providers() function (AC4)."""

    def test_list_providers_returns_frozenset(self, reset_registry: None) -> None:
        """AC4: list_providers() returns immutable frozenset."""
        from bmad_assist.providers.registry import list_providers

        result = list_providers()

        assert isinstance(result, frozenset)

    def test_list_providers_contains_all_default_providers(self, reset_registry: None) -> None:
        """AC4: list_providers() contains exactly 8 default providers."""
        from bmad_assist.providers.registry import list_providers

        result = list_providers()

        expected = frozenset({
            "amp", "claude", "claude-subprocess", "codex",
            "copilot", "cursor-agent", "gemini", "opencode"
        })
        assert result == expected
        assert len(result) == 8

    def test_list_providers_is_immutable(self, reset_registry: None) -> None:
        """AC4: Result is immutable (frozenset, not set)."""
        from bmad_assist.providers.registry import list_providers

        result = list_providers()

        # frozenset has no add/remove methods
        assert not hasattr(result, "add")
        assert not hasattr(result, "remove")


class TestIsValidProvider:
    """Tests for is_valid_provider() function (AC5)."""

    def test_is_valid_provider_returns_true_for_claude(self, reset_registry: None) -> None:
        """AC5: is_valid_provider('claude') returns True."""
        from bmad_assist.providers.registry import is_valid_provider

        assert is_valid_provider("claude") is True

    def test_is_valid_provider_returns_true_for_codex(self, reset_registry: None) -> None:
        """AC5: is_valid_provider('codex') returns True."""
        from bmad_assist.providers.registry import is_valid_provider

        assert is_valid_provider("codex") is True

    def test_is_valid_provider_returns_true_for_gemini(self, reset_registry: None) -> None:
        """AC5: is_valid_provider('gemini') returns True."""
        from bmad_assist.providers.registry import is_valid_provider

        assert is_valid_provider("gemini") is True

    def test_is_valid_provider_returns_true_for_claude_subprocess(
        self, reset_registry: None
    ) -> None:
        """AC5: is_valid_provider('claude-subprocess') returns True."""
        from bmad_assist.providers.registry import is_valid_provider

        assert is_valid_provider("claude-subprocess") is True

    def test_is_valid_provider_returns_false_for_invalid(self, reset_registry: None) -> None:
        """AC5: is_valid_provider('invalid-name') returns False."""
        from bmad_assist.providers.registry import is_valid_provider

        assert is_valid_provider("invalid-name") is False
        assert is_valid_provider("") is False
        assert is_valid_provider("CLAUDE") is False  # Case sensitive


class TestRegisterProvider:
    """Tests for register_provider() function (AC6, AC7, AC10)."""

    def test_register_provider_adds_custom_provider(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """AC6: register_provider() adds custom provider to registry."""
        from bmad_assist.providers.registry import (
            get_provider,
            list_providers,
            register_provider,
        )

        register_provider("my-custom", custom_provider_class)

        # Provider is now in registry
        assert "my-custom" in list_providers()

        # Can get instance
        provider = get_provider("my-custom")
        assert provider.provider_name == "custom-test"

    def test_register_provider_duplicate_raises_config_error(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """AC7: Duplicate registration raises ConfigError."""
        from bmad_assist.providers.registry import register_provider

        with pytest.raises(ConfigError) as exc_info:
            register_provider("claude", custom_provider_class)

        error_msg = str(exc_info.value)
        assert "already registered" in error_msg
        assert "claude" in error_msg

    def test_register_provider_duplicate_preserves_original(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """AC7: Original registration NOT overwritten on duplicate attempt."""
        from bmad_assist.providers.registry import get_provider, register_provider
        from bmad_assist.providers.claude_sdk import ClaudeSDKProvider

        try:
            register_provider("claude", custom_provider_class)
        except ConfigError:
            pass  # Expected

        # Original still works
        provider = get_provider("claude")
        assert isinstance(provider, ClaudeSDKProvider)

    def test_register_provider_non_baseprovider_raises_type_error(
        self, reset_registry: None
    ) -> None:
        """AC10: Non-BaseProvider class raises TypeError."""
        from bmad_assist.providers.registry import register_provider

        class NotAProvider:
            pass

        with pytest.raises(TypeError) as exc_info:
            register_provider("bad", NotAProvider)  # type: ignore[arg-type]

        error_msg = str(exc_info.value)
        assert "must be a subclass of BaseProvider" in error_msg

    def test_register_provider_non_class_raises_type_error(self, reset_registry: None) -> None:
        """AC10: Non-class object raises TypeError."""
        from bmad_assist.providers.registry import register_provider

        with pytest.raises(TypeError) as exc_info:
            register_provider("bad", "not-a-class")  # type: ignore[arg-type]

        error_msg = str(exc_info.value)
        assert "must be a subclass of BaseProvider" in error_msg

    def test_register_provider_empty_name_raises_config_error(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """register_provider('', ...) raises ConfigError for empty name."""
        from bmad_assist.providers.registry import register_provider

        with pytest.raises(ConfigError) as exc_info:
            register_provider("", custom_provider_class)

        error_msg = str(exc_info.value)
        assert "Provider name cannot be empty" in error_msg

    def test_register_provider_whitespace_name_raises_config_error(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """register_provider('  ', ...) raises ConfigError for whitespace name."""
        from bmad_assist.providers.registry import register_provider

        with pytest.raises(ConfigError) as exc_info:
            register_provider("   ", custom_provider_class)

        error_msg = str(exc_info.value)
        assert "Provider name cannot be empty" in error_msg


class TestModelNameNormalization:
    """Tests for model name normalization functions (AC8)."""

    def test_normalize_model_name_converts_underscores_to_hyphens(
        self, reset_registry: None
    ) -> None:
        """AC8: normalize_model_name() converts underscores to hyphens."""
        from bmad_assist.providers.registry import normalize_model_name

        assert normalize_model_name("opus_4") == "opus-4"
        assert normalize_model_name("claude_sonnet_4") == "claude-sonnet-4"

    def test_normalize_model_name_empty_string(self, reset_registry: None) -> None:
        """AC8 edge case: Empty string unchanged."""
        from bmad_assist.providers.registry import normalize_model_name

        assert normalize_model_name("") == ""

    def test_normalize_model_name_no_underscores(self, reset_registry: None) -> None:
        """AC8 edge case: String without underscores unchanged (idempotent)."""
        from bmad_assist.providers.registry import normalize_model_name

        assert normalize_model_name("opus4") == "opus4"

    def test_normalize_model_name_already_normalized(self, reset_registry: None) -> None:
        """AC8 edge case: Already normalized string unchanged (idempotent)."""
        from bmad_assist.providers.registry import normalize_model_name

        assert normalize_model_name("opus-4") == "opus-4"

    def test_normalize_model_name_mixed_separators(self, reset_registry: None) -> None:
        """AC8 edge case: Mixed separators - underscores become hyphens."""
        from bmad_assist.providers.registry import normalize_model_name

        assert normalize_model_name("opus_4-beta") == "opus-4-beta"

    def test_denormalize_model_name_converts_hyphens_to_underscores(
        self, reset_registry: None
    ) -> None:
        """AC8: denormalize_model_name() converts hyphens to underscores."""
        from bmad_assist.providers.registry import denormalize_model_name

        assert denormalize_model_name("opus-4") == "opus_4"
        assert denormalize_model_name("claude-sonnet-4") == "claude_sonnet_4"

    def test_denormalize_model_name_empty_string(self, reset_registry: None) -> None:
        """AC8 edge case: Empty string unchanged."""
        from bmad_assist.providers.registry import denormalize_model_name

        assert denormalize_model_name("") == ""

    def test_denormalize_model_name_no_hyphens(self, reset_registry: None) -> None:
        """AC8 edge case: String without hyphens unchanged."""
        from bmad_assist.providers.registry import denormalize_model_name

        assert denormalize_model_name("opus4") == "opus4"

    def test_denormalize_model_name_already_denormalized(self, reset_registry: None) -> None:
        """AC8 edge case: Already denormalized string unchanged."""
        from bmad_assist.providers.registry import denormalize_model_name

        assert denormalize_model_name("opus_4") == "opus_4"


class TestPackageExports:
    """Tests for package exports (AC9)."""

    def test_get_provider_exported_from_package(self) -> None:
        """AC9: get_provider can be imported from bmad_assist.providers."""
        from bmad_assist.providers import get_provider

        assert callable(get_provider)

    def test_list_providers_exported_from_package(self) -> None:
        """AC9: list_providers can be imported from bmad_assist.providers."""
        from bmad_assist.providers import list_providers

        assert callable(list_providers)

    def test_is_valid_provider_exported_from_package(self) -> None:
        """AC9: is_valid_provider can be imported from bmad_assist.providers."""
        from bmad_assist.providers import is_valid_provider

        assert callable(is_valid_provider)

    def test_register_provider_exported_from_package(self) -> None:
        """AC9: register_provider can be imported from bmad_assist.providers."""
        from bmad_assist.providers import register_provider

        assert callable(register_provider)

    def test_normalize_model_name_exported_from_package(self) -> None:
        """AC9: normalize_model_name can be imported from bmad_assist.providers."""
        from bmad_assist.providers import normalize_model_name

        assert callable(normalize_model_name)

    def test_denormalize_model_name_exported_from_package(self) -> None:
        """AC9: denormalize_model_name can be imported from bmad_assist.providers."""
        from bmad_assist.providers import denormalize_model_name

        assert callable(denormalize_model_name)

    def test_all_registry_functions_in_package_all(self) -> None:
        """AC9: All registry functions in __all__."""
        from bmad_assist import providers

        expected_exports = {
            "get_provider",
            "list_providers",
            "is_valid_provider",
            "register_provider",
            "normalize_model_name",
            "denormalize_model_name",
        }

        assert expected_exports.issubset(set(providers.__all__))

    def test_direct_import_from_registry_module(self) -> None:
        """AC9: Direct import from registry module works."""
        from bmad_assist.providers.registry import (
            denormalize_model_name,
            get_provider,
            is_valid_provider,
            list_providers,
            normalize_model_name,
            register_provider,
        )

        assert callable(get_provider)
        assert callable(list_providers)
        assert callable(is_valid_provider)
        assert callable(register_provider)
        assert callable(normalize_model_name)
        assert callable(denormalize_model_name)


class TestRegistryStateIsolation:
    """Tests for registry state isolation between tests."""

    def test_custom_provider_in_first_test(
        self, reset_registry: None, custom_provider_class: type
    ) -> None:
        """Register custom provider in first test."""
        from bmad_assist.providers.registry import list_providers, register_provider

        register_provider("test-isolation-1", custom_provider_class)
        assert "test-isolation-1" in list_providers()

    def test_custom_provider_not_in_second_test(self, reset_registry: None) -> None:
        """Custom provider from first test should NOT exist in second test."""
        from bmad_assist.providers.registry import list_providers

        # This test runs after test_custom_provider_in_first_test
        # Due to reset_registry fixture, the custom provider should not exist
        assert "test-isolation-1" not in list_providers()


class TestLazyInitialization:
    """Tests for lazy initialization pattern.

    These tests manually manage registry state to verify lazy initialization.
    They do NOT use the reset_registry fixture to avoid interference.
    """

    def test_list_providers_initializes_empty_registry(self) -> None:
        """list_providers() initializes registry when empty."""
        from bmad_assist.providers.registry import (
            _REGISTRY,
            list_providers,
        )

        # Clear registry to simulate fresh state
        _REGISTRY.clear()
        assert len(_REGISTRY) == 0

        # First access triggers initialization
        providers = list_providers()

        # Now registry has providers
        assert len(_REGISTRY) == 8
        assert len(providers) == 8

        # Clean up
        _REGISTRY.clear()

    def test_get_provider_initializes_empty_registry(self) -> None:
        """get_provider() initializes registry when empty (covers line 84)."""
        from bmad_assist.providers.registry import (
            _REGISTRY,
            get_provider,
        )
        from bmad_assist.providers.claude_sdk import ClaudeSDKProvider

        # Clear registry to simulate fresh state
        _REGISTRY.clear()
        assert len(_REGISTRY) == 0

        # get_provider triggers initialization
        provider = get_provider("claude")

        # Now registry has providers
        assert len(_REGISTRY) == 8
        assert isinstance(provider, ClaudeSDKProvider)

        # Clean up
        _REGISTRY.clear()

    def test_is_valid_provider_initializes_empty_registry(self) -> None:
        """is_valid_provider() initializes registry when empty (covers line 133)."""
        from bmad_assist.providers.registry import (
            _REGISTRY,
            is_valid_provider,
        )

        # Clear registry to simulate fresh state
        _REGISTRY.clear()
        assert len(_REGISTRY) == 0

        # is_valid_provider triggers initialization
        result = is_valid_provider("claude")

        # Now registry has providers
        assert len(_REGISTRY) == 8
        assert result is True

        # Clean up
        _REGISTRY.clear()

    def test_register_provider_initializes_empty_registry(
        self, custom_provider_class: type
    ) -> None:
        """register_provider() initializes registry when empty (covers line 158)."""
        from bmad_assist.providers.registry import (
            _REGISTRY,
            register_provider,
        )

        # Clear registry to simulate fresh state
        _REGISTRY.clear()
        assert len(_REGISTRY) == 0

        # register_provider triggers initialization before adding custom
        register_provider("test-lazy-init", custom_provider_class)

        # Now registry has default providers + custom (8 default + 1 custom)
        assert len(_REGISTRY) == 9
        assert "test-lazy-init" in _REGISTRY

        # Clean up
        _REGISTRY.clear()


# Fixtures


@pytest.fixture
def reset_registry():
    """Reset registry to default state before and after each test.

    This fixture ensures each test starts with a clean registry state.
    Uses private symbols deliberately - there's no public reset API by design.
    """
    from bmad_assist.providers.registry import _REGISTRY, _init_default_providers

    _REGISTRY.clear()
    _init_default_providers()
    yield
    _REGISTRY.clear()


@pytest.fixture
def custom_provider_class() -> type:
    """Create a custom provider class for testing registration."""
    from pathlib import Path

    class CustomTestProvider(BaseProvider):
        """Custom test provider for registration tests."""

        @property
        def provider_name(self) -> str:
            return "custom-test"

        @property
        def default_model(self) -> str | None:
            return "test-model"

        def invoke(
            self,
            prompt: str,
            *,
            model: str | None = None,
            timeout: int | None = None,
            settings_file: Path | None = None,
        ) -> ProviderResult:
            return ProviderResult(
                stdout="test output",
                stderr="",
                exit_code=0,
                duration_ms=100,
                model=model,
                command=("test",),
            )

        def parse_output(self, result: ProviderResult) -> str:
            return result.stdout

        def supports_model(self, model: str) -> bool:
            return True

    return CustomTestProvider
