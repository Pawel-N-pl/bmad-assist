"""Source context configuration for workflow compilers."""

from pydantic import BaseModel, ConfigDict, Field


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
        default=5000,  # Reduced from 15k: synthesis only needs git diff, not full source
        ge=0,
        description="Token budget for code_review_synthesis (git diff only, skip source files)",
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
    # TEA workflow budgets (per ADR-4 in tech-spec-tea-context-loader.md)
    # Most TEA workflows don't need source context (budget=0)
    # Only automate and nfr-assess need source for feature/code discovery
    testarch_atdd: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-atdd (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_trace: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-trace (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_test_review: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-test-review (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_framework: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-framework (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_ci: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-ci (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_test_design: int = Field(
        default=0,
        ge=0,
        description="Token budget for testarch-test-design (disabled by default)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_automate: int = Field(
        default=10000,
        ge=0,
        description="Token budget for testarch-automate (needs source for feature discovery)",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    testarch_nfr_assess: int = Field(
        default=10000,
        ge=0,
        description="Token budget for testarch-nfr-assess (needs source for code health)",
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
            If file_tokens > (budget/files)*threshold -> extract hunks only.
        hunk_context_lines: Minimum context lines around changes.
        hunk_context_scale: Scale factor for context calculation.
        max_files: Hard cap on files included (prevents budget dilution).

    """

    model_config = ConfigDict(frozen=True)

    adaptive_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Threshold: file_tokens > (budget/files)*threshold -> hunks only",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
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
        json_schema_extra={"security": "safe", "ui_widget": "number"},
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
