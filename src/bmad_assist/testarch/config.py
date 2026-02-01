"""Testarch module configuration models.

This module provides Pydantic configuration models for the testarch
(Test Architect) module, enabling ATDD (Acceptance Test Driven Development)
features and eligibility detection configuration.

Usage:
    from bmad_assist.core import get_config

    config = get_config()
    if config.testarch is not None:
        atdd_mode = config.testarch.atdd_mode
        eligibility = config.testarch.eligibility
        if config.testarch.playwright:
            browsers = config.testarch.playwright.browsers

Story 25.5 additions:
    from bmad_assist.testarch.config import (
        SourceConfigModel,
        EvidenceConfig,
        KnowledgeConfig,
    )

    # Configure evidence collection
    evidence = EvidenceConfig(
        enabled=True,
        coverage=SourceConfigModel(patterns=["coverage/lcov.info"]),
    )

    # Configure knowledge loading
    knowledge = KnowledgeConfig(
        playwright_utils=True,
        default_fragments={"atdd": ["custom-fragment"]},
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from bmad_assist.testarch.context.config import TEAContextConfig

logger = logging.getLogger(__name__)

# Valid browser options for PlaywrightConfig
VALID_BROWSERS: tuple[str, ...] = ("chromium", "firefox", "webkit")


class PlaywrightConfig(BaseModel):
    """Playwright browser testing configuration.

    Controls Playwright test execution settings including browser selection,
    display mode, and concurrency.

    Attributes:
        browsers: List of browsers to test against.
        headless: Run browsers without visible UI.
        timeout: Test timeout in milliseconds.
        workers: Number of parallel test workers.

    """

    __test__ = False  # Tell pytest this is not a test class
    model_config = ConfigDict(frozen=True)

    browsers: list[str] = Field(
        default_factory=lambda: ["chromium"],
        description="Browsers to test against: chromium, firefox, webkit",
        json_schema_extra={
            "security": "safe",
            "ui_widget": "checkbox_group",
            "options": list(VALID_BROWSERS),
        },
    )
    headless: bool = Field(
        default=True,
        description="Run browsers without visible UI",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    timeout: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        description="Test timeout in milliseconds",
        json_schema_extra={"security": "safe", "ui_widget": "number", "unit": "ms"},
    )
    workers: int = Field(
        default=1,
        ge=1,
        le=16,
        description="Number of parallel test workers",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )

    @field_validator("browsers", mode="after")
    @classmethod
    def validate_browsers(cls, v: list[str]) -> list[str]:
        """Validate that all browsers are valid Playwright browsers."""
        invalid = [b for b in v if b not in VALID_BROWSERS]
        if invalid:
            raise ValueError(
                f"Invalid browser(s): {', '.join(invalid)}. "
                f"Valid options: {', '.join(VALID_BROWSERS)}"
            )
        return v


class EligibilityConfig(BaseModel):
    """ATDD eligibility configuration with keyword/LLM weight balancing.

    Controls how stories are assessed for ATDD eligibility when atdd_mode
    is "auto". The hybrid scoring combines keyword-based detection with
    LLM-based assessment using the configured helper provider.

    Note: The deprecated `provider` and `model` fields are ignored for
    backward compatibility. Use `providers.helper` in the main config instead.

    Attributes:
        keyword_weight: Weight for keyword-based ATDD eligibility detection.
        llm_weight: Weight for LLM-based ATDD eligibility assessment.
        threshold: Score threshold to enable ATDD in auto mode.

    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    keyword_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for keyword-based ATDD eligibility detection",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    llm_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for LLM-based ATDD eligibility assessment",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score threshold to enable ATDD in auto mode",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )

    @model_validator(mode="after")
    def validate_weights_sum(self) -> Self:
        """Ensure keyword and LLM weights sum to 1.0 (with epsilon tolerance)."""
        total = self.keyword_weight + self.llm_weight
        if abs(total - 1.0) > 0.001:
            raise ValueError("eligibility weights must sum to 1.0")
        return self


