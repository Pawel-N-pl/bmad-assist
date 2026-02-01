"""Main Config model that aggregates all configuration sections."""

from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bmad_assist.core.config.models.features import (
    AntipatternConfig,
    BenchmarkingConfig,
    CompilerConfig,
    QAConfig,
    TimeoutsConfig,
)
from bmad_assist.core.config.models.loop import LoopConfig, SprintConfig, WarningsConfig
from bmad_assist.core.config.models.paths import (
    BmadPathsConfig,
    PowerPromptConfig,
    ProjectPathsConfig,
)
from bmad_assist.core.config.models.providers import (
    PhaseModelsConfig,
    ProviderConfig,
    parse_phase_models,
)
from bmad_assist.notifications.config import NotificationConfig
from bmad_assist.testarch.config import TestarchConfig


class Config(BaseModel):
    """Main bmad-assist configuration model.

    This is the root configuration model that composes all nested
    configuration sections.

    Migration Notes (v6.0.0+):
        The `providers.helper` section is now the single source of truth for
        secondary LLM tasks (metrics extraction, summarization, eligibility).
        Old config paths are deprecated but still work:
        - `benchmarking.extraction_provider`/`extraction_model` -> use `providers.helper`
        - `testarch.eligibility.provider`/`model` -> use `providers.helper`

    Attributes:
        providers: Provider configuration section.
        power_prompts: Power-prompt configuration section.
        state_path: Path to state file, or None to use default (~/.bmad-assist/state.yaml).
            Tilde (~) is expanded to home directory. Use get_state_path() for resolved path.
        timeout: Global timeout for provider operations in seconds.
        bmad_paths: Paths to BMAD documentation files.
        paths: Project paths configuration for artifact organization.
        compiler: Compiler configuration options.
        benchmarking: Benchmarking/metrics extraction configuration.
        notifications: Notification system configuration (optional).
        testarch: Testarch module configuration (optional).
        sprint: Sprint-status management configuration (optional).
        workflow_variant: Workflow variant identifier for A/B testing.

    """

    model_config = ConfigDict(frozen=True)

    providers: ProviderConfig
    phase_models: PhaseModelsConfig | None = Field(
        default=None,
        description="Per-phase provider configuration overrides. "
        "Single-LLM phases accept object {provider, model, model_name?, settings?}. "
        "Multi-LLM phases accept array of objects.",
        json_schema_extra={"security": "risky"},
    )
    power_prompts: PowerPromptConfig = Field(default_factory=PowerPromptConfig)
    state_path: str | None = Field(
        default=None,
        description="Path to state file. If None, defaults to ~/.bmad-assist/state.yaml. "
        "Supports tilde (~) expansion and relative paths.",
        json_schema_extra={"security": "dangerous"},
    )
    timeout: int = Field(
        default=300,
        description="Global timeout for providers in seconds (legacy, prefer timeouts)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    timeouts: TimeoutsConfig | None = Field(
        default=None,
        description="Per-phase timeout configuration (optional, overrides timeout)",
    )
    bmad_paths: BmadPathsConfig = Field(default_factory=BmadPathsConfig)
    paths: ProjectPathsConfig = Field(default_factory=ProjectPathsConfig)
    compiler: CompilerConfig = Field(default_factory=CompilerConfig)
    benchmarking: BenchmarkingConfig = Field(default_factory=BenchmarkingConfig)
    antipatterns: AntipatternConfig = Field(
        default_factory=AntipatternConfig,
        description="Antipatterns extraction and loading configuration",
    )
    notifications: NotificationConfig | None = Field(
        default=None,
        description="Notification system configuration (optional)",
    )
    testarch: TestarchConfig | None = Field(
        default=None,
        description="Testarch module configuration (optional)",
    )
    sprint: SprintConfig | None = Field(
        default=None,
        description="Sprint-status management configuration (optional)",
    )
    qa: QAConfig | None = Field(
        default=None,
        description="QA execution configuration (optional)",
    )
    loop: LoopConfig | None = Field(
        default=None,
        description="Loop phase configuration (optional, uses DEFAULT_LOOP_CONFIG if not set)",
    )
    warnings: WarningsConfig | None = Field(
        default=None,
        description="Warning suppression configuration (optional)",
    )
    workflow_variant: str = Field(
        default="default",
        description="Workflow variant identifier for A/B testing",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    parallel_delay: str | float | None = Field(
        default=1.0,
        description="Delay between parallel LLM calls in seconds. "
        "Float for fixed delay (e.g., 1.0), string for random range (e.g., '0.5-1.5').",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )

    @model_validator(mode="before")
    @classmethod
    def parse_raw_phase_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw phase_models dict into typed config before Pydantic validation.

        Pydantic can't auto-discriminate dict vs list union types, so we need
        to explicitly parse the raw YAML into MasterProviderConfig or
        list[MultiProviderConfig] based on phase category.

        If phase_models values are already typed (e.g., passed directly in code),
        skip parsing and return as-is.
        """
        from bmad_assist.core.config.models.providers import (
            MasterProviderConfig,
            MultiProviderConfig,
        )

        if not isinstance(data, dict):
            return data

        raw_phase_models = data.get("phase_models")
        if raw_phase_models is None:
            return data

        if not isinstance(raw_phase_models, dict):
            return data

        # Check if ALL values are already typed (not raw dicts)
        # If any value is a raw dict, we need to parse; if all typed, skip
        all_typed = True
        for value in raw_phase_models.values():
            if isinstance(value, MasterProviderConfig):
                continue  # Already typed single-LLM
            elif isinstance(value, list) and value and isinstance(value[0], MultiProviderConfig):
                continue  # Already typed multi-LLM
            else:
                # Raw dict or empty list - needs parsing
                all_typed = False
                break

        if all_typed:
            return data

        # Parse raw dicts into typed config
        data["phase_models"] = parse_phase_models(raw_phase_models)

        return data

    @model_validator(mode="after")
    def expand_state_path(self) -> Self:
        """Expand ~ to user home directory in state_path.

        Only expands user home (~) - does not modify relative paths.
        Uses model_validator to ensure default values are also processed.
        Skips expansion if state_path is None (uses default via get_state_path).
        """
        if self.state_path is not None and self.state_path.startswith("~"):
            # Use object.__setattr__ since model is frozen
            object.__setattr__(self, "state_path", str(Path(self.state_path).expanduser()))
        return self


def _rebuild_models_for_forward_refs() -> None:
    """Rebuild models to resolve forward references.

    TestarchConfig has a forward reference to TEAContextConfig which
    needs to be resolved. We do this here after all modules are loaded.
    """
    from bmad_assist.testarch.context.config import TEAContextConfig

    TestarchConfig.model_rebuild(_types_namespace={"TEAContextConfig": TEAContextConfig})


# Resolve forward references after all models are defined
_rebuild_models_for_forward_refs()
