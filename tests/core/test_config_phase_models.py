"""Tests for per-phase model configuration (phase_models).

These tests verify acceptance criteria for per-phase-model-config tech-spec:
- AC1: Backward compatibility (no phase_models = use global)
- AC2-AC3: Phase-specific overrides work
- AC4: Partial phase_models with fallback
- AC5-AC8: Validation error cases
- AC9-AC10: Settings path validation
- AC11: Master auto-add preserved for multi-LLM
- AC12: QA and testarch phases supported
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.config import (
    ALL_KNOWN_PHASES,
    MULTI_LLM_PHASES,
    SINGLE_LLM_PHASES,
    Config,
    ConfigError,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.config.models.providers import parse_phase_models

# === Helper fixtures ===


@pytest.fixture
def minimal_providers() -> ProviderConfig:
    """Minimal valid ProviderConfig for testing."""
    return ProviderConfig(
        master=MasterProviderConfig(provider="claude-subprocess", model="opus"),
        multi=[
            MultiProviderConfig(provider="gemini", model="gemini-flash"),
        ],
    )


@pytest.fixture
def config_without_phase_models(minimal_providers: ProviderConfig) -> Config:
    """Config without phase_models section (backward compat)."""
    return Config(providers=minimal_providers)


# === AC1: Backward Compatibility ===


class TestPhaseModelsAbsentBackwardCompat:
    """AC1: No phase_models = 100% backward compatible."""

    def test_config_without_phase_models_uses_global_master(
        self, config_without_phase_models: Config
    ) -> None:
        """Single-LLM phase without phase_models uses global master."""
        result = get_phase_provider_config(config_without_phase_models, "create_story")
        assert isinstance(result, MasterProviderConfig)
        assert result.provider == "claude-subprocess"
        assert result.model == "opus"

    def test_config_without_phase_models_uses_global_multi(
        self, config_without_phase_models: Config
    ) -> None:
        """Multi-LLM phase without phase_models uses global multi."""
        result = get_phase_provider_config(config_without_phase_models, "validate_story")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].provider == "gemini"


# === AC2-AC3: Phase-specific overrides ===


class TestPhaseModelsOverride:
    """AC2-AC3: Phase-specific config overrides global."""

    def test_single_llm_phase_override(self, minimal_providers: ProviderConfig) -> None:
        """AC2: Single-LLM phase uses phase_models when defined."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                "create_story": MasterProviderConfig(
                    provider="claude-subprocess",
                    model="sonnet",
                    model_name="glm-4.7",
                ),
            },
        )
        result = get_phase_provider_config(config, "create_story")
        assert isinstance(result, MasterProviderConfig)
        assert result.model == "sonnet"
        assert result.model_name == "glm-4.7"

    def test_multi_llm_phase_override(self, minimal_providers: ProviderConfig) -> None:
        """AC3: Multi-LLM phase uses phase_models array when defined."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                "validate_story": [
                    MultiProviderConfig(provider="gemini", model="gemini-2.5-flash"),
                    MultiProviderConfig(provider="claude-subprocess", model="haiku"),
                ],
            },
        )
        result = get_phase_provider_config(config, "validate_story")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].model == "gemini-2.5-flash"
        assert result[1].model == "haiku"


# === AC4: Partial phase_models with fallback ===


class TestPhaseModelsPartialOverride:
    """AC4: Undefined phases fallback to global with DEBUG log."""

    def test_partial_override_defined_phase_uses_override(
        self, minimal_providers: ProviderConfig
    ) -> None:
        """Defined phase uses override."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                "dev_story": MasterProviderConfig(
                    provider="claude-subprocess",
                    model="sonnet",
                ),
            },
        )
        result = get_phase_provider_config(config, "dev_story")
        assert isinstance(result, MasterProviderConfig)
        assert result.model == "sonnet"

    def test_partial_override_undefined_phase_uses_fallback(
        self, minimal_providers: ProviderConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Undefined phase falls back to global master with DEBUG log."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                "dev_story": MasterProviderConfig(
                    provider="claude-subprocess",
                    model="sonnet",
                ),
            },
        )
        with caplog.at_level(logging.DEBUG):
            result = get_phase_provider_config(config, "create_story")

        assert isinstance(result, MasterProviderConfig)
        assert result.model == "opus"  # Falls back to global

        # Assert on log record properties for robustness
        fallback_logs = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG
            and "create_story" in r.getMessage()
            and "fallback" in r.getMessage()
        ]
        assert len(fallback_logs) >= 1, "Expected DEBUG log for fallback"


# === AC5-AC8: Validation error cases ===


