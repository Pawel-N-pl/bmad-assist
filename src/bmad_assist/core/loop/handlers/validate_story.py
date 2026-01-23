"""VALIDATE_STORY phase handler.

Performs Multi-LLM validation of the created story using parallel
invocation of configured validators.

Story 11.7: Validation Phase Loop Integration

This handler orchestrates:
1. Parallel invocation of all Multi-LLM validators
2. Collection and anonymization of validation outputs
3. Saving individual validation reports
4. Passing data to synthesis handler via file-based cache

"""

import asyncio
import logging
from typing import Any

from bmad_assist.core.config import get_phase_timeout
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult

# get_paths() NOT used - base_dir derived from self.project_path directly
# to ensure evaluation records are saved to the correct project
from bmad_assist.core.state import State
from bmad_assist.validation.orchestrator import (
    InsufficientValidationsError,
    ValidationError,
    run_validation_phase,
    save_validations_for_synthesis,
)

logger = logging.getLogger(__name__)


class ValidateStoryHandler(BaseHandler):
    """Handler for VALIDATE_STORY phase.

    Invokes Multi-LLM validators to review the created story.
    Uses async orchestrator for parallel execution.

    Unlike other handlers that use single provider invocation,
    this handler runs multiple validators in parallel and
    collects/anonymizes their outputs for synthesis.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "validate_story"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for validate_story prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def execute(self, state: State) -> PhaseResult:
        """Execute multi-LLM validation phase.

        Overrides base execute() to use async orchestrator instead of
        single provider invocation.

        Flow:
        1. Extract story info from state
        2. Run validation_phase (parallel multi-LLM)
        3. Save anonymized validations for synthesis handler
        4. Return PhaseResult with session_id in outputs

        Args:
            state: Current loop state with story info.

        Returns:
            PhaseResult with validation metadata for synthesis phase.

        """
        from bmad_assist.core.loop.interactive import get_debugger

        try:
            # Extract story info
            epic_num = state.current_epic
            story_num_str = self._extract_story_num(state.current_story)

            if epic_num is None or story_num_str is None:
                return PhaseResult.fail("Cannot validate: missing epic_num or story_num in state")

            story_num = int(story_num_str)

            logger.info(
                "Starting validation phase for story %s.%s",
                epic_num,
                story_num,
            )

            # Run async orchestrator
            result = asyncio.run(
                run_validation_phase(
                    config=self.config,
                    project_path=self.project_path,
                    epic_num=epic_num,
                    story_num=story_num,
                )
            )

            # Save validations for synthesis handler to retrieve
            # Use session_id from mapping to maintain traceability
            # Story 22.8 AC#4: Pass failed_validators for synthesis context
            # TIER 2: Pass evidence_aggregate for Evidence Score caching
            save_validations_for_synthesis(
                result.anonymized_validations,
                self.project_path,
                session_id=result.session_id,  # Use mapping session_id
                failed_validators=result.failed_validators,
                evidence_aggregate=result.evidence_aggregate,
            )

            # Save evaluation records for benchmarking (Story 13.4)
            if result.evaluation_records:
                from bmad_assist.benchmarking.storage import get_benchmark_base_dir, save_evaluation_record

                # CRITICAL: Use centralized path utility, not get_paths() singleton!
                # get_paths() is initialized for CLI working directory, but records
                # must be saved to the TARGET project directory.
                base_dir = get_benchmark_base_dir(self.project_path)
                for record in result.evaluation_records:
                    try:
                        record_path = save_evaluation_record(record, base_dir)
                        logger.debug("Saved evaluation record: %s", record_path)
                    except Exception as e:
                        logger.warning("Failed to save evaluation record: %s", e)

                logger.info(
                    "Saved %d evaluation records to benchmarks/",
                    len(result.evaluation_records),
                )

            logger.info(
                "Validation complete: %d succeeded, %d failed. Session: %s",
                result.validation_count,
                len(result.failed_validators),
                result.session_id,
            )

            # Build outputs for synthesis phase
            outputs = result.to_dict()
            # session_id already in outputs from result.to_dict()
            outputs["anonymized_count"] = len(result.anonymized_validations)

            phase_result = PhaseResult.ok(outputs)

            # Interactive debug mode check
            debugger = get_debugger()
            if debugger.is_enabled:
                result_summary = (
                    f"VALIDATION COMPLETE - {result.validation_count} validators, "
                    f"session: {result.session_id[:8]}..."
                )
                continue_execution = debugger.run_debug_loop(
                    phase_name=self.phase_name,
                    result_summary=result_summary,
                    provider=self.get_provider(),
                    model=self.get_model(),
                    timeout=get_phase_timeout(self.config, self.phase_name),
                )
                if not continue_execution:
                    return PhaseResult.fail("User interrupted execution")

            return phase_result

        except InsufficientValidationsError as e:
            logger.error("Validation failed: %s", e)
            return PhaseResult.fail(
                f"Insufficient validations: {e.count}/{e.minimum} required. "
                f"Check provider configuration and network connectivity."
            )

        except ValidationError as e:
            logger.error("Validation error: %s", e)
            return PhaseResult.fail(str(e))

        except Exception as e:
            logger.error("Validation handler failed: %s", e, exc_info=True)
            return PhaseResult.fail(f"Validation failed: {e}")
