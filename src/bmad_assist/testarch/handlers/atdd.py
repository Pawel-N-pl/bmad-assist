"""ATDD phase handler for testarch module.

Handles the ATDD (Acceptance Test Driven Development) phase, which runs
between VALIDATE_STORY_SYNTHESIS and DEV_STORY to generate acceptance tests
before implementation.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State, get_state_path, save_state
from bmad_assist.testarch.core import extract_checklist_path
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.testarch import ATDDEligibilityResult

logger = logging.getLogger(__name__)


class ATDDHandler(TestarchBaseHandler):
    """Handler for ATDD phase.

    Executes the testarch-atdd workflow when stories are eligible for ATDD.

    The handler:
    1. Runs preflight check on first story of epic (once per project)
    2. Checks ATDD eligibility based on atdd_mode config
    3. Invokes the ATDD workflow for eligible stories
    4. Tracks ATDD execution in state (atdd_ran_for_story, atdd_ran_in_epic)

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
        return "atdd"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "atdd"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for ATDD prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def _run_preflight_if_needed(self, state: State) -> None:
        """Run preflight check if this is first story in epic.

        Only runs once per project - result stored in state.
        Preflight is advisory - warnings don't block ATDD.

        Args:
            state: Current loop state (modified in place).

        """
        from bmad_assist.testarch import PreflightChecker
        from bmad_assist.testarch.config import PreflightConfig

        # Only run for first story in epic
        if not self._is_first_story_in_epic(state):
            return

        # Check if preflight already completed
        if not PreflightChecker.should_run(state):
            logger.info("Preflight already completed, skipping")
            return

        # Get preflight config (use defaults if None)
        preflight_config = PreflightConfig()
        if (
            hasattr(self.config, "testarch")
            and self.config.testarch is not None
            and self.config.testarch.preflight is not None
        ):
            preflight_config = self.config.testarch.preflight

        # Run preflight
        checker = PreflightChecker(
            config=preflight_config,
            project_root=self.project_path,
        )
        result = checker.check()

        # Mark completed and save state
        PreflightChecker.mark_completed(state, result)
        state_path = get_state_path(self.config, project_root=self.project_path)
        save_state(state, state_path)

        logger.info("Preflight completed: all_passed=%s", result.all_passed)

        # Log warnings (advisory, don't block ATDD)
        for warning in result.warnings:
            logger.warning("Preflight warning: %s", warning)

    def _load_story_content(self, state: State) -> str:
        """Load story content for eligibility analysis.

        Args:
            state: Current loop state with story info.

        Returns:
            Story file content as string (empty if not found).

        """
        path = self._get_story_file_path(state)
        if not path:
            logger.warning("Story file not found for %s", state.current_story)
            return ""

        logger.debug("Loading story content from: %s", path)
        return path.read_text(encoding="utf-8")

    def _check_eligibility(self, state: State) -> ATDDEligibilityResult:
        """Run eligibility check using hybrid detector.

        The ATDDEligibilityDetector resolves its own provider internally
        via get_provider(config.provider).

        Args:
            state: Current loop state.

        Returns:
            ATDDEligibilityResult with eligible, final_score, reasoning.

        """
        from bmad_assist.testarch import ATDDEligibilityDetector
        from bmad_assist.testarch.config import EligibilityConfig

        # Load story content for analysis
        story_content = self._load_story_content(state)

        # Get eligibility config (use defaults if None)
        eligibility_config = EligibilityConfig()
        if (
            hasattr(self.config, "testarch")
            and self.config.testarch is not None
            and self.config.testarch.eligibility is not None
        ):
            eligibility_config = self.config.testarch.eligibility

        # Create detector - it handles provider internally
        detector = ATDDEligibilityDetector(config=eligibility_config)

        return detector.detect(story_content)

    def _extract_checklist_path(self, output: str) -> str | None:
        """Extract ATDD checklist path from workflow output.

        Delegates to centralized extraction function from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Path to checklist file or None if not found.

        """
        return extract_checklist_path(output)

    def _invoke_atdd_workflow(self, state: State) -> PhaseResult:
        """Invoke the ATDD workflow using master provider.

        Delegates to base handler's _invoke_generic_workflow with ATDD-specific
        parameters.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - tests_generated: Whether tests were generated
            - atdd_checklist: Path to extracted checklist (if found)
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "atdd-checklists"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        result = self._invoke_generic_workflow(
            workflow_name="testarch-atdd",
            state=state,
            extractor_fn=self._extract_checklist_path,
            report_dir=report_dir,
            report_prefix="atdd-checklist",
            story_id=state.current_story,
            metric_key="atdd_checklist",
            file_key="file",
        )

        # Add tests_generated flag for success cases
        if result.success:
            outputs = dict(result.outputs)
            outputs["tests_generated"] = True
            return PhaseResult.ok(outputs)

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the ATDD phase handler.

        This overrides the base execute() to implement custom ATDD logic:
        1. Reset atdd_ran_for_story flag (idempotency for crash recovery)
        2. Run preflight if first story in epic
        3. Check eligibility based on atdd_mode
        4. Invoke ATDD workflow if eligible
        5. Update state tracking flags

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        story_id = state.current_story or "unknown"
        logger.info("ATDD handler starting for story %s", story_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("ATDD skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Reset atdd_ran_for_story at START for idempotency (AC #6)
        state.atdd_ran_for_story = False

        # Check ATDD mode
        mode, _ = self._check_mode(state, "atdd_mode")
        should_check_eligibility = (mode == "auto")

        # Handle not configured case
        if mode == "not_configured":
            logger.info("ATDD skipped: testarch not configured")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "testarch not configured",
                    "atdd_mode": "not_configured",
                    "eligible": None,
                }
            )

        # Handle mode=off
        if mode == "off":
            logger.info("ATDD skipped: atdd_mode=off")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "atdd_mode=off",
                    "atdd_mode": "off",
                    "eligible": None,
                }
            )

        # Run preflight if needed (first story in epic)
        try:
            self._run_preflight_if_needed(state)
        except Exception as e:
            logger.warning("Preflight check failed (continuing anyway): %s", e)

        # Check eligibility if mode=auto
        if should_check_eligibility:
            logger.info("ATDD mode: %s, checking eligibility...", mode)
            try:
                result = self._check_eligibility(state)
                logger.info(
                    "ATDD eligibility: %s (score: %s)",
                    result.eligible,
                    result.final_score,
                )

                if not result.eligible:
                    logger.info("ATDD skipped: %s", result.reasoning)
                    return PhaseResult.ok(
                        {
                            "skipped": True,
                            "reason": result.reasoning,
                            "atdd_mode": mode,
                            "eligible": False,
                        }
                    )

            except Exception as e:
                logger.error("Eligibility check failed: %s", e)
                return PhaseResult.fail(f"Eligibility check failed: {e}")

        # Invoke ATDD workflow
        try:
            workflow_result = self._invoke_atdd_workflow(state)

            if workflow_result.success:
                # Update state tracking flags
                state.atdd_ran_for_story = True
                state.atdd_ran_in_epic = True

                # Add mode to outputs
                outputs = dict(workflow_result.outputs)
                outputs["atdd_mode"] = mode
                outputs["eligible"] = True

                logger.info("ATDD workflow completed successfully")

                return PhaseResult.ok(outputs)
            else:
                return workflow_result

        except Exception as e:
            logger.error("ATDD workflow invocation failed: %s", e)
            return PhaseResult.fail(f"ATDD workflow failed: {e}")
