"""Automate phase handler for testarch module.

Handles the TEA_AUTOMATE phase, which runs during epic_setup to expand
test automation coverage (for TEA Lite engagement model).

Story 25.11: AutomateHandler implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import extract_automation_status, extract_test_count
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class AutomateHandler(TestarchBaseHandler):
    """Handler for TEA_AUTOMATE phase.

    Executes the testarch-automate workflow to expand test automation
    coverage during epic_setup scope.

    The handler:
    1. Detects existing automation summary
    2. Skips if automation already exists (returns skipped result)
    3. Invokes testarch-automate workflow if mode allows
    4. Tracks execution in state (automate_ran_in_epic)

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
        return "tea_automate"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "automate"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for automate workflow template.

        Args:
            state: Current loop state.

        Returns:
            Context dictionary with common TEA variables.

        """
        return self._build_common_context(state)

    def _detect_existing_automation(self) -> tuple[bool, Path | None]:
        """Check if automation summary already exists for current epic.

        Checks for {output_folder}/automation/automation-summary.md or
        automation-summary-{epic_id}-*.md (timestamped pattern from _save_report).

        Returns:
            Tuple of (exists: bool, path: Path | None).

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "automation"
            if not report_dir.exists():
                return False, None

            # First check for the simple filename (for test compatibility)
            simple_path = report_dir / "automation-summary.md"
            if simple_path.exists():
                logger.debug("Detected existing automation summary: %s", simple_path)
                return True, simple_path

            # Also check for timestamped files: automation-summary-{epic_id}-*.md
            matches = sorted(report_dir.glob("automation-summary-*.md"))
            if matches:
                logger.debug("Detected existing automation summary: %s", matches[-1])
                return True, matches[-1]
            return False, None
        except RuntimeError:
            return False, None

    def _extract_automation_outputs(self, output: str) -> dict[str, Any]:
        """Extract automation metrics from workflow output.

        Delegates to centralized extraction functions from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Dict with extracted metrics (automation_status, test_count).

        """
        return {
            "automation_status": extract_automation_status(output),
            "test_count": extract_test_count(output),
        }

    def _invoke_automate_workflow(self, state: State) -> PhaseResult:
        """Invoke the testarch-automate workflow using master provider.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - automation_status: Extracted status (PASS/PARTIAL/CONCERNS)
            - test_count: Extracted test count
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "automation"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        # Use epic ID for story_id since this is an epic_setup phase
        story_id = str(state.current_epic) if state.current_epic else "epic"

        # Invoke workflow with generic method
        result = self._invoke_generic_workflow(
            workflow_name="testarch-automate",
            state=state,
            extractor_fn=lambda output: extract_automation_status(output),
            report_dir=report_dir,
            report_prefix="automation-summary",
            story_id=story_id,
            metric_key="automation_status",
            file_key="file",
        )

        # If successful, also extract test_count and update state
        if result.success:
            outputs = dict(result.outputs)
            # Get test count from the response
            response = outputs.get("response", "")
            outputs["test_count"] = extract_test_count(response)
            state.automate_ran_in_epic = True
            logger.info("Automate workflow completed successfully")
            return PhaseResult.ok(outputs)

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the TEA_AUTOMATE phase handler.

        Execution flow:
        1. Check engagement model (skip if disabled)
        2. Check if automation already exists (skip if detected)
        3. Use _execute_with_mode_check for mode handling
        4. Invoke automate workflow if mode allows and no existing automation

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("Automate handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("Automate skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Check if automation already exists
        exists, summary_path = self._detect_existing_automation()
        if exists:
            logger.info("Automation summary already exists, skipping")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"automation-summary.md already exists: {summary_path}",
                    "automate_mode": getattr(
                        self.config.testarch, "automate_mode", "off"
                    ),
                }
            )

        # Use mode check wrapper
        return self._execute_with_mode_check(
            state=state,
            mode_field="automate_mode",
            state_flag=None,  # No state flag check - runs based on mode only
            workflow_fn=self._invoke_automate_workflow,
            mode_output_key="automate_mode",
            skip_reason_auto="automate not enabled",
        )
