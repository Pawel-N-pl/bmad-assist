"""Phase dispatch and execution.

Story 6.1: get_handler() for phase dispatch.
Story 6.2: execute_phase() for single phase execution.

"""

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.loop.types import PhaseHandler, PhaseResult
from bmad_assist.core.state import Phase, State

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.core.loop.handlers.base import BaseHandler


logger = logging.getLogger(__name__)


__all__ = [
    "init_handlers",
    "get_handler",
    "execute_phase",
]


# =============================================================================
# Handler Registry - initialized once per run_loop invocation
# =============================================================================

_handler_instances: dict[Phase, "BaseHandler"] = {}
_handlers_initialized: bool = False


def init_handlers(config: "Config", project_path: Path) -> None:
    """Initialize handler instances with config and project path.

    Must be called once before get_handler() can return real handlers.
    Called from run_loop() at startup.

    Validates that all phases in LoopConfig have registered handlers.
    Raises ConfigError if any config phase is missing a handler.

    Args:
        config: Application configuration with provider settings.
        project_path: Path to the project root directory.

    Raises:
        ConfigError: If a phase in LoopConfig has no registered handler.

    """
    global _handler_instances, _handlers_initialized

    # Import here to avoid circular imports
    from bmad_assist.core.config import ConfigError, get_loop_config
    from bmad_assist.core.loop.handlers import (
        CodeReviewHandler,
        CodeReviewSynthesisHandler,
        CreateStoryHandler,
        DevStoryHandler,
        QaPlanExecuteHandler,
        QaPlanGenerateHandler,
        RetrospectiveHandler,
        ValidateStoryHandler,
        ValidateStorySynthesisHandler,
    )
    from bmad_assist.testarch.handlers import (
        ATDDHandler,
        AutomateHandler,
        CIHandler,
        FrameworkHandler,
        NFRAssessHandler,
        TestDesignHandler,
        TestReviewHandler,
        TraceHandler,
    )

    _handler_instances = {
        Phase.CREATE_STORY: CreateStoryHandler(config, project_path),
        Phase.VALIDATE_STORY: ValidateStoryHandler(config, project_path),
        Phase.VALIDATE_STORY_SYNTHESIS: ValidateStorySynthesisHandler(config, project_path),
        Phase.ATDD: ATDDHandler(config, project_path),
        Phase.TEA_FRAMEWORK: FrameworkHandler(config, project_path),
        Phase.TEA_CI: CIHandler(config, project_path),
        Phase.TEA_TEST_DESIGN: TestDesignHandler(config, project_path),
        Phase.TEA_AUTOMATE: AutomateHandler(config, project_path),
        Phase.DEV_STORY: DevStoryHandler(config, project_path),
        Phase.CODE_REVIEW: CodeReviewHandler(config, project_path),
        Phase.CODE_REVIEW_SYNTHESIS: CodeReviewSynthesisHandler(config, project_path),
        Phase.TEST_REVIEW: TestReviewHandler(config, project_path),
        Phase.TRACE: TraceHandler(config, project_path),
        Phase.TEA_NFR_ASSESS: NFRAssessHandler(config, project_path),
        Phase.RETROSPECTIVE: RetrospectiveHandler(config, project_path),
        Phase.QA_PLAN_GENERATE: QaPlanGenerateHandler(config, project_path),
        Phase.QA_PLAN_EXECUTE: QaPlanExecuteHandler(config, project_path),
    }
    _handlers_initialized = True

    logger.debug("Initialized %d phase handlers", len(_handler_instances))

    # Validate that all phases in LoopConfig have handlers
    loop_config = get_loop_config()
    all_config_phases = loop_config.epic_setup + loop_config.story + loop_config.epic_teardown

    for phase_name in all_config_phases:
        try:
            phase = Phase(phase_name)
        except ValueError:
            raise ConfigError(
                f"Invalid phase '{phase_name}' in loop config - not a valid Phase enum value"
            ) from None

        if phase not in _handler_instances:
            raise ConfigError(
                f"Phase '{phase_name}' in loop config has no registered handler"
            )

    logger.debug("Validated loop config: all %d phases have handlers", len(all_config_phases))


