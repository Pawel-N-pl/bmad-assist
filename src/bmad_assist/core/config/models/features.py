"""Feature configuration models (Compiler, Timeouts, Benchmarking, QA, Stream)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bmad_assist.core.config.models.source_context import SourceContextConfig
from bmad_assist.core.config.models.strategic_context import StrategicContextConfig


class StreamConfig(BaseModel):
    """LLM stream output configuration.

    Controls how much LLM streaming output is shown during runs.
    Can be overridden by CLI flags (--stream, --stream-chars).

    Attributes:
        mode: Stream mode - 'off' (default), 'preview' (truncated), or 'full' (all output).
        preview_chars: Characters to show in preview mode (min 10).

    Example YAML:
        stream:
          mode: preview
          preview_chars: 200

    """

    model_config = ConfigDict(frozen=True)

    mode: Literal["off", "preview", "full"] = Field(
        default="off",
        description="Stream mode: 'off' = no streaming, "
        "'preview' = truncated previews, 'full' = all output",
    )
    preview_chars: int = Field(
        default=150,
        ge=10,
        description="Characters to show in stream preview mode (min 10)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )


class CompilerConfig(BaseModel):
    """Compiler configuration section.

    Configuration options for the BMAD workflow compiler.

    Attributes:
        patch_path: Custom path to patch files directory.
            Relative paths are resolved from project root.
            Defaults to {project}/.bmad-assist/patches.
        source_context: Source file collection configuration.
        strategic_context: Strategic document loading configuration.
            If None, legacy behavior (load all docs). Use {} for optimized defaults.

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
    strategic_context: StrategicContextConfig | None = Field(
        default=None,
        description="Strategic document loading config. None = legacy behavior (all docs).",
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
    security_review: int | None = Field(
        default=600,
        ge=60,
        description="Timeout for security review agent (default 600s, separate from code_review)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    qa_plan_generate: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for qa_plan_generate phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    qa_plan_execute: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for qa_plan_execute phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    qa_remediate: int | None = Field(
        default=None,
        ge=60,
        description="Timeout for qa_remediate phase (None = use default)",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "s"},
    )
    retries: int | None = Field(
        default=None,
        ge=0,
        description="Retry provider invocation on timeout (None = skip retry, 0 = infinite, N = specific count)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
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
        phase_timeout: int | None = getattr(self, normalized, None)
        if phase_timeout is not None:
            return phase_timeout
        return self.default

    def get_retries(self, phase: str) -> int | None:
        """Get retry count for a specific phase on timeout.

        Args:
            phase: Phase name (e.g., 'validate_story', 'code_review').

        Returns:
            retries value (None = skip retry, 0 = infinite, N = specific count).

        """
        return self.retries


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
    remediate_max_iterations: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max fix→retest cycles for qa_remediate (1-5)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    remediate_max_age_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Skip sources older than this many days (1-30)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    remediate_safety_cap: float = Field(
        default=0.8,
        ge=0.1,
        le=1.0,
        description="If >this fraction is AUTO-FIX, overflow → ESCALATE (0.1-1.0)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    remediate_max_issues: int = Field(
        default=200,
        ge=10,
        le=1000,
        description="Max issues to send to LLM per remediation iteration (10-1000)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )


class AntipatternConfig(BaseModel):
    """Antipatterns extraction and loading configuration.

    Attributes:
        enabled: Enable antipatterns extraction and loading.

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable antipatterns extraction from synthesis and loading into compilers",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