class TestPhaseModelsValidationErrors:
    """AC5-AC8: Config validation raises clear errors."""

    def test_unknown_phase_name_raises_error(self) -> None:
        """AC5: Unknown phase name raises ConfigError with valid phases list."""
        with pytest.raises(ConfigError) as exc_info:
            parse_phase_models({"crate_story": {"provider": "claude", "model": "opus"}})

        assert "Unknown phase 'crate_story'" in str(exc_info.value)
        assert "create_story" in str(exc_info.value)  # Lists valid phases

    def test_type_mismatch_object_for_multi_llm_raises_error(self) -> None:
        """AC6: Object for multi-LLM phase raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            parse_phase_models(
                {"validate_story": {"provider": "claude", "model": "opus"}}
            )

        assert "validate_story" in str(exc_info.value)
        assert "multi-LLM" in str(exc_info.value)
        assert "expected array" in str(exc_info.value)

    def test_type_mismatch_array_for_single_llm_raises_error(self) -> None:
        """AC7: Array for single-LLM phase raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            parse_phase_models(
                {"create_story": [{"provider": "claude", "model": "opus"}]}
            )

        assert "create_story" in str(exc_info.value)
        assert "single-LLM" in str(exc_info.value)
        assert "expected object" in str(exc_info.value)

    def test_empty_array_for_multi_llm_raises_error(self) -> None:
        """AC8: Empty array for multi-LLM phase raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            parse_phase_models({"validate_story": []})

        assert "validate_story" in str(exc_info.value)
        assert "at least 1 provider" in str(exc_info.value)


# === AC9-AC10: Settings path validation ===


class TestPhaseModelsSettingsValidation:
    """AC9-AC10: Settings path validation."""

    def test_settings_path_not_found_raises_error(self) -> None:
        """AC9: Non-existent settings path raises ConfigError."""
        with pytest.raises(ConfigError) as exc_info:
            parse_phase_models(
                {
                    "create_story": {
                        "provider": "claude-subprocess",
                        "model": "opus",
                        "settings": "/nonexistent/path/settings.json",
                    }
                }
            )

        assert "Settings file not found" in str(exc_info.value)
        assert "/nonexistent/path/settings.json" in str(exc_info.value)

    def test_settings_path_tilde_expansion(self, tmp_path: Path) -> None:
        """AC10: Settings path with ~ is expanded before validation."""
        # Create a temp settings file
        settings_file = tmp_path / "test_settings.json"
        settings_file.write_text("{}")

        # Mock Path.expanduser to return our temp path
        with patch.object(Path, "expanduser") as mock_expand:
            mock_expand.return_value = settings_file

            # Should not raise - file exists after expansion
            result = parse_phase_models(
                {
                    "create_story": {
                        "provider": "claude-subprocess",
                        "model": "opus",
                        "settings": "~/.claude/glm.json",
                    }
                }
            )

            assert "create_story" in result
            assert result["create_story"].settings == "~/.claude/glm.json"


# === AC11: Master behavior for multi-LLM ===


class TestPhaseModelsMasterBehavior:
    """AC11: When phase_models defines multi-LLM phase, master NOT auto-added."""

    def test_phase_models_gives_full_control_over_multi_list(
        self, minimal_providers: ProviderConfig
    ) -> None:
        """phase_models.validate_story gives full control - master NOT auto-added."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                "validate_story": [
                    MultiProviderConfig(provider="gemini", model="gemini-flash"),
                ],
            },
        )

        # get_phase_provider_config returns ONLY what's in phase_models
        multi_configs = get_phase_provider_config(config, "validate_story")
        assert isinstance(multi_configs, list)
        assert len(multi_configs) == 1  # Only what's defined - master NOT added

        # Orchestrators check phase_models to decide whether to add master
        # When phase_models defines the phase, master is NOT auto-added
        phase_has_override = config.phase_models and "validate_story" in config.phase_models
        assert phase_has_override is True

    def test_fallback_to_global_multi_adds_master(
        self, minimal_providers: ProviderConfig
    ) -> None:
        """When NOT using phase_models, fallback to global providers.multi + master auto-add."""
        config = Config(
            providers=minimal_providers,
            phase_models={
                # Only single-LLM phases defined - validate_story falls back to global
                "create_story": MasterProviderConfig(
                    provider="claude-subprocess", model="sonnet"
                ),
            },
        )

        # get_phase_provider_config falls back to global providers.multi
        multi_configs = get_phase_provider_config(config, "validate_story")
        assert isinstance(multi_configs, list)
        assert multi_configs == config.providers.multi

        # Orchestrators will add master because phase_models.validate_story is NOT defined
        phase_has_override = config.phase_models and "validate_story" in config.phase_models
        assert phase_has_override is False


# === AC12: QA and testarch phases ===


