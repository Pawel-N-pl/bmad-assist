"""CI phase handler for testarch module.

Handles the TEA_CI phase, which runs during epic_setup to initialize
CI pipelines (GitHub Actions/GitLab CI/etc) before story implementation begins.

Story 25.9: CIHandler implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import CIPlatform, detect_ci_platform, extract_ci_platform
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class CIHandler(TestarchBaseHandler):
    """Handler for TEA_CI phase.

    Executes the testarch-ci workflow to initialize CI pipelines
    (GitHub Actions, GitLab CI, etc.) during epic_setup scope.

    The handler:
    1. Detects existing CI platform configuration
    2. Skips if CI already exists (returns skipped result)
    3. Invokes testarch-ci workflow if no CI detected
    4. Tracks execution in state (ci_ran_in_epic)

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
        return "tea_ci"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "ci"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for CI workflow template.

        Args:
            state: Current loop state.

        Returns:
            Context dictionary with common TEA variables.

        """
        return self._build_common_context(state)

    def _detect_existing_ci(self) -> str | None:
        """Detect existing CI platform configuration.

        Uses detect_ci_platform() from testarch.core which checks for
        CI config files in priority order: github > gitlab > circleci > azure > jenkins.

        Returns:
            CI platform string or None if UNKNOWN.

        """
        result = detect_ci_platform(self.project_path)
        if result != CIPlatform.UNKNOWN.value:
            logger.debug("Detected existing CI platform: %s", result)
            return result
        return None

    def _extract_ci_platform(self, output: str) -> str | None:
        """Extract CI platform from workflow output.

        Delegates to centralized extraction function from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            CI platform string or None.

        """
        return extract_ci_platform(output)

    def _invoke_ci_workflow(self, state: State) -> PhaseResult:
        """Invoke the testarch-ci workflow using master provider.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - ci_platform: Extracted CI platform
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "ci-setup"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        # Use epic ID for story_id since this is an epic_setup phase
        story_id = str(state.current_epic) if state.current_epic else "epic"

        result = self._invoke_generic_workflow(
            workflow_name="testarch-ci",
            state=state,
            extractor_fn=self._extract_ci_platform,
            report_dir=report_dir,
            report_prefix="ci-setup",
            story_id=story_id,
            metric_key="ci_platform",
            file_key="file",
        )

        # Update state flag on success
        if result.success:
            state.ci_ran_in_epic = True
            logger.info("CI setup completed successfully")

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the TEA_CI phase handler.

        Execution flow:
        1. Check engagement model (skip if disabled)
        2. Check if CI already exists (skip if detected)
        3. Use _execute_with_mode_check for mode handling
        4. Invoke CI workflow if mode allows and no existing CI

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("CI handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("CI skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Check if CI already exists
        existing = self._detect_existing_ci()
        if existing:
            logger.info("CI already exists: %s, skipping", existing)
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"CI already exists: {existing}",
                    "ci_platform": existing,
                    "ci_mode": getattr(self.config.testarch, "ci_mode", "auto"),
                }
            )

        # Use mode check wrapper
        return self._execute_with_mode_check(
            state=state,
            mode_field="ci_mode",
            state_flag=None,  # No state flag check - runs once per epic
            workflow_fn=self._invoke_ci_workflow,
            mode_output_key="ci_mode",
            skip_reason_auto="CI setup not enabled",
        )
