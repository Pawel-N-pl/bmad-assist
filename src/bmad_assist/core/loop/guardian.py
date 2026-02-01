"""Guardian phase progression and anomaly detection.

Story 6.5: Main loop runner helpers - get_next_phase, guardian_check_anomaly.

"""

import logging
import os

from bmad_assist.core.loop.types import GuardianDecision, PhaseResult
from bmad_assist.core.state import Phase, State

logger = logging.getLogger(__name__)


def _is_qa_enabled() -> bool:
    """Check if QA phases are enabled via --qa flag."""
    return os.environ.get("BMAD_QA_ENABLED") == "1"


def _is_testarch_enabled() -> bool:
    """Check if testarch phases (ATDD, TEST_REVIEW) are enabled.

    Testarch is enabled if config.testarch is not None.
    Uses get_config() singleton to check configuration.
    """
    try:
        from bmad_assist.core.config import get_config

        config = get_config()
        return config.testarch is not None
    except Exception:
        # Config not loaded yet or other error - default to disabled
        return False


# Testarch phases that should be skipped when testarch is disabled
TESTARCH_PHASES: frozenset[Phase] = frozenset({Phase.ATDD, Phase.TEST_REVIEW})


__all__ = [
    "get_next_phase",
    "guardian_check_anomaly",
]


# =============================================================================
# Story 6.5: Main Loop Runner Helpers
# =============================================================================


def get_next_phase(current_phase: Phase, phase_list: list[str] | None = None) -> Phase | None:
    """Get next phase in the phase sequence.

    Pure function that calculates the next phase without modifying state.
    Uses LoopConfig.story (via get_loop_config()) by default, or explicit phase_list.

    - Testarch phases (ATDD, TEST_REVIEW) are skipped if config.testarch is None
    - QA phases (QA_PLAN_GENERATE, QA_PLAN_EXECUTE) are skipped unless
      the --qa flag is enabled (BMAD_QA_ENABLED=1)

    Args:
        current_phase: Current phase to advance from.
        phase_list: Optional explicit phase list (snake_case strings).
            If None, uses get_loop_config().story.

    Returns:
        Next phase in sequence, or None if current_phase is the last
        applicable phase or not found in the sequence.

    Example:
        >>> get_next_phase(Phase.CREATE_STORY)
        <Phase.VALIDATE_STORY: 'validate_story'>
        >>> get_next_phase(Phase.CODE_REVIEW_SYNTHESIS)  # last story phase
        None

    """
    from bmad_assist.core.config import get_loop_config

    qa_enabled = _is_qa_enabled()
    testarch_enabled = _is_testarch_enabled()

    # Get phase list from loop config if not provided
    if phase_list is None:
        loop_config = get_loop_config()
        phase_list = loop_config.story

    # Without --qa, QA phases are skipped (they're in epic_teardown anyway)
    # RETROSPECTIVE handling moved to runner - it's in epic_teardown now
    if not qa_enabled and current_phase in (Phase.QA_PLAN_GENERATE, Phase.QA_PLAN_EXECUTE):
        logger.debug("QA phase %s disabled, returning None", current_phase.name)
        return None

    try:
        # Find current phase in the list by value (snake_case string)
        current_value = current_phase.value
        idx = phase_list.index(current_value)

        # Find next applicable phase (skip disabled phases)
        while idx + 1 < len(phase_list):
            candidate_value = phase_list[idx + 1]

            # Convert string to Phase enum
            try:
                candidate = Phase(candidate_value)
            except ValueError:
                logger.warning("Unknown phase '%s' in loop config, skipping", candidate_value)
                idx += 1
                continue

            # Skip testarch phases if testarch is disabled
            if not testarch_enabled and candidate in TESTARCH_PHASES:
                logger.debug("Skipping %s (testarch disabled)", candidate.name)
                idx += 1
                continue

            # Skip QA phases if QA is disabled
            if not qa_enabled and candidate in (Phase.QA_PLAN_GENERATE, Phase.QA_PLAN_EXECUTE):
                logger.debug("Skipping %s (QA disabled)", candidate.name)
                idx += 1
                continue

            return candidate

        return None  # No more phases
    except ValueError:
        return None  # Current phase not in list


def guardian_check_anomaly(result: PhaseResult, state: State) -> GuardianDecision:
    """Check Guardian for anomaly detection (placeholder).

    MVP implementation that halts on phase failure to prevent infinite loops.
    Full Guardian implementation with anomaly detection, user intervention,
    and configurable retry policies will be added in Epic 8.

    Args:
        result: PhaseResult from execute_phase() (contains success flag, error, duration).
        state: Current State object (contains epic, story, phase position).

    Returns:
        GuardianDecision.CONTINUE - proceed to next phase (on success)
        GuardianDecision.HALT - stop loop for user intervention (on failure)

    Note:
        Full implementation in Epic 8. MVP halts on failure to prevent
        infinite retry loops when handlers are not yet implemented.

    """
    # MVP: Halt on failure to prevent infinite loops with placeholder handlers
    if not result.success:
        decision = GuardianDecision.HALT
        logger.debug(
            "Guardian: phase=%s story=%s FAILED - stopping loop",
            state.current_phase.name if state.current_phase else "None",
            state.current_story,
        )
    else:
        decision = GuardianDecision.CONTINUE
        logger.debug(
            "Guardian: phase=%s story=%s SUCCESS - continuing",
            state.current_phase.name if state.current_phase else "None",
            state.current_story,
        )
    return decision