def get_handler(phase: Phase) -> PhaseHandler:
    """Get the handler function for a workflow phase.

    Dispatches to the appropriate handler based on phase.
    If handlers are initialized (via init_handlers), uses the new
    class-based handlers. Otherwise falls back to stub handlers.

    Args:
        phase: The Phase enum value to get handler for.

    Returns:
        The PhaseHandler callable for the specified phase.

    Raises:
        StateError: If phase is not a valid Phase enum member.

    Example:
        >>> handler = get_handler(Phase.DEV_STORY)
        >>> result = handler(state)

    """
    global _handler_instances, _handlers_initialized

    if _handlers_initialized and phase in _handler_instances:
        # Return the execute method of the handler instance
        return _handler_instances[phase].execute

    # Fallback to stub handlers if not initialized
    from bmad_assist.core.loop.handlers_stub import WORKFLOW_HANDLERS

    try:
        return WORKFLOW_HANDLERS[phase]
    except KeyError as e:
        raise StateError(f"Unknown workflow phase: {phase!r}") from e


# =============================================================================
# execute_phase Function - Story 6.2
# =============================================================================


def execute_phase(state: State) -> PhaseResult:
    """Execute a single workflow phase and return its result.

    Dispatches to the correct handler via get_handler() based on state.current_phase,
    captures timing information, and handles any exceptions raised by handlers.

    This function NEVER raises exceptions to the caller - all errors are captured
    and returned as PhaseResult.fail() with appropriate error messages.

    Args:
        state: Current loop state containing current_phase and other context.

    Returns:
        PhaseResult with success status, handler outputs, and duration_ms.
        On success: handler's result with duration_ms added to outputs.
        On failure: PhaseResult.fail() with error message and duration_ms.

    Example:
        >>> state = State(current_phase=Phase.DEV_STORY)
        >>> result = execute_phase(state)
        >>> result.outputs.get("duration_ms")  # Always present
        42

    Note:
        - duration_ms is ALWAYS added to outputs (success and failure cases)
        - Catches Exception (not BaseException) to allow KeyboardInterrupt/SystemExit
        - Uses dataclasses.replace() for immutable PhaseResult modification

    """
    start_time = time.perf_counter()

    # AC2: Handle None current_phase immediately
    if state.current_phase is None:
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)
        result = PhaseResult.fail("Cannot execute phase: no current phase set")
        return replace(result, outputs={**result.outputs, "duration_ms": duration_ms})

    phase = state.current_phase
    phase_name = phase.value

    # AC3: Log phase start
    logger.info("Starting phase: %s", phase_name)

    try:
        # AC6: Get handler (may raise StateError)
        handler = get_handler(phase)
    except StateError as e:
        # AC6: StateError returns raw message (no "Handler error:" prefix)
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        logger.error("Phase %s dispatch failed: %s", phase_name, e, exc_info=True)

        # AC3: Log completion/duration even on exception
        logger.info("Phase %s completed: success=%s", phase_name, False)
        logger.info("Phase %s duration: %dms", phase_name, duration_ms)

        result = PhaseResult.fail(str(e))
        return replace(result, outputs={**result.outputs, "duration_ms": duration_ms})

    try:
        # AC1, AC4: Call handler (may raise Exception)
        handler_result = handler(state)

        # Defensive: validate handler returned correct type
        if not isinstance(handler_result, PhaseResult):
            raise TypeError(
                f"Handler returned {type(handler_result).__name__}, expected PhaseResult"
            )

    except Exception as e:
        # AC4: Handler exceptions get "Handler error:" prefix
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        error_message = f"Handler error: {e}"
        logger.error("Phase %s handler failed: %s", phase_name, e, exc_info=True)

        # AC3: Log completion/duration even on exception
        logger.info("Phase %s completed: success=%s", phase_name, False)
        logger.info("Phase %s duration: %dms", phase_name, duration_ms)

        result = PhaseResult.fail(error_message)
        return replace(result, outputs={**result.outputs, "duration_ms": duration_ms})

    # Calculate duration for successful execution
    end_time = time.perf_counter()
    duration_ms = int((end_time - start_time) * 1000)

    # AC3: Log phase completion
    logger.info("Phase %s completed: success=%s", phase_name, handler_result.success)
    logger.info("Phase %s duration: %dms", phase_name, duration_ms)

    # AC1, AC5: Create NEW PhaseResult with duration_ms merged into outputs
    new_outputs = {**handler_result.outputs, "duration_ms": duration_ms}
    return replace(handler_result, outputs=new_outputs)
