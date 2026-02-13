"""Loop and sprint configuration models."""

import logging
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class LoopConfig(BaseModel):
    """Development loop phase configuration.

    Defines the phases that run at different scopes in the development loop.
    This is the declarative configuration for workflow ordering.

    All phase names use snake_case to match Phase enum values exactly
    (e.g., "create_story", NOT "create-story").

    Attributes:
        epic_setup: Phases to run once at the start of each epic
            (before first story's CREATE_STORY).
            TEA phases available: tea_framework, tea_ci, tea_test_design, tea_automate
        story: Phases to run for each story in sequence.
            Standard: ["create_story", "validate_story", "validate_story_synthesis",
                      "atdd", "dev_story", "code_review", "code_review_synthesis",
                      "test_review"]
            TEA phases available: atdd (before dev_story), test_review (after code_review_synthesis)
        epic_teardown: Phases to run once at the end of each epic
            (after last story's CODE_REVIEW_SYNTHESIS).
            TEA phases available: trace (before retrospective), tea_nfr_assess (after trace)

    Available TEA Phases:
        - epic_setup scope:
            - tea_framework: Initialize test framework (Playwright/Cypress)
            - tea_ci: Initialize CI pipeline (GitHub Actions/GitLab CI)
            - tea_test_design: Test design planning (system-level for first epic)
            - tea_automate: Expand test automation (TEA Lite model)
        - story scope:
            - atdd: Acceptance TDD before implementation
            - test_review: Test quality review after code review
        - epic_teardown scope:
            - trace: Requirements traceability matrix generation
            - tea_nfr_assess: Non-functional requirements assessment

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

    @field_validator("epic_setup", "story", "epic_teardown", mode="before")
    @classmethod
    def coerce_none_to_empty_list(cls, v: Any) -> list[str]:
        """YAML parses empty keys (all items commented out) as None."""
        if v is None:
            return []
        return list(v)

    @model_validator(mode="after")
    def validate_non_empty_story(self) -> Self:
        """Validate that story list is non-empty.

        An empty story list would cause the loop to have nothing to execute,
        which is always an error in the loop configuration.
        """
        if not self.story:
            raise ValueError("LoopConfig.story must contain at least one phase")
        return self

    @model_validator(mode="after")
    def validate_phase_ordering(self) -> Self:
        """Warn about potentially incorrect TEA phase ordering.

        Logs warnings for common misconfiguration patterns:
        - atdd after dev_story (should be before for TDD flow)
        - test_review before code_review_synthesis (should be after)
        - trace after retrospective (should be before)
        - epic_setup phases out of expected order
        """
        story = self.story
        teardown = self.epic_teardown
        setup = self.epic_setup

        # ATDD should come before dev_story
        if "atdd" in story and "dev_story" in story:
            atdd_idx = story.index("atdd")
            dev_idx = story.index("dev_story")
            if atdd_idx > dev_idx:
                logger.warning(
                    "Phase ordering: 'atdd' appears after 'dev_story'. "
                    "ATDD should run before implementation for TDD flow."
                )

        # test_review should come after code_review_synthesis
        if "test_review" in story and "code_review_synthesis" in story:
            review_idx = story.index("test_review")
            synthesis_idx = story.index("code_review_synthesis")
            if review_idx < synthesis_idx:
                logger.warning(
                    "Phase ordering: 'test_review' appears before 'code_review_synthesis'. "
                    "Test review should run after code review is complete."
                )

        # trace should come before retrospective in teardown
        if "trace" in teardown and "retrospective" in teardown:
            trace_idx = teardown.index("trace")
            retro_idx = teardown.index("retrospective")
            if trace_idx > retro_idx:
                logger.warning(
                    "Phase ordering: 'trace' appears after 'retrospective'. "
                    "Traceability matrix should be generated before retrospective."
                )

        # qa_remediate should come after qa_plan_execute in teardown
        if "qa_remediate" in teardown and "qa_plan_execute" in teardown:
            rem_idx = teardown.index("qa_remediate")
            exe_idx = teardown.index("qa_plan_execute")
            if rem_idx < exe_idx:
                logger.warning(
                    "Phase ordering: 'qa_remediate' appears before 'qa_plan_execute'. "
                    "Remediation should run after test execution."
                )

        # epic_setup phases should be ordered: framework → ci → test_design → automate
        setup_order = ["tea_framework", "tea_ci", "tea_test_design", "tea_automate"]
        for i in range(len(setup_order) - 1):
            if setup_order[i] in setup and setup_order[i + 1] in setup:
                first_idx = setup.index(setup_order[i])
                second_idx = setup.index(setup_order[i + 1])
                if first_idx > second_idx:
                    logger.warning(
                        "Phase ordering: epic_setup has '%s' before '%s'. "
                        "Recommended order: tea_framework → tea_ci → tea_test_design → tea_automate",
                        setup_order[i + 1],
                        setup_order[i],
                    )

        return self


# Default loop configuration - basic workflow without TEA phases.
# Use --tea flag or configure loop in bmad-assist.yaml for TEA integration.
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
    epic_teardown=[
        "retrospective",
    ],
)

# Full TEA Enterprise loop configuration with all phases enabled.
# Activated via --tea CLI flag or by configuring loop in bmad-assist.yaml.
# Individual phases can be disabled via testarch.{workflow}_mode = "off"
# or globally via testarch.engagement_model = "off".
TEA_FULL_LOOP_CONFIG: LoopConfig = LoopConfig(
    epic_setup=[
        "tea_framework",  # Initialize test framework (Playwright/Cypress)
        "tea_ci",  # Initialize CI pipeline
        "tea_test_design",  # System-level test design (first epic)
        "tea_automate",  # Expand test automation (TEA Lite)
    ],
    story=[
        "create_story",
        "validate_story",
        "validate_story_synthesis",
        "atdd",  # Acceptance TDD before implementation
        "dev_story",
        "code_review",
        "code_review_synthesis",
        "test_review",  # Test quality review after code review
    ],
    epic_teardown=[
        "trace",  # Requirements traceability matrix
        "tea_nfr_assess",  # NFR assessment (release-level)
        "retrospective",
        "qa_plan_generate",  # Generate E2E test plan
        "qa_plan_execute",  # Execute E2E tests
        "qa_remediate",  # Collect issues, auto-fix or escalate
    ],
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
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
