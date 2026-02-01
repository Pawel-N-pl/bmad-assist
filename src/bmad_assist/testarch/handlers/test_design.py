"""Test design phase handler for testarch module.

Handles the TEA_TEST_DESIGN phase, which runs during epic_setup to plan tests
before story implementation begins. Supports dual-mode execution:
- System-level: First epic or no sprint-status.yaml - creates architecture + QA docs.
- Epic-level: Subsequent epics - creates per-epic test plan.

Story 25.10: TestDesignHandler implementation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.core.types import EpicId
from bmad_assist.testarch.core import extract_design_level, extract_risk_count
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class TestDesignHandler(TestarchBaseHandler):
    """Handler for TEA_TEST_DESIGN phase.

    Executes the testarch-test-design workflow in dual-mode:
    - System-level: Testability review before first epic (creates architecture + QA docs).
    - Epic-level: Per-epic test planning (creates test-design-epic-{N}.md).

    The handler:
    1. Detects design level (system vs epic) based on project state
    2. Skips if design already exists for the detected level
    3. Invokes testarch-test-design workflow if needed
    4. Tracks execution in state (test_design_ran_in_epic)

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
        return "tea_test_design"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "test-design"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for test design workflow template.

        Args:
            state: Current loop state.

        Returns:
            Context dictionary with common TEA variables.

        """
        return self._build_common_context(state)

    def _detect_design_level(self, state: State) -> Literal["system", "epic"]:
        """Detect whether to run system-level or epic-level test design.

        Priority:
        1. Config override (test_design_level != "auto") -> use configured level
        2. No sprint-status.yaml -> system-level (first-time setup)
        3. Has sprint-status + no system output + first epic -> system-level
        4. Otherwise -> epic-level

        Args:
            state: Current loop state.

        Returns:
            Design level ("system" or "epic").

        """
        # Check for config override
        if hasattr(self.config, "testarch") and self.config.testarch:
            level = getattr(self.config.testarch, "test_design_level", "auto")
            if level != "auto":
                logger.debug("Using configured test_design_level: %s", level)
                return level  # type: ignore

        # Check for sprint-status.yaml
        try:
            paths = get_paths()
            sprint_status = paths.implementation_artifacts / "sprint-status.yaml"
        except RuntimeError:
            # Paths not initialized - default to system-level
            logger.debug("Paths not initialized, defaulting to system-level")
            return "system"

        if not sprint_status.exists():
            logger.debug("No sprint-status.yaml, using system-level")
            return "system"

        # Has sprint-status - check if system output exists
        if not self._has_system_level_output():
            # No system output yet - run system-level for first epic
            epic = state.current_epic
            if epic == 1 or epic == "1" or str(epic) == "1":
                logger.debug("First epic without system output, using system-level")
                return "system"

        logger.debug("Defaulting to epic-level")
        return "epic"

    def _has_system_level_output(self) -> bool:
        """Check if system-level test design already exists.

        Checks for BOTH test-design-architecture.md AND test-design-qa.md
        in output folder (system-level creates two documents per AC2).

        Returns:
            True if both system-level design files already exist.

        """
        try:
            paths = get_paths()
            arch_path = paths.output_folder / "test-design-architecture.md"
            qa_path = paths.output_folder / "test-design-qa.md"
            return arch_path.exists() and qa_path.exists()
        except RuntimeError:
            logger.warning("Paths not initialized when checking system-level output")
            return False

    def _has_epic_level_output(self, epic_num: EpicId) -> bool:
        """Check if epic-level test design exists for given epic.

        Checks for test-design-epic-{epic_num}.md in test-designs subdirectory.

        Args:
            epic_num: Epic ID to check for.

        Returns:
            True if epic-level design already exists for given epic.

        """
        try:
            paths = get_paths()
            # Sanitize epic_num for filename (remove Windows/Unix invalid chars)
            safe_epic = re.sub(r'[\\/:*?"<>|]', "-", str(epic_num))
            epic_path = paths.output_folder / "test-designs" / f"test-design-epic-{safe_epic}.md"
            return epic_path.exists()
        except RuntimeError:
            return False

    def _extract_design_outputs(self, output: str) -> dict[str, Any]:
        """Extract design outputs from workflow output.

        Delegates to centralized extraction functions from testarch.core.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Dictionary with extracted values:
            - design_level: "system" or "epic" or None
            - risk_count: Integer count or None

        """
        return {
            "design_level": extract_design_level(output),
            "risk_count": extract_risk_count(output),
        }

    def _invoke_test_design_workflow(
        self, state: State, level: Literal["system", "epic"]
    ) -> PhaseResult:
        """Invoke the testarch-test-design workflow using master provider.

        Args:
            state: Current loop state.
            level: Design level ("system" or "epic").

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - design_level: Extracted design level
            - risk_count: Extracted risk count
            - file: Path to saved report

        """
        try:
            paths = get_paths()
            if level == "system":
                report_dir = paths.output_folder
            else:
                report_dir = paths.output_folder / "test-designs"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        # Build story_id based on level
        if level == "system":
            story_id = "architecture"
        else:
            story_id = f"epic-{state.current_epic}" if state.current_epic else "epic"

        # Create extractor function that returns design_level
        def extractor(output: str) -> str | None:
            return extract_design_level(output)

        result = self._invoke_generic_workflow(
            workflow_name="testarch-test-design",
            state=state,
            extractor_fn=extractor,
            report_dir=report_dir,
            report_prefix="test-design",
            story_id=story_id,
            metric_key="design_level",
            file_key="file",
        )

        # Update state flag on success
        if result.success:
            state.test_design_ran_in_epic = True
            outputs = dict(result.outputs)
            # Add risk_count to outputs (None if no response)
            if result.outputs.get("response"):
                risk_count = extract_risk_count(result.outputs["response"])
                outputs["risk_count"] = risk_count
            else:
                outputs["risk_count"] = None
            logger.info("Test design completed successfully")
            return PhaseResult.ok(outputs)

        return result

    def execute(self, state: State) -> PhaseResult:
        """Execute the TEA_TEST_DESIGN phase handler.

        Execution flow:
        1. Check engagement model (skip if disabled)
        2. Detect design level (system vs epic)
        3. Check if design already exists for detected level
        4. Use _execute_with_mode_check for mode handling
        5. Invoke test design workflow if mode allows

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("TestDesign handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("TestDesign skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        # Detect design level
        level = self._detect_design_level(state)
        logger.info("Detected test-design level: %s", level)

        # Check if output already exists for this level
        if level == "system" and self._has_system_level_output():
            paths = get_paths()
            arch_path = paths.output_folder / "test-design-architecture.md"
            qa_path = paths.output_folder / "test-design-qa.md"
            files_str = f"{arch_path}, {qa_path}"
            logger.info("System-level test-design already exists, skipping")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": f"system-level test-design already exists: {files_str}",
                    "design_level": "system",
                    "test_design_mode": getattr(
                        self.config.testarch, "test_design_mode", "auto"
                    )
                    if self.config.testarch
                    else "auto",
                }
            )
        elif level == "epic" and epic_id != "unknown":
            if self._has_epic_level_output(epic_id):
                paths = get_paths()
                safe_epic = re.sub(r'[\\/:*?"<>|]', "-", str(epic_id))
                epic_path = paths.output_folder / "test-designs" / f"test-design-epic-{safe_epic}.md"
                logger.info(
                    "Epic-level test-design already exists for epic %s, skipping", epic_id
                )
                return PhaseResult.ok(
                    {
                        "skipped": True,
                        "reason": f"epic-level test-design already exists: {epic_path}",
                        "design_level": "epic",
                        "test_design_mode": getattr(
                            self.config.testarch, "test_design_mode", "auto"
                        )
                        if self.config.testarch
                        else "auto",
                    }
                )

        # Use mode check wrapper
        return self._execute_with_mode_check(
            state=state,
            mode_field="test_design_mode",
            state_flag=None,  # No state flag check - runs based on level detection
            workflow_fn=lambda s: self._invoke_test_design_workflow(s, level),
            mode_output_key="test_design_mode",
            skip_reason_auto="test design not enabled",
        )
