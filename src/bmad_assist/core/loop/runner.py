"""Main loop runner orchestration.

Story 6.5: run_loop() and _run_loop_body() implementation.
Story 15.4: Event notification dispatch integration.
Story 20.10: Sprint-status sync and repair integration.
Story XX: CLI Observability - Phase banners and run tracking.

This module has been refactored to import helper functions from:
- helpers.py: _count_epic_stories, _get_story_title
- notifications.py: _dispatch_event
- sprint_sync.py: Sprint sync and repair functions
- epic_phases.py: _execute_epic_setup, _execute_epic_teardown
- locking.py: Lock file management

"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bmad_assist import __version__
from bmad_assist.core.config import Config
from bmad_assist.core.exceptions import StateError

# Story 22.9: Dashboard SSE event emission
from bmad_assist.core.loop.dashboard_events import (
    emit_story_transition,
    emit_workflow_status,
    generate_run_id,
    parse_story_id,
    story_id_from_parts,
)
from bmad_assist.core.loop.dispatch import execute_phase, init_handlers

# Extracted helper modules
from bmad_assist.core.loop.epic_phases import (
    _execute_epic_setup,
    _execute_epic_teardown,
)
from bmad_assist.core.loop.epic_transitions import handle_epic_completion
from bmad_assist.core.loop.guardian import get_next_phase, guardian_check_anomaly
from bmad_assist.core.loop.helpers import (
    _count_epic_stories,
    _get_story_title,
    _print_phase_banner,
)
from bmad_assist.core.loop.interactive import checkpoint_and_prompt, is_skip_story_prompts
from bmad_assist.core.loop.locking import _running_lock
from bmad_assist.core.loop.notifications import _dispatch_event
from bmad_assist.core.loop.run_tracking import (
    PhaseInvocation,
    PhaseStatus,
    RunLog,
    RunStatus,
    mask_cli_args,
    save_run_log,
)
from bmad_assist.core.loop.signals import (
    _get_interrupt_exit_reason,
    register_signal_handlers,
    reset_shutdown,
    shutdown_requested,
    unregister_signal_handlers,
)
from bmad_assist.core.loop.sprint_sync import (
    _ensure_sprint_sync_callback,
    _invoke_sprint_sync,
    _run_archive_artifacts,
    _trigger_interactive_repair,
    _validate_resume_against_sprint,
)
from bmad_assist.core.loop.story_transitions import handle_story_completion
from bmad_assist.core.loop.types import GuardianDecision, LoopExitReason
from bmad_assist.core.state import (
    Phase,
    State,
    get_epic_duration_ms,
    get_phase_duration_ms,
    get_project_duration_ms,
    get_state_path,
    get_story_duration_ms,
    load_state,
    save_state,
    start_epic_timing,
    start_phase_timing,
    start_project_timing,
    start_story_timing,
)
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Temp file suffix for atomic writes
_EFFECTIVE_CONFIG_TEMP_SUFFIX = ".tmp"
_REDACTED_VALUE = "***REDACTED***"




def _get_dangerous_field_paths(
    model: type,
    prefix: str = "",
) -> set[str]:
    """Recursively find all field paths marked as security: dangerous.

    Args:
        model: Pydantic model class to inspect.
        prefix: Dot-separated prefix for nested paths.

    Returns:
        Set of dot-separated field paths (e.g., "state_path", "providers.settings").

    """
    from pydantic import BaseModel

    dangerous_paths: set[str] = set()

    if not hasattr(model, "model_fields"):
        return dangerous_paths

    for field_name, field_info in model.model_fields.items():
        field_path = f"{prefix}.{field_name}" if prefix else field_name

        # Check if this field is marked dangerous
        extra = field_info.json_schema_extra
        if isinstance(extra, dict) and extra.get("security") == "dangerous":
            dangerous_paths.add(field_path)

        # Recurse into nested Pydantic models
        annotation = field_info.annotation

        # Handle Optional[X], Union[X, None], list[X], etc.
        if hasattr(annotation, "__args__"):
            for arg in annotation.__args__:
                if arg is type(None):
                    continue
                # Recurse into BaseModel types (handles Optional[X], Union[X, Y], list[X])
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    dangerous_paths.update(_get_dangerous_field_paths(arg, field_path))

        # Direct Pydantic model (not wrapped in generic)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            dangerous_paths.update(_get_dangerous_field_paths(annotation, field_path))

    return dangerous_paths


def _redact_secrets(config_dict: dict[str, Any], dangerous_paths: set[str]) -> dict[str, Any]:
    """Recursively redact fields marked as security: dangerous.

    Args:
        config_dict: Serialized config dictionary.
        dangerous_paths: Set of dot-separated paths to redact.

    Returns:
        New dictionary with dangerous values replaced by "***REDACTED***".

    """
    result: dict[str, Any] = {}

    for key, value in config_dict.items():
        if key in dangerous_paths:
            # Top-level dangerous field
            result[key] = _REDACTED_VALUE
        elif isinstance(value, dict):
            # Recurse into nested dict, adjusting paths
            nested_dangerous = {
                p[len(key) + 1 :] for p in dangerous_paths if p.startswith(f"{key}.")
            }
            result[key] = _redact_secrets(value, nested_dangerous)
        elif isinstance(value, list):
            # Handle lists (e.g., providers.multi is a list)
            # Find paths that start with "key." (these apply to list items)
            list_item_dangerous = {
                p[len(key) + 1 :] for p in dangerous_paths if p.startswith(f"{key}.")
            }
            if list_item_dangerous:
                result[key] = [
                    _redact_secrets(item, list_item_dangerous)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        else:
            result[key] = value

    return result


def _save_effective_config(
    config: Config,
    project_path: Path,
    started_at: datetime,
) -> None:
    """Save merged config snapshot for reproducibility.

    Creates a timestamped YAML file with the full merged configuration.
    Fields marked with security: dangerous are redacted.

    This is a non-blocking operation - failures are logged but don't interrupt the run.

    Args:
        config: The merged Config instance.
        project_path: Project root directory.
        started_at: Timestamp from State.started_at (for filename).

    """
    # Format: 2026-01-26T12-34-56-123456 (filesystem-safe)
    timestamp_str = started_at.strftime("%Y-%m-%dT%H-%M-%S-%f")
    # Store in _bmad-output/ to avoid polluting project root
    output_dir = project_path / "_bmad-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"effective-config-{timestamp_str}.yaml"
    temp_path = output_path.with_suffix(output_path.suffix + _EFFECTIVE_CONFIG_TEMP_SUFFIX)

    try:
        # Serialize config to JSON-compatible dict (Path -> str)
        config_dict = config.model_dump(mode="json")

        # Find and redact dangerous fields
        dangerous_paths = _get_dangerous_field_paths(Config)
        redacted_config = _redact_secrets(config_dict, dangerous_paths)

        # Build header
        header = {
            "bmad_assist_version": __version__,
            "snapshot_timestamp": started_at.isoformat(),
            "project_name": project_path.name,
        }

        # Combine header and config
        output_data = {**header, "config": redacted_config}

        # Atomic write: temp file + os.replace
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        os.replace(temp_path, output_path)

        logger.info("Saved effective config snapshot: %s", output_path)

    except (OSError, yaml.YAMLError) as e:
        logger.warning("Failed to save effective config to %s: %s", output_path, e)
    finally:
        # Clean up temp file if it exists (e.g., after os.replace failure)
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()


__all__ = [
    "run_loop",
]


# Type alias for state parameter
LoopState = State


# =============================================================================
# run_loop - Story 6.5
# =============================================================================


def run_loop(
    config: Config,
    project_path: Path,
    epic_list: list[EpicId],
    epic_stories_loader: Callable[[EpicId], list[str]],
) -> LoopExitReason:
    """Execute the main BMAD development loop.

    Main orchestrator that ties together all phase execution, story transitions,
    and epic transitions. Implements the "fire-and-forget" design where the loop
    runs autonomously until project completion, guardian halt, or signal interrupt.

    The loop:
    - Loads or creates state on startup
    - Executes phases in sequence using execute_phase() from Story 6.2
    - Handles story completion using handle_story_completion() from Story 6.3
    - Handles epic completion using handle_epic_completion() from Story 6.4
    - Saves state after each phase
    - Checks for shutdown signals after each save_state()
    - Continues until project completion, anomaly detection, or signal interrupt

    Args:
        config: Pydantic Config model with state_path, provider settings.
        project_path: Path to project root directory.
        epic_list: Sorted list of epic numbers (e.g., [1, 2, 3, 6]).
            Typically generated via glob docs/epics/epic-*.md → extract numbers → sort.
        epic_stories_loader: Callable that returns story IDs for given epic.
            Takes epic number (int), returns list of story IDs (list[str]).

    Returns:
        LoopExitReason indicating how the loop exited:
        - COMPLETED: Project finished successfully
        - INTERRUPTED_SIGINT: Interrupted by Ctrl+C (SIGINT)
        - INTERRUPTED_SIGTERM: Interrupted by kill signal (SIGTERM)
        - GUARDIAN_HALT: Halted by Guardian for user intervention

    Raises:
        StateError: If epic_list is empty.
        StateError: If first epic has no stories.
        StateError: If state file exists but is corrupted (propagated from load_state).

    Example:
        >>> epic_list = [1, 2, 3]
        >>> loader = lambda epic: [f"{epic}.1", f"{epic}.2", f"{epic}.3"]
        >>> result = run_loop(config, project_path, epic_list, loader)
        >>> result
        <LoopExitReason.COMPLETED: 'completed'>

    Note:
        - Guardian integration is placeholder only (Epic 8)
        - Dashboard update is log placeholder only (Epic 9)
        - Signal handlers (SIGINT/SIGTERM) are registered for graceful shutdown (Story 6.6)
        - NEVER calls sys.exit() - returns LoopExitReason for CLI to handle

    """
    # AC1: Validate epic_list not empty
    if not epic_list:
        raise StateError("No epics found in project")

    # Story 6.6: Clear shutdown state from any previous invocation and register handlers
    reset_shutdown()
    register_signal_handlers()

    try:
        # Load loop config and set singleton for this run
        from bmad_assist.core.config import load_loop_config, set_loop_config

        loop_config = load_loop_config(project_path)
        set_loop_config(loop_config)
        logger.debug(
            "Loaded loop config: epic_setup=%d phases, story=%d phases, epic_teardown=%d phases",
            len(loop_config.epic_setup),
            len(loop_config.story),
            len(loop_config.epic_teardown),
        )

        # Initialize phase handlers with config and project path
        init_handlers(config, project_path)

        # Story 20.10: Register sprint sync callback at loop startup
        _ensure_sprint_sync_callback()

        # CLI Observability: Initialize run tracking
        run_log = RunLog(
            cli_args=sys.argv[1:],
            cli_args_masked=mask_cli_args(sys.argv[1:]),
            project_path=str(project_path),
        )

        # Dashboard: Create lock file for process detection
        with _running_lock(project_path):
            try:
                exit_reason = _run_loop_body(
                    config, project_path, epic_list, epic_stories_loader, run_log
                )
                # Update run_log with final status
                run_log.status = RunStatus.COMPLETED
                run_log.ended_at = datetime.now(UTC)
                return exit_reason
            except Exception:
                # Mark run as crashed on unhandled exception
                run_log.status = RunStatus.CRASHED
                run_log.ended_at = datetime.now(UTC)
                raise
            finally:
                # Always save run log on exit
                csv_enabled = os.environ.get("BMAD_CSV_OUTPUT") == "1"
                try:
                    save_run_log(run_log, project_path, as_csv=csv_enabled)
                except Exception as e:
                    logger.warning("Failed to save run log: %s", e)
    finally:
        # Story 6.6: Always restore previous signal handlers on exit
        # Moved outside _running_lock to ensure cleanup even if lock acquisition fails
        unregister_signal_handlers()


def _run_loop_body(
    config: Config,
    project_path: Path,
    epic_list: list[EpicId],
    epic_stories_loader: Callable[[EpicId], list[str]],
    run_log: RunLog | None = None,
) -> LoopExitReason:
    """Execute the main loop body with signal handling active.

    This function contains the actual loop logic. It is called by run_loop()
    within a try/finally block that ensures signal handlers are properly
    restored on exit.

    Args:
        config: Pydantic Config model with state_path, provider settings.
        project_path: Path to project root directory.
        epic_list: Sorted list of epic numbers (validated non-empty by run_loop).
        epic_stories_loader: Callable that returns story IDs for given epic.
        run_log: Optional RunLog for tracking phase invocations.

    Returns:
        LoopExitReason indicating how the loop exited.

    """
    # Resolve state_path - stored in project directory
    state_path = get_state_path(config, project_root=project_path)

    # Story 22.9: Initialize dashboard event tracking
    run_id = generate_run_id()
    sequence_id = 0

    # AC1: Load state or create fresh
    try:
        state = load_state(state_path)
        logger.info(
            "Loaded state: epic=%s story=%s phase=%s",
            state.current_epic,
            state.current_story,
            state.current_phase.name if state.current_phase else "None",
        )
    except StateError:
        # Invalid state file - let exception propagate per AC1
        raise

    # Get loop config early for use in fresh start and epic scope phases
    from bmad_assist.core.config import get_loop_config

    loop_config = get_loop_config()

    # Check if this is a fresh start (ALL position fields are None)
    # Code Review Fix: Use AND logic - only fresh start if ALL fields are None
    # Partial state (some None, some set) indicates corruption and should error
    is_fresh_start = (
        state.current_epic is None and state.current_story is None and state.current_phase is None
    )

    # Code Review Fix: Validate partial state as corruption
    if not is_fresh_start and any(
        [
            state.current_epic is None,
            state.current_story is None,
            state.current_phase is None,
        ]
    ):
        raise StateError(
            f"State file has partial data: epic={state.current_epic}, "
            f"story={state.current_story}, phase={state.current_phase}. "
            "Expected all or none to be None"
        )

    if is_fresh_start:
        # AC1: Create fresh state with first epic, first story, CREATE_STORY phase
        # epic_list is already sorted per contract - no need to sort again
        first_epic = epic_list[0]

        # Code Review Fix: Wrap epic_stories_loader in try-except
        try:
            first_epic_stories = epic_stories_loader(first_epic)
        except Exception as e:
            raise StateError(f"Failed to load stories for epic {first_epic}: {e}") from e

        # AC1: Validate first epic has stories
        if not first_epic_stories:
            raise StateError(f"No stories found in epic {first_epic}")

        first_story = first_epic_stories[0]

        # Ensure we're on the correct branch for this epic
        # Import here to avoid circular dependency
        from bmad_assist.git.branch import ensure_epic_branch, is_git_enabled

        if is_git_enabled():
            ensure_epic_branch(first_epic, project_path)

        # Get first story phase from loop config (not hardcoded CREATE_STORY)
        first_story_phase = Phase(loop_config.story[0])

        # Get naive UTC timestamp (project convention)
        now = datetime.now(UTC).replace(tzinfo=None)

        state = state.model_copy(
            update={
                "current_epic": first_epic,
                "current_story": first_story,
                "current_phase": first_story_phase,
                "started_at": now,
                "updated_at": now,
            }
        )

        # Story standalone-03 AC6/AC7: Start timing for project, epic, and story
        start_project_timing(state)
        start_epic_timing(state)
        start_story_timing(state)

        logger.info(
            "Fresh start: epic=%s story=%s phase=%s",
            first_epic,
            first_story,
            first_story_phase.name,
        )

        # Save effective config snapshot for reproducibility (non-blocking)
        # Note: state.started_at is guaranteed non-None here (just set above in model_copy)
        if state.started_at is None:
            raise StateError("state.started_at is None after fresh start initialization")
        _save_effective_config(config, project_path, state.started_at)

        # AC1: Persist initial state BEFORE first phase execution
        save_state(state, state_path)

        # Story 20.10: Trigger interactive repair on fresh start
        # Note: repair_sprint_status already includes state sync, so no separate
        # _invoke_sprint_sync call is needed here (avoids redundant I/O)
        _trigger_interactive_repair(project_path, state)

        # Story 15.4: Dispatch story_started event
        story_title = _get_story_title(project_path, first_story)
        _dispatch_event(
            "story_started",
            project_path,
            state,
            phase=first_story_phase.name,
            story_title=story_title,
        )

        # Story 22.9: Emit dashboard story_transition and workflow_status events
        sequence_id += 1
        epic_num = int(state.current_epic) if state.current_epic else 1
        story_num = int(first_story.split(".")[-1])
        story_title = (
            first_story.split(".")[-1].replace("-", " ") if "." in first_story else first_story
        )
        story_id = story_id_from_parts(epic_num, story_num, story_title)
        emit_story_transition(
            run_id=run_id,
            sequence_id=sequence_id,
            action="started",
            epic_num=epic_num,
            story_num=story_num,
            story_id=story_id,
            story_title=story_title,
        )
        emit_workflow_status(
            run_id=run_id,
            sequence_id=sequence_id,
            epic_num=epic_num,
            story_id=first_story,
            phase=first_story_phase.name,
            phase_status="in-progress",
        )

    # ALWAYS validate state against sprint-status on loop start
    # This catches cases where:
    # - sprint-status shows work is done but state.yaml is stale (resume case)
    # - project has existing sprint-status from previous runs (fresh start on existing project)
    # This must run AFTER fresh start initialization so we have a valid state
    state, is_project_complete = _validate_resume_against_sprint(
        state, project_path, epic_list, epic_stories_loader, state_path
    )
    if is_project_complete:
        logger.info("Project complete! All epics finished (detected on startup)")
        return LoopExitReason.COMPLETED

    # Handle resume case
    if not is_fresh_start:
        # Ensure timing context exists (resuming from crash where timing may be missing)
        timing_updated = False
        if state.phase_started_at is None:
            logger.info("Resuming: initializing phase timing")
            start_phase_timing(state)
            timing_updated = True
        if state.story_started_at is None:
            logger.info("Resuming: initializing story timing")
            start_story_timing(state)
            timing_updated = True
        if state.epic_started_at is None:
            logger.info("Resuming: initializing epic timing")
            start_epic_timing(state)
            timing_updated = True
        if state.project_started_at is None:
            logger.info("Resuming: initializing project timing")
            start_project_timing(state)
            timing_updated = True
        if timing_updated:
            save_state(state, state_path)

        # Ensure we're on the correct branch for the current epic
        # (Fresh start is handled inside is_fresh_start block)
        from bmad_assist.git.branch import ensure_epic_branch, is_git_enabled

        if is_git_enabled() and state.current_epic is not None:
            ensure_epic_branch(state.current_epic, project_path)

    # SECURITY WARNING:
    # Never log full config objects, API keys, or fields that may contain secrets.
    # Only log non-sensitive scalar values (provider names, model names, paths).
    logger.debug("Config providers.master.provider: %s", config.providers.master.provider)
    logger.debug("Config providers.master.model: %s", config.providers.master.model)
    logger.debug("Project path: %s", project_path)

    # Epic setup: run before first story if not already complete
    # Per ADR-007: This also handles resume-after-setup-crash by restarting all setup phases
    if not state.epic_setup_complete and loop_config.epic_setup:
        logger.info("Running epic setup phases for epic %s", state.current_epic)
        state, setup_success = _execute_epic_setup(state, state_path, project_path)
        if not setup_success:
            logger.error("Epic setup failed, halting loop")
            return LoopExitReason.GUARDIAN_HALT

    # Main loop - runs until project complete or guardian halt
    while True:
        # Story standalone-03 AC1: Reset phase timing BEFORE each phase execution
        # This ensures accurate duration reporting in notifications
        start_phase_timing(state)
        save_state(state, state_path)

        # CLI Observability: Print phase banner (visible regardless of log level)
        _print_phase_banner(
            phase=state.current_phase.name if state.current_phase else "UNKNOWN",
            epic=state.current_epic,
            story=state.current_story,
        )

        # AC2: Execute current phase
        result = execute_phase(state)

        # Code Review Fix: Log phase completion with duration for observability
        logger.info(
            "Phase %s completed: success=%s duration=%dms error=%s",
            state.current_phase.name if state.current_phase else "None",
            result.success,
            result.outputs.get("duration_ms", 0),
            result.error if not result.success else "none",
        )

        # CLI Observability: Record phase invocation in run log
        if run_log is not None:
            phase_ended = datetime.now(UTC)
            phase_started = state.phase_started_at or phase_ended
            # Make phase_started timezone-aware if needed
            if phase_started.tzinfo is None:
                phase_started = phase_started.replace(tzinfo=UTC)
            duration_ms = int((phase_ended - phase_started).total_seconds() * 1000)

            # Determine phase status
            if result.success:
                phase_status = PhaseStatus.SUCCESS
            elif result.error and "timeout" in result.error.lower():
                phase_status = PhaseStatus.TIMEOUT
            else:
                phase_status = PhaseStatus.ERROR

            run_log.phases.append(
                PhaseInvocation(
                    phase=state.current_phase.name if state.current_phase else "UNKNOWN",
                    started_at=phase_started,
                    ended_at=phase_ended,
                    duration_ms=duration_ms,
                    provider=config.providers.master.provider,
                    model=config.providers.master.model,
                    status=phase_status,
                    error_type=result.error[:100] if result.error else None,
                )
            )
            # Update run_log with current epic/story
            run_log.epic = state.current_epic
            run_log.story = state.current_story

        # Story 22.9: Emit dashboard workflow_status event with completed/failed status
        # This complements the "in-progress" emission at phase start
        if state.current_phase is not None and state.current_epic is not None:
            sequence_id += 1
            emit_workflow_status(
                run_id=run_id,
                sequence_id=sequence_id,
                epic_num=state.current_epic,
                story_id=str(state.current_story) if state.current_story else "unknown",
                phase=state.current_phase.name,
                phase_status="completed" if result.success else "failed",
            )

        # AC5: Handle phase failures
        if not result.success:
            logger.warning(
                "Phase %s failed for story %s: %s",
                state.current_phase.name if state.current_phase else "None",
                state.current_story,
                result.error,
            )

            # Story 15.4: Dispatch error_occurred event
            _dispatch_event(
                "error_occurred",
                project_path,
                state,
                error_type="phase_failure",
                message=result.error or "Unknown error",
            )

            # Check if this is a teardown phase failure (resume case)
            # Teardown phases should warn and continue, not halt (per ADR-002)
            teardown_phases = (
                [Phase(p) for p in loop_config.epic_teardown]
                if loop_config.epic_teardown
                else []
            )
            is_teardown_failure = state.current_phase in teardown_phases

            if is_teardown_failure:
                # Teardown phase failure - log warning and advance to next epic
                logger.warning(
                    "Teardown phase %s failed for epic %s: %s. Continuing to next epic.",
                    state.current_phase.name if state.current_phase else "None",
                    state.current_epic,
                    result.error,
                )
                save_state(state, state_path)
                _invoke_sprint_sync(state, project_path)

                # Calculate epic timing before handle_epic_completion modifies state
                epic_duration_ms = get_epic_duration_ms(state)
                epic_stories_count = _count_epic_stories(state)

                # Advance to next epic
                new_state, is_project_complete = handle_epic_completion(
                    state, epic_list, epic_stories_loader, state_path
                )

                # Dispatch epic_completed event (even on teardown failure)
                _dispatch_event(
                    "epic_completed",
                    project_path,
                    state,
                    duration_ms=epic_duration_ms,
                    stories_completed=epic_stories_count,
                )

                if is_project_complete:
                    project_duration_ms = get_project_duration_ms(state)
                    total_stories = len(state.completed_stories) if state.completed_stories else 0
                    _dispatch_event(
                        "project_completed",
                        project_path,
                        state,
                        duration_ms=project_duration_ms,
                        epics_completed=len(epic_list),
                        stories_completed=total_stories,
                    )
                    _invoke_sprint_sync(new_state, project_path)
                    logger.info(
                        "Project complete after teardown failure. All %d epics finished.",
                        len(epic_list),
                    )
                    return LoopExitReason.COMPLETED

                # Continue with next epic
                state = new_state
                start_epic_timing(state)
                start_story_timing(state)
                logger.info(
                    "Advanced to epic %s after teardown failure",
                    state.current_epic,
                )
                continue

            # Story phase failure - goes through normal guardian flow
            # AC5: Save state FIRST (before guardian call) to preserve position
            save_state(state, state_path)
            # Story 20.10: Invoke sync callbacks after failure path save
            _invoke_sprint_sync(state, project_path)

            # AC5: Guardian check for anomaly
            guardian_decision = guardian_check_anomaly(result, state)

            # Code Review Fix: Use GuardianDecision enum instead of magic string
            if guardian_decision == GuardianDecision.HALT:
                # AC5: Guardian "halt" - stop loop due to phase failure
                logger.debug("Loop stopped due to phase failure")

                # Story 15.4: Dispatch queue_blocked event
                _dispatch_event(
                    "queue_blocked",
                    project_path,
                    state,
                    reason="guardian_halt",
                    waiting_tasks=0,
                )

                # Code Review Fix: Remove duplicate save - state already saved above
                return LoopExitReason.GUARDIAN_HALT

            # Story 6.6: Check for shutdown after failure path save_state
            if shutdown_requested():
                logger.info("Loop interrupted by signal, state saved")
                return _get_interrupt_exit_reason()

            # AC5: MVP guardian ALWAYS returns "continue" - proceed to next phase
            # Note: In MVP, failures don't block loop (acknowledged risk - NFR4 deferred to Epic 8)
            # Code Review Fix: Skip AC6 save below - already saved above before guardian
            continue

        # AC6: Save state after each phase completion (SUCCESS PATH ONLY)
        # NOTE: This saves on EVERY successful iteration for maximum crash resilience (NFR1).
        # Performance cost: ~N atomic writes per story (N = phases executed).
        # Optimization deferred until profiling shows I/O is bottleneck.

        # Save state BEFORE advancing - current_phase is the phase that just completed
        save_state(state, state_path)

        # Story 20.10: Invoke sync callbacks after success path save
        _invoke_sprint_sync(state, project_path)

        # Story 22.10 - Task 3: Check for pause flag at safe interrupt point (after state persist)
        from bmad_assist.core.loop.dashboard_events import emit_loop_paused, emit_loop_resumed
        from bmad_assist.core.loop.pause import (
            check_pause_flag,
            validate_state_for_pause,
            wait_for_resume,
        )

        if check_pause_flag(project_path):
            logger.info(
                "Pause detected - entering wait loop (phase %s completed)",
                state.current_phase.name if state.current_phase else "None",
            )

            # Validate state before pause (AC #3, #6)
            if not validate_state_for_pause(state_path):
                logger.error("State validation failed - unsafe to pause, continuing loop")
                # Clean up pause flag to prevent re-detection in next iteration
                pause_flag = project_path / ".bmad-assist" / "pause.flag"
                try:
                    pause_flag.unlink(missing_ok=True)
                    logger.info("Removed pause flag due to state validation failure")
                except OSError as e:
                    logger.warning("Failed to remove pause flag: %s", e)
                # Continue loop instead of pausing with corrupted state
            else:
                # State is valid - emit paused event before entering wait loop
                sequence_id += 1
                emit_loop_paused(
                    run_id=run_id,
                    sequence_id=sequence_id,
                    current_phase=state.current_phase.name if state.current_phase else None,
                )

                # Wait for resume (pause.flag cleared) or stop request
                # shutdown_requested() is checked inside wait_for_resume (Story 22.10)
                resumed = wait_for_resume(project_path, stop_event=None, pause_timeout_minutes=60)

                if not resumed:
                    # Stop requested while paused or timeout
                    logger.info("Terminating loop after stop while paused")
                    return (
                        _get_interrupt_exit_reason()
                        if shutdown_requested()
                        else LoopExitReason.COMPLETED
                    )

                # Resumed - emit resumed event and continue loop
                sequence_id += 1
                emit_loop_resumed(run_id=run_id, sequence_id=sequence_id)
                logger.info("Resumed from pause - continuing to next phase")

        # Story 15.4: Dispatch phase_completed event with actual duration
        phase_duration = get_phase_duration_ms(state)
        _dispatch_event(
            "phase_completed",
            project_path,
            state,
            phase=state.current_phase.name if state.current_phase else "unknown",
            duration_ms=phase_duration,
        )

        # Git auto-commit for the COMPLETED phase (before advancing)
        # Only commits if phase is in COMMIT_PHASES (CREATE_STORY, DEV_STORY, CODE_REVIEW_SYNTHESIS, RETROSPECTIVE) # noqa: E501
        # Validation phases are NOT in COMMIT_PHASES, so their reports are not committed.
        # Lazy import to avoid circular dependency
        from bmad_assist.git import auto_commit_phase

        auto_commit_phase(
            phase=state.current_phase,
            story_id=state.current_story,
            project_path=project_path,
        )

        # Determine what to do next based on current phase
        current_phase = state.current_phase

        # AC3: CODE_REVIEW_SYNTHESIS success → handle story completion
        # CRITICAL: This check MUST happen before get_next_phase() because story completion
        # determines whether we advance to RETROSPECTIVE (epic complete) or next story.
        if current_phase == Phase.CODE_REVIEW_SYNTHESIS and result.success:
            # Archive multi-LLM artifacts (idempotent - safe if LLM already ran it)
            _run_archive_artifacts(project_path)

            # Get stories for current epic
            if state.current_epic is None:
                raise StateError("Logic error: current_epic is None at CODE_REVIEW_SYNTHESIS")

            # Code Review Fix: Wrap epic_stories_loader in try-except
            try:
                epic_stories = epic_stories_loader(state.current_epic)
            except Exception as e:
                raise StateError(
                    f"Failed to load stories for epic {state.current_epic}: {e}"
                ) from e

            # Story 15.4: Dispatch story_completed event with TOTAL story duration
            story_duration = get_story_duration_ms(state)
            _dispatch_event(
                "story_completed",
                project_path,
                state,
                duration_ms=story_duration,
                outcome="success",
            )

            new_state, is_epic_complete = handle_story_completion(state, epic_stories, state_path)

            if is_epic_complete:
                # Run all epic teardown phases (retrospective, qa_plan_*, etc.)
                logger.info("Epic %s stories complete, running teardown phases", state.current_epic)
                state, _teardown_result = _execute_epic_teardown(
                    new_state, state_path, project_path
                )
                _invoke_sprint_sync(state, project_path)

                # Story 6.6: Check for shutdown after teardown
                if shutdown_requested():
                    logger.info("Loop interrupted by signal, state saved")
                    return _get_interrupt_exit_reason()

                # Teardown complete - now handle epic transition
                # Calculate epic timing before handle_epic_completion modifies state
                epic_duration_ms = get_epic_duration_ms(state)
                epic_stories_count = _count_epic_stories(state)

                # Advance to next epic (or complete project)
                advanced_state, is_project_complete = handle_epic_completion(
                    state, epic_list, epic_stories_loader, state_path
                )

                # Story standalone-03 AC6: Dispatch epic_completed event
                _dispatch_event(
                    "epic_completed",
                    project_path,
                    state,
                    duration_ms=epic_duration_ms,
                    stories_completed=epic_stories_count,
                )

                # Interactive continuation prompt at epic boundary (only if NOT project complete)
                if not is_project_complete and not checkpoint_and_prompt(
                    advanced_state, state_path, f"Epic {state.current_epic} complete. Continue?"
                ):
                    return LoopExitReason.COMPLETED  # Graceful exit - state already saved

                if is_project_complete:
                    # Story standalone-03 AC7: Dispatch project_completed event
                    project_duration_ms = get_project_duration_ms(state)
                    total_stories = len(state.completed_stories) if state.completed_stories else 0
                    _dispatch_event(
                        "project_completed",
                        project_path,
                        state,
                        duration_ms=project_duration_ms,
                        epics_completed=len(epic_list),
                        stories_completed=total_stories,
                    )
                    _invoke_sprint_sync(advanced_state, project_path)
                    logger.info("Project complete after epic %s teardown", state.current_epic)
                    return LoopExitReason.COMPLETED

                # Continue with next epic
                state = advanced_state
                # Reset timing for new epic
                start_epic_timing(state)
                start_story_timing(state)
                logger.info("Advanced to epic %s after teardown", state.current_epic)
                continue  # Next iteration will run epic_setup for new epic
            else:
                # AC3: Not last story - advance to next story
                # Interactive continuation prompt at story boundary
                # Skip if --skip-story-prompts flag is set (but epic prompts still show)
                if not is_skip_story_prompts() and not checkpoint_and_prompt(
                    new_state, state_path, f"Story {state.current_story} complete. Continue?"
                ):
                    return LoopExitReason.COMPLETED  # Graceful exit - state already saved

                state = new_state
                # Start timing for the new story
                start_story_timing(state)
                # Story 20.10: Sync after story completion (non-last in epic)
                _invoke_sprint_sync(state, project_path)
                logger.info(
                    "Advanced to story %s at phase %s",
                    state.current_story,
                    state.current_phase.name if state.current_phase else "None",
                )

                # Story 15.4: Dispatch story_started for new story
                story_title = _get_story_title(project_path, state.current_story or "")
                _dispatch_event(
                    "story_started",
                    project_path,
                    state,
                    phase=state.current_phase.name if state.current_phase else "CREATE_STORY",
                    story_title=story_title,
                )

                # Story 22.9: Emit dashboard story_transition and workflow_status events
                sequence_id += 1
                if state.current_epic is not None and state.current_story is not None:
                    story_id_str = str(state.current_story)
                    # Parse story_id using helper function
                    try:
                        parsed_epic, parsed_story = parse_story_id(story_id_str)
                    except ValueError:
                        # Fallback for standalone stories or non-standard IDs
                        # Use current_epic directly as EpicId (supports string epics)
                        parsed_epic = state.current_epic if state.current_epic is not None else 1
                        parsed_story = 1

                    # Get story title from story file or use default
                    # For now, use a slugified version of story_id as title
                    story_title = story_id_str.replace(".", "-").replace("_", "-").lower()

                    # Generate full story_id (epic-story-title format)
                    full_story_id = story_id_from_parts(parsed_epic, parsed_story, story_title)
                    emit_story_transition(
                        run_id=run_id,
                        sequence_id=sequence_id,
                        action="started",
                        epic_num=parsed_epic,
                        story_num=parsed_story,
                        story_id=full_story_id,
                        story_title=story_title,
                    )
                    emit_workflow_status(
                        run_id=run_id,
                        sequence_id=sequence_id,
                        epic_num=parsed_epic,
                        story_id=story_id_str,
                        phase=state.current_phase.name if state.current_phase else "CREATE_STORY",
                        phase_status="in-progress",
                    )

            continue

        # AC4: QA_PLAN_EXECUTE success → handle epic completion
        # Note: This is the FINAL phase of an epic (after RETROSPECTIVE → QA_PLAN_GENERATE → QA_PLAN_EXECUTE) # noqa: E501
        if current_phase == Phase.QA_PLAN_EXECUTE and result.success:
            # Calculate epic timing before handle_epic_completion modifies state
            epic_duration_ms = get_epic_duration_ms(state)
            epic_stories_count = _count_epic_stories(state)

            new_state, is_project_complete = handle_epic_completion(
                state, epic_list, epic_stories_loader, state_path
            )

            # Story standalone-03 AC6: Dispatch epic_completed event
            _dispatch_event(
                "epic_completed",
                project_path,
                state,
                duration_ms=epic_duration_ms,
                stories_completed=epic_stories_count,
            )

            if is_project_complete:
                # Story standalone-03 AC7: Dispatch project_completed event
                project_duration_ms = get_project_duration_ms(state)
                total_stories = len(state.completed_stories) if state.completed_stories else 0
                _dispatch_event(
                    "project_completed",
                    project_path,
                    state,
                    duration_ms=project_duration_ms,
                    epics_completed=len(epic_list),
                    stories_completed=total_stories,
                )
                # Bug fix: Sync sprint-status before returning to mark epic/retro as done
                # Use new_state which has epic in completed_epics
                _invoke_sprint_sync(new_state, project_path)
                # AC4: Last epic - project complete, terminate gracefully
                logger.info(
                    "Project complete! All %d epics finished.",
                    len(epic_list),
                )
                return LoopExitReason.COMPLETED

            # AC4: Not last epic - advance to next epic
            state = new_state

            # Ensure we're on the correct branch for the new epic
            from bmad_assist.git.branch import ensure_epic_branch, is_git_enabled

            if is_git_enabled() and state.current_epic is not None:
                ensure_epic_branch(state.current_epic, project_path)

            # Story standalone-03 AC6: Start timing for the new epic
            start_epic_timing(state)
            start_story_timing(state)
            # Story 20.10: Sync after epic completion (non-last in project)
            _invoke_sprint_sync(state, project_path)
            logger.info(
                "Advanced to epic %s, story %s",
                state.current_epic,
                state.current_story,
            )

            # Story 15.4: Dispatch story_started for new epic's first story
            story_title = _get_story_title(project_path, state.current_story or "")
            _dispatch_event(
                "story_started",
                project_path,
                state,
                phase=state.current_phase.name if state.current_phase else "CREATE_STORY",
                story_title=story_title,
            )

            continue

        # Code Review Fix: Honor PhaseResult.next_phase override from handlers
        if result.next_phase is not None:
            now = datetime.now(UTC).replace(tzinfo=None)
            state = state.model_copy(
                update={
                    "current_phase": result.next_phase,
                    "updated_at": now,
                }
            )
            logger.info("Phase override: jumping to %s", result.next_phase.name)
            continue

        # AC7: Normal phase advancement via get_next_phase()
        # Note: When QA is disabled (--qa flag not set), RETROSPECTIVE is the last phase
        # and get_next_phase() returns None. In this case, handle epic completion.

        # Defensive check: current_phase could still be None if all prior
        # conditions failed (e.g., phase not in special cases). Verify before use.
        if current_phase is None:
            raise StateError("Logic error: current_phase is None in main loop")

        next_phase = get_next_phase(current_phase)
        if next_phase is None:
            # NOTE: Epic teardown phases (retrospective, qa_plan_*, etc.) are now handled
            # in _execute_epic_teardown() called from the CODE_REVIEW_SYNTHESIS block above.
            # This check should only be reached for unexpected cases.
            #
            # Check if this is the last epic_teardown phase (in case get_next_phase
            # returns None for a phase that's part of teardown but executed separately)
            teardown_phases = (
                [Phase(p) for p in loop_config.epic_teardown]
                if loop_config.epic_teardown
                else []
            )
            is_teardown_phase = current_phase in teardown_phases

            if is_teardown_phase and result.success:
                # This path handles edge case where a teardown phase is executed
                # through the main loop (e.g., resumed mid-teardown)
                logger.info(
                    "Teardown phase %s complete for epic %s",
                    current_phase.name,
                    state.current_epic,
                )
                # Calculate epic timing before handle_epic_completion modifies state
                epic_duration_ms = get_epic_duration_ms(state)
                epic_stories_count = _count_epic_stories(state)

                new_state, is_project_complete = handle_epic_completion(
                    state, epic_list, epic_stories_loader, state_path
                )

                # Dispatch epic_completed event
                _dispatch_event(
                    "epic_completed",
                    project_path,
                    state,
                    duration_ms=epic_duration_ms,
                    stories_completed=epic_stories_count,
                )

                if is_project_complete:
                    project_duration_ms = get_project_duration_ms(state)
                    total_stories = len(state.completed_stories) if state.completed_stories else 0
                    _dispatch_event(
                        "project_completed",
                        project_path,
                        state,
                        duration_ms=project_duration_ms,
                        epics_completed=len(epic_list) if epic_list else 1,
                        stories_completed=total_stories,
                    )
                    _invoke_sprint_sync(new_state, project_path)
                    logger.info(
                        "Project complete! All %d epics finished.",
                        len(epic_list) if epic_list else 1,
                    )
                    return LoopExitReason.COMPLETED

                # Not last epic - advance to next epic
                state = new_state

                # Ensure we're on the correct branch for the new epic
                from bmad_assist.git.branch import ensure_epic_branch, is_git_enabled

                if is_git_enabled() and state.current_epic is not None:
                    ensure_epic_branch(state.current_epic, project_path)

                # Start timing for the new epic
                start_epic_timing(state)
                start_story_timing(state)
                _invoke_sprint_sync(state, project_path)
                logger.info(
                    "Advanced to epic %s, story %s",
                    state.current_epic,
                    state.current_story,
                )

                # Dispatch story_started for new epic's first story
                story_title = _get_story_title(project_path, state.current_story or "")
                _dispatch_event(
                    "story_started",
                    project_path,
                    state,
                    phase=state.current_phase.name if state.current_phase else "CREATE_STORY",
                    story_title=story_title,
                )

                continue

            # Other phases returning None is unexpected - raise error
            raise StateError(f"Cannot advance past {current_phase.name}")

        # Code Review Fix: Include updated_at in phase advancement
        now = datetime.now(UTC).replace(tzinfo=None)
        state = state.model_copy(
            update={
                "current_phase": next_phase,
                "updated_at": now,
            }
        )
        logger.debug(
            "Advanced to phase %s",
            next_phase.name,
        )

        # Story 22.9: Emit dashboard workflow_status event on phase transition
        sequence_id += 1
        if state.current_epic is not None and state.current_story is not None:
            emit_workflow_status(
                run_id=run_id,
                sequence_id=sequence_id,
                epic_num=state.current_epic,
                story_id=str(state.current_story),
                phase=next_phase.name,
                phase_status="in-progress",
            )
