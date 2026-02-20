"""State data model for bmad-assist development loop.

This module defines the core data structures for tracking loop progress,
enabling crash recovery and resume functionality (FR4, FR34, NFR1).

State files are stored per-project at {project_root}/.bmad-assist/state.yaml.
This ensures each project has independent state tracking.

Usage:
    from bmad_assist.core.state import State, Phase, save_state, get_state_path
    from pathlib import Path

    # Create default (empty) state
    state = State()

    # Create state with values
    state = State(
        current_epic=3,
        current_story="3.1",
        current_phase=Phase.DEV_STORY,
        completed_stories=["1.1", "1.2"],
    )

    # Get state path for a project
    project = Path("/path/to/project")
    state_path = get_state_path(project_root=project)
    # Returns: /path/to/project/.bmad-assist/state.yaml

    # Save state atomically to YAML file
    save_state(state, state_path)

    # Serialize for YAML persistence
    data = state.model_dump(mode="json")

    # Deserialize from YAML data
    state = State.model_validate(data)
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.timing import utc_now_naive
from bmad_assist.core.types import EpicId
from bmad_assist.reporting.models import AnomalyItem


def _get_now() -> datetime:
    """Get current UTC datetime without timezone info.

    Uses centralized timing module for consistency and testability.
    """
    return utc_now_naive()


if TYPE_CHECKING:
    from bmad_assist.core.config import Config

# State file name (relative to project root)
STATE_FILENAME: str = "state.yaml"
STATE_DIR: str = ".bmad-assist"

# Legacy default (kept for backwards compatibility with tests)
DEFAULT_STATE_PATH: str = "~/.bmad-assist/state.yaml"

__all__ = [
    "State",
    "Phase",
    "PreflightStateEntry",
    "save_state",
    "load_state",
    "update_position",
    "mark_story_completed",
    "advance_state",
    "ResumePoint",
    "CleanupResult",
    "get_resume_point",
    "cleanup_partial_outputs",
    "DEFAULT_STATE_PATH",
    "STATE_FILENAME",
    "STATE_DIR",
    "get_state_path",
    # Timing functions
    "start_story_timing",
    "start_phase_timing",
    "get_phase_duration_ms",
    "get_story_duration_ms",
    # Epic/Project timing (Story standalone-03)
    "start_epic_timing",
    "start_project_timing",
    "get_epic_duration_ms",
    "get_project_duration_ms",
]

logger = logging.getLogger(__name__)

# Suffix for temporary files during atomic write
TEMP_FILE_SUFFIX = ".tmp"


class Phase(Enum):
    """Workflow phases for the main development loop.

    Phases execute in this order for each story:
        1. CREATE_STORY - Create story context from epic
        2. VALIDATE_STORY - Multi-LLM validation of story
        3. VALIDATE_STORY_SYNTHESIS - Master LLM synthesizes validation
        4. ATDD - Acceptance Test Driven Development (testarch module)
        5. DEV_STORY - Master LLM implements story
        6. CODE_REVIEW - Multi-LLM code review
        7. CODE_REVIEW_SYNTHESIS - Master LLM synthesizes review
        8. TEST_REVIEW - Test quality review (testarch module)
        9. TRACE - Requirements traceability matrix (testarch module)
        10. TEA_FRAMEWORK - Test framework initialization (epic_setup phase)
        11. TEA_CI - CI pipeline initialization (epic_setup phase)
        12. TEA_TEST_DESIGN - Test design planning (dual-scope: epic_setup or story)
        13. RETROSPECTIVE - Epic retrospective (after last story in epic)
        14. QA_PLAN_GENERATE - Generate E2E test plan for epic
        15. QA_PLAN_EXECUTE - Execute E2E tests for epic
        16. QA_REMEDIATE - Collect epic issues and auto-fix or escalate

    The phase ordering enables workflow orchestration in Epic 6.

    Epic Setup Phases (run once per epic before first story):
        TEA_FRAMEWORK: Initialize test framework (Playwright/Cypress).
        TEA_CI: Initialize CI pipeline (GitHub Actions/GitLab CI/etc).
        TEA_TEST_DESIGN: Test design planning (dual-scope phase).
            - System-level: First epic or no sprint-status.yaml - creates architecture + QA docs.
            - Epic-level: Subsequent epics - creates per-epic test plan.

    Attributes:
        CREATE_STORY: Initial story creation phase.
        VALIDATE_STORY: Parallel Multi-LLM validation phase.
        VALIDATE_STORY_SYNTHESIS: Master synthesis of validation reports.
        ATDD: Acceptance Test Driven Development phase (testarch module).
        DEV_STORY: Story implementation by Master LLM.
        CODE_REVIEW: Parallel Multi-LLM code review phase.
        CODE_REVIEW_SYNTHESIS: Master synthesis of code reviews.
        TEST_REVIEW: Test quality review phase (testarch module).
        TRACE: Requirements traceability matrix phase (testarch module).
        TEA_FRAMEWORK: Test framework initialization phase (epic_setup scope).
        TEA_CI: CI pipeline initialization phase (epic_setup scope).
        TEA_TEST_DESIGN: Test design planning phase (dual-scope: epic_setup or story).
        TEA_AUTOMATE: Test automation expansion phase (epic_setup scope, after test_design).
        TEA_NFR_ASSESS: Non-functional requirements assessment phase (epic_teardown scope).
        RETROSPECTIVE: Epic retrospective phase (after last story in epic).
        QA_PLAN_GENERATE: Generate E2E test plan for completed epic.
        QA_PLAN_EXECUTE: Execute E2E tests using generated test plan.
        QA_REMEDIATE: Collect epic issues from multiple sources and auto-fix or escalate.

    """

    CREATE_STORY = "create_story"
    VALIDATE_STORY = "validate_story"
    VALIDATE_STORY_SYNTHESIS = "validate_story_synthesis"
    ATDD = "atdd"
    DEV_STORY = "dev_story"
    CODE_REVIEW = "code_review"
    CODE_REVIEW_SYNTHESIS = "code_review_synthesis"
    TEST_REVIEW = "test_review"
    TRACE = "trace"
    TEA_FRAMEWORK = "tea_framework"
    TEA_CI = "tea_ci"
    TEA_TEST_DESIGN = "tea_test_design"
    TEA_AUTOMATE = "tea_automate"  # epic_setup scope: after test_design
    TEA_NFR_ASSESS = "tea_nfr_assess"  # epic_teardown scope: after trace
    RETROSPECTIVE = "retrospective"
    HARDENING = "hardening"
    QA_PLAN_GENERATE = "qa_plan_generate"
    QA_PLAN_EXECUTE = "qa_plan_execute"
    QA_REMEDIATE = "qa_remediate"


class PreflightStateEntry(BaseModel):
    """State entry for testarch preflight completion tracking.

    Note: String fields store PreflightStatus.value for YAML serialization.
    Only populated when preflight completes via mark_completed().

    Attributes:
        completed_at: When preflight was run (UTC, naive).
        test_design: Status string (found/not_found/skipped).
        framework: Status string (found/not_found/skipped).
        ci: Status string (found/not_found/skipped).

    """

    completed_at: datetime
    test_design: str  # PreflightStatus.value
    framework: str  # PreflightStatus.value
    ci: str  # PreflightStatus.value


class State(BaseModel):
    """Persistent state for the bmad-assist development loop.

    This model tracks the current position in the development loop,
    enabling crash recovery and resume functionality. All datetime
    values are timezone-naive and assumed to be UTC.

    Attributes:
        current_epic: Current epic ID (int or str), None if not started.
        current_story: Current story ID (e.g., "2.3"), None if not started.
        current_phase: Current workflow phase, None if not started.
        completed_stories: List of completed story IDs (e.g., ["1.1", "1.2"]).
        completed_epics: List of completed epic IDs (e.g., [1, 2, "testarch"]).
        started_at: Timestamp when loop was first started (UTC, naive).
        updated_at: Timestamp of last state update (UTC, naive).
        story_started_at: When current story execution began (for total duration).
        phase_started_at: When current phase execution began (for phase duration).
        testarch_preflight: Preflight check completion tracking (None if not run).
        atdd_ran_for_story: True if ATDD ran for current story (reset at handler start).
        atdd_ran_in_epic: True if ATDD ran for any story in current epic.
        framework_ran_in_epic: True if framework handler ran in current epic.
            Reset to False when epic changes.
        ci_ran_in_epic: True if CI handler ran in current epic.
            Reset to False when epic changes.
        automate_ran_in_epic: True if automate handler ran in current epic.
            Reset to False when epic changes.
        nfr_assess_ran_in_epic: True if NFR assessment handler ran in current epic.
            Reset to False when epic changes.
        epic_setup_complete: True if epic_setup phases ran for current epic.
            Reset to False when epic changes in handle_epic_completion().

    Example:
        >>> state = State()
        >>> state.current_epic is None
        True

        >>> state = State(
        ...     current_epic=3,
        ...     current_story="3.1",
        ...     current_phase=Phase.DEV_STORY,
        ... )
        >>> state.current_phase.value
        'dev_story'

    """

    current_epic: EpicId | None = None
    current_story: str | None = None
    current_phase: Phase | None = None
    completed_stories: list[str] = Field(default_factory=list)
    completed_epics: list[EpicId] = Field(default_factory=list)
    started_at: datetime | None = None
    updated_at: datetime | None = None
    # Timing context for notifications (persisted for crash recovery)
    story_started_at: datetime | None = None
    phase_started_at: datetime | None = None
    # Story standalone-03 AC6/AC7: Epic and project timing for cumulative notifications
    epic_started_at: datetime | None = None
    project_started_at: datetime | None = None
    anomalies: list[AnomalyItem] = Field(default_factory=list)
    testarch_preflight: PreflightStateEntry | None = None
    atdd_ran_for_story: bool = False
    atdd_ran_in_epic: bool = False
    # Story 25.9: Track framework/CI handler execution in current epic
    framework_ran_in_epic: bool = False  # True if framework handler ran in current epic
    ci_ran_in_epic: bool = False  # True if CI handler ran in current epic
    # Story 25.10: Track test design handler execution in current epic
    test_design_ran_in_epic: bool = False  # True if test design ran (system or epic level)
    # Story 25.11: Track automate and NFR assessment handler execution in current epic
    automate_ran_in_epic: bool = False  # True if automate handler ran in current epic
    nfr_assess_ran_in_epic: bool = False  # True if NFR assessment ran in current epic
    qa_category: str = "A"  # Test category for QA phases: "A", "B", or "all"
    # Configurable loop architecture: track epic setup completion
    epic_setup_complete: bool = False  # Reset to False on epic change


def save_state(state: State, path: str | Path) -> None:
    """Save state to YAML file using atomic write.

    Uses temporary file + os.replace() to ensure crash resilience.
    Previous valid state is never corrupted by partial writes.
    Works cross-platform (os.replace handles Windows overwrite).

    Args:
        state: The State instance to persist.
        path: Target file path (str or Path). Tilde (~) is expanded.

    Raises:
        StateError: If write operation fails.

    Example:
        >>> state = State(current_epic=3, current_story="3.1")
        >>> save_state(state, Path("~/.bmad-assist/state.yaml"))

    """
    path = Path(path).expanduser()
    temp_path = path.with_suffix(path.suffix + TEMP_FILE_SUFFIX)

    try:
        # Create parent directories if missing
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize state to YAML-compatible dict
        data = state.model_dump(mode="json")

        # Write to temp file first (explicit UTF-8 for cross-platform)
        # Use fsync to ensure data reaches disk before rename (durability on hard kill)
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replace (os.replace works cross-platform, unlike os.rename on Windows)
        os.replace(temp_path, path)

    except OSError as e:
        # Clean up temp file if it exists
        if temp_path.exists():
            temp_path.unlink()
        raise StateError(f"Failed to save state to {path}: {e}") from e


def _cleanup_temp_files(path: str | Path) -> None:
    """Remove orphaned temp files from previous crashed writes.

    Should be called during state loading to clean up after crashes.

    Args:
        path: The state file path (will check for "{path}.tmp").

    Raises:
        StateError: If temp file exists but cannot be removed.

    """
    path = Path(path).expanduser()
    temp_path = path.with_suffix(path.suffix + TEMP_FILE_SUFFIX)

    if temp_path.exists():
        logger.warning(f"Removing orphaned temp file from previous crash: {temp_path}")
        try:
            temp_path.unlink()
        except OSError as e:
            raise StateError(f"Cannot remove orphaned temp file {temp_path}: {e}") from e


def load_state(path: str | Path) -> State:
    """Load state from YAML file with validation.

    Restores persisted state on restart. If file doesn't exist or is empty,
    returns fresh initial state for new sessions. Cleans up orphaned temp
    files from previous crashes before loading.

    Args:
        path: Source file path (str or Path). Tilde (~) is expanded.

    Returns:
        State instance loaded from file, or fresh State() if file missing/empty.

    Raises:
        StateError: If file is corrupted, contains invalid data, or cannot be read.

    Example:
        >>> state = load_state("~/.bmad-assist/state.yaml")
        >>> if state.current_epic is None:
        ...     print("Fresh start - no previous state")

    """
    path = Path(path).expanduser()

    # Clean up orphaned temp files from previous crashes
    _cleanup_temp_files(path)

    # Handle missing file - fresh start
    if not path.exists():
        logger.info(f"No state file at {path}, starting fresh")
        return State()

    # Read file content with explicit error handling for IO issues
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        # Covers PermissionError, IOError, network filesystem errors
        raise StateError(f"Cannot read state file at {path}: {e}") from e
    except UnicodeDecodeError as e:
        # File exists but contains invalid UTF-8 (corrupted or binary)
        raise StateError(f"State file at {path} is not valid UTF-8: {e}") from e

    # Handle empty file - fresh start
    if not content.strip():
        logger.info(f"Empty state file at {path}, starting fresh")
        return State()

    # Parse YAML and validate
    try:
        data = yaml.safe_load(content)

        # Handle YAML that parses to non-dict (e.g., just a string or number)
        if not isinstance(data, dict):
            raise StateError(
                f"State file corrupted at {path}: expected dict, got {type(data).__name__}"
            )

        # Validate with Pydantic
        return State.model_validate(data)

    except yaml.YAMLError as e:
        raise StateError(f"State file corrupted at {path}: invalid YAML") from e
    except ValidationError as e:
        raise StateError(f"State file validation failed at {path}: {e}") from e


def update_position(
    state: State,
    *,
    epic: EpicId | None = None,
    story: str | None = None,
    phase: Phase | None = None,
) -> None:
    """Update current position in the development loop.

    Updates only the specified fields, preserving others. Automatically
    manages timestamps: sets started_at on first update, updates
    updated_at on every call.

    When epic changes, resets atdd_ran_in_epic flag to False (new epic
    starts fresh for ATDD tracking).

    Args:
        state: The State instance to modify.
        epic: New epic number (1-based), or None to keep current.
        story: New story ID (e.g., "2.3"), or None to keep current.
        phase: New workflow phase, or None to keep current.

    Example:
        >>> state = State()
        >>> update_position(state, epic=1, story="1.1", phase=Phase.CREATE_STORY)
        >>> state.current_epic
        1

    """
    now = _get_now()

    # Reset epic-scoped flags when epic changes (new epic starts fresh)
    if epic is not None and epic != state.current_epic:
        state.atdd_ran_in_epic = False
        state.framework_ran_in_epic = False
        state.ci_ran_in_epic = False
        state.test_design_ran_in_epic = False
        state.automate_ran_in_epic = False
        state.nfr_assess_ran_in_epic = False

    if epic is not None:
        state.current_epic = epic
    if story is not None:
        state.current_story = story
    if phase is not None:
        state.current_phase = phase

    # Set started_at on first position update
    if state.started_at is None:
        state.started_at = now

    state.updated_at = now


def mark_story_completed(state: State) -> None:
    """Mark current story as completed.

    Adds current_story to completed_stories list if not already present.
    Idempotent: calling multiple times won't create duplicates.

    Args:
        state: The State instance to modify.

    Raises:
        StateError: If current_story is None.

    Example:
        >>> state = State(current_story="2.3", completed_stories=["2.1", "2.2"])
        >>> mark_story_completed(state)
        >>> state.completed_stories
        ['2.1', '2.2', '2.3']

    """
    if state.current_story is None:
        raise StateError("Cannot mark story completed: no current story set")

    # Idempotent: don't add duplicates
    if state.current_story not in state.completed_stories:
        state.completed_stories.append(state.current_story)

    state.updated_at = _get_now()


def advance_state(state: State, phase_list: list[str] | None = None) -> dict[str, Any]:
    """Advance state to the next phase in the workflow.

    Moves current_phase to the next phase in the configured story phase sequence.
    Uses LoopConfig.story (via get_loop_config()) by default, or explicit phase_list.

    Note: epic_complete detection is now handled by runner.py using LoopConfig.
    This function returns epic_complete=True for backwards compatibility when at
    the last phase in the story sequence.

    Args:
        state: The State instance to modify.
        phase_list: Optional explicit phase list (snake_case strings).
            If None, uses get_loop_config().story.

    Returns:
        Dict with transition info:
        - "previous_phase": Phase before transition
        - "new_phase": Phase after transition (same if at last phase)
        - "transitioned": True if phase changed
        - "epic_complete": True if at last phase in story sequence

    Raises:
        StateError: If current_phase is None or not found in phase sequence.

    Example:
        >>> state = State(current_phase=Phase.DEV_STORY)
        >>> result = advance_state(state)
        >>> result["new_phase"]
        <Phase.CODE_REVIEW: 'code_review'>

    """
    from bmad_assist.core.config import get_loop_config

    if state.current_phase is None:
        raise StateError("Cannot advance state: no current phase set")

    previous = state.current_phase

    # Get phase list from loop config if not provided
    if phase_list is None:
        loop_config = get_loop_config()
        phase_list = loop_config.story

    # Find current index in the phase sequence
    current_value = previous.value
    try:
        current_idx = phase_list.index(current_value)
    except ValueError as e:
        raise StateError(
            f"Cannot advance state: phase {previous!r} not in loop config story sequence"
        ) from e

    # Check if at last phase in story sequence
    if current_idx + 1 >= len(phase_list):
        state.updated_at = _get_now()
        return {
            "previous_phase": previous,
            "new_phase": previous,
            "transitioned": False,
            "epic_complete": True,
        }

    # Advance to next phase
    next_value = phase_list[current_idx + 1]
    try:
        next_phase = Phase(next_value)
    except ValueError as e:
        raise StateError(f"Invalid phase '{next_value}' in loop config") from e

    state.current_phase = next_phase
    state.updated_at = _get_now()

    return {
        "previous_phase": previous,
        "new_phase": next_phase,
        "transitioned": True,
        "epic_complete": False,
    }


# =============================================================================
# Resume Point (Story 3.5)
# =============================================================================


@dataclass
class ResumePoint:
    """Information about where to resume the development loop.

    Used by loop orchestration (Epic 6) to determine whether to start fresh
    or resume from a previous position after crash/restart.

    Attributes:
        epic: Current epic ID to resume from, or None for fresh start.
        story: Current story ID to resume from, or None for fresh start.
        phase: Current phase to resume from, or None for fresh start.
        is_fresh_start: True if no valid resume point exists.
        completed_stories: List of completed story IDs for context.
        started_at: When the loop was originally started, or None.

    Example:
        >>> resume = get_resume_point("/path/to/state.yaml")
        >>> if resume.is_fresh_start:
        ...     print("Starting fresh")
        ... else:
        ...     print(f"Resuming {resume.epic}.{resume.story}")

    """

    epic: EpicId | None
    story: str | None
    phase: Phase | None
    is_fresh_start: bool
    completed_stories: list[str] = field(default_factory=list)
    started_at: datetime | None = None


@dataclass
class CleanupResult:
    """Result of partial output cleanup after crash.

    Returned by cleanup_partial_outputs() to report what was cleaned
    and any warnings encountered during cleanup.

    Attributes:
        uncommitted_files: Git-tracked files with uncommitted changes (warning, not auto-cleaned).
        cleaned_files: Files that were removed as partial outputs.
        warnings: Warning messages about cleanup actions.

    Example:
        >>> result = cleanup_partial_outputs(state, Path("docs/sprint-artifacts"))
        >>> if result.warnings:
        ...     for w in result.warnings:
        ...         print(f"Warning: {w}")

    """

    uncommitted_files: list[str] = field(default_factory=list)
    cleaned_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def get_resume_point(state_path: str | Path) -> ResumePoint:
    """Determine resume point from persisted state.

    Loads state from file and determines whether to resume from a previous
    position or start fresh. If state file is corrupted, raises StateError
    (crash recovery requires explicit handling of corruption, not silent
    fresh start).

    Args:
        state_path: Path to state file (str or Path). Tilde (~) is expanded.

    Returns:
        ResumePoint with resume position or is_fresh_start=True.

    Raises:
        StateError: If state file exists but is corrupted or invalid.

    Example:
        >>> resume = get_resume_point("~/.bmad-assist/state.yaml")
        >>> if resume.is_fresh_start:
        ...     print("Starting fresh")
        ... else:
        ...     print(f"Resuming {resume.epic}.{resume.story} at {resume.phase.value}")

    """
    state = load_state(state_path)  # Raises StateError if corrupted

    # Check if state has a valid position (all three must be set)
    has_position = (
        state.current_epic is not None
        and state.current_story is not None
        and state.current_phase is not None
    )

    if not has_position:
        logger.info("Fresh start - state has no position")
        return ResumePoint(
            epic=None,
            story=None,
            phase=None,
            is_fresh_start=True,
            completed_stories=list(state.completed_stories),
            started_at=state.started_at,
        )

    # Type narrowing for mypy - we know these are not None due to has_position check
    assert state.current_phase is not None  # for mypy
    logger.info(
        f"Resuming from epic {state.current_epic}, "
        f"story {state.current_story}, "
        f"phase {state.current_phase.value}"
    )

    return ResumePoint(
        epic=state.current_epic,
        story=state.current_story,
        phase=state.current_phase,
        is_fresh_start=False,
        completed_stories=list(state.completed_stories),
        started_at=state.started_at,
    )


def cleanup_partial_outputs(state: State, sprint_artifacts: Path) -> CleanupResult:
    """Clean up partial outputs from crashed phase.

    Different phases have different cleanup needs:
    - Validation phases (VALIDATE_STORY, CODE_REVIEW): Idempotent, no cleanup
    - Synthesis phases (VALIDATE_STORY_SYNTHESIS, CODE_REVIEW_SYNTHESIS): Remove ALL
      master synthesis reports for the current story
    - DEV_STORY: Check for uncommitted git changes (warn, don't auto-clean)
    - Other phases (CREATE_STORY, RETROSPECTIVE): Idempotent, no cleanup

    Handles edge cases gracefully:
    - Git unavailable: Warning added, no exception (AC11)
    - sprint_artifacts missing: Returns empty result (AC12)

    Args:
        state: Current State with phase to clean up.
        sprint_artifacts: Path to sprint artifacts directory.

    Returns:
        CleanupResult with details of cleanup actions.

    Example:
        >>> result = cleanup_partial_outputs(state, Path("docs/sprint-artifacts"))
        >>> if result.warnings:
        ...     for w in result.warnings:
        ...         print(f"Warning: {w}")
        >>> if result.cleaned_files:
        ...     print(f"Cleaned {len(result.cleaned_files)} partial outputs")

    """
    result = CleanupResult()

    if state.current_phase is None:
        return result

    phase = state.current_phase

    # Validation phases are idempotent - no cleanup needed (AC4)
    if phase in (Phase.VALIDATE_STORY, Phase.CODE_REVIEW):
        logger.info(f"Phase {phase.value} is idempotent, no cleanup needed")
        return result

    # CREATE_STORY and RETROSPECTIVE are also idempotent
    if phase in (Phase.CREATE_STORY, Phase.RETROSPECTIVE):
        logger.info(f"Phase {phase.value} is idempotent, no cleanup needed")
        return result

    # DEV_STORY: Check git status for uncommitted changes (AC5)
    if phase == Phase.DEV_STORY:
        try:
            git_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Check for git command failure (non-zero returncode)
            if git_result.returncode != 0:
                error_msg = git_result.stderr.strip() or "unknown error"
                result.warnings.append(
                    f"Could not check git status (exit {git_result.returncode}): {error_msg}"
                )
                logger.warning(result.warnings[-1])
            elif git_result.stdout.strip():
                uncommitted = git_result.stdout.strip().split("\n")
                result.uncommitted_files = uncommitted
                result.warnings.append(
                    f"Uncommitted changes detected from interrupted DEV_STORY phase: "
                    f"{len(uncommitted)} files. Review before continuing."
                )
                logger.warning(result.warnings[-1])
        except subprocess.TimeoutExpired as e:
            # AC11: Git timeout handled gracefully
            result.warnings.append(f"Could not check git status: {e}")
            logger.warning(result.warnings[-1])
        except FileNotFoundError as e:
            # AC11: Git unavailable handled gracefully
            result.warnings.append(f"Could not check git status: {e}")
            logger.warning(result.warnings[-1])

        return result

    # Synthesis phases: Remove ALL master synthesis reports for story (AC6)
    if phase in (Phase.VALIDATE_STORY_SYNTHESIS, Phase.CODE_REVIEW_SYNTHESIS):
        story_id = state.current_story
        # AC12: Handle missing directory gracefully
        if not sprint_artifacts.exists():
            return result
        if not sprint_artifacts.is_dir():
            msg = f"sprint_artifacts path is not a directory: {sprint_artifacts}"
            result.warnings.append(msg)
            logger.warning(msg)
            return result
        if story_id:
            # Pattern: story-validation-{story}-master-*.md or code-review-{story}-master-*.md
            prefix = (
                "story-validation" if phase == Phase.VALIDATE_STORY_SYNTHESIS else "code-review"
            )
            story_key = story_id.replace(".", "-")

            # Check story-validations subdirectory
            validations_dir = sprint_artifacts / "story-validations"
            if validations_dir.exists():
                for report in validations_dir.glob(f"{prefix}-{story_key}-master-*.md"):
                    try:
                        logger.info(f"Removing partial synthesis report: {report}")
                        report.unlink()
                        result.cleaned_files.append(str(report))
                    except OSError as e:
                        msg = f"Failed to remove partial report {report}: {e}"
                        logger.warning(msg)
                        result.warnings.append(msg)

            # Also check code-reviews subdirectory for code review synthesis
            if phase == Phase.CODE_REVIEW_SYNTHESIS:
                code_reviews_dir = sprint_artifacts / "code-reviews"
                if code_reviews_dir.exists():
                    for report in code_reviews_dir.glob(f"{prefix}-{story_key}-master-*.md"):
                        try:
                            logger.info(f"Removing partial synthesis report: {report}")
                            report.unlink()
                            result.cleaned_files.append(str(report))
                        except OSError as e:
                            msg = f"Failed to remove partial report {report}: {e}"
                            logger.warning(msg)
                            result.warnings.append(msg)

        return result

    return result


# =============================================================================
# State Path Resolution (Story 3.6)
# =============================================================================


def get_state_path(
    config: "Config | None" = None,
    *,
    project_root: Path | None = None,
) -> Path:
    """Get resolved state file path for a project.

    State is stored per-project in {project_root}/.bmad-assist/state.yaml.
    This ensures each project has its own independent state.

    Priority:
    1. If config.state_path is set → use that path (for backwards compatibility)
    2. If project_root is provided → use {project_root}/.bmad-assist/state.yaml
    3. Otherwise → use CWD as project root

    Note:
        Global state in ~/.bmad-assist/state.yaml is NOT used by default.
        Each project should have its own state file.

    Args:
        config: Optional Config instance. If config.state_path is set, uses that.
        project_root: Project root directory. If None, uses current working directory.

    Returns:
        Absolute Path to the state file location.

    Example:
        >>> from bmad_assist.core.state import get_state_path
        >>> from pathlib import Path
        >>> # With project root
        >>> state_path = get_state_path(project_root=Path("/my/project"))
        >>> str(state_path)
        '/my/project/.bmad-assist/state.yaml'

        >>> # Without project root (uses CWD)
        >>> state_path = get_state_path()
        >>> state_path.name
        'state.yaml'

    """
    # Priority 1: Use explicit config.state_path if set (backwards compatibility)
    if config is not None and config.state_path:
        return Path(config.state_path).expanduser().resolve()

    # Priority 2: Use project_root if provided
    if project_root is not None:
        return (project_root / STATE_DIR / STATE_FILENAME).resolve()

    # Priority 3: Use CWD as project root
    return (Path.cwd() / STATE_DIR / STATE_FILENAME).resolve()


# =============================================================================
# Timing Functions (Story 21.X - Notification timing)
# =============================================================================


def start_story_timing(state: State) -> None:
    """Mark story execution start time.

    Sets both story_started_at and phase_started_at to current time.
    Called when a new story begins execution (first phase of story).

    This timestamp is persisted in state.yaml for crash recovery.
    If the process crashes and resumes, timing continues from the
    stored value (conservative timing - includes downtime).

    Args:
        state: The State instance to modify.

    Example:
        >>> state = State()
        >>> start_story_timing(state)
        >>> state.story_started_at is not None
        True
        >>> state.phase_started_at is not None
        True

    """
    now = _get_now()
    state.story_started_at = now
    state.phase_started_at = now
    state.updated_at = now


def start_phase_timing(state: State) -> None:
    """Mark phase execution start time.

    Sets phase_started_at to current time. Called when a new phase
    begins execution (after previous phase completes).

    If story_started_at is None (resuming mid-story after crash),
    also sets story_started_at to maintain valid timing context.

    Args:
        state: The State instance to modify.

    Example:
        >>> state = State()
        >>> start_phase_timing(state)
        >>> state.phase_started_at is not None
        True

    """
    now = _get_now()
    state.phase_started_at = now
    # Ensure story timing exists (handles resume from crash)
    if state.story_started_at is None:
        state.story_started_at = now
    state.updated_at = now


def get_phase_duration_ms(state: State) -> int:
    """Calculate phase duration in milliseconds.

    Returns time elapsed since phase_started_at. If phase_started_at
    is None, returns 0 (defensive - should not happen in normal flow).

    Args:
        state: The State instance with timing context.

    Returns:
        Phase duration in milliseconds (int, >= 0).

    Example:
        >>> state = State()
        >>> start_phase_timing(state)
        >>> # ... some time passes ...
        >>> duration = get_phase_duration_ms(state)
        >>> duration >= 0
        True

    """
    if state.phase_started_at is None:
        logger.warning("get_phase_duration_ms called with phase_started_at=None")
        return 0

    now = _get_now()
    delta = now - state.phase_started_at
    return int(delta.total_seconds() * 1000)


def get_story_duration_ms(state: State) -> int:
    """Calculate story total duration in milliseconds.

    Returns time elapsed since story_started_at. This is the TOTAL
    time from when the story's first phase started until now.

    If story_started_at is None, returns 0 (defensive - should not
    happen in normal flow).

    Args:
        state: The State instance with timing context.

    Returns:
        Story total duration in milliseconds (int, >= 0).

    Example:
        >>> state = State()
        >>> start_story_timing(state)
        >>> # ... multiple phases execute ...
        >>> duration = get_story_duration_ms(state)
        >>> duration >= 0
        True

    """
    if state.story_started_at is None:
        logger.warning("get_story_duration_ms called with story_started_at=None")
        return 0

    now = _get_now()
    delta = now - state.story_started_at
    return int(delta.total_seconds() * 1000)


# =============================================================================
# Epic and Project Timing Functions (Story standalone-03 AC6/AC7)
# =============================================================================


def start_epic_timing(state: State) -> None:
    """Mark epic execution start time.

    Sets epic_started_at to current time. Called when a new epic begins
    (first story of the epic starts).

    This timestamp is persisted in state.yaml for crash recovery.
    Used to calculate cumulative epic duration in notifications.

    Args:
        state: The State instance to modify.

    Example:
        >>> state = State()
        >>> start_epic_timing(state)
        >>> state.epic_started_at is not None
        True

    """
    now = _get_now()
    state.epic_started_at = now
    state.updated_at = now


def start_project_timing(state: State) -> None:
    """Mark project execution start time.

    Sets project_started_at to current time. Called when the first epic
    of the project begins. Only set once per project (not reset on resume).

    This timestamp is persisted in state.yaml for crash recovery.
    Used to calculate cumulative project duration in notifications.

    Args:
        state: The State instance to modify.

    Example:
        >>> state = State()
        >>> start_project_timing(state)
        >>> state.project_started_at is not None
        True

    """
    now = _get_now()
    state.project_started_at = now
    state.updated_at = now


def get_epic_duration_ms(state: State) -> int:
    """Calculate epic duration in milliseconds.

    Returns time elapsed since epic_started_at. If epic_started_at
    is None, returns 0 (defensive - handles resume from older state).

    Args:
        state: The State instance with timing context.

    Returns:
        Epic duration in milliseconds (int, >= 0).

    Example:
        >>> state = State()
        >>> start_epic_timing(state)
        >>> # ... stories complete ...
        >>> duration = get_epic_duration_ms(state)
        >>> duration >= 0
        True

    """
    if state.epic_started_at is None:
        logger.warning("get_epic_duration_ms called with epic_started_at=None")
        return 0

    now = _get_now()
    delta = now - state.epic_started_at
    return int(delta.total_seconds() * 1000)


def get_project_duration_ms(state: State) -> int:
    """Calculate project duration in milliseconds.

    Returns time elapsed since project_started_at. If project_started_at
    is None, returns 0 (defensive - handles resume from older state).

    Args:
        state: The State instance with timing context.

    Returns:
        Project duration in milliseconds (int, >= 0).

    Example:
        >>> state = State()
        >>> start_project_timing(state)
        >>> # ... epics complete ...
        >>> duration = get_project_duration_ms(state)
        >>> duration >= 0
        True

    """
    if state.project_started_at is None:
        logger.warning("get_project_duration_ms called with project_started_at=None")
        return 0

    now = _get_now()
    delta = now - state.project_started_at
    return int(delta.total_seconds() * 1000)
