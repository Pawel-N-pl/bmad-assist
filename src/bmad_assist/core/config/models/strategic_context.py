"""Strategic context configuration for workflow compilers."""

import re
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Valid strategic document types
StrategicDocType = Literal["project-context", "prd", "architecture", "ux", "project-tree"]


class StrategicContextDefaultsConfig(BaseModel):
    """Default strategic context settings applied to all workflows.

    Attributes:
        include: Doc types to include by default. Order matters - files load in this order.
        main_only: For sharded docs, load only index.md; for non-sharded, load main file.

    """

    model_config = ConfigDict(frozen=True)

    include: tuple[StrategicDocType, ...] = Field(
        default=("project-context",),
        description="Doc types to include. Order is significant.",
    )
    main_only: bool = Field(
        default=True,
        description="For sharded: load index.md only; for non-sharded: load main .md file",
    )

    @field_validator("include", mode="before")
    @classmethod
    def convert_list_to_tuple(cls, v: Any) -> tuple[StrategicDocType, ...]:
        """Convert list to tuple and deduplicate while preserving order."""
        if isinstance(v, (list, tuple)):
            seen: set[str] = set()
            result: list[StrategicDocType] = []
            for x in v:
                if x not in seen:
                    seen.add(x)
                    result.append(x)
            return tuple(result)
        # For non-list/tuple (like already-tuple), cast to expected type
        return cast("tuple[StrategicDocType, ...]", v)


class StrategicContextWorkflowConfig(BaseModel):
    """Per-workflow strategic context overrides.

    Fields set to None inherit from defaults.

    Attributes:
        include: Doc types to include (None = use defaults).
        main_only: Override main_only flag (None = use defaults).

    """

    model_config = ConfigDict(frozen=True)

    include: tuple[StrategicDocType, ...] | None = Field(
        default=None,
        description="Doc types to include. None = inherit from defaults.",
    )
    main_only: bool | None = Field(
        default=None,
        description="Override main_only flag. None = inherit from defaults.",
    )

    @field_validator("include", mode="before")
    @classmethod
    def convert_list_to_tuple(cls, v: Any) -> tuple[StrategicDocType, ...] | None:
        """Convert list to tuple and deduplicate while preserving order."""
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            seen: set[str] = set()
            result: list[StrategicDocType] = []
            for x in v:
                if x not in seen:
                    seen.add(x)
                    result.append(x)
            return tuple(result)
        return cast("tuple[StrategicDocType, ...] | None", v)


# Named factory functions for Pydantic compatibility (lambdas don't serialize)
def _create_story_defaults() -> StrategicContextWorkflowConfig:
    """Create default config for create_story (all docs, full shards)."""
    return StrategicContextWorkflowConfig(
        include=("project-context", "prd", "architecture", "ux"),
        main_only=False,
    )


def _validate_story_defaults() -> StrategicContextWorkflowConfig:
    """Create default config for validate_story (project-context + architecture)."""
    return StrategicContextWorkflowConfig(
        include=("project-context", "architecture"),
    )


def _validate_story_synthesis_defaults() -> StrategicContextWorkflowConfig:
    """Create default config for validate_story_synthesis (project-context only)."""
    return StrategicContextWorkflowConfig(
        include=("project-context",),
    )


# TEA workflow default factories (per ADR-4 in tech-spec-tea-context-loader.md)
def _testarch_atdd_defaults() -> StrategicContextWorkflowConfig:
    """testarch-atdd: minimal context - focuses on story requirements."""
    return StrategicContextWorkflowConfig(include=("project-context",))


def _testarch_trace_defaults() -> StrategicContextWorkflowConfig:
    """testarch-trace: needs architecture for traceability mapping."""
    return StrategicContextWorkflowConfig(include=("project-context", "architecture"))


def _testarch_test_review_defaults() -> StrategicContextWorkflowConfig:
    """testarch-test-review: minimal - reviews test code."""
    return StrategicContextWorkflowConfig(include=("project-context",))


def _testarch_framework_defaults() -> StrategicContextWorkflowConfig:
    """testarch-framework: needs tech stack from architecture."""
    return StrategicContextWorkflowConfig(include=("project-context", "architecture"))


def _testarch_ci_defaults() -> StrategicContextWorkflowConfig:
    """testarch-ci: needs CI/CD patterns from architecture."""
    return StrategicContextWorkflowConfig(include=("project-context", "architecture"))


def _testarch_test_design_defaults() -> StrategicContextWorkflowConfig:
    """testarch-test-design: needs full context for test strategy."""
    return StrategicContextWorkflowConfig(include=("project-context", "prd", "architecture"))


def _testarch_automate_defaults() -> StrategicContextWorkflowConfig:
    """testarch-automate: needs PRD/Arch for feature discovery."""
    return StrategicContextWorkflowConfig(include=("project-context", "prd", "architecture"))


def _testarch_nfr_assess_defaults() -> StrategicContextWorkflowConfig:
    """testarch-nfr-assess: needs PRD for NFR requirements, Arch for patterns."""
    return StrategicContextWorkflowConfig(include=("project-context", "prd", "architecture"))


