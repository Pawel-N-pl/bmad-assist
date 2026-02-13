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

import logging
from typing import Any

from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult

# get_paths() NOT used - base_dir derived from self.project_path directly
# to ensure evaluation records are saved to the correct project
from bmad_assist.core.state import State
from bmad_assist.deep_verify.core.types import Severity
from bmad_assist.deep_verify.integration.reports import save_deep_verify_report
from bmad_assist.validation.orchestrator import (
    InsufficientValidationsError,
    ValidationError,
    _filter_outlier_validations,
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
            # CRITICAL: Use run_async_with_timeout() instead of asyncio.run()
            # to prevent hanging on executor shutdown if threads don't terminate
            from bmad_assist.core.async_utils import run_async_with_timeout

            logger.debug("HANG_DEBUG: Starting run_async_with_timeout(run_validation_phase)")
            result = run_async_with_timeout(
                run_validation_phase(
                    config=self.config,
                    project_path=self.project_path,
                    epic_num=epic_num,
                    story_num=story_num,
                ),
                executor_timeout=15.0,  # Allow 15s for executor cleanup
            )
            logger.debug(
                "HANG_DEBUG: asyncio.run() returned with %d validations, session=%s",
                len(result.anonymized_validations),
                result.session_id,
            )

            # Filter outlier validations by size (F4-IMPL: prevent token explosion)
            filtered_validations = _filter_outlier_validations(
                result.anonymized_validations,
                sigma_threshold=2.0,  # Reject if > mean + 2*std_dev
            )

            # Save validations for synthesis handler to retrieve
            # Use session_id from mapping to maintain traceability
            # Story 22.8 AC#4: Pass failed_validators for synthesis context
            # TIER 2: Pass evidence_aggregate for Evidence Score caching
            # Story 26.16: Pass Deep Verify result for synthesis
            logger.debug("HANG_DEBUG: Calling save_validations_for_synthesis")
            save_validations_for_synthesis(
                filtered_validations,
                self.project_path,
                session_id=result.session_id,  # Use mapping session_id
                failed_validators=result.failed_validators,
                evidence_aggregate=result.evidence_aggregate,
                deep_verify_result=result.deep_verify_result,
            )
            logger.debug("HANG_DEBUG: save_validations_for_synthesis completed")

            # Story 26.16: Save Deep Verify report (if DV was run)
            # Reports go to dedicated deep-verify/ directory in implementation_artifacts
            if result.deep_verify_result is not None:
                from bmad_assist.core.paths import get_paths

                deep_verify_dir = get_paths().deep_verify_dir
                try:
                    save_deep_verify_report(
                        result=result.deep_verify_result,
                        epic=epic_num,
                        story=story_num,
                        output_dir=deep_verify_dir,
                        phase_type="story-validation",
                    )
                except Exception as e:
                    logger.warning("Failed to save Deep Verify report: %s", e)

            # Log CRITICAL findings as warning - they flow to synthesis phase
            # where they have 1.5x weight multiplier for higher priority
            if result.deep_verify_result is not None:
                dv = result.deep_verify_result
                has_critical = any(f.severity == Severity.CRITICAL for f in dv.findings)

                if has_critical:
                    critical_count = sum(1 for f in dv.findings if f.severity == Severity.CRITICAL)
                    logger.warning(
                        "Deep Verify found %d CRITICAL finding(s). "
                        "These will be prioritized in synthesis phase (1.5x weight).",
                        critical_count,
                    )

            # Save evaluation records for benchmarking (Story 13.4)
            logger.debug(
                "HANG_DEBUG: About to save %d evaluation records",
                len(result.evaluation_records) if result.evaluation_records else 0,
            )
            if result.evaluation_records:
                from bmad_assist.benchmarking.storage import (
                    get_benchmark_base_dir,
                    save_evaluation_record,
                )

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
