"""Tests for security agent configuration models.

Covers:
- SecurityAgentConfig defaults and validation
- SecurityAgentProviderConfig fields and properties
- Frozen model immutability
- max_findings bounds validation
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bmad_assist.security.config import (
    SecurityAgentConfig,
    SecurityAgentProviderConfig,
)

# =============================================================================
# SecurityAgentProviderConfig Tests
# =============================================================================


class TestSecurityAgentProviderConfigFields:
    """Test SecurityAgentProviderConfig field definitions."""

    def test_required_fields(self) -> None:
        """Test provider and model are required."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        assert config.provider == "claude-sdk"
        assert config.model == "haiku"

    def test_optional_fields_default_none(self) -> None:
        """Test optional fields default to None/False."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        assert config.model_name is None
        assert config.settings is None
        assert config.thinking is False
        assert config.reasoning_effort is None

    def test_all_fields_set(self) -> None:
        """Test all fields can be set explicitly."""
        config = SecurityAgentProviderConfig(
            provider="gemini",
            model="gemini-2.5-flash",
            model_name="Gemini Flash",
            settings="~/.claude/gemini.json",
            thinking=True,
            reasoning_effort="high",
        )
        assert config.provider == "gemini"
        assert config.model == "gemini-2.5-flash"
        assert config.model_name == "Gemini Flash"
        assert config.settings == "~/.claude/gemini.json"
        assert config.thinking is True
        assert config.reasoning_effort == "high"

    def test_missing_provider_raises_error(self) -> None:
        """Test missing provider raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SecurityAgentProviderConfig(model="haiku")  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("provider",) for e in errors)

    def test_missing_model_raises_error(self) -> None:
        """Test missing model raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SecurityAgentProviderConfig(provider="claude-sdk")  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("model",) for e in errors)


class TestSecurityAgentProviderConfigDisplayModel:
    """Test display_model property."""

    def test_display_model_returns_model_name_when_set(self) -> None:
        """Test display_model returns model_name if provided."""
        config = SecurityAgentProviderConfig(
            provider="claude-sdk",
            model="haiku",
            model_name="Claude Haiku 3.5",
        )
        assert config.display_model == "Claude Haiku 3.5"

    def test_display_model_falls_back_to_model(self) -> None:
        """Test display_model falls back to model when model_name is None."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        assert config.display_model == "haiku"

    def test_display_model_empty_string_model_name(self) -> None:
        """Test display_model with empty string model_name falls back to model."""
        config = SecurityAgentProviderConfig(
            provider="claude-sdk",
            model="haiku",
            model_name="",
        )
        # Empty string is falsy, so should fall back to model
        assert config.display_model == "haiku"


