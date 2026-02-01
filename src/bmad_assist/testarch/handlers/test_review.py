"""Test review handler for testarch module.

Runs the testarch-test-review workflow to validate test quality after
code review synthesis completes. Only runs when ATDD was used for the story.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import extract_quality_score
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class TestReviewHandler(TestarchBaseHandler):
    """Handler for test review workflow.

    Executes the testarch-test-review workflow when enabled. This handler
    runs after CODE_REVIEW_SYNTHESIS to review test quality for stories
    that used ATDD.

    The handler:
    1. Checks test_review mode (off/auto/on) to determine if review should run
    2. Invokes the test review workflow for eligible stories
    3. Extracts quality score (0-100) from output
    4. Saves review report to test-reviews/ directory

    Mode behavior:
    - off: Never run test review
    - auto: Only run if atdd_ran_for_story is True
    - on: Always run test review

    """

    def __init__(self, config: Config, project_path: Path) -> None:
        """Initialize handler with config and project path.

        Args:
            config: Application configuration with provider settings.
            project_path: Path to the project root directory.

        """
        super().__init__(config, project_path)

    @property
    def phase_name(self) -> str:
        """Return the phase name."""
        return "test_review"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "test-review"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for test review prompt template.

        Args:
            state: Current loop state.

        Returns:
            Context dict with common variables:
            epic_num, story_num, story_id, project_path.

        """
        return self._build_common_context(state)

    def _extract_quality_score(self, output: str) -> int | None:
        """Extract quality score from test review workflow output.

        Delegates to centralized extraction function from testarch.core.

        Args:
            output: Raw test review workflow output.

        Returns:
            Quality score as integer (0-100) or None if not found.

        """
        return extract_quality_score(output)

    def _invoke_test_review_workflow(self, state: State) -> PhaseResult:
        """Invoke test review workflow via master provider.

        Delegates to base handler's _invoke_generic_workflow with test review
        specific parameters.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - quality_score: 0-100 score if extracted
            - file: Path to saved review report

        """
        story_id = f"{state.current_epic}-{state.current_story}"

        try:
            paths = get_paths()
            report_dir = paths.output_folder / "test-reviews"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        return self._invoke_generic_workflow(
            workflow_name="testarch-test-review",
            state=state,
            extractor_fn=self._extract_quality_score,
            report_dir=report_dir,
            report_prefix="test-review",
            story_id=story_id,
            metric_key="quality_score",
            file_key="review_file",
        )

    def execute(self, state: State) -> PhaseResult:
        """Execute test review phase. Called by main loop.

        Delegates to base handler's _execute_with_mode_check for standardized
        mode handling and workflow invocation.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        story_id = f"{state.current_epic}-{state.current_story}"
        logger.info("Test review handler starting for story %s", story_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("Test review skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        return self._execute_with_mode_check(
            state=state,
            mode_field="test_review_on_code_complete",
            state_flag="atdd_ran_for_story",
            workflow_fn=self._invoke_test_review_workflow,
            mode_output_key="test_review_mode",
            skip_reason_auto="no ATDD ran for story",
        )