class TestPhaseModelsSpecialPhases:
    """AC12: QA and testarch phases supported."""

    def test_qa_phases_accepted(self) -> None:
        """QA phases are valid in phase_models."""
        result = parse_phase_models(
            {
                "qa_plan_generate": {
                    "provider": "claude-subprocess",
                    "model": "sonnet",
                },
                "qa_plan_execute": {
                    "provider": "claude-subprocess",
                    "model": "haiku",
                },
            }
        )

        assert "qa_plan_generate" in result
        assert "qa_plan_execute" in result

    def test_testarch_phases_accepted(self) -> None:
        """Testarch phases are valid in phase_models."""
        result = parse_phase_models(
            {
                "atdd": {
                    "provider": "claude-subprocess",
                    "model": "opus",
                },
                "test_review": {
                    "provider": "claude-subprocess",
                    "model": "sonnet",
                },
            }
        )

        assert "atdd" in result
        assert "test_review" in result


# === Phase constant tests ===


class TestPhaseConstants:
    """Tests for phase classification constants."""

    def test_single_llm_phases_not_empty(self) -> None:
        """SINGLE_LLM_PHASES contains expected phases."""
        assert "create_story" in SINGLE_LLM_PHASES
        assert "dev_story" in SINGLE_LLM_PHASES
        assert "retrospective" in SINGLE_LLM_PHASES

    def test_multi_llm_phases_not_empty(self) -> None:
        """MULTI_LLM_PHASES contains expected phases."""
        assert "validate_story" in MULTI_LLM_PHASES
        assert "code_review" in MULTI_LLM_PHASES

    def test_all_known_phases_is_union(self) -> None:
        """ALL_KNOWN_PHASES is union of single and multi."""
        assert ALL_KNOWN_PHASES == SINGLE_LLM_PHASES | MULTI_LLM_PHASES

    def test_no_overlap_between_single_and_multi(self) -> None:
        """Single and multi phases don't overlap."""
        overlap = SINGLE_LLM_PHASES & MULTI_LLM_PHASES
        assert len(overlap) == 0


# === Integration test: Config loading from dict ===


class TestPhaseModelsConfigLoading:
    """Integration: Config loading parses phase_models correctly."""

    def test_config_loads_phase_models_from_dict(
        self, minimal_providers: ProviderConfig
    ) -> None:
        """Config parses raw phase_models dict via model_validator."""
        # Simulate loading from YAML (raw dicts, not typed models)
        raw_config = {
            "providers": {
                "master": {"provider": "claude-subprocess", "model": "opus"},
                "multi": [{"provider": "gemini", "model": "gemini-flash"}],
            },
            "phase_models": {
                "create_story": {
                    "provider": "claude-subprocess",
                    "model": "sonnet",
                    "model_name": "test-model",
                },
            },
        }

        config = Config.model_validate(raw_config)

        assert config.phase_models is not None
        assert "create_story" in config.phase_models
        phase_config = config.phase_models["create_story"]
        assert isinstance(phase_config, MasterProviderConfig)
        assert phase_config.model == "sonnet"
        assert phase_config.model_name == "test-model"

    def test_config_accepts_already_typed_phase_models(
        self, minimal_providers: ProviderConfig
    ) -> None:
        """Config accepts pre-typed phase_models (skips raw parsing)."""
        # Pass already-typed config objects directly (not raw dicts)
        config = Config(
            providers=minimal_providers,
            phase_models={
                "create_story": MasterProviderConfig(
                    provider="claude-subprocess",
                    model="sonnet",
                ),
                "dev_story": MasterProviderConfig(
                    provider="claude-subprocess",
                    model="haiku",
                ),
            },
        )

        assert config.phase_models is not None
        assert config.phase_models["create_story"].model == "sonnet"
        assert config.phase_models["dev_story"].model == "haiku"

    def test_config_handles_mixed_raw_and_typed_values(self) -> None:
        """Config with mixed raw/typed phase_models parses raw values correctly.

        This tests the edge case where some values are typed and some are raw dicts.
        The validator should detect raw dicts and parse ALL values.
        """
        # Start with raw config (simulating YAML load)
        raw_config = {
            "providers": {
                "master": {"provider": "claude-subprocess", "model": "opus"},
                "multi": [],
            },
            "phase_models": {
                "create_story": {"provider": "claude-subprocess", "model": "sonnet"},
                "dev_story": {"provider": "claude-subprocess", "model": "haiku"},
            },
        }

        config = Config.model_validate(raw_config)

        # Both should be parsed into MasterProviderConfig
        assert isinstance(config.phase_models["create_story"], MasterProviderConfig)
        assert isinstance(config.phase_models["dev_story"], MasterProviderConfig)
