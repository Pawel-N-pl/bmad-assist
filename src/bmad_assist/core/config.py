"""Pydantic configuration models and singleton access for bmad-assist.

This module provides type-safe configuration models with validation,
ensuring configuration errors are caught early with clear error messages.

Usage:
    from bmad_assist.core import get_config, load_config, load_global_config

    # Load configuration from file (typical startup)
    load_global_config()  # Loads from ~/.bmad-assist/config.yaml

    # Or load from dictionary (for testing/programmatic use)
    config_dict = {"providers": {"master": {"provider": "claude", "model": "opus_4"}}}
    load_config(config_dict)

    # Access configuration from anywhere
    config = get_config()
    print(config.providers.master.provider)  # "claude"
"""

import copy
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self, cast, get_args, get_origin

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefinedType

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.types import SecurityLevel, WidgetType
from bmad_assist.notifications.config import NotificationConfig
from bmad_assist.testarch.config import TestarchConfig

logger = logging.getLogger(__name__)

# Maximum parent directory levels to search for loop config
MAX_LOOP_CONFIG_PARENT_DEPTH: int = 10

# Constants for global configuration
GLOBAL_CONFIG_PATH: Path = Path.home() / ".bmad-assist" / "config.yaml"
PROJECT_CONFIG_NAME: str = "bmad-assist.yaml"
MAX_CONFIG_SIZE: int = 1_048_576  # 1MB - protection against YAML bombs


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base dictionary.

    Rules:
    - Dicts are merged recursively
    - Lists are replaced (NOT merged/appended)
    - Scalar values are replaced by override
    - Keys only in base are preserved
    - Keys only in override are added

    Args:
        base: Base configuration dictionary.
        override: Override dictionary with higher priority.

    Returns:
        Merged dictionary (new dict, does not modify inputs).

    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


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


class PowerPromptConfig(BaseModel):
    """Power-prompt configuration section.

    Power-prompts are enhanced prompts tailored to specific tech stacks
    and project types.

    Attributes:
        set_name: Name of power-prompt set to use (e.g., "python-cli").
        variables: Custom variables to inject into prompts.

    """

    model_config = ConfigDict(frozen=True)

    set_name: str | None = Field(
        default=None,
        description="Name of power-prompt set to use",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="Custom variables to inject into prompts",
        json_schema_extra={"security": "safe"},
    )


class BmadPathsConfig(BaseModel):
    """Paths to BMAD documentation files.

    These paths point to project documentation that provides context
    for LLM operations.

    All path fields are marked as dangerous and excluded from dashboard schema.

    Attributes:
        prd: Path to Product Requirements Document.
        architecture: Path to Architecture document.
        epics: Path to Epics document.
        stories: Path to Stories directory.

    """

    model_config = ConfigDict(frozen=True)

    prd: str | None = Field(
        default=None,
        description="Path to Product Requirements Document",
        json_schema_extra={"security": "dangerous"},
    )
    architecture: str | None = Field(
        default=None,
        description="Path to Architecture document",
        json_schema_extra={"security": "dangerous"},
    )
    epics: str | None = Field(
        default=None,
        description="Path to Epics document",
        json_schema_extra={"security": "dangerous"},
    )
    stories: str | None = Field(
        default=None,
        description="Path to Stories directory",
        json_schema_extra={"security": "dangerous"},
    )


class ProjectPathsConfig(BaseModel):
    """Project paths configuration for artifact organization.

    Defines the folder structure for planning and implementation artifacts.
    All paths support {project-root} placeholder which is resolved at runtime.

    All path fields are marked as dangerous and excluded from dashboard schema.

    Attributes:
        output_folder: Base output folder for all generated artifacts.
        planning_artifacts: Folder for planning phase artifacts (epics, stories).
        implementation_artifacts: Folder for implementation artifacts (validations, reviews).
        project_knowledge: Folder for project documentation (PRD, architecture).

    """

    model_config = ConfigDict(frozen=True)

    output_folder: str = Field(
        default="{project-root}/_bmad-output",
        description="Base output folder for all generated artifacts",
        json_schema_extra={"security": "dangerous"},
    )
    planning_artifacts: str = Field(
        default="{project-root}/_bmad-output/planning-artifacts",
        description="Folder for planning phase artifacts (epics, stories)",
        json_schema_extra={"security": "dangerous"},
    )
    implementation_artifacts: str = Field(
        default="{project-root}/_bmad-output/implementation-artifacts",
        description="Folder for implementation artifacts (validations, reviews, benchmarks)",
        json_schema_extra={"security": "dangerous"},
    )
    project_knowledge: str = Field(
        default="{project-root}/docs",
        description="Folder for project documentation (PRD, architecture)",
        json_schema_extra={"security": "dangerous"},
    )


