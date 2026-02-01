"""NFR assessment phase handler for testarch module.

Handles the TEA_NFR_ASSESS phase, which runs during epic_teardown to assess
non-functional requirements (for release-level quality gates).

Story 25.11: NFRAssessHandler implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import extract_nfr_blocked_domains, extract_nfr_overall_status
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class NFRAssessHandler(TestarchBaseHandler):
    """Handler for TEA_NFR_ASSESS phase.

    Executes the testarch-nfr workflow to assess non-functional requirements
    during epic_teardown scope (after trace, before retrospective).

    The handler:
    1. Detects existing NFR assessment
    2. Skips if assessment already exists (returns skipped result)
    3. Invokes testarch-nfr workflow if mode allows
    4. Tracks execution in state (nfr_assess_ran_in_epic)

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
        return "tea_nfr_assess"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "nfr-assess"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for NFR assessment workflow template.

        Args:
            state: Current loop state.

        Returns:
            Context dictionary with common TEA variables.

        """
        return self._build_common_context(state)

    def _detect_existing_assessment(self) -> tuple[bool, Path | None]:
        """Check if NFR assessment already exists for current epic.

        Checks for {output_folder}/nfr-assessments/nfr-assessment.md or
        nfr-assessment-{epic_id}-*.md (timestamped pattern from _save_report).

        Returns:
            Tuple of (exists: bool, path: Path | None).

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "nfr-assessments"
            if not report_dir.exists():
                return False, None

            # First check for the simple filename (for test compatibility)
            simple_path = report_dir / "nfr-assessment.md"
            if simple_path.exists():
                logger.debug("Detected existing NFR assessment: %s", simple_path)
                return True, simple_path

            # Also check for timestamped files: nfr-assessment-{epic_id}-*.md
            matches = sorted(report_dir.glob("nfr-assessment-*.md"))
            if matches:
                logger.debug("Detected existing NFR assessment: %s", matches[-1])
                return True, matches[-1]
            return False, None
        except RuntimeError:
            return False, None

    def _extract_nfr_outputs(self, output: str) -> dict[str, Any]:
        """Extract NFR assessment metrics from workflow output.

        Delegates to centralized extraction functions from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Dict with extracted metrics (overall_status, blocked_domains).

        """
        return {
            "overall_status": extract_nfr_overall_status(output),
            "blocked_domains": extract_nfr_blocked_domains(output),
        }

    def _invoke_nfr_assess_workflow(self, state: State) -> PhaseResult:
        """Invoke the testarch-nfr workflow using master provider.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - overall_status: Extracted status (PASS/CONCERNS/FAIL)
            - blocked_domains: List of failed domains
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "nfr-assessments"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        # Use epic ID for story_id since this is an epic_teardown phase
        story_id = str(state.current_epic) if state.current_epic else "epic"

        # Invoke workflow with generic method
        result = self._invoke_generic_workflow(
            workflow_name="testarch-nfr",
            state=state,
            extractor_fn=lambda output: extract_nfr_overall_status(output),
            report_dir=report_dir,
            report_prefix="nfr-assessment",
            story_id=story_id,
            metric_key="overall_status",
            file_key="file",
        )

        # If successful, also extract blocked_domains and update state
        if result.success:
            outputs = dict(result.outputs)
            # Get blocked domains from the response
            response = outputs.get("response", "")
            outputs["blocked_domains"] = extract_nfr_blocked_domains(response)
            state.nfr_assess_ran_in_epic = True
            logger.info("NFR assessment workflow completed successfully")
            return PhaseResult.ok(outputs)

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the TEA_NFR_ASSESS phase handler.

        Execution flow:
        1. Check engagement model (skip if disabled)
        2. Check if assessment already exists (skip if detected)
        3. Use _execute_with_mode_check for mode handling
        4. Invoke NFR assessment workflow if mode allows and no existing assessment

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("NFR assess handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("NFR assess skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Check if assessment already exists
        exists, assessment_path = self._detect_existing_assessment()
        if exists:
            logger.info("NFR assessment already exists, skipping")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"nfr-assessment.md already exists: {assessment_path}",
                    "nfr_assess_mode": getattr(
                        self.config.testarch, "nfr_assess_mode", "off"
                    ),
                }
            )

        # Use mode check wrapper
        return self._execute_with_mode_check(
            state=state,
            mode_field="nfr_assess_mode",
            state_flag=None,  # No state flag check - runs based on mode only
            workflow_fn=self._invoke_nfr_assess_workflow,
            mode_output_key="nfr_assess_mode",
            skip_reason_auto="NFR assessment not enabled",
        )
