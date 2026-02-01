"""Epic-scope phase execution (setup and teardown).

Per ADR-007: Epic setup phases run before first story.
Per ADR-002: Epic teardown phases continue on failure.
Extracted from runner.py as part of the runner refactoring.

"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from bmad_assist.core.loop.dispatch import execute_phase
from bmad_assist.core.loop.helpers import _print_phase_banner
from bmad_assist.core.loop.notifications import _dispatch_event
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import (
    Phase,
    State,
    get_phase_duration_ms,
    save_state,
    start_phase_timing,
)

logger = logging.getLogger(__name__)

__all__ = ["_execute_epic_setup", "_execute_epic_teardown"]

# Type alias for state parameter
LoopState = State


def _execute_epic_setup(
    state: LoopState,
    state_path: Path,
    project_path: Path,
) -> tuple[LoopState, bool]:
    """Execute epic setup phases before first story.

    Iterates through all phases in loop_config.epic_setup and executes each.
    On failure, returns immediately with success=False (loop should HALT).
    On success, sets epic_setup_complete=True and persists state.

    Per ADR-007: If resuming after a crash during setup, this function will
    re-run ALL setup phases from the beginning (setup phases must be idempotent).

    Args:
        state: Current loop state.
        state_path: Path to state file for persistence.
        project_path: Project root directory.

    Returns:
        Tuple of (updated_state, success).
        - success=True: All setup phases completed, epic_setup_complete=True
        - success=False: A setup phase failed, loop should halt with GUARDIAN_HALT

    """
    from bmad_assist.core.config import get_loop_config

    loop_config = get_loop_config()

    if not loop_config.epic_setup:
        # No setup phases configured - nothing to do
        logger.debug("No epic_setup phases configured, skipping")
        return state, True

    logger.info(
        "Running %d epic setup phases for epic %s: %s",
        len(loop_config.epic_setup),
        state.current_epic,
        loop_config.epic_setup,
    )

    for phase_name in loop_config.epic_setup:
        # Set current phase for this setup phase
        now = datetime.now(UTC).replace(tzinfo=None)
        state = state.model_copy(
            update={
                "current_phase": Phase(phase_name),
                "updated_at": now,
            }
        )
        # Reset phase timing before execution (consistent with main loop)
        start_phase_timing(state)
        save_state(state, state_path)

        # CLI Observability: Print phase banner (visible regardless of log level)
        _print_phase_banner(
            phase=phase_name,
            epic=state.current_epic,
            story=None,  # Epic setup phases don't have a story
        )

        # Execute the setup phase
        logger.info("Executing epic setup phase: %s", phase_name)
        result = execute_phase(state)

        # Dispatch phase_completed notification (regardless of success/failure)
        phase_duration = get_phase_duration_ms(state)
        _dispatch_event(
            "phase_completed",
            project_path,
            state,
            phase=phase_name,
            duration_ms=phase_duration,
        )

        if not result.success:
            # Setup failure - halt the loop (per ADR-001)
            logger.error(
                "Epic setup phase %s failed for epic %s: %s",
                phase_name,
                state.current_epic,
                result.error,
            )
            # Save state with failed phase for resume
            save_state(state, state_path)
            return state, False

        logger.info("Epic setup phase %s completed successfully", phase_name)

    # All setup phases completed successfully - set to first story phase from config
    first_story_phase = Phase(loop_config.story[0])
    now = datetime.now(UTC).replace(tzinfo=None)
    state = state.model_copy(
        update={
            "epic_setup_complete": True,
            "current_phase": first_story_phase,  # Ready for first story phase
            "updated_at": now,
        }
    )
    save_state(state, state_path)

    logger.info(
        "Epic setup complete for epic %s, ready for %s",
        state.current_epic,
        first_story_phase.name,
    )
    return state, True


def _execute_epic_teardown(
    state: LoopState,
    state_path: Path,
    project_path: Path,
) -> tuple[LoopState, PhaseResult | None]:
    """Execute epic teardown phases after last story.

    Iterates through all phases in loop_config.epic_teardown and executes each.
    On failure, logs warning and CONTINUES to next phase (per ADR-002).
    Returns the last PhaseResult for metrics/logging purposes.

    Args:
        state: Current loop state after last story's CODE_REVIEW_SYNTHESIS.
        state_path: Path to state file for persistence.
        project_path: Project root directory.

    Returns:
        Tuple of (updated_state, last_result).
        - last_result: PhaseResult from the last executed phase (for metrics)
        - last_result is None if epic_teardown is empty

    """
    from bmad_assist.core.config import get_loop_config

    loop_config = get_loop_config()

    if not loop_config.epic_teardown:
        # No teardown phases configured - nothing to do
        logger.debug("No epic_teardown phases configured, skipping")
        return state, None

    logger.info(
        "Running %d epic teardown phases for epic %s: %s",
        len(loop_config.epic_teardown),
        state.current_epic,
        loop_config.epic_teardown,
    )

    last_result: PhaseResult | None = None

    for phase_name in loop_config.epic_teardown:
        # Set current phase for this teardown phase
        now = datetime.now(UTC).replace(tzinfo=None)
        state = state.model_copy(
            update={
                "current_phase": Phase(phase_name),
                "updated_at": now,
            }
        )
        # Reset phase timing before execution (consistent with main loop)
        start_phase_timing(state)
        save_state(state, state_path)

        # CLI Observability: Print phase banner (visible regardless of log level)
        _print_phase_banner(
            phase=phase_name,
            epic=state.current_epic,
            story=None,  # Epic teardown phases don't have a story
        )

        # Execute the teardown phase
        logger.info("Executing epic teardown phase: %s", phase_name)
        result = execute_phase(state)
        last_result = result

        # Dispatch phase_completed notification (regardless of success/failure)
        phase_duration = get_phase_duration_ms(state)
        _dispatch_event(
            "phase_completed",
            project_path,
            state,
            phase=phase_name,
            duration_ms=phase_duration,
        )

        if not result.success:
            # Teardown failure - log warning and CONTINUE (per ADR-002)
            logger.warning(
                "Epic teardown phase %s failed for epic %s: %s. "
                "Continuing to next teardown phase.",
                phase_name,
                state.current_epic,
                result.error,
            )
            # Still save state even on failure
            save_state(state, state_path)
            continue

        logger.info("Epic teardown phase %s completed successfully", phase_name)

    logger.info("Epic teardown complete for epic %s", state.current_epic)
    return state, last_result