class SourceContextBudgetsConfig(BaseModel):
    """Token budgets per workflow for source file collection.

    Budget values:
    - 0-99: Disabled (source context collection skipped)
    - 100+: Active budget in tokens

    Attributes:
        code_review: Budget for code review workflow.
        code_review_synthesis: Budget for code review synthesis.
        create_story: Budget for create-story workflow.
        dev_story: Budget for dev-story workflow.
        validate_story: Budget for validate-story (disabled by default).
        validate_story_synthesis: Budget for synthesis (disabled by default).
        default: Fallback for unlisted workflows.

    """

    model_config = ConfigDict(frozen=True)

    code_review: int = Field(
        default=15000,
        ge=0,
        description="Token budget for code_review workflow (0-99 = disabled)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    code_review_synthesis: int = Field(
        default=15000,
        ge=0,
        description="Token budget for code_review_synthesis workflow",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    create_story: int = Field(
        default=20000,
        ge=0,
        description="Token budget for create_story workflow",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    dev_story: int = Field(
        default=20000,
        ge=0,
        description="Token budget for dev_story workflow",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    validate_story: int = Field(
        default=10000,
        ge=0,
        description="Token budget for validate_story workflow",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    validate_story_synthesis: int = Field(
        default=10000,
        ge=0,
        description="Token budget for validate_story_synthesis workflow",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    default: int = Field(
        default=20000,
        ge=0,
        description="Fallback budget for unlisted workflows",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )

    def get_budget(self, workflow_name: str) -> int:
        """Get budget for a workflow by name.

        Args:
            workflow_name: Name of the workflow (e.g., 'code_review').

        Returns:
            Token budget for the workflow, or default if not found.

        """
        # Normalize name (replace hyphens with underscores)
        normalized = workflow_name.replace("-", "_")
        return getattr(self, normalized, self.default)


class SourceContextScoringConfig(BaseModel):
    """Scoring weights for file prioritization.

    Higher scores = more likely to be included in source context.

    Attributes:
        in_file_list: Bonus for files in story's File List.
        in_git_diff: Bonus for files in git diff.
        is_test_file: Penalty for test files (usually negative).
        is_config_file: Penalty for config files (usually negative).
        change_lines_factor: Points per changed line in git diff.
        change_lines_cap: Max points from change_lines.

    """

    model_config = ConfigDict(frozen=True)

    in_file_list: int = Field(
        default=50,
        description="Bonus points for files in story's File List section",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    in_git_diff: int = Field(
        default=50,
        description="Bonus points for files in git diff",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    is_test_file: int = Field(
        default=-10,
        description="Points for test files (negative = penalty)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    is_config_file: int = Field(
        default=-5,
        description="Points for config files (negative = penalty)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    change_lines_factor: int = Field(
        default=1,
        ge=0,
        description="Points per changed line in git diff",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    change_lines_cap: int = Field(
        default=50,
        ge=0,
        description="Max points from change_lines",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )


class SourceContextExtractionConfig(BaseModel):
    """Content extraction settings for source files.

    Controls adaptive mode and hunk extraction behavior.

    Attributes:
        adaptive_threshold: Threshold for full vs hunk extraction.
            If file_tokens > (budget/files)*threshold → extract hunks only.
        hunk_context_lines: Minimum context lines around changes.
        hunk_context_scale: Scale factor for context calculation.
        max_files: Hard cap on files included (prevents budget dilution).

    """

    model_config = ConfigDict(frozen=True)

    adaptive_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Threshold: file_tokens > (budget/files)*threshold → hunks only",
        json_schema_extra={"security": "safe", "ui_widget": "slider"},
    )
    hunk_context_lines: int = Field(
        default=20,
        ge=1,
        description="Minimum context lines around each change",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    hunk_context_scale: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Context = max(hunk_context_lines, changes * scale)",
        json_schema_extra={"security": "safe", "ui_widget": "slider"},
    )
    max_files: int = Field(
        default=15,
        ge=1,
        description="Max files included (prevents budget dilution)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )


class SourceContextConfig(BaseModel):
    """Source context collection configuration.

    Controls how source files are collected and prioritized
    for inclusion in compiled workflow prompts.

    Attributes:
        budgets: Per-workflow token budgets.
        scoring: File prioritization weights.
        extraction: Content extraction settings.

    """

    model_config = ConfigDict(frozen=True)

    budgets: SourceContextBudgetsConfig = Field(
        default_factory=SourceContextBudgetsConfig,
        description="Per-workflow token budgets",
    )
    scoring: SourceContextScoringConfig = Field(
        default_factory=SourceContextScoringConfig,
        description="File prioritization weights",
    )
    extraction: SourceContextExtractionConfig = Field(
        default_factory=SourceContextExtractionConfig,
        description="Content extraction settings",
    )


class CompilerConfig(BaseModel):
    """Compiler configuration section.

    Configuration options for the BMAD workflow compiler.

    Attributes:
        patch_path: Custom path to patch files directory.
            Relative paths are resolved from project root.
            Defaults to {project}/.bmad-assist/patches.
        source_context: Source file collection configuration.

    """

    model_config = ConfigDict(frozen=True)

    patch_path: str | None = Field(
        default=None,
        description="Custom path to patch files directory",
        json_schema_extra={"security": "dangerous"},
    )
    source_context: SourceContextConfig = Field(
        default_factory=SourceContextConfig,
        description="Source file collection configuration",
    )


class TimeoutsConfig(BaseModel):
    """Per-phase timeout configuration.

    Allows configuring different timeouts for different workflow phases.
    If a phase-specific timeout is not set, falls back to default.

    Attributes:
        default: Default timeout for all phases (seconds).
        create_story: Timeout for create_story phase.
        validate_story: Timeout for validate_story phase.
        validate_story_synthesis: Timeout for validate_story_synthesis phase.
        dev_story: Timeout for dev_story phase.
        code_review: Timeout for code_review phase.
        code_review_synthesis: Timeout for code_review_synthesis phase.
        retrospective: Timeout for retrospective phase.

    Example:
        >>> config = TimeoutsConfig(default=3600, validate_story=600, code_review=900)
        >>> config.get_timeout("validate_story")
        600
        >>> config.get_timeout("unknown_phase")
        3600

    """

    model_config = ConfigDict(frozen=True)

    default: int = Field(
        default=3600,
        ge=60,
        description="Default timeout for all phases in seconds",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    create_story: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for create_story phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    validate_story: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for validate_story phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    validate_story_synthesis: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for validate_story_synthesis phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    dev_story: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for dev_story phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    code_review: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for code_review phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    code_review_synthesis: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for code_review_synthesis phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    retrospective: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for retrospective phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )

    def get_timeout(self, phase: str) -> int:
        """Get timeout for a specific phase.

        Args:
            phase: Phase name (e.g., 'validate_story', 'code_review').
                   Hyphens are normalized to underscores.

        Returns:
            Phase-specific timeout if set, otherwise default timeout.

        """
        # Normalize phase name (hyphens to underscores)
        normalized = phase.replace("-", "_")
        phase_timeout = getattr(self, normalized, None)
        if phase_timeout is not None:
            return phase_timeout
        return self.default


class BenchmarkingConfig(BaseModel):
    """Benchmarking/metrics extraction configuration.

    Controls how metrics are extracted from validator outputs.

    Attributes:
        enabled: Enable automatic metrics collection during validation.
        extraction_provider: LLM provider for metrics extraction.
        extraction_model: Model for extraction (should be fast/cheap).

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable automatic metrics collection during validation",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    extraction_provider: str = Field(
        default="claude",
        description="LLM provider for metrics extraction (e.g., 'claude', 'anthropic-sdk')",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )
    extraction_model: str = Field(
        default="haiku",
        description="Model for extraction (e.g., 'haiku', 'claude-3-5-haiku-latest')",
        json_schema_extra={"security": "risky", "ui_widget": "dropdown"},
    )


class PlaywrightServerConfig(BaseModel):
    """Playwright server management configuration.

    Controls automatic server startup/shutdown for E2E tests.

    Attributes:
        command: Shell command to start the server (e.g., "npm run dev").
            Empty string means no auto-start (server must be running).
        startup_timeout: Seconds to wait for server to be ready.
        reuse_existing: If True, skip starting if server already running.

    """

    model_config = ConfigDict(frozen=True)

    command: str = Field(
        default="",
        description="Shell command to start server (empty = no auto-start)",
        json_schema_extra={"security": "risky", "ui_widget": "text"},
    )
    startup_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Seconds to wait for server to be ready",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    reuse_existing: bool = Field(
        default=True,
        description="Skip starting if server already running at base_url",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )


class PlaywrightConfig(BaseModel):
    """Playwright E2E test configuration.

    Attributes:
        base_url: Base URL for Playwright tests (e.g., "http://localhost:8765").
        server: Server management configuration.
        headless: Run tests in headless mode (default True).
        timeout: Test timeout in seconds.
        screenshot: When to capture screenshots.
        video: When to capture video recordings.
        trace: When to capture execution traces.

    """

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(
        default="http://localhost:3000",
        description="Base URL for Playwright tests",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    server: PlaywrightServerConfig = Field(default_factory=PlaywrightServerConfig)
    headless: bool = Field(
        default=True,
        description="Run tests in headless mode",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    timeout: int = Field(
        default=300,
        ge=10,
        le=1800,
        description="Test execution timeout in seconds",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    screenshot: str = Field(
        default="only-on-failure",
        description="Screenshot capture: off, on, only-on-failure",
        json_schema_extra={
            "security": "safe",
            "ui_widget": "dropdown",
            "options": ["off", "on", "only-on-failure"],
        },
    )
    video: str = Field(
        default="retain-on-failure",
        description="Video recording: off, on, retain-on-failure, on-first-retry",
        json_schema_extra={
            "security": "safe",
            "ui_widget": "dropdown",
            "options": ["off", "on", "retain-on-failure", "on-first-retry"],
        },
    )
    trace: str = Field(
        default="retain-on-failure",
        description="Trace capture: off, on, retain-on-failure, on-first-retry",
        json_schema_extra={
            "security": "safe",
            "ui_widget": "dropdown",
            "options": ["off", "on", "retain-on-failure", "on-first-retry"],
        },
    )


class QAConfig(BaseModel):
    """QA execution configuration.

    Configuration for automated test execution including Playwright E2E tests.

    Attributes:
        check_on_startup: Check for missing QA plans on startup.
        generate_after_retro: Generate QA plan after retrospective.
        qa_artifacts_path: Output path for QA artifacts.
        playwright: Playwright E2E test configuration.

    """

    model_config = ConfigDict(frozen=True)

    check_on_startup: bool = Field(
        default=True,
        description="Check for missing QA plans on startup",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    generate_after_retro: bool = Field(
        default=True,
        description="Generate QA plan after retrospective",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    qa_artifacts_path: str = Field(
        default="{project-root}/_bmad-output/qa-artifacts",
        description="Output path for QA artifacts",
        json_schema_extra={"security": "dangerous"},
    )
    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)


class LoopConfig(BaseModel):
    """Development loop phase configuration.

    Defines the phases that run at different scopes in the development loop.
    This is the declarative configuration for workflow ordering.

    All phase names use snake_case to match Phase enum values exactly
    (e.g., "create_story", NOT "create-story").

    Attributes:
        epic_setup: Phases to run once at the start of each epic
            (before first story's CREATE_STORY). Example: ["testarch_setup"]
        story: Phases to run for each story in sequence.
            Standard: ["create_story", "validate_story", "validate_story_synthesis",
                      "dev_story", "code_review", "code_review_synthesis"]
        epic_teardown: Phases to run once at the end of each epic
            (after last story's CODE_REVIEW_SYNTHESIS). Example: ["retrospective"]

    Example:
        >>> config = LoopConfig(
        ...     epic_setup=[],
        ...     story=["create_story", "dev_story"],
        ...     epic_teardown=["retrospective"]
        ... )
        >>> "create_story" in config.story
        True

    Raises:
        ValueError: If story list is empty (must have at least one phase).

    """

    model_config = ConfigDict(frozen=True)

    epic_setup: list[str] = Field(
        default_factory=list,
        description="Phases to run once at the start of each epic",
    )
    story: list[str] = Field(
        default_factory=list,
        description="Phases to run for each story in sequence",
    )
    epic_teardown: list[str] = Field(
        default_factory=list,
        description="Phases to run once at the end of each epic",
    )

    @model_validator(mode="after")
    def validate_non_empty_story(self) -> Self:
        """Validate that story list is non-empty.

        An empty story list would cause the loop to have nothing to execute,
        which is always an error in the loop configuration.
        """
        if not self.story:
            raise ValueError("LoopConfig.story must contain at least one phase")
        return self


# Default loop configuration when no loop config found in any config file
DEFAULT_LOOP_CONFIG: LoopConfig = LoopConfig(
    epic_setup=[],
    story=[
        "create_story",
        "validate_story",
        "validate_story_synthesis",
        "dev_story",
        "code_review",
        "code_review_synthesis",
    ],
    epic_teardown=["retrospective"],
)


class SprintConfig(BaseModel):
    """Sprint-status management configuration.

    Controls sprint-status repair behavior including divergence thresholds,
    dialog timeouts, and module story prefixes.

    Attributes:
        divergence_threshold: Threshold for interactive repair dialog (0.3 = 30%).
            When divergence exceeds this, INTERACTIVE mode shows confirmation dialog.
        dialog_timeout_seconds: Timeout for repair dialog before auto-cancel.
            Range: 5-300 seconds. Default: 60 seconds.
        module_prefixes: Prefixes for module story classification.
            Stories with these prefixes are treated as MODULE_STORY entries.
        auto_repair: Enable silent auto-repair after phase completions.
        preserve_unknown: Never delete unknown entries during reconciliation.

    Example:
        >>> config = SprintConfig(
        ...     divergence_threshold=0.25,
        ...     dialog_timeout_seconds=30,
        ... )
        >>> config.divergence_threshold
        0.25

    """

    model_config = ConfigDict(frozen=True)

    divergence_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Threshold for interactive repair dialog (0.3 = 30%)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    dialog_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Timeout for repair dialog before auto-cancel (5-300 seconds)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    module_prefixes: list[str] = Field(
        default_factory=lambda: ["testarch", "guardian"],
        description="Prefixes for module story classification",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    auto_repair: bool = Field(
        default=True,
        description="Enable silent auto-repair after phase completions",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    preserve_unknown: bool = Field(
        default=True,
        description="Never delete unknown entries during reconciliation",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )


class WarningsConfig(BaseModel):
    """Warning suppression configuration."""

    model_config = ConfigDict(frozen=True)

    suppress_gitignore: bool = Field(
        default=False,
        description="Suppress gitignore configuration warnings during run/init",
        json_schema_extra={"security": "safe", "ui_widget": "checkbox"},
    )


class Config(BaseModel):
    """Main bmad-assist configuration model.

    This is the root configuration model that composes all nested
    configuration sections.

    Migration Notes (v6.0.0+):
        The `providers.helper` section is now the single source of truth for
        secondary LLM tasks (metrics extraction, summarization, eligibility).
        Old config paths are deprecated but still work:
        - `benchmarking.extraction_provider`/`extraction_model` → use `providers.helper`
        - `testarch.eligibility.provider`/`model` → use `providers.helper`

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


# Module-level singleton for configuration
_config: Config | None = None


def get_phase_timeout(config: Config, phase: str) -> int:
    """Get timeout for a specific workflow phase.

    Provides backward-compatible timeout resolution:
    1. If config.timeouts is set, use phase-specific or default timeout
    2. Otherwise, fall back to legacy config.timeout

    Args:
        config: Application configuration.
        phase: Phase name (e.g., 'validate_story', 'code_review').
               Hyphens are normalized to underscores.

    Returns:
        Timeout in seconds for the specified phase.

    Example:
        >>> timeout = get_phase_timeout(config, "validate_story")
        >>> timeout = get_phase_timeout(config, "code_review")
        >>> # Hyphens also work: get_phase_timeout(config, "code-review")

    """
    if config.timeouts is not None:
        return config.timeouts.get_timeout(phase)
    return config.timeout


def load_config(config_data: dict[str, Any]) -> Config:
    """Load and validate configuration from a dictionary.

    This function validates the configuration dictionary using Pydantic models
    and stores the result in a module-level singleton. File loading (YAML)
    will be added in Story 1.3, which will call this function after parsing.

    Args:
        config_data: Configuration dictionary to validate.

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If config_data is not a dict or validation fails.

    """
    global _config
    if not isinstance(config_data, dict):
        raise ConfigError(f"config_data must be a dict, got {type(config_data).__name__}")
    try:
        _config = Config.model_validate(config_data)
        return _config
    except ValidationError as e:
        _config = None
        raise ConfigError(f"Configuration validation failed: {e}") from e


def get_config() -> Config:
    """Get the loaded configuration singleton.

    Returns:
        The loaded Config instance.

    Raises:
        ConfigError: If config has not been loaded yet.

    """
    if _config is None:
        raise ConfigError("Config not loaded. Call load_config() first.")
    return _config


def _reset_config() -> None:
    """Reset config singleton for testing purposes only.

    This function should only be used in tests to ensure clean state
    between test cases.
    """
    global _config
    _config = None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file with safety checks.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML content as dictionary.

    Raises:
        ConfigError: If file cannot be read, is too large, is empty,
            is a directory, or YAML is invalid.

    """
    try:
        # Read with size limit to avoid TOCTOU vulnerability
        # (stat-then-read allows file swap between calls)
        with path.open("r", encoding="utf-8") as f:
            content = f.read(MAX_CONFIG_SIZE + 1)

        if len(content) > MAX_CONFIG_SIZE:
            raise ConfigError(
                f"Config file {path} exceeds 1MB limit "
                f"(read {len(content):,} bytes before stopping)."
            )

        parsed = yaml.safe_load(content)

        # Explicit empty file detection for better error messages
        if parsed is None:
            raise ConfigError(
                f"Config file {path} is empty or contains only whitespace. "
                f"At minimum, the 'providers.master' section must be present."
            )

        if not isinstance(parsed, dict):
            raise ConfigError(
                f"Config file {path} must contain a YAML mapping, got {type(parsed).__name__}."
            )

        return parsed
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e
    except IsADirectoryError as e:
        raise ConfigError(f"{path} is a directory, not a config file.") from e
    except PermissionError as e:
        raise ConfigError(f"Permission denied reading {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Cannot read config file {path}: {e}") from e


def load_global_config(path: str | Path | None = None) -> Config:
    """Load global configuration from YAML file.

    Loads configuration from the specified path or the default global
    config location (~/.bmad-assist/config.yaml). The YAML content is
    validated against Pydantic models and stored in the module singleton.

    Args:
        path: Optional custom path to config file (string or Path object).
            Strings with ~ are expanded. Defaults to ~/.bmad-assist/config.yaml

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If file doesn't exist, cannot be read, is too large,
            contains invalid YAML, or fails validation.

    Example:
        >>> load_global_config()  # Uses default ~/.bmad-assist/config.yaml
        Config(providers=...)

        >>> load_global_config("/custom/config.yaml")  # Custom string path
        Config(providers=...)

        >>> load_global_config(Path.home() / "my-config.yaml")  # Path object
        Config(providers=...)

    """
    global _config

    config_path = GLOBAL_CONFIG_PATH if path is None else Path(path).expanduser()

    if not config_path.exists():
        raise ConfigError(
            f"Global config not found at {config_path}.\nRun 'bmad-assist init' to create one."
        )

    if not config_path.is_file():
        raise ConfigError(f"Config path {config_path} exists but is not a file.")

    try:
        config_data = _load_yaml_file(config_path)
    except ConfigError:
        # Clear singleton on YAML parse error to prevent stale state
        _config = None
        raise

    try:
        return load_config(config_data)
    except ConfigError as e:
        # Singleton already cleared by load_config on validation failure
        # Re-raise with path context
        raise ConfigError(f"Invalid configuration in {config_path}: {e}") from e


def _load_project_config(project_path: Path) -> dict[str, Any] | None:
    """Load project configuration from a directory.

    Attempts to load bmad-assist.yaml from the specified project directory.
    Returns None if the file doesn't exist (not an error).

    Args:
        project_path: Path to project directory (must be a directory).

    Returns:
        Parsed configuration dictionary, or None if file doesn't exist.

    Raises:
        ConfigError: If file exists but contains invalid YAML.
            Error message includes "project config" to distinguish from global config errors.

    """
    config_file = project_path / PROJECT_CONFIG_NAME

    if not config_file.exists():
        return None

    if not config_file.is_file():
        raise ConfigError(f"Project config path {config_file} exists but is not a file.")

    try:
        return _load_yaml_file(config_file)
    except ConfigError as e:
        # Re-raise with "project config" prefix to distinguish from global config errors
        raise ConfigError(f"Failed to parse project config at {config_file}: {e}") from e


def load_config_with_project(
    project_path: str | Path | None = None,
    *,
    global_config_path: str | Path | None = None,
    cwd_config_path: str | Path | None | Literal[False] = None,
) -> Config:
    """Load configuration with three-tier hierarchy support.

    Configuration is loaded and merged from three sources (in order of precedence):
    1. Global: ~/.bmad-assist/config.yaml (base defaults)
    2. CWD: {cwd}/bmad-assist.yaml (workspace-level overrides, if different from project)
    3. Project: {project_path}/bmad-assist.yaml (project-specific overrides)

    This allows running `bmad-assist run --project experiments/fixtures/foo` from
    the main bmad-assist directory and having the main bmad-assist.yaml config
    apply, with fixture-specific overrides taking precedence.

    Also loads environment variables from {project_path}/.env before config
    validation, so CLI providers can use credentials immediately.

    Args:
        project_path: Path to project directory. Defaults to current working directory.
            MUST be a directory, not a file.
        global_config_path: Custom global config path (for testing).
        cwd_config_path: CWD config path override. Use False to disable CWD tier
            entirely (for testing). Defaults to None (auto-detect from cwd).

    Returns:
        Validated Config instance with merged configuration.

    Raises:
        ConfigError: If no config exists at any tier, if config is invalid YAML,
            if project_path is not a directory, or if Pydantic validation fails.
            Error messages list which config sources were merged.

    Example:
        >>> # From /home/user/bmad-assist-22 with bmad-assist.yaml
        >>> load_config_with_project("experiments/fixtures/simple")
        # Merges: global <- cwd (bmad-assist.yaml) <- project (if exists)

        >>> load_config_with_project()  # Uses cwd as project path
        Config(providers=...)

    """
    global _config

    # Resolve project path
    resolved_project = Path.cwd() if project_path is None else Path(project_path).expanduser()

    # Load .env file BEFORE config validation (AC9: env vars available for CLI providers)
    # This is done early so credentials are available even if config fails
    if resolved_project.exists() and resolved_project.is_dir():
        load_env_file(resolved_project)

    # Validate project_path is a directory
    if resolved_project.exists() and not resolved_project.is_dir():
        raise ConfigError(f"project_path must be a directory, got file: {resolved_project}")

    # Resolve global config path
    resolved_global = (
        GLOBAL_CONFIG_PATH if global_config_path is None else Path(global_config_path).expanduser()
    )

    # Check existence - three-tier hierarchy:
    # 1. Global (~/.bmad-assist/config.yaml) - base defaults
    # 2. CWD (current working directory) - workspace-level overrides
    # 3. Project (--project flag) - project-specific overrides
    global_exists = resolved_global.exists() and resolved_global.is_file()

    # CWD config (only if different from project and not disabled)
    cwd_exists = False
    resolved_cwd_config: Path | None = None
    if cwd_config_path is not False:  # False = disabled entirely
        if cwd_config_path is not None:
            # Custom path provided (for testing)
            resolved_cwd_config = Path(cwd_config_path).expanduser()
        else:
            # Auto-detect from cwd
            cwd_path = Path.cwd()
            resolved_cwd_config = cwd_path / PROJECT_CONFIG_NAME
            # Only use if different from project path (don't load twice)
            if cwd_path.resolve() == resolved_project.resolve():
                resolved_cwd_config = None

        if resolved_cwd_config is not None:
            cwd_exists = resolved_cwd_config.exists() and resolved_cwd_config.is_file()

    project_config_path = resolved_project / PROJECT_CONFIG_NAME
    project_exists = project_config_path.exists() and project_config_path.is_file()

    # Handle no config scenario
    if not global_exists and not cwd_exists and not project_exists:
        raise ConfigError("No configuration found. Run 'bmad-assist init' to create config.")

    global_data: dict[str, Any] = {}
    cwd_data: dict[str, Any] | None = None
    project_data: dict[str, Any] | None = None

    # Load global config if exists (tier 1 - base)
    if global_exists:
        try:
            global_data = _load_yaml_file(resolved_global)
        except ConfigError as e:
            # Clear singleton on YAML parse error to prevent stale state
            _config = None
            raise ConfigError(f"Failed to parse global config at {resolved_global}: {e}") from e

    # Load CWD config if exists (tier 2 - workspace overrides)
    if cwd_exists and resolved_cwd_config is not None:
        try:
            cwd_data = _load_yaml_file(resolved_cwd_config)
            logger.debug("Loaded CWD config from %s", resolved_cwd_config)
        except ConfigError as e:
            _config = None
            raise ConfigError(f"Failed to parse CWD config at {resolved_cwd_config}: {e}") from e

    # Load project config if exists (tier 3 - project overrides)
    if project_exists:
        try:
            project_data = _load_project_config(resolved_project)
            logger.debug("Loaded project config from %s", project_config_path)
        except ConfigError:
            # Clear singleton on YAML parse error to prevent stale state
            _config = None
            raise

    # Merge configurations: global <- cwd <- project
    merged_data = global_data
    if cwd_data is not None:
        merged_data = _deep_merge(merged_data, cwd_data)
    if project_data is not None:
        merged_data = _deep_merge(merged_data, project_data)

    # Validate and load
    try:
        return load_config(merged_data)
    except ConfigError as e:
        # Singleton already cleared by load_config on validation failure
        # Build descriptive error message based on which configs were loaded
        sources = []
        if global_exists:
            sources.append(f"global ({resolved_global})")
        if cwd_exists and resolved_cwd_config is not None:
            sources.append(f"CWD ({resolved_cwd_config})")
        if project_exists:
            sources.append(f"project ({project_config_path})")

        if len(sources) > 1:
            raise ConfigError(f"Invalid configuration (merged from {' + '.join(sources)})") from e
        elif sources:
            raise ConfigError(f"Invalid configuration in {sources[0]}") from e
        else:
            raise ConfigError("Invalid configuration") from e


# =============================================================================
# Story 1.5: Credentials Security with .env
# =============================================================================

# Known credential environment variable names (AC7)
# Note: API keys (ANTHROPIC, OPENAI, GEMINI) are NOT used by bmad-assist.
# bmad-assist orchestrates CLI tools which handle their own authentication.
# These are notification credentials used by the notification system.
ENV_CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DISCORD_WEBHOOK_URL",
    }
)

# .env file name constant
ENV_FILE_NAME: str = ".env"


def _mask_credential(value: str | None) -> str:
    """Mask credential value for safe logging.

    Args:
        value: Credential value to mask. None values are handled gracefully.

    Returns:
        Masked value showing only first 7 characters + "***",
        or "***" if value is None, empty, or 7 characters or shorter.

    """
    if not value:
        return "***"
    if len(value) <= 7:
        return "***"
    return value[:7] + "***"


def _check_env_file_permissions(path: Path) -> None:
    """Check if .env file has secure permissions (600 or 400 on Unix).

    Only checks on Unix-like systems (Linux, macOS).
    Logs warning if permissions are too permissive.
    Accepts both 0600 (owner read-write) and 0400 (owner read-only).

    Args:
        path: Path to .env file.

    """
    if sys.platform == "win32":
        return  # Windows has different permission model

    try:
        mode = path.stat().st_mode & 0o777
        # Accept 0600 (rw owner) or 0400 (r owner) - both secure
        if mode not in (0o600, 0o400):
            logger.warning(
                ".env file %s has insecure permissions %03o, "
                "expected 600 or 400. Run: chmod 600 %s",
                path,
                mode,
                path,
            )
    except OSError:
        pass  # File may have been deleted between check and stat


def load_env_file(
    project_path: str | Path | None = None,
    *,
    check_permissions: bool = True,
) -> bool:
    """Load environment variables from .env file.

    Loads environment variables from {project_path}/.env or {cwd}/.env.
    Does NOT override existing environment variables (override=False).

    Args:
        project_path: Path to project directory. Defaults to current working directory.
        check_permissions: Whether to check file permissions (default True).

    Returns:
        True if .env file was found and loaded, False otherwise.

    Note:
        - Missing .env file is not an error (returns False)
        - On Unix, warns if permissions are not 600
        - On Windows, permission check is skipped

    """
    # Resolve project path
    resolved_path = Path.cwd() if project_path is None else Path(project_path).expanduser()

    # Build .env file path
    env_file = resolved_path / ENV_FILE_NAME

    # Check if .env file exists
    if not env_file.exists():
        logger.debug(".env file not found at %s, skipping", env_file)
        return False

    if not env_file.is_file():
        logger.debug(".env path %s is not a file, skipping", env_file)
        return False

    # Check permissions before loading
    if check_permissions:
        _check_env_file_permissions(env_file)

    # Load environment variables - CRITICAL: override=False preserves existing env vars
    load_dotenv(env_file, encoding="utf-8", override=False)
    logger.debug("Loaded environment variables from %s", env_file)

    return True


# =============================================================================
# Story 17.1: Config Schema Export for Dashboard
# =============================================================================

# Default security level for fields without explicit annotation
DEFAULT_SECURITY_LEVEL: SecurityLevel = "safe"


def get_field_security(
    model: type[BaseModel],
    field_name: str,
) -> SecurityLevel:
    """Get security level for a field.

    Resolution order:
    1. Field's explicit json_schema_extra["security"]
    2. Model's model_config default (not yet implemented)
    3. DEFAULT_SECURITY_LEVEL ("safe")

    Args:
        model: Pydantic model class.
        field_name: Name of the field.

    Returns:
        Security level for the field.

    Raises:
        KeyError: If field does not exist on model.

    """
    if field_name not in model.model_fields:
        raise KeyError(f"Field '{field_name}' not found on {model.__name__}")

    field_info = model.model_fields[field_name]
    extra = field_info.json_schema_extra

    if isinstance(extra, dict) and "security" in extra:
        security = extra["security"]
        if security in ("safe", "risky", "dangerous"):
            return cast(SecurityLevel, security)

    return DEFAULT_SECURITY_LEVEL


def get_field_widget(
    model: type[BaseModel],
    field_name: str,
) -> WidgetType:
    """Get UI widget type for a field.

    Resolution order:
    1. Field's explicit json_schema_extra["ui_widget"]
    2. Type-based default:
       - bool → "toggle"
       - int/float → "number"
       - Literal[...] → "dropdown"
       - list[str] → "text"
       - str → "text"

    Args:
        model: Pydantic model class.
        field_name: Name of the field.

    Returns:
        UI widget type for the field.

    Raises:
        KeyError: If field does not exist on model.

    """
    if field_name not in model.model_fields:
        raise KeyError(f"Field '{field_name}' not found on {model.__name__}")

    field_info = model.model_fields[field_name]
    extra = field_info.json_schema_extra

    # Check explicit widget hint
    if isinstance(extra, dict) and "ui_widget" in extra:
        widget = extra["ui_widget"]
        if widget in ("checkbox_group", "toggle", "number", "dropdown", "text", "readonly"):
            return cast(WidgetType, widget)

    # Type-based defaults
    return _infer_widget_from_type(field_info)


def _infer_widget_from_type(field_info: FieldInfo) -> WidgetType:
    """Infer UI widget type from field's Python type annotation."""
    annotation = field_info.annotation

    # Handle Optional types (Union with None)
    origin = get_origin(annotation)
    if origin is type(None):
        return "text"

    # Unwrap Optional[T] to get T
    # For Union types like int | None, get the non-None type
    if hasattr(annotation, "__origin__"):
        args = get_args(annotation)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)

    # bool -> toggle (check before int since bool is subtype of int)
    if annotation is bool:
        return "toggle"

    # int/float -> number
    if annotation in (int, float):
        return "number"

    # Literal -> dropdown
    if origin is not None and origin is not type(None):
        # Check for Literal type
        origin_name = getattr(origin, "__name__", str(origin))
        if "Literal" in origin_name or origin is Literal:
            return "dropdown"
    elif hasattr(annotation, "__origin__"):
        origin_attr = getattr(annotation, "__origin__", None)
        if origin_attr is not None:
            origin_name = getattr(origin_attr, "__name__", str(origin_attr))
            if "Literal" in origin_name:
                return "dropdown"

    # list[str] -> text (unless checkbox_group specified)
    if origin is list:
        return "text"

    # Default to text
    return "text"


def _build_field_schema(
    field_name: str,
    field_info: FieldInfo,
    json_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Build schema entry for a single field.

    Returns None if field has dangerous security level (excluded from schema).
    """
    extra = field_info.json_schema_extra
    security: SecurityLevel = DEFAULT_SECURITY_LEVEL
    ui_widget: WidgetType | None = None
    options: list[str] | None = None
    unit: str | None = None

    if isinstance(extra, dict):
        raw_security = extra.get("security", DEFAULT_SECURITY_LEVEL)
        if raw_security in ("safe", "risky", "dangerous"):
            security = cast(SecurityLevel, raw_security)
        raw_widget = extra.get("ui_widget")
        if raw_widget in ("checkbox_group", "toggle", "number", "dropdown", "text", "readonly"):
            ui_widget = cast(WidgetType, raw_widget)
        raw_options = extra.get("options")
        if isinstance(raw_options, list):
            options = cast(list[str], raw_options)
        raw_unit = extra.get("unit")
        if isinstance(raw_unit, str):
            unit = raw_unit

    # Exclude dangerous fields from schema entirely
    if security == "dangerous":
        return None

    # Get type info from JSON schema
    field_schema = json_schema.get("properties", {}).get(field_name, {})

    result: dict[str, Any] = {
        "type": field_schema.get("type", "string"),
        "security": security,
        "ui_widget": ui_widget or _infer_widget_from_type(field_info),
    }

    # Add optional fields (exclude PydanticUndefined for required fields)
    if (
        field_info.default is not None
        and field_info.default is not ...
        and not isinstance(field_info.default, PydanticUndefinedType)
    ):
        result["default"] = field_info.default
    elif field_info.default_factory is not None:
        try:
            # default_factory may be a type (like list) or a callable
            factory: Any = field_info.default_factory
            result["default"] = factory()
        except Exception:
            pass

    if field_info.description:
        result["description"] = field_info.description

    if options:
        result["options"] = options

    if unit:
        result["unit"] = unit

    # Add constraints from JSON schema
    for constraint in ("minimum", "maximum", "minLength", "maxLength", "enum"):
        if constraint in field_schema:
            result[constraint] = field_schema[constraint]

    return result


def _build_model_schema(
    model: type[BaseModel],
    json_schema: dict[str, Any],
    definitions: dict[str, Any],
) -> dict[str, Any]:
    """Build schema for a Pydantic model, recursively handling nested models."""
    result: dict[str, Any] = {}

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        is_list_of_models = False

        # Get origin for generics (list, Union, etc.)
        origin = get_origin(annotation)

        # Handle Optional[T] -> T (Union with None)
        # But NOT list[T] which also has an origin
        if origin is not None and origin is not list:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                annotation = non_none_args[0]
                origin = get_origin(annotation)

        # Check for list[BaseModel]
        if origin is list:
            list_args = get_args(annotation)
            if list_args:
                item_type = list_args[0]
                if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                    is_list_of_models = True
                    annotation = item_type

        # Check if field is a nested BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            # Get the definition for this model
            model_name = annotation.__name__
            if model_name in definitions:
                nested_schema = definitions[model_name]
            else:
                nested_schema = annotation.model_json_schema()

            nested_result = _build_model_schema(annotation, nested_schema, definitions)
            if nested_result:  # Only add if not all fields are dangerous
                if is_list_of_models:
                    # Wrap in array schema for list[BaseModel]
                    result[field_name] = {
                        "type": "array",
                        "items": nested_result,
                    }
                else:
                    result[field_name] = nested_result
        else:
            field_schema = _build_field_schema(field_name, field_info, json_schema)
            if field_schema is not None:
                result[field_name] = field_schema

    return result


@lru_cache(maxsize=1)
def get_config_schema() -> dict[str, Any]:
    """Get configuration schema with security and UI metadata.

    Returns a nested dictionary structure matching the config hierarchy,
    with security levels and UI widget hints for each field. Fields with
    security level "dangerous" are excluded entirely.

    Returns:
        Nested dictionary with field metadata for dashboard rendering.

    Example:
        >>> schema = get_config_schema()
        >>> schema["benchmarking"]["enabled"]["security"]
        'safe'
        >>> schema["benchmarking"]["enabled"]["ui_widget"]
        'toggle'

    """
    # Get full JSON schema with definitions
    full_schema = Config.model_json_schema()
    definitions = full_schema.get("$defs", {})

    return _build_model_schema(Config, full_schema, definitions)


# =============================================================================
# Story 17.0: Config Reload for Dashboard
# =============================================================================


def reload_config(project_path: Path | None = None) -> Config:
    """Reload configuration singleton without restart.

    This function performs an atomic swap of the global config singleton,
    allowing configuration changes to take effect without restarting
    the application.

    Args:
        project_path: Path to project directory for merging with global config.
            If None, only global config is loaded.

    Returns:
        The new Config instance after reload.

    Raises:
        ConfigError: If configuration loading or validation fails.

    Note:
        - Running tasks continue with old config (Python GC keeps reference)
        - New tasks use new config immediately
        - Thread-safe: uses simple assignment (Python GIL protects)
        - Clears schema cache to ensure fresh schema on next call

    Example:
        >>> reload_config()  # Reload global config only
        Config(providers=...)

        >>> reload_config(Path("/path/to/project"))  # Reload with project override
        Config(providers=...)

    """
    global _config

    if project_path is not None:
        new_config = load_config_with_project(
            project_path=project_path,
            global_config_path=GLOBAL_CONFIG_PATH,
        )
    else:
        new_config = load_global_config(GLOBAL_CONFIG_PATH)

    # Atomic swap of singleton
    _config = new_config

    # Clear schema cache to ensure fresh schema reflects new config
    get_config_schema.cache_clear()

    # Reset loop config singleton so it gets reloaded on next access
    # This is needed because loop config may be defined in the config files
    global _loop_config
    _loop_config = None

    logger.info("Configuration reloaded")

    return _config


# =============================================================================
# Loop Config Loading (Configurable Loop Architecture)
# =============================================================================

# Module-level singleton for loop configuration
_loop_config: LoopConfig | None = None


def _try_load_loop_config_from_yaml(path: Path) -> LoopConfig | None:
    """Attempt to load loop config from a YAML file.

    Returns None if file doesn't exist, doesn't contain 'loop' key,
    or validation fails. Logs warnings on validation failures.

    Args:
        path: Path to YAML file (bmad-assist.yaml or config.yaml).

    Returns:
        LoopConfig if found and valid, None otherwise.

    """
    if not path.exists() or not path.is_file():
        return None

    try:
        data = _load_yaml_file(path)
    except ConfigError as e:
        logger.warning("Failed to parse %s for loop config: %s", path, e)
        return None

    loop_data = data.get("loop")
    if loop_data is None:
        return None

    if not isinstance(loop_data, dict):
        logger.warning("Invalid loop config in %s: expected dict, got %s", path, type(loop_data).__name__)
        return None

    try:
        config = LoopConfig.model_validate(loop_data)
        logger.debug("Loaded loop config from %s", path)
        return config
    except ValidationError as e:
        logger.warning("Loop config validation failed in %s: %s", path, e)
        return None


def load_loop_config(project_path: Path | None = None) -> LoopConfig:
    """Load loop configuration with fallback chain.

    Searches for loop config in the following order:
    1. {project_path}/bmad-assist.yaml → check for 'loop:' key
    2. Parent directories (up to 10 levels) → check for 'loop:' key
    3. ~/.bmad-assist/config.yaml → check for 'loop:' key
    4. DEFAULT_LOOP_CONFIG constant

    Each file is only used if it contains a valid 'loop:' key with valid LoopConfig.
    Invalid YAML or validation errors log warnings and continue to next fallback.

    Detects symlink cycles by tracking visited directories (resolved paths).

    Args:
        project_path: Path to project directory. If None, uses current working directory.

    Returns:
        LoopConfig instance from first valid source, or DEFAULT_LOOP_CONFIG.

    Example:
        >>> config = load_loop_config(Path("/my/project"))
        >>> "create_story" in config.story
        True

    """
    resolved_project = Path.cwd() if project_path is None else Path(project_path).expanduser().resolve()
    visited: set[Path] = set()

    # Step 1: Check project-level bmad-assist.yaml
    if resolved_project.is_dir():
        project_config_path = resolved_project / PROJECT_CONFIG_NAME
        config = _try_load_loop_config_from_yaml(project_config_path)
        if config is not None:
            return config
        visited.add(resolved_project.resolve())

    # Step 2: Search parent directories (up to MAX_LOOP_CONFIG_PARENT_DEPTH levels)
    current = resolved_project.parent.resolve() if resolved_project.is_dir() else resolved_project.resolve()
    depth = 0

    while depth < MAX_LOOP_CONFIG_PARENT_DEPTH:
        # Detect symlink cycle
        if current in visited:
            logger.warning("Symlink cycle detected at %s, stopping parent search", current)
            break

        visited.add(current)

        # Stop at filesystem root
        if current == current.parent:
            break

        parent_config_path = current / PROJECT_CONFIG_NAME
        config = _try_load_loop_config_from_yaml(parent_config_path)
        if config is not None:
            return config

        current = current.parent.resolve()
        depth += 1

    if depth >= MAX_LOOP_CONFIG_PARENT_DEPTH:
        logger.debug("Parent search stopped at max depth %d", MAX_LOOP_CONFIG_PARENT_DEPTH)

    # Step 3: Check global config (~/.bmad-assist/config.yaml)
    global_config_path = GLOBAL_CONFIG_PATH
    config = _try_load_loop_config_from_yaml(global_config_path)
    if config is not None:
        return config

    # Step 4: Use default
    logger.debug("No loop config found, using DEFAULT_LOOP_CONFIG")
    return DEFAULT_LOOP_CONFIG


def get_loop_config() -> LoopConfig:
    """Get the loaded loop configuration singleton.

    For CLI use only - loads and caches loop config on first call.
    Dashboard should call load_loop_config() directly for hot-reload.

    Returns:
        The cached LoopConfig instance.

    Note:
        If config hasn't been loaded yet, loads from current working directory.
        To load from a specific project path, call load_loop_config() first.

    Example:
        >>> config = get_loop_config()
        >>> "create_story" in config.story
        True

    """
    global _loop_config

    if _loop_config is None:
        _loop_config = load_loop_config()

    return _loop_config


def _reset_loop_config() -> None:
    """Reset loop config singleton for testing purposes only.

    This function should only be used in tests to ensure clean state
    between test cases.
    """
    global _loop_config
    _loop_config = None


def set_loop_config(config: LoopConfig) -> None:
    """Set loop config singleton explicitly.

    Used by runner.py to set loop config at startup, ensuring
    all components use the same config instance.

    Args:
        config: LoopConfig instance to set as singleton.

    """
    global _loop_config
    _loop_config = config