class PreflightConfig(BaseModel):
    """Preflight check configuration for test infrastructure.

    Controls which preflight checks are run before ATDD execution.
    Each check verifies and optionally initializes test infrastructure.

    Attributes:
        test_design: Check/initialize test-design-system.md.
        framework: Check/initialize Playwright/Cypress config.
        ci: Check/initialize CI pipeline.

    """

    model_config = ConfigDict(frozen=True)

    test_design: bool = Field(
        default=True,
        description="Check/initialize test-design-system.md",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    framework: bool = Field(
        default=True,
        description="Check/initialize Playwright/Cypress config",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    ci: bool = Field(
        default=True,
        description="Check/initialize CI pipeline",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )


# =============================================================================
# Story 25.5: Evidence & Knowledge Configuration Models
# =============================================================================


class SourceConfigModel(BaseModel):
    """Configuration for an evidence source (Pydantic model for YAML config).

    This model mirrors the frozen dataclass SourceConfig in evidence/models.py
    but uses Pydantic for YAML config parsing and validation.

    Attributes:
        enabled: Whether this source is enabled.
        patterns: Glob patterns to search for evidence files.
        command: Optional command to run for evidence collection.
        timeout: Command execution timeout in seconds (1-300).

    Example:
        ```yaml
        coverage:
          enabled: true
          patterns: ["coverage/lcov.info", "**/coverage-summary.json"]
          timeout: 30
        ```

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Whether this source is enabled",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns to search for evidence files",
        json_schema_extra={"security": "safe", "ui_widget": "list"},
    )
    command: str | None = Field(
        default=None,
        description="Optional command to run for evidence collection",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Command execution timeout in seconds (1-300)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )

    @model_validator(mode="after")
    def validate_patterns_when_enabled(self) -> Self:
        """Ensure patterns are non-empty when source is enabled.

        Validates that patterns list contains at least one non-empty string
        when the source is enabled. All-empty-string lists are rejected.

        Note: Empty list [] is allowed when enabled - the source will use
        its default_patterns in that case. This validator only rejects
        lists that contain exclusively empty strings.

        """
        if self.enabled and self.patterns:
            # Check if all patterns are empty strings
            non_empty = [p for p in self.patterns if p.strip()]
            if not non_empty:
                raise ValueError(
                    "patterns must contain at least one non-empty string when enabled"
                )
        return self


class EvidenceConfig(BaseModel):
    """Evidence collection configuration.

    Controls evidence collection behavior including storage location,
    timing, and per-source configuration.

    Attributes:
        enabled: Master switch for evidence collection.
        storage_path: Evidence persistence location (supports placeholder).
        collect_before_step: Inject evidence before workflow steps.
        coverage: Coverage source configuration.
        test_results: Test results source configuration.
        security: Security scan source configuration.
        performance: Performance metrics source configuration.

    Example:
        ```yaml
        evidence:
          enabled: true
          storage_path: "{implementation_artifacts}/testarch/evidence/"
          collect_before_step: true
          coverage:
            enabled: true
            patterns: ["coverage/lcov.info"]
          security:
            enabled: true
            command: "npm audit --json"
            timeout: 60
        ```

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Master switch for evidence collection",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    storage_path: str | None = Field(
        default=None,
        description=(
            "Evidence persistence location. "
            "Supports {implementation_artifacts} placeholder. "
            "Default: {implementation_artifacts}/testarch/evidence/"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    collect_before_step: bool = Field(
        default=True,
        description="Inject evidence before workflow steps",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    coverage: SourceConfigModel | None = Field(
        default=None,
        description="Coverage source configuration",
    )
    test_results: SourceConfigModel | None = Field(
        default=None,
        description="Test results source configuration",
    )
    security: SourceConfigModel | None = Field(
        default=None,
        description="Security scan source configuration",
    )
    performance: SourceConfigModel | None = Field(
        default=None,
        description="Performance metrics source configuration",
    )

    @field_validator("storage_path", mode="after")
    @classmethod
    def validate_storage_path(cls, v: str | None) -> str | None:
        """Validate storage_path for security.

        Rejects:
        - Paths containing '..' (path traversal)
        - Absolute paths (starting with '/' or drive letter)

        Allows:
        - Relative paths
        - {implementation_artifacts} placeholder

        """
        if v is None:
            return v

        # Check for path traversal
        if ".." in v:
            raise ValueError(
                "storage_path must not contain '..' (path traversal not allowed)"
            )

        # Check for absolute paths (Unix or Windows)
        if v.startswith("/"):
            raise ValueError(
                "storage_path must be a relative path (absolute paths not allowed)"
            )
        if len(v) >= 2 and v[1] == ":":
            # Windows drive letter (e.g., C:\)
            raise ValueError(
                "storage_path must be a relative path (absolute paths not allowed)"
            )

        return v


class KnowledgeConfig(BaseModel):
    """Knowledge base loading configuration.

    Controls knowledge fragment loading including index location,
    tag filters, and workflow-specific overrides.

    Attributes:
        index_path: Path to knowledge index CSV file.
        playwright_utils: Enable/disable playwright-utils tagged fragments.
        mcp_enhancements: Enable/disable MCP enhancement fragments.
        default_fragments: Workflow-specific fragment ID overrides.

    Example:
        ```yaml
        knowledge:
          index_path: "_bmad/tea/testarch/tea-index.csv"
          playwright_utils: true
          mcp_enhancements: false
          default_fragments:
            atdd: ["fixture-architecture", "network-first"]
        ```

    """

    model_config = ConfigDict(frozen=True)

    index_path: str = Field(
        default="_bmad/tea/testarch/tea-index.csv",
        description="Path to knowledge index CSV file",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    playwright_utils: bool = Field(
        default=True,
        description="Enable/disable playwright-utils tagged fragments",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    mcp_enhancements: bool = Field(
        default=True,
        description="Enable/disable MCP enhancement fragments",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    default_fragments: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "Workflow-specific fragment ID overrides. "
            "When set, replaces WORKFLOW_KNOWLEDGE_MAP defaults for that workflow."
        ),
        json_schema_extra={"security": "safe", "ui_widget": "object"},
    )

    @field_validator("index_path", mode="after")
    @classmethod
    def validate_index_path(cls, v: str) -> str:
        """Validate index_path format and security.

        Requirements:
        - Must end with .csv
        - Must be a relative path (no absolute paths)
        - Must not contain .. (path traversal)

        """
        if not v.endswith(".csv"):
            raise ValueError("index_path must end with .csv")

        # Check for path traversal
        if ".." in v:
            raise ValueError(
                "index_path must not contain '..' (path traversal not allowed)"
            )

        # Check for absolute paths (Unix or Windows)
        if v.startswith("/"):
            raise ValueError(
                "index_path must be a relative path (absolute paths not allowed)"
            )
        if len(v) >= 2 and v[1] == ":":
            # Windows drive letter (e.g., C:\)
            raise ValueError(
                "index_path must be a relative path (absolute paths not allowed)"
            )

        return v

    def get_workflow_fragments(self, workflow_id: str) -> list[str]:
        """Get fragment IDs for a workflow with override support.

        Returns fragments in priority order:
        1. User-provided override from default_fragments (if set)
        2. Default from WORKFLOW_KNOWLEDGE_MAP
        3. Empty list if workflow_id not found

        Args:
            workflow_id: Workflow identifier (e.g., "atdd", "test-review").

        Returns:
            List of fragment IDs for the workflow.

        """
        # Check for user override first
        if self.default_fragments and workflow_id in self.default_fragments:
            return list(self.default_fragments[workflow_id])

        # Fall back to defaults from WORKFLOW_KNOWLEDGE_MAP
        from bmad_assist.testarch.knowledge.defaults import WORKFLOW_KNOWLEDGE_MAP

        return list(WORKFLOW_KNOWLEDGE_MAP.get(workflow_id, []))


class TestarchConfig(BaseModel):
    """Testarch module configuration.

    Root configuration for the Test Architect module, which integrates
    ATDD (Acceptance Test Driven Development) into the bmad-assist loop.

    Attributes:
        context: TEA context loader configuration (optional, Story TEA Context Loader).
        engagement_model: TEA engagement model controlling which workflows are enabled.
            - off: All TEA workflows disabled regardless of loop config (overrides individual modes)
            - lite: Only automate workflow enabled (standalone test generation)
            - solo: All standalone workflows enabled (framework, ci, automate, test-design, nfr-assess)
            - integrated: Full TEA integration with all phases (overrides all individual modes)
            - auto: Individual workflow modes determine execution (default, no override)
        atdd_mode: ATDD operation mode (off/auto/on).
        eligibility: ATDD eligibility scoring configuration.
        preflight: Preflight infrastructure check configuration.
        playwright: Playwright browser testing configuration (optional).
        trace_on_epic_complete: Trace generation on epic completion.
        test_review_on_code_complete: Test quality review on code completion.
        evidence: Evidence collection configuration (Story 25.5).
        knowledge: Knowledge base loading configuration (Story 25.5).
        test_dir: Test directory location (Story 25.5).
        framework_mode: Framework initialization mode (off/auto/on) (Story 25.9).
        ci_mode: CI pipeline initialization mode (off/auto/on) (Story 25.9).
        test_design_mode: Test design mode (off/auto/on) (Story 25.10).
        test_design_level: Test design level override (auto/system/epic) (Story 25.10).
        automate_mode: Automate workflow mode (off/auto/on) (Story 25.11).
            Default "off" - for TEA Lite engagement model.
        nfr_assess_mode: NFR assessment mode (off/auto/on) (Story 25.11).
            Default "off" - for release-level quality gates.

    Example (full configuration):
        ```yaml
        testarch:
          engagement_model: integrated  # off | lite | solo | integrated | auto
          atdd_mode: auto
          test_dir: tests/
          framework_mode: auto
          ci_mode: auto
          test_design_mode: auto
          test_design_level: auto
          automate_mode: off        # Enable for TEA Lite model
          nfr_assess_mode: off      # Enable for release quality gates
          evidence:
            enabled: true
            storage_path: "{implementation_artifacts}/testarch/evidence/"
            collect_before_step: true
            coverage:
              enabled: true
              patterns: ["coverage/lcov.info", "**/coverage-summary.json"]
            security:
              enabled: true
              command: "npm audit --json"
              timeout: 60
          knowledge:
            index_path: "_bmad/tea/testarch/tea-index.csv"
            playwright_utils: true
            mcp_enhancements: false
            default_fragments:
              atdd: ["fixture-architecture", "network-first"]
        ```

    """

    __test__ = False  # Tell pytest this is not a test class
    model_config = ConfigDict(frozen=True)

    # Master switch for TEA module
    enabled: bool = Field(
        default=True,
        description=(
            "Master switch for TEA module. "
            "When False, all TEA workflows are completely disabled "
            "and no TEA-related checks or handlers are executed."
        ),
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )

    # TEA Context Loader configuration (Story TEA Context Loader)
    context: TEAContextConfig | None = Field(
        default=None,
        description="TEA context loader configuration for artifact injection",
    )

    # Story 25.12: Engagement model for conditional TEA phase execution
    engagement_model: Literal["off", "lite", "solo", "integrated", "auto"] = Field(
        default="auto",
        description=(
            "TEA engagement model controlling which workflows are enabled: "
            "off=all TEA workflows disabled; "
            "lite=only automate workflow (standalone test generation); "
            "solo=standalone workflows only (framework, ci, automate, test-design, nfr-assess); "
            "integrated=all TEA workflows enabled; "
            "auto=individual workflow modes determine execution (default)"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )

    atdd_mode: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "ATDD operation mode: "
            "off=skip ATDD for all stories; "
            "auto=detect story eligibility using hybrid scoring; "
            "on=run ATDD for every story"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    eligibility: EligibilityConfig = Field(
        default_factory=EligibilityConfig,
        description="ATDD eligibility scoring configuration",
    )
    preflight: PreflightConfig = Field(
        default_factory=PreflightConfig,
        description="Preflight infrastructure check configuration",
    )
    playwright: PlaywrightConfig | None = Field(
        default=None,
        description="Playwright browser testing configuration (optional)",
    )
    trace_on_epic_complete: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "Trace generation on epic completion: "
            "off=never run trace; "
            "auto=run if ATDD was used in epic; "
            "on=always run trace"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    test_review_on_code_complete: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "Test quality review on code completion: "
            "off=never run test review; "
            "auto=run if ATDD was used for story; "
            "on=always run test review"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    # Story 25.5: Evidence & Knowledge Configuration
    evidence: EvidenceConfig | None = Field(
        default=None,
        description="Evidence collection configuration (optional)",
    )
    knowledge: KnowledgeConfig | None = Field(
        default=None,
        description="Knowledge base loading configuration (optional)",
    )
    test_dir: str = Field(
        default="tests/",
        description="Test directory location",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )
    # Story 25.9: Framework and CI handler modes
    framework_mode: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "Framework initialization mode: "
            "off=never run framework setup; "
            "auto=run if no framework detected (default); "
            "on=enable framework setup (skips if already detected)"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    ci_mode: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "CI pipeline initialization mode: "
            "off=never run CI setup; "
            "auto=run if no CI config detected (default); "
            "on=enable CI setup (skips if already detected)"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    # Story 25.10: Test design handler modes
    test_design_mode: Literal["off", "auto", "on"] = Field(
        default="auto",
        description=(
            "Test design mode: "
            "off=never run test design; "
            "auto=run based on level detection (default); "
            "on=enable test design (skips if already exists)"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    test_design_level: Literal["auto", "system", "epic"] = Field(
        default="auto",
        description=(
            "Test design level override: "
            "auto=detect based on project state (default); "
            "system=force system-level design; "
            "epic=force epic-level design"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    # Story 25.11: Automate and NFR assessment handler modes
    automate_mode: Literal["off", "auto", "on"] = Field(
        default="off",
        description=(
            "Automate workflow mode: "
            "off=never run automate (default); "
            "auto=run if framework exists (detected test framework config); "
            "on=always run automate"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    nfr_assess_mode: Literal["off", "auto", "on"] = Field(
        default="off",
        description=(
            "NFR assessment mode: "
            "off=never run NFR assessment (default); "
            "auto=run if trace gate decision is PASS; "
            "on=always run assessment"
        ),
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )

    @model_validator(mode="after")
    def validate_engagement_model_consistency(self) -> Self:
        """Validate engagement_model doesn't conflict with explicit mode settings.

        Logs a warning if engagement_model is set to "off" but individual workflow
        modes are explicitly set to "on", as those individual settings will be ignored.
        """
        if self.engagement_model == "off":
            # Check if any individual modes are set to "on" but will be ignored
            conflicting = []
            mode_fields = [
                ("atdd_mode", self.atdd_mode),
                ("framework_mode", self.framework_mode),
                ("ci_mode", self.ci_mode),
                ("test_design_mode", self.test_design_mode),
                ("automate_mode", self.automate_mode),
                ("nfr_assess_mode", self.nfr_assess_mode),
                ("test_review_on_code_complete", self.test_review_on_code_complete),
                ("trace_on_epic_complete", self.trace_on_epic_complete),
            ]
            for field_name, field_value in mode_fields:
                if field_value == "on":
                    conflicting.append(field_name)
            if conflicting:
                logger.warning(
                    "engagement_model='off' but %s are set to 'on'. "
                    "Individual workflow modes are ignored when engagement_model is 'off'.",
                    conflicting,
                )
        return self


