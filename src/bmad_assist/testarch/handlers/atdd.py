"""ATDD phase handler for testarch module.

Handles the ATDD (Acceptance Test Driven Development) phase, which runs
between VALIDATE_STORY_SYNTHESIS and DEV_STORY to generate acceptance tests
before implementation.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State, get_state_path, save_state
from bmad_assist.providers import get_provider

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.testarch import ATDDEligibilityResult

logger = logging.getLogger(__name__)


class ATDDHandler(BaseHandler):
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

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for ATDD prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def _check_atdd_mode(self) -> tuple[str, bool]:
        """Check ATDD mode and return (mode, should_check_eligibility).

        Returns:
            Tuple of (mode: str, should_check: bool)
            - ("off", False) - skip ATDD entirely
            - ("on", False) - run ATDD without eligibility check
            - ("auto", True) - check eligibility first
            - ("not_configured", False) - no testarch config

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return ("not_configured", False)

        mode = self.config.testarch.atdd_mode
        if mode == "off":
            return ("off", False)
        elif mode == "on":
            return ("on", False)
        else:  # auto
            return ("auto", True)

    def _is_first_story_in_epic(self, state: State) -> bool:
        """Check if current story is the first story in the epic.

        Supports both numeric (1.1) and module (testarch.1) story IDs.

        Args:
            state: Current loop state.

        Returns:
            True if this is story 1 of the current epic.

        """
        if state.current_story is None:
            return False

        parts = state.current_story.split(".")
        if len(parts) != 2:
            return False

        return parts[-1] == "1"

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

        Finds story file by globbing for pattern {epic}-{story}-*.md in
        the stories directory.

        Args:
            state: Current loop state with story info.

        Returns:
            Story file content as string (empty if not found).

        """
        if state.current_epic is None or state.current_story is None:
            logger.warning("Cannot load story: missing epic or story ID")
            return ""

        # Extract story number from story ID (e.g., "1.2" -> "2")
        story_parts = state.current_story.split(".")
        if len(story_parts) != 2:
            logger.warning("Invalid story ID format: %s", state.current_story)
            return ""

        story_num = story_parts[-1]

        try:
            from bmad_assist.core.paths import get_paths

            stories_dir = get_paths().stories_dir
        except RuntimeError:
            # Fallback if paths not initialized - stories are in implementation_artifacts directly
            stories_dir = self.project_path / "_bmad-output" / "implementation-artifacts"

        # Glob for story file pattern
        pattern = f"{state.current_epic}-{story_num}-*.md"
        matches = sorted(stories_dir.glob(pattern))

        if not matches:
            logger.warning("Story file not found: %s in %s", pattern, stories_dir)
            return ""

        story_path = matches[0]
        logger.debug("Loading story content from: %s", story_path)

        return story_path.read_text(encoding="utf-8")

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

    def _extract_story_num(self, story_id: str | None) -> str | None:
        """Extract story number from story ID.

        Args:
            story_id: Story ID like "1.2" or "testarch.1".

        Returns:
            Story number as string, or None if invalid.

        """
        if story_id is None:
            return None
        parts = story_id.split(".")
        if len(parts) != 2:
            return None
        return parts[-1]

    def _extract_checklist_path(self, output: str) -> str | None:
        """Extract ATDD checklist path from workflow output.

        Searches for common patterns indicating where the checklist was saved.

        Args:
            output: Raw workflow output from provider.

        Returns:
            Path to checklist file or None if not found.

        """
        import re

        # Common patterns for checklist path in output
        patterns = [
            r"(?:saved|written|created|checklist).*?[:\s]+([^\s]+atdd-checklist[^\s]*\.md)",
            r"([^\s]+atdd-checklist[^\s]*\.md)",
            r"(?:output|file)[:\s]+([^\s]+\.md)",
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                path = match.group(1).strip()
                # Basic sanity check - path should look like a valid file path
                if "/" in path or "\\" in path or path.endswith(".md"):
                    return path

        return None

    def _invoke_atdd_workflow(self, state: State) -> PhaseResult:
        """Invoke the ATDD workflow using master provider.

        Creates a CompilerContext with state variables, compiles the
        testarch-atdd workflow, and invokes the master provider.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - tests_generated: Whether tests were generated
            - atdd_checklist: Path to checklist file (if generated)

        """
        from bmad_assist.core.exceptions import CompilerError

        story_id = state.current_story or "unknown"
        logger.info("Invoking ATDD workflow for story %s", story_id)

        try:
            # 1. Create CompilerContext from state
            # Use get_original_cwd() to preserve original CWD when running as subprocess
            paths = get_paths()
            context = CompilerContext(
                project_root=self.project_path,
                output_folder=paths.output_folder,
                project_knowledge=paths.project_knowledge,
                cwd=get_original_cwd(),
            )

            # Set resolved variables
            story_num = self._extract_story_num(state.current_story)
            context.resolved_variables = {
                "epic_num": state.current_epic,
                "story_num": story_num,
            }

            # 2. Compile workflow
            compiled = compile_workflow("testarch-atdd", context)
            logger.debug("ATDD workflow compiled successfully")

            # 3. Get provider from config
            provider_name = self.config.providers.master.provider
            provider = get_provider(provider_name)
            model = self.config.providers.master.model

            logger.debug("Using provider %s with model %s", provider_name, model)

            # Agent tracking
            from bmad_assist.core.tracking import track_agent_end, track_agent_start

            _timeout = getattr(self.config, "timeout", 120)
            _track_cli = {"model": model, "timeout": _timeout, "cwd": self.project_path}
            _track_start = track_agent_start(
                self.project_path, state.current_epic or "", story_num or "",
                "atdd", provider_name, model or "unknown", compiled.context,
                cli_params=_track_cli,
            )

            # 4. Invoke provider with compiled prompt
            result = provider.invoke(
                prompt=compiled.context,
                model=model,
                timeout=_timeout,
                cwd=self.project_path,
            )

            track_agent_end(
                self.project_path, state.current_epic or "", story_num or "",
                "atdd", provider_name, model or "unknown", compiled.context,
                _track_start, cli_params=_track_cli,
            )

            # 5. Parse result
            if result.exit_code != 0:
                logger.error("ATDD provider error for %s: %s", story_id, result.stderr)
                return PhaseResult.fail(f"Provider error: {result.stderr}")

            logger.info("ATDD workflow completed for story %s", story_id)

            # Parse atdd_checklist path from output (AC #3)
            atdd_checklist = self._extract_checklist_path(result.stdout)
            if atdd_checklist:
                logger.debug("ATDD checklist path extracted: %s", atdd_checklist)

            return PhaseResult.ok(
                {
                    "response": result.stdout,
                    "tests_generated": True,
                    "atdd_checklist": atdd_checklist,
                }
            )

        except CompilerError as e:
            logger.error("ATDD compiler error for %s: %s", story_id, e)
            return PhaseResult.fail(f"Compiler error: {e}")
        except Exception as e:
            logger.error("ATDD workflow failed for %s: %s", story_id, e)
            return PhaseResult.fail(f"ATDD workflow failed: {e}")

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

        # Reset atdd_ran_for_story at START for idempotency (AC #6)
        state.atdd_ran_for_story = False

        # Check ATDD mode
        mode, should_check_eligibility = self._check_atdd_mode()

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