class StrategicContextConfig(BaseModel):
    """Strategic context configuration for workflow compilers.

    Controls which strategic documents (PRD, Architecture, UX, project-context)
    are included in compiled workflow prompts and how sharded documents are handled.

    Note: If this section is absent from config (None), legacy behavior is used
    (load all docs unconditionally). Use `strategic_context: {}` to enable
    optimized defaults.

    Attributes:
        budget: Total token cap for strategic docs. 0 = disabled (returns empty dict).
        defaults: Default settings applied to all workflows.
        create_story: Overrides for create_story workflow.
        validate_story: Overrides for validate_story workflow.
        validate_story_synthesis: Overrides for validate_story_synthesis workflow.

    Example:
        >>> config = StrategicContextConfig(budget=5000)
        >>> include, main_only = config.get_workflow_config("dev_story")
        >>> include
        ('project-context',)

    """

    model_config = ConfigDict(frozen=True)

    budget: int = Field(
        default=8000,
        ge=0,
        description="Token budget for strategic docs. 0 = disabled.",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    tree_budget: int = Field(
        default=5000,
        ge=0,
        description="Token budget for project tree generation. 0 = disabled.",
        json_schema_extra={"security": "safe", "ui_widget": "number"},
    )
    defaults: StrategicContextDefaultsConfig = Field(
        default_factory=StrategicContextDefaultsConfig,
        description="Default settings for all workflows",
    )
    create_story: StrategicContextWorkflowConfig = Field(
        default_factory=_create_story_defaults,
        description="Overrides for create_story (all docs, full shards)",
    )
    validate_story: StrategicContextWorkflowConfig = Field(
        default_factory=_validate_story_defaults,
        description="Overrides for validate_story (project-context + architecture)",
    )
    validate_story_synthesis: StrategicContextWorkflowConfig = Field(
        default_factory=_validate_story_synthesis_defaults,
        description="Overrides for validate_story_synthesis (project-context only)",
    )
    dev_story: StrategicContextWorkflowConfig = Field(
        default_factory=StrategicContextWorkflowConfig,
        description="Overrides for dev_story (defaults to project-context only)",
    )
    code_review: StrategicContextWorkflowConfig = Field(
        default_factory=StrategicContextWorkflowConfig,
        description="Overrides for code_review (defaults to project-context only)",
    )
    code_review_synthesis: StrategicContextWorkflowConfig = Field(
        default_factory=StrategicContextWorkflowConfig,
        description="Overrides for code_review_synthesis (defaults to project-context only)",
    )
    # TEA workflow configs (per ADR-4 in tech-spec-tea-context-loader.md)
    testarch_atdd: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_atdd_defaults,
        description="Overrides for testarch-atdd (project-context only)",
    )
    testarch_trace: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_trace_defaults,
        description="Overrides for testarch-trace (project-context + architecture)",
    )
    testarch_test_review: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_test_review_defaults,
        description="Overrides for testarch-test-review (project-context only)",
    )
    testarch_framework: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_framework_defaults,
        description="Overrides for testarch-framework (project-context + architecture)",
    )
    testarch_ci: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_ci_defaults,
        description="Overrides for testarch-ci (project-context + architecture)",
    )
    testarch_test_design: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_test_design_defaults,
        description="Overrides for testarch-test-design (project-context + prd + architecture)",
    )
    testarch_automate: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_automate_defaults,
        description="Overrides for testarch-automate (project-context + prd + architecture)",
    )
    testarch_nfr_assess: StrategicContextWorkflowConfig = Field(
        default_factory=_testarch_nfr_assess_defaults,
        description="Overrides for testarch-nfr-assess (project-context + prd + architecture)",
    )

    def get_workflow_config(self, workflow_name: str) -> tuple[tuple[StrategicDocType, ...], bool]:
        """Get merged config for a workflow.

        Merges workflow-specific overrides with defaults. User-specified include
        order IS respected - files load in that order.

        Args:
            workflow_name: Workflow name (e.g., 'dev_story', 'code-review').
                           Non-alphanumeric chars are normalized to underscores.

        Returns:
            Tuple of (include_tuple, main_only).

        Example:
            >>> config = StrategicContextConfig()
            >>> include, main_only = config.get_workflow_config("dev_story")
            >>> include
            ('project-context',)
            >>> main_only
            True

        """
        # Normalize: lowercase, replace non-alphanumeric with underscore
        name = re.sub(r"[^a-z0-9]", "_", workflow_name.lower())

        # Get workflow-specific config if exists
        workflow_cfg: StrategicContextWorkflowConfig | None = getattr(self, name, None)

        # Merge with defaults
        include = (
            workflow_cfg.include
            if workflow_cfg and workflow_cfg.include is not None
            else self.defaults.include
        )
        main_only = (
            workflow_cfg.main_only
            if workflow_cfg and workflow_cfg.main_only is not None
            else self.defaults.main_only
        )

        return include, main_only

    @model_validator(mode="after")
    def validate_tree_budget(self) -> Self:
        """Validate that tree_budget does not exceed budget.

        Only validates when both budget and tree_budget are > 0.
        tree_budget=0 disables project tree entirely.

        Raises:
            ValueError: If tree_budget exceeds strategic_context.budget (when budget > 0).

        """
        if self.tree_budget == 0:
            return self
        if self.budget > 0 and self.tree_budget > self.budget:
            raise ValueError(
                f"tree_budget ({self.tree_budget}) cannot exceed "
                f"strategic_context.budget ({self.budget})"
            )
        return self
