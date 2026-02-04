"""CODE_REVIEW phase handler.

Performs Multi-LLM code review of the implementation.

Story 13.10: Code Review Benchmarking Integration

This handler orchestrates:
1. Parallel invocation of all Multi-LLM code reviewers
2. Collection and anonymization of review outputs
3. Saving individual code review reports
4. Passing data to synthesis handler via file-based cache
5. Collecting benchmarking metrics when enabled

"""

import logging
from typing import Any

from bmad_assist.code_review.orchestrator import (
    CodeReviewError,
    InsufficientReviewsError,
    run_code_review_phase,
    save_reviews_for_synthesis,
)
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State

logger = logging.getLogger(__name__)


class CodeReviewHandler(BaseHandler):
    """Handler for CODE_REVIEW phase.

    Invokes Multi-LLM reviewers to analyze the implementation.
    Uses async orchestrator for parallel execution.

    Unlike other handlers that use single provider invocation,
    this handler runs multiple reviewers in parallel and
    collects/anonymizes their outputs for synthesis.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "code_review"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for code_review prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def execute(self, state: State) -> PhaseResult:
        """Execute multi-LLM code review phase.

        Overrides base execute() to use async orchestrator instead of
        single provider invocation.

        Flow:
        1. Extract story info from state
        2. Run code_review_phase (parallel multi-LLM)
        3. Save anonymized reviews for synthesis handler
        4. Save evaluation records if benchmarking enabled
        5. Return PhaseResult with session_id in outputs

        Args:
            state: Current loop state with story info.

        Returns:
            PhaseResult with review metadata for synthesis phase.

        """
        from bmad_assist.benchmarking.storage import get_benchmark_base_dir, save_evaluation_record

        try:
            # Extract story info
            epic_num = state.current_epic
            story_num_str = self._extract_story_num(state.current_story)

            if epic_num is None or story_num_str is None:
                return PhaseResult.fail("Cannot review: missing epic_num or story_num in state")

            # Use story_num_str directly - orchestrator accepts int | str (EpicId)
            # Epic 22 TD-001: Support string-based story IDs (e.g., "6a", "test")
            story_num = story_num_str

            logger.info(
                "Starting code review phase for story %s.%s",
                epic_num,
                story_num,
            )

            # Run async orchestrator
            # CRITICAL: Use run_async_with_timeout() instead of asyncio.run()
            # to prevent hanging on executor shutdown if threads don't terminate
            from bmad_assist.core.async_utils import run_async_with_timeout

            result = run_async_with_timeout(
                run_code_review_phase(
                    config=self.config,
                    project_path=self.project_path,
                    epic_num=epic_num,
                    story_num=story_num,
                ),
                executor_timeout=15.0,  # Allow 15s for executor cleanup
            )

            # Save reviews for synthesis handler to retrieve
            # Use session_id from mapping to maintain traceability
            # Story 22.7: Include failed reviewer metadata for synthesis
            save_reviews_for_synthesis(
                result.anonymized_reviews,
                self.project_path,
                session_id=result.session_id,
                failed_reviewers=result.failed_reviewers,
                evidence_aggregate=result.evidence_aggregate,
            )

            # Save evaluation records if any were created
            # CRITICAL: Use centralized path utility, not get_paths() singleton!
            # get_paths() is initialized for CLI working directory, but records
            # must be saved to the TARGET project directory.
            base_dir = get_benchmark_base_dir(self.project_path)
            for record in result.evaluation_records:
                try:
                    save_evaluation_record(record, base_dir)
                except Exception as e:
                    logger.warning("Failed to save evaluation record: %s", e)

            logger.info(
                "Code review complete: %d succeeded, %d failed. Session: %s",
                result.review_count,
                len(result.failed_reviewers),
                result.session_id,
            )

            # Build outputs for synthesis phase
            outputs = result.to_dict()
            # session_id already in outputs from result.to_dict()
            outputs["anonymized_count"] = len(result.anonymized_reviews)
            outputs["evaluation_records_saved"] = len(result.evaluation_records)

            phase_result = PhaseResult.ok(outputs)

            return phase_result

        except InsufficientReviewsError as e:
            logger.error("Code review failed: %s", e)
            return PhaseResult.fail(
                f"Insufficient reviews: {e.count}/{e.minimum} required. "
                f"Check provider configuration and network connectivity."
            )

        except CodeReviewError as e:
            logger.error("Code review error: %s", e)
            return PhaseResult.fail(str(e))

        except Exception as e:
            logger.error("Code review handler failed: %s", e, exc_info=True)
            return PhaseResult.fail(f"Code review failed: {e}")
