"""Framework phase handler for testarch module.

Handles the TEA_FRAMEWORK phase, which runs during epic_setup to initialize
test frameworks (Playwright/Cypress) before story implementation begins.

Story 25.9: FrameworkHandler implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import extract_framework_type
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)

# Framework config file patterns (from preflight.py)
PLAYWRIGHT_CONFIGS = ("playwright.config.ts", "playwright.config.js")
CYPRESS_CONFIGS = (
    "cypress.config.ts",
    "cypress.config.js",
    "cypress.config.mjs",
)


class FrameworkHandler(TestarchBaseHandler):
    """Handler for TEA_FRAMEWORK phase.

    Executes the testarch-framework workflow to initialize test frameworks
    (Playwright or Cypress) during epic_setup scope.

    The handler:
    1. Detects existing framework configuration files
    2. Skips if framework already exists (returns skipped result)
    3. Invokes testarch-framework workflow if no framework detected
    4. Tracks execution in state (framework_ran_in_epic)

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
        return "tea_framework"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "framework"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for framework workflow template.

        Args:
            state: Current loop state.

        Returns:
            Context dictionary with common TEA variables.

        """
        return self._build_common_context(state)

    def _detect_existing_framework(self) -> str | None:
        """Detect existing test framework configuration.

        Checks for Playwright and Cypress config files at project root.

        Returns:
            Framework type string ("playwright" or "cypress") or None if not found.

        """
        # Check for Playwright config files
        for config in PLAYWRIGHT_CONFIGS:
            if (self.project_path / config).exists():
                logger.debug("Detected existing Playwright config: %s", config)
                return "playwright"

        # Check for Cypress config files
        for config in CYPRESS_CONFIGS:
            if (self.project_path / config).exists():
                logger.debug("Detected existing Cypress config: %s", config)
                return "cypress"

        return None

    def _extract_framework_type(self, output: str) -> str | None:
        """Extract framework type from workflow output.

        Delegates to centralized extraction function from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Framework type string ("playwright" or "cypress") or None.

        """
        return extract_framework_type(output)

    def _invoke_framework_workflow(self, state: State) -> PhaseResult:
        """Invoke the testarch-framework workflow using master provider.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - framework_type: Extracted framework type
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            report_dir = paths.output_folder / "framework-setup"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        # Use epic ID for story_id since this is an epic_setup phase
        story_id = str(state.current_epic) if state.current_epic else "epic"

        result = self._invoke_generic_workflow(
            workflow_name="testarch-framework",
            state=state,
            extractor_fn=self._extract_framework_type,
            report_dir=report_dir,
            report_prefix="framework-setup",
            story_id=story_id,
            metric_key="framework_type",
            file_key="file",
        )

        # Update state flag on success
        if result.success:
            state.framework_ran_in_epic = True
            logger.info("Framework setup completed successfully")

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the TEA_FRAMEWORK phase handler.

        Execution flow:
        1. Check if framework already exists (skip if detected)
        2. Use _execute_with_mode_check for mode handling
        3. Invoke framework workflow if mode allows and no existing framework

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("Framework handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("Framework skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Check if framework already exists
        existing = self._detect_existing_framework()
        if existing:
            logger.info("Framework already exists: %s, skipping", existing)
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"framework already exists: {existing}",
                    "framework_type": existing,
                    "framework_mode": getattr(self.config.testarch, "framework_mode", "auto"),
                }
            )

        # Use mode check wrapper
        return self._execute_with_mode_check(
            state=state,
            mode_field="framework_mode",
            state_flag=None,  # No state flag check - runs once per epic
            workflow_fn=self._invoke_framework_workflow,
            mode_output_key="framework_mode",
            skip_reason_auto="framework setup not enabled",
        )
