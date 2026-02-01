"""Provider configuration models for Master, Multi, and Helper LLMs."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from bmad_assist.core.exceptions import ConfigError

if TYPE_CHECKING:
    from bmad_assist.core.config.models.main import Config

logger = logging.getLogger(__name__)

# Phase classification for per-phase model configuration
# Single-LLM phases use MasterProviderConfig (one provider executes)
SINGLE_LLM_PHASES: frozenset[str] = frozenset({
    # Core workflow phases
    "create_story",
    "validate_story_synthesis",
    "dev_story",
    "code_review_synthesis",
    "retrospective",
    # Testarch phases
    "atdd",
    "test_review",
    # QA phases
    "qa_plan_generate",
    "qa_plan_execute",
})

# Multi-LLM phases use list[MultiProviderConfig] (parallel execution)
# NOTE: When phase_models defines a multi-LLM phase, user has FULL control over the list.
# Master is NOT auto-added. When falling back to global providers.multi, master IS auto-added.
MULTI_LLM_PHASES: frozenset[str] = frozenset({
    "validate_story",
    "code_review",
})

# All known phases (union of single and multi)
ALL_KNOWN_PHASES: frozenset[str] = SINGLE_LLM_PHASES | MULTI_LLM_PHASES


class MasterProviderConfig(BaseModel):
    """Configuration for Master LLM provider.

    The Master provider is the primary LLM that can modify files and
    synthesize validation reports.

    Attributes:
        provider: Provider name (e.g., "claude-subprocess", "codex", "gemini").
        model: Model identifier for CLI invocation (e.g., "opus", "sonnet").
        model_name: Display name for the model (e.g., "glm-4.7"). If set,
            used in logs/reports instead of model. Useful when "tricking"
            a CLI to use alternative models.
        settings: Optional path to provider settings JSON file (tilde expanded).

    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        ...,
        description="Provider name: claude-subprocess, codex, gemini",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model: str = Field(
        ...,
        description="Model identifier for CLI: opus, sonnet, etc.",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model_name: str | None = Field(
        None,
        description="Display name for model (used in logs/reports instead of model)",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    settings: str | None = Field(
        None,
        description="Path to provider settings JSON (tilde expanded)",
        json_schema_extra={"security": "dangerous"},
    )

    @property
    def display_model(self) -> str:
        """Return model name for display (model_name if set, else model)."""
        return self.model_name or self.model

    @property
    def settings_path(self) -> Path | None:
        """Return expanded settings path, or None if not set."""
        if self.settings is None:
            return None
        return Path(self.settings).expanduser()


class MultiProviderConfig(BaseModel):
    """Configuration for Multi LLM validator.

    Multi providers are used for parallel validation during
    VALIDATE_STORY and CODE_REVIEW phases.

    Attributes:
        provider: Provider name (e.g., "claude-subprocess", "codex", "gemini").
        model: Model identifier for CLI invocation (e.g., "opus", "sonnet").
        model_name: Display name for the model (e.g., "glm-4.7"). If set,
            used in logs/reports instead of model.
        settings: Optional path to provider settings JSON file (tilde expanded).
        thinking: Enable thinking mode for supported providers (e.g., kimi).
            If None, auto-detected from model name.

    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        ...,
        description="Provider name: claude-subprocess, codex, gemini",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model: str = Field(
        ...,
        description="Model identifier for CLI: opus, sonnet, etc.",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model_name: str | None = Field(
        None,
        description="Display name for model (used in logs/reports instead of model)",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    settings: str | None = Field(
        None,
        description="Path to provider settings JSON (tilde expanded)",
        json_schema_extra={"security": "dangerous"},
    )
    thinking: bool | None = Field(
        None,
        description="Enable thinking mode for supported providers (kimi). None=auto-detect.",
        json_schema_extra={"security": "safe", "ui_widget": "checkbox"},
    )

    @property
    def display_model(self) -> str:
        """Return model name for display (model_name if set, else model)."""
        return self.model_name or self.model

    @property
    def settings_path(self) -> Path | None:
        """Return expanded settings path, or None if not set."""
        if self.settings is None:
            return None
        return Path(self.settings).expanduser()


class HelperProviderConfig(BaseModel):
    """Configuration for Helper LLM provider.

    The Helper provider is used for secondary tasks like metrics extraction,
    summarization, and eligibility assessment. Typically a fast/cheap model.

    Attributes:
        provider: Provider name (e.g., "claude-subprocess", "codex", "gemini").
        model: Model identifier for CLI invocation (e.g., "haiku", "sonnet").
        model_name: Display name for the model (e.g., "glm-4.7"). If set,
            used in logs/reports instead of model. Useful when "tricking"
            a CLI to use alternative models.
        settings: Optional path to provider settings JSON file (tilde expanded).

    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        default="claude",
        description="Provider name: claude-subprocess, codex, gemini",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model: str = Field(
        default="haiku",
        description="Model identifier for CLI: haiku, sonnet, etc.",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    model_name: str | None = Field(
        None,
        description="Display name for model (used in logs/reports instead of model)",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    settings: str | None = Field(
        None,
        description="Path to provider settings JSON (tilde expanded)",
        json_schema_extra={"security": "dangerous"},
    )

    @property
    def display_model(self) -> str:
        """Return model name for display (model_name if set, else model)."""
        return self.model_name or self.model

    @property
    def settings_path(self) -> Path | None:
        """Return expanded settings path, or None if not set."""
        if self.settings is None:
            return None
        return Path(self.settings).expanduser()


class ProviderConfig(BaseModel):
    """Provider configuration section.

    Contains configuration for Master, Multi, and Helper LLM providers.

    Attributes:
        master: Configuration for the Master LLM provider.
        multi: List of Multi LLM validator configurations.
        helper: Configuration for the Helper LLM provider (metrics extraction, summarization, etc.).

    """

    model_config = ConfigDict(frozen=True)

    master: MasterProviderConfig
    multi: list[MultiProviderConfig] = Field(default_factory=list)
    helper: HelperProviderConfig = Field(default_factory=HelperProviderConfig)


# Type alias for phase_models config section
PhaseModelsConfig = dict[str, MasterProviderConfig | list[MultiProviderConfig]]


def parse_phase_models(raw: dict[str, object]) -> PhaseModelsConfig:
    """Parse raw YAML phase_models dict into typed PhaseModelsConfig.

    Validates:
    - Phase name is in ALL_KNOWN_PHASES
    - Type matches phase category (object for single-LLM, array for multi-LLM)
    - Non-empty array for multi-LLM phases
    - Settings path exists if specified

    Args:
        raw: Raw dict from YAML with phase names as keys.

    Returns:
        PhaseModelsConfig with validated MasterProviderConfig or list[MultiProviderConfig].

    Raises:
        ConfigError: If validation fails.

    """
    result: PhaseModelsConfig = {}

    for phase_name, value in raw.items():
        # Validate phase name is known
        if phase_name not in ALL_KNOWN_PHASES:
            valid_list = ", ".join(sorted(ALL_KNOWN_PHASES))
            raise ConfigError(
                f"Unknown phase '{phase_name}' in phase_models. "
                f"Valid phases: {valid_list}"
            )

        # Parse based on phase category
        if phase_name in SINGLE_LLM_PHASES:
            # Single-LLM: expect dict (object)
            if not isinstance(value, dict):
                raise ConfigError(
                    f"Phase '{phase_name}' is single-LLM, expected object not "
                    f"{type(value).__name__}"
                )
            try:
                single_config = MasterProviderConfig(**value)
            except Exception as e:
                raise ConfigError(
                    f"Invalid config for phase '{phase_name}': {e}"
                ) from e
            _validate_settings_path(single_config.settings, phase_name)
            result[phase_name] = single_config

        else:
            # Multi-LLM: expect list (array)
            if not isinstance(value, list):
                raise ConfigError(
                    f"Phase '{phase_name}' is multi-LLM, expected array not "
                    f"{type(value).__name__}"
                )
            if len(value) == 0:
                raise ConfigError(
                    f"Phase '{phase_name}' requires at least 1 provider"
                )
            configs: list[MultiProviderConfig] = []
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    raise ConfigError(
                        f"Phase '{phase_name}' item {i}: expected object not "
                        f"{type(item).__name__}"
                    )
                try:
                    multi_config = MultiProviderConfig(**item)
                except Exception as e:
                    raise ConfigError(
                        f"Invalid config for phase '{phase_name}' item {i}: {e}"
                    ) from e
                _validate_settings_path(multi_config.settings, f"{phase_name}[{i}]")
                configs.append(multi_config)
            result[phase_name] = configs

    return result


def _validate_settings_path(settings: str | None, context: str) -> None:
    """Validate settings path exists if specified.

    Args:
        settings: Settings path string (may contain ~) or None.
        context: Context for error message (e.g., phase name).

    Raises:
        ConfigError: If settings path is specified but doesn't exist.

    """
    if settings is None:
        return

    expanded = Path(settings).expanduser()
    if not expanded.exists():
        raise ConfigError(
            f"Settings file not found: {settings} (in phase_models.{context})"
        )


def get_phase_provider_config(
    config: "Config",
    phase_name: str,
) -> MasterProviderConfig | list[MultiProviderConfig]:
    """Get provider config for a specific phase.

    Resolution order:
    1. phase_models[phase_name] if defined
    2. providers.master (single-LLM) or providers.multi (multi-LLM)

    Logs DEBUG when using fallback.

    Args:
        config: Application Config instance.
        phase_name: Phase name (e.g., "create_story", "validate_story").

    Returns:
        MasterProviderConfig for single-LLM phases,
        list[MultiProviderConfig] for multi-LLM phases.

    """
    if config.phase_models and phase_name in config.phase_models:
        logger.debug(
            "Phase '%s' using phase_models override",
            phase_name,
        )
        return config.phase_models[phase_name]

    # Fallback to global providers
    if phase_name in MULTI_LLM_PHASES:
        logger.debug(
            "Phase '%s' using global multi fallback",
            phase_name,
        )
        return config.providers.multi
    else:
        logger.debug(
            "Phase '%s' using global master fallback",
            phase_name,
        )
        return config.providers.master