class TestSecurityAgentProviderConfigSettingsPath:
    """Test settings_path property."""

    def test_settings_path_none_when_no_settings(self) -> None:
        """Test settings_path returns None when settings is None."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        assert config.settings_path is None

    def test_settings_path_returns_expanded_path(self) -> None:
        """Test settings_path returns Path with tilde expansion."""
        config = SecurityAgentProviderConfig(
            provider="claude-sdk",
            model="haiku",
            settings="~/.claude/settings.json",
        )
        result = config.settings_path
        assert isinstance(result, Path)
        assert "~" not in str(result)
        assert str(result).endswith(".claude/settings.json")

    def test_settings_path_absolute_path(self) -> None:
        """Test settings_path with absolute path."""
        config = SecurityAgentProviderConfig(
            provider="claude-sdk",
            model="haiku",
            settings="/etc/bmad/settings.json",
        )
        result = config.settings_path
        assert isinstance(result, Path)
        assert str(result) == "/etc/bmad/settings.json"


class TestSecurityAgentProviderConfigFrozen:
    """Test SecurityAgentProviderConfig immutability."""

    def test_frozen_provider(self) -> None:
        """Test provider field cannot be mutated."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        with pytest.raises(ValidationError):
            config.provider = "gemini"  # type: ignore[misc]

    def test_frozen_model(self) -> None:
        """Test model field cannot be mutated."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        with pytest.raises(ValidationError):
            config.model = "sonnet"  # type: ignore[misc]

    def test_frozen_thinking(self) -> None:
        """Test thinking field cannot be mutated."""
        config = SecurityAgentProviderConfig(provider="claude-sdk", model="haiku")
        with pytest.raises(ValidationError):
            config.thinking = True  # type: ignore[misc]


# =============================================================================
# SecurityAgentConfig Tests
# =============================================================================


class TestSecurityAgentConfigDefaults:
    """Test SecurityAgentConfig default values."""

    def test_default_enabled(self) -> None:
        """Test enabled defaults to True."""
        config = SecurityAgentConfig()
        assert config.enabled is True

    def test_default_provider_config(self) -> None:
        """Test provider_config defaults to None."""
        config = SecurityAgentConfig()
        assert config.provider_config is None

    def test_default_languages(self) -> None:
        """Test languages defaults to None."""
        config = SecurityAgentConfig()
        assert config.languages is None

    def test_default_max_findings(self) -> None:
        """Test max_findings defaults to 25."""
        config = SecurityAgentConfig()
        assert config.max_findings == 25


class TestSecurityAgentConfigCustomValues:
    """Test SecurityAgentConfig with custom values."""

    def test_disabled(self) -> None:
        """Test enabled can be set to False."""
        config = SecurityAgentConfig(enabled=False)
        assert config.enabled is False

    def test_custom_languages(self) -> None:
        """Test languages list can be set."""
        config = SecurityAgentConfig(languages=["go", "python", "typescript"])
        assert config.languages == ["go", "python", "typescript"]

    def test_empty_languages_list(self) -> None:
        """Test languages can be set to empty list."""
        config = SecurityAgentConfig(languages=[])
        assert config.languages == []

    def test_custom_max_findings(self) -> None:
        """Test max_findings can be set to custom value."""
        config = SecurityAgentConfig(max_findings=50)
        assert config.max_findings == 50

    def test_custom_provider_config(self) -> None:
        """Test provider_config can be set."""
        provider = SecurityAgentProviderConfig(
            provider="gemini",
            model="gemini-2.5-flash",
        )
        config = SecurityAgentConfig(provider_config=provider)
        assert config.provider_config is not None
        assert config.provider_config.provider == "gemini"
        assert config.provider_config.model == "gemini-2.5-flash"

    def test_all_custom_values(self) -> None:
        """Test all fields set to custom values simultaneously."""
        provider = SecurityAgentProviderConfig(
            provider="claude-sdk",
            model="sonnet",
            model_name="Claude Sonnet",
            thinking=True,
        )
        config = SecurityAgentConfig(
            enabled=False,
            provider_config=provider,
            languages=["rust", "go"],
            max_findings=10,
        )
        assert config.enabled is False
        assert config.provider_config is not None
        assert config.provider_config.display_model == "Claude Sonnet"
        assert config.languages == ["rust", "go"]
        assert config.max_findings == 10


class TestSecurityAgentConfigMaxFindingsValidation:
    """Test max_findings field bounds validation (ge=1, le=100)."""

    def test_max_findings_at_minimum(self) -> None:
        """Test max_findings accepts minimum value of 1."""
        config = SecurityAgentConfig(max_findings=1)
        assert config.max_findings == 1

    def test_max_findings_at_maximum(self) -> None:
        """Test max_findings accepts maximum value of 100."""
        config = SecurityAgentConfig(max_findings=100)
        assert config.max_findings == 100

    def test_max_findings_below_minimum(self) -> None:
        """Test max_findings rejects value below 1."""
        with pytest.raises(ValidationError) as exc_info:
            SecurityAgentConfig(max_findings=0)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("max_findings",) for e in errors)

    def test_max_findings_above_maximum(self) -> None:
        """Test max_findings rejects value above 100."""
        with pytest.raises(ValidationError) as exc_info:
            SecurityAgentConfig(max_findings=101)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("max_findings",) for e in errors)

    def test_max_findings_negative(self) -> None:
        """Test max_findings rejects negative value."""
        with pytest.raises(ValidationError) as exc_info:
            SecurityAgentConfig(max_findings=-5)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("max_findings",) for e in errors)


class TestSecurityAgentConfigFrozen:
    """Test SecurityAgentConfig immutability."""

    def test_frozen_enabled(self) -> None:
        """Test enabled field cannot be mutated."""
        config = SecurityAgentConfig()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]

    def test_frozen_languages(self) -> None:
        """Test languages field cannot be mutated."""
        config = SecurityAgentConfig()
        with pytest.raises(ValidationError):
            config.languages = ["python"]  # type: ignore[misc]

    def test_frozen_max_findings(self) -> None:
        """Test max_findings field cannot be mutated."""
        config = SecurityAgentConfig()
        with pytest.raises(ValidationError):
            config.max_findings = 50  # type: ignore[misc]

    def test_frozen_provider_config(self) -> None:
        """Test provider_config field cannot be mutated."""
        config = SecurityAgentConfig()
        with pytest.raises(ValidationError):
            config.provider_config = SecurityAgentProviderConfig(  # type: ignore[misc]
                provider="claude-sdk", model="haiku"
            )
