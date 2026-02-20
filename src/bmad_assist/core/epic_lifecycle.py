"""Epic lifecycle status tracking.

Tracks the complete lifecycle of an epic including post-story phases:
- All stories done
- Retrospective completed
- QA plan generated (only when --qa flag enabled)
- QA plan executed (only when --qa flag enabled)

This module is used by CLI to determine what phase to start when
user specifies an epic with all stories completed.

QA phases are experimental and disabled by default. Enable with --qa flag.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import Phase
from bmad_assist.core.types import EpicId

if TYPE_CHECKING:
    from bmad_assist.bmad.state_reader import ProjectState
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


def is_qa_enabled() -> bool:
    """Check if QA phases are enabled via --qa flag.

    QA phases (qa-plan-generate, qa-plan-execute) are experimental
    and disabled by default. Enable with --qa flag.

    Returns:
        True if BMAD_QA_ENABLED environment variable is set.

    """
    return os.environ.get("BMAD_QA_ENABLED") == "1"


@dataclass(frozen=True)
class EpicLifecycleStatus:
    """Status of an epic in its lifecycle.

    Attributes:
        epic_id: Epic identifier.
        all_stories_done: True if all stories have status 'done'.
        retro_completed: True if retrospective artifact exists.
        qa_plan_generated: True if QA plan file exists.
        qa_plan_executed: True if QA results file exists.
        next_phase: Recommended next phase based on status.
        next_phase: Recommended next phase based on status.
        last_story: Last story number in epic (for phase positioning).
        hardening_enabled: True if hardening phase is enabled in config.
        hardening_completed: True if hardening story has been generated.

    """

    epic_id: EpicId
    all_stories_done: bool
    retro_completed: bool
    qa_plan_generated: bool
    qa_plan_executed: bool
    next_phase: Phase | None
    last_story: str | None
    hardening_enabled: bool = False
    hardening_completed: bool = False

    @property
    def is_fully_completed(self) -> bool:
        """Check if epic is fully completed (all phases done).

        When QA is disabled (default), epic is complete after retrospective.
        When QA is enabled (--qa flag), epic requires QA phases too.
        """
        if not self.all_stories_done or not self.retro_completed:
            return False

        # Hardening phase check
        if self.hardening_enabled and not self.hardening_completed:
            return False

        # QA phases only count if QA is enabled
        if is_qa_enabled():
            return self.qa_plan_generated and self.qa_plan_executed

        # Without --qa flag, epic is complete after retrospective
        return True

    def describe(self) -> str:
        """Return human-readable status description."""
        if not self.all_stories_done:
            return "stories in progress"
        if not self.retro_completed:
            return "ready for retrospective"

        if self.hardening_enabled and not self.hardening_completed:
            return "ready for hardening"

        # QA phases only shown if QA is enabled
        if is_qa_enabled():
            if not self.qa_plan_generated:
                return "ready for QA plan generation"
            if not self.qa_plan_executed:
                return "ready for QA plan execution"

        return "fully completed"


def _check_retro_exists(epic_id: EpicId, project_path: Path) -> bool:
    """Check if retrospective is completed for epic.

    Checks BOTH:
    1. Retrospective artifact file exists
    2. OR epic-{id}-retrospective has status "done" in sprint-status.yaml

    This dual check ensures we don't re-run retrospective when it's already
    marked as done in sprint-status.yaml, even if the file check fails.

    Args:
        epic_id: Epic identifier.
        project_path: Project root directory.

    Returns:
        True if retrospective is completed (file exists OR status is done).

    """
    from bmad_assist.core.paths import get_paths

    # Check 1: Retrospective file exists
    paths = get_paths()
    retro_pattern = f"epic-{epic_id}-retro-*.md"
    retro_files = list(paths.retrospectives_dir.glob(retro_pattern))
    if retro_files:
        logger.debug("Retro exists for epic %s: found file(s)", epic_id)
        return True

    # Check 2: Sprint-status shows retrospective as done
    try:
        from bmad_assist.sprint.parser import parse_sprint_status

        sprint_status_path = paths.sprint_status_file
        if sprint_status_path.exists():
            sprint_status = parse_sprint_status(sprint_status_path)
            retro_key = f"epic-{epic_id}-retrospective"
            retro_entry = sprint_status.entries.get(retro_key)
            if retro_entry is not None and retro_entry.status == "done":
                logger.debug("Retro exists for epic %s: sprint-status shows done", epic_id)
                return True
    except Exception as e:
        logger.warning("Could not check sprint-status for retro: %s", e)

    return False


def _check_hardening_completed(epic_id: EpicId, project_path: Path) -> bool:
    """Check if hardening is completed for epic.

    Checks if epic-{id}-hardening has status "done" in sprint-status.yaml.

    Args:
        epic_id: Epic identifier.
        project_path: Project root directory.

    Returns:
        True if hardening is completed.

    """
    from bmad_assist.core.paths import get_paths
    from bmad_assist.sprint.parser import parse_sprint_status

    paths = get_paths()
    sprint_status_path = paths.sprint_status_file

    if not sprint_status_path.exists():
        return False

    try:
        sprint_status = parse_sprint_status(sprint_status_path)
        hardening_key = f"epic-{epic_id}-hardening"
        entry = sprint_status.entries.get(hardening_key)

        if entry is not None and entry.status == "done":
            logger.debug("Hardening completed for epic %s: sprint-status done", epic_id)
            return True

    except Exception as e:
        logger.warning("Could not check sprint-status for hardening: %s", e)

    return False


def _check_qa_plan_exists(config: Config, project_path: Path, epic_id: EpicId) -> bool:
    """Check if QA plan exists for epic.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic identifier.

    Returns:
        True if QA plan file exists.

    """
    from bmad_assist.qa.checker import get_qa_plan_path

    qa_plan_path = get_qa_plan_path(config, project_path, epic_id)
    return qa_plan_path.exists()


def _check_qa_results_exist(epic_id: EpicId) -> bool:
    """Check if QA execution results exist for epic.

    Args:
        epic_id: Epic identifier.

    Returns:
        True if QA results file exists.

    """
    paths = get_paths()
    qa_artifacts = paths.output_folder / "qa-artifacts"
    results_dir = qa_artifacts / "test-results"
    results_pattern = f"epic-{epic_id}-run-*.yaml"
    results_files = list(results_dir.glob(results_pattern))
    return len(results_files) > 0


def get_epic_lifecycle_status(
    epic_id: EpicId,
    project_state: ProjectState,
    config: Config,
    project_path: Path,
) -> EpicLifecycleStatus:
    """Get complete lifecycle status for an epic.

    Checks all phases of epic lifecycle:
    1. All stories done?
    2. Retrospective completed?
    3. QA plan generated?
    4. QA plan executed?

    Args:
        epic_id: Epic identifier.
        project_state: Current project state with stories.
        config: Configuration instance.
        project_path: Project root directory.

    Returns:
        EpicLifecycleStatus with current state and recommended next phase.

    """
    # Get stories for this epic
    epic_stories = [s for s in project_state.all_stories if s.number.startswith(f"{epic_id}.")]

    if not epic_stories:
        logger.warning("No stories found for epic %s", epic_id)
        return EpicLifecycleStatus(
            epic_id=epic_id,
            all_stories_done=False,
            retro_completed=False,
            qa_plan_generated=False,
            qa_plan_executed=False,
            next_phase=Phase.CREATE_STORY,
            last_story=None,
        )

    # Check if all stories are done
    all_done = all(s.status == "done" for s in epic_stories)
    last_story = epic_stories[-1].number if epic_stories else None

    # If not all stories done, return early
    if not all_done:
        # Find first non-done story
        first_incomplete = next((s for s in epic_stories if s.status != "done"), epic_stories[0])
        return EpicLifecycleStatus(
            epic_id=epic_id,
            all_stories_done=False,
            retro_completed=False,
            qa_plan_generated=False,
            qa_plan_executed=False,
            next_phase=Phase.CREATE_STORY,  # Will be adjusted by status in CLI
            last_story=first_incomplete.number,
        )

    # All stories done - check post-story phases
    retro_done = _check_retro_exists(epic_id, project_path)

    # QA phases only checked when --qa flag is enabled
    qa_enabled = is_qa_enabled()
    if qa_enabled:
        qa_plan_done = _check_qa_plan_exists(config, project_path, epic_id)
        qa_exec_done = _check_qa_results_exist(epic_id)
    else:
        # When QA disabled, mark as done to skip these phases
        qa_plan_done = True
        qa_exec_done = True

    # Check hardening status
    hardening_enabled = False
    hardening_completed = True  # Default to True if disabled
    from bmad_assist.core.config.models.loop import LoopConfig
    if (
        isinstance(config.loop, LoopConfig)
        and config.loop.epic_teardown
        and "hardening" in config.loop.epic_teardown
    ):
        hardening_enabled = True
        hardening_completed = _check_hardening_completed(epic_id, project_path)

    # Determine next phase
    if not retro_done:
        next_phase = Phase.RETROSPECTIVE
    elif hardening_enabled and not hardening_completed:
        next_phase = Phase.HARDENING
    elif qa_enabled and not qa_plan_done:
        next_phase = Phase.QA_PLAN_GENERATE
    elif qa_enabled and not qa_exec_done:
        next_phase = Phase.QA_PLAN_EXECUTE
    else:
        next_phase = None  # Fully completed

    logger.debug(
        "Epic %s lifecycle: retro=%s, qa_plan=%s, qa_exec=%s, qa_enabled=%s, next=%s",
        epic_id,
        retro_done,
        qa_plan_done,
        qa_exec_done,
        qa_enabled,
        next_phase.value if next_phase else "COMPLETED",
    )

    return EpicLifecycleStatus(
        epic_id=epic_id,
        all_stories_done=True,
        retro_completed=retro_done,
        qa_plan_generated=qa_plan_done,
        qa_plan_executed=qa_exec_done,
        next_phase=next_phase,
        last_story=last_story,
        hardening_enabled=hardening_enabled,
        hardening_completed=hardening_completed,
    )
