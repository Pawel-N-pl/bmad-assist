"""Test review handler for testarch module.

Runs the testarch-test-review workflow to validate test quality after
code review synthesis completes. Only runs when ATDD was used for the story.

The handler follows the same pattern as ATDDHandler:
1. Check mode configuration (off/auto/on)
2. Skip if mode=off or (mode=auto and no ATDD ran)
3. Compile and invoke workflow via master provider
4. Save report to test-reviews/ directory
5. Extract quality score from output

"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.providers import get_provider

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class TestReviewHandler(BaseHandler):
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

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for test review prompt template.

        Args:
            state: Current loop state.

        Returns:
            Context dict with common variables:
            epic_num, story_num, story_id, project_path.

        """
        return self._build_common_context(state)

    def _check_test_review_mode(self, state: State) -> tuple[str, bool]:
        """Check test review mode and return (mode, should_run).

        Returns:
            Tuple of (mode: str, should_run: bool)
            - ("off", False) - skip test review entirely
            - ("on", True) - run test review unconditionally
            - ("auto", True/False) - check atdd_ran_for_story flag
            - ("not_configured", False) - no testarch config

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return ("not_configured", False)

        mode = self.config.testarch.test_review_on_code_complete
        if mode == "off":
            return ("off", False)
        elif mode == "on":
            return ("on", True)
        else:  # auto
            should_run = state.atdd_ran_for_story
            return ("auto", should_run)

    def _extract_quality_score(self, output: str) -> int | None:
        """Extract quality score from test review workflow output.

        Looks for patterns like:
        - "Quality Score: 87/100"
        - "**Quality Score**: 78/100"
        - "Score: 92"

        Args:
            output: Raw test review workflow output.

        Returns:
            Quality score as integer (0-100) or None if not found.

        """
        # Try patterns in order of specificity
        patterns = [
            r"\*?\*?Quality Score\*?\*?:?\s*(\d{1,3})\s*/\s*100",  # Quality Score: 87/100
            r"\*?\*?Score\*?\*?:?\s*(\d{1,3})\s*/\s*100",  # Score: 87/100
            r"(\d{1,3})\s*/\s*100\s*\(",  # 87/100 (
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                if 0 <= score <= 100:
                    return score

        return None

    def _invoke_test_review_workflow(self, state: State) -> PhaseResult:
        """Invoke test review workflow via master provider.

        Creates a CompilerContext with state variables, compiles the
        testarch-test-review workflow, invokes the master provider, and saves
        the review report to file.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - quality_score: 0-100 score if extracted
            - review_file: Path to saved review report

        """
        from bmad_assist.core.exceptions import CompilerError

        story_id = f"{state.current_epic}-{state.current_story}"
        logger.info("Invoking test review workflow for story %s", story_id)

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
            context.resolved_variables = {
                "epic_num": state.current_epic,
                "story_num": state.current_story,
            }

            # 2. Compile workflow
            compiled = compile_workflow("testarch-test-review", context)
            logger.debug("Test review workflow compiled successfully")

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
                self.project_path, state.current_epic or "", state.current_story or "",
                "test_review", provider_name, model or "unknown", compiled.context,
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
                self.project_path, state.current_epic or "", state.current_story or "",
                "test_review", provider_name, model or "unknown", compiled.context,
                _track_start, cli_params=_track_cli,
            )

            # 5. Parse result
            if result.exit_code != 0:
                logger.error(
                    "Test review provider error for story %s: %s",
                    story_id,
                    result.stderr,
                )
                return PhaseResult.fail(f"Provider error: {result.stderr}")

            # 6. Extract quality score
            quality_score = self._extract_quality_score(result.stdout)
            logger.info(
                "Test review quality score for story %s: %s",
                story_id,
                quality_score,
            )

            # 7. Create test-reviews directory
            test_reviews_dir = paths.output_folder / "test-reviews"
            test_reviews_dir.mkdir(parents=True, exist_ok=True)

            # 8. Save review file using atomic write
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            review_filename = f"test-review-{story_id}-{timestamp}.md"
            review_path = test_reviews_dir / review_filename

            # Atomic write: write to temp file, then rename
            fd, temp_path = tempfile.mkstemp(
                suffix=".md",
                prefix="test_review_",
                dir=str(test_reviews_dir),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                os.rename(temp_path, review_path)
                logger.info("Test review file saved: %s", review_path)
            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

            return PhaseResult.ok(
                {
                    "response": result.stdout,
                    "quality_score": quality_score,
                    "review_file": str(review_path),
                }
            )

        except CompilerError as e:
            logger.error("Test review compiler error for story %s: %s", story_id, e)
            return PhaseResult.fail(f"Compiler error: {e}")
        except Exception as e:
            logger.error("Test review workflow failed for story %s: %s", story_id, e)
            return PhaseResult.fail(f"Test review workflow failed: {e}")

    def execute(self, state: State) -> PhaseResult:
        """Execute test review phase. Called by main loop.

        This method:
        1. Checks test_review mode configuration
        2. Skips if mode=off or (mode=auto and no ATDD ran)
        3. Invokes test review workflow if enabled
        4. Extracts quality score from output

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        story_id = f"{state.current_epic}-{state.current_story}"
        logger.info("Test review handler starting for story %s", story_id)

        # Check test review mode
        mode, should_run = self._check_test_review_mode(state)
        logger.info(
            "Test review mode: %s, ATDD ran for story: %s",
            mode,
            state.atdd_ran_for_story,
        )

        # Handle not configured case
        if mode == "not_configured":
            logger.info("Test review skipped: testarch not configured")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "testarch not configured",
                    "test_review_mode": "not_configured",
                }
            )

        # Handle mode=off
        if mode == "off":
            logger.info("Test review skipped: test_review_on_code_complete=off")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "test_review_on_code_complete=off",
                    "test_review_mode": "off",
                }
            )

        # Handle mode=auto with no ATDD
        if not should_run:
            logger.info("Test review skipped: no ATDD ran for story")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "no ATDD ran for story",
                    "test_review_mode": "auto",
                }
            )

        # Invoke test review workflow
        try:
            workflow_result = self._invoke_test_review_workflow(state)

            if workflow_result.success:
                outputs = dict(workflow_result.outputs)

                # Extract quality score if not already in outputs
                if "quality_score" not in outputs or outputs["quality_score"] is None:
                    response = outputs.get("response", "")
                    quality_score = self._extract_quality_score(response)
                    outputs["quality_score"] = quality_score

                logger.info(
                    "Test review completed: quality_score=%s",
                    outputs.get("quality_score"),
                )

                return PhaseResult.ok(outputs)
            else:
                logger.warning("Test review failed: %s", workflow_result.error)
                return workflow_result

        except Exception as e:
            logger.warning("Test review failed: %s", e)
            return PhaseResult.fail(f"Test review workflow failed: {e}")
