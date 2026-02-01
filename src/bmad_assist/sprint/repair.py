"""Sprint-status repair orchestrator with auto-repair capability.

This module provides the repair orchestrator that integrates all Epic 20 components
to perform comprehensive sprint-status repair:
1. Parse existing sprint-status
2. Generate entries from epic files
3. Scan project artifacts
4. Reconcile using evidence-based inference
5. Apply state sync
6. Write atomically with comment preservation

Two operation modes:
- SILENT: Auto-fix without prompting, used after phase completions
- INTERACTIVE: Check divergence threshold, log WARNING if >30%, used on loop init

CRITICAL: This module is designed to NEVER crash or block the main loop.
All operations are wrapped in comprehensive exception handling.

Public API:
    - RepairMode: Enum for repair operation modes
    - RepairResult: Dataclass with repair statistics and errors
    - repair_sprint_status: Main entry point for sprint-status repair
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.exceptions import ParserError, StateError

if TYPE_CHECKING:
    from bmad_assist.core.state import State
    from bmad_assist.sprint.dialog import RepairSummary

logger = logging.getLogger(__name__)

__all__ = [
    "RepairMode",
    "RepairResult",
    "repair_sprint_status",
]


# =============================================================================
# RepairMode Enum (Task 1)
# =============================================================================


class RepairMode(Enum):
    """Mode for sprint-status repair operations.

    SILENT:
        Auto-fix without prompting. Used after phase completions.
        Logs changes at INFO level.

    INTERACTIVE:
        Check divergence threshold before repair. Used on loop init.
        If divergence > 30%, logs WARNING with summary.
        Story 20.12 will add actual dialog - for now, always proceeds.

    Examples:
        >>> mode = RepairMode.SILENT
        >>> mode.value
        'silent'
        >>> mode = RepairMode.INTERACTIVE
        >>> mode.value
        'interactive'

    """

    SILENT = "silent"
    INTERACTIVE = "interactive"


# =============================================================================
# RepairResult Dataclass (Task 1)
# =============================================================================


@dataclass(frozen=True)
class RepairResult:
    """Result of sprint-status repair operation.

    Frozen dataclass ensuring immutability. All error information is captured
    in the errors tuple rather than raising exceptions.

    Attributes:
        changes_count: Number of entries modified.
        divergence_pct: Percentage of entries that diverged (0.0 - 100.0).
        was_interactive: True if INTERACTIVE mode was triggered.
        user_cancelled: True if user cancelled in interactive mode.
        errors: Any errors encountered (empty tuple if none).

    Examples:
        >>> result = RepairResult(changes_count=5, divergence_pct=15.0)
        >>> result.summary()
        'Repaired 5 entries (15.0% divergence)'
        >>> result.success
        True

    """

    changes_count: int = 0
    divergence_pct: float = 0.0
    was_interactive: bool = False
    user_cancelled: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        """Return True if repair completed without errors."""
        return len(self.errors) == 0 and not self.user_cancelled

    def __repr__(self) -> str:
        """Return debug-friendly representation."""
        return (
            f"RepairResult(changes={self.changes_count}, "
            f"divergence={self.divergence_pct:.1f}%, "
            f"errors={len(self.errors)}, "
            f"cancelled={self.user_cancelled})"
        )

    def summary(self) -> str:
        """Return human-readable summary.

        Returns:
            Summary string for logging.

        Examples:
            >>> RepairResult(changes_count=3, divergence_pct=12.5).summary()
            'Repaired 3 entries (12.5% divergence)'
            >>> RepairResult(user_cancelled=True).summary()
            'Repair cancelled by user'
            >>> RepairResult(errors=("File not found",)).summary()
            'Repair failed: File not found'

        """
        if self.user_cancelled:
            return "Repair cancelled by user"
        if self.errors:
            return f"Repair failed: {', '.join(self.errors)}"
        return f"Repaired {self.changes_count} entries ({self.divergence_pct:.1f}% divergence)"


# =============================================================================
# Divergence Calculation (Task 2)
# =============================================================================


def _calculate_divergence(
    existing_count: int,
    changes_count: int,
) -> float:
    """Calculate divergence percentage.

    Divergence = changed_entries / total_entries * 100

    Args:
        existing_count: Number of entries in existing sprint-status.
        changes_count: Number of entries changed during reconciliation.

    Returns:
        Divergence percentage (0.0 - 100.0).
        Returns 0.0 if existing_count is 0 (empty file needs population, not repair).

    Examples:
        >>> _calculate_divergence(100, 30)
        30.0
        >>> _calculate_divergence(0, 10)
        0.0
        >>> _calculate_divergence(10, 0)
        0.0

    """
    if existing_count == 0:
        return 0.0
    return (changes_count / existing_count) * 100


# =============================================================================
# Sprint Status Path Convention
# =============================================================================


def _get_sprint_status_path(project_root: Path) -> Path:
    """Get sprint-status.yaml path using paths singleton.

    Args:
        project_root: Project root directory (used as fallback).

    Returns:
        Path to sprint-status.yaml in implementation artifacts.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().sprint_status_file
    except RuntimeError:
        # Paths not initialized (e.g., in tests) - use project_root defaults
        return project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"


# =============================================================================
# Helper: Build RepairSummary from Reconciliation (Task 4)
# =============================================================================


def _build_repair_summary(
    reconciliation_result: object,
    existing_count: int,
    changes_count: int,
    divergence_pct: float,
) -> RepairSummary:
    """Build RepairSummary from reconciliation result.

    Analyzes the reconciliation changes to produce categorized counts
    for the dialog display.

    Args:
        reconciliation_result: ReconciliationResult from reconciler.
        existing_count: Count of entries before reconciliation.
        changes_count: Total changes made.
        divergence_pct: Calculated divergence percentage.

    Returns:
        RepairSummary with categorized change counts.

    """
    from bmad_assist.sprint.classifier import EntryType
    from bmad_assist.sprint.dialog import RepairSummary
    from bmad_assist.sprint.reconciler import ReconciliationResult

    # Type assertion for IDE/type checker
    result = reconciliation_result
    if not isinstance(result, ReconciliationResult):
        # Fallback if type is unexpected
        return RepairSummary(
            stories_to_update=changes_count,
            epics_to_update=0,
            new_entries=0,
            removed_entries=0,
            divergence_pct=divergence_pct,
        )

    stories = 0
    epics = 0
    new = 0
    removed = 0

    for change in result.changes:
        # Determine category from change entry type or old/new status
        entry_type = change.entry_type

        if entry_type == EntryType.EPIC_STORY or entry_type == EntryType.MODULE_STORY:
            if change.old_status is None:
                new += 1
            elif change.new_status == "deferred":
                removed += 1
            else:
                stories += 1
        elif entry_type == EntryType.EPIC_META:
            epics += 1
        elif change.old_status is None:
            new += 1
        elif change.new_status == "deferred":
            removed += 1
        else:
            stories += 1  # Default to story

    return RepairSummary(
        stories_to_update=stories,
        epics_to_update=epics,
        new_entries=new,
        removed_entries=removed,
        divergence_pct=divergence_pct,
    )


def _get_divergence_threshold() -> float:
    """Get divergence threshold from config or use default (0.3).

    Returns:
        Divergence threshold as decimal (e.g., 0.3 for 30%).

    """
    try:
        from bmad_assist.core.config import get_config

        config = get_config()
        if config.sprint is not None:
            return config.sprint.divergence_threshold
    except Exception:
        pass
    return 0.3  # Default 30%


# =============================================================================
# Main Repair Function (Tasks 2, 3)
# =============================================================================


def repair_sprint_status(
    project_root: Path,
    mode: RepairMode,
    state: State | None = None,
    auto_exclude_legacy: bool = True,
) -> RepairResult:
    """Repair sprint-status from epics and artifact evidence.

    CRITICAL: This function NEVER raises exceptions that could crash the loop.
    All errors are caught, logged, and returned in RepairResult.errors.

    Operation:
    1. Load existing sprint-status (or create empty)
    2. Generate entries from epic files
    3. Scan artifacts for evidence
    4. Reconcile using 3-way merge
    5. Apply state sync if state provided
    6. Check divergence for INTERACTIVE mode
    7. Write result atomically

    Args:
        project_root: Project root directory.
        mode: Repair mode (SILENT or INTERACTIVE).
        state: Optional current State for sync integration.
        auto_exclude_legacy: If True (default), auto-detect and exclude epics
            tracked in docs/sprint-artifacts/sprint-status.yaml.

    Returns:
        RepairResult with statistics and any errors encountered.
        NEVER raises exceptions - errors are captured in result.

    Examples:
        >>> result = repair_sprint_status(Path("/project"), RepairMode.SILENT)
        >>> result.success
        True
        >>> result.changes_count
        5

    """
    try:
        return _repair_sprint_status_impl(project_root, mode, state, auto_exclude_legacy)
    except (StateError, ParserError) as e:
        logger.warning("Sprint repair failed (data error): %s", e)
        return RepairResult(errors=(str(e),))
    except OSError as e:
        logger.warning("Sprint repair failed (file error): %s", e)
        return RepairResult(errors=(str(e),))
    except (ValueError, KeyError) as e:
        logger.warning("Sprint repair failed (data corruption): %s", e)
        return RepairResult(errors=(str(e),))
    except Exception as e:
        logger.warning("Sprint repair failed (unexpected): %s", e)
        return RepairResult(errors=(str(e),))


def _repair_sprint_status_impl(
    project_root: Path,
    mode: RepairMode,
    state: State | None,
    auto_exclude_legacy: bool,
) -> RepairResult:
    """Execute repair_sprint_status implementation (may raise exceptions).

    Separated from main function to allow comprehensive exception handling
    at the outer level.

    """
    from bmad_assist.sprint.generator import generate_from_epics
    from bmad_assist.sprint.models import SprintStatus
    from bmad_assist.sprint.parser import parse_sprint_status
    from bmad_assist.sprint.reconciler import reconcile
    from bmad_assist.sprint.scanner import ArtifactIndex
    from bmad_assist.sprint.sync import sync_state_to_sprint
    from bmad_assist.sprint.writer import write_sprint_status

    # Get sprint path with fallback for when paths singleton not initialized
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        sprint_path = paths.sprint_status_file
        legacy_path = paths.legacy_sprint_artifacts / "sprint-status.yaml"
    except RuntimeError:
        # Paths not initialized (e.g., in tests) - use project_root defaults
        sprint_path = project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml" # noqa: E501
        legacy_path = project_root / "docs" / "sprint-artifacts" / "sprint-status.yaml"

    # Determine effective sprint path and auto_exclude_legacy setting
    # If only legacy location exists, use it and disable auto_exclude
    effective_auto_exclude = auto_exclude_legacy
    if not sprint_path.exists() and legacy_path.exists():
        sprint_path = legacy_path
        effective_auto_exclude = False
        logger.info("Using legacy sprint-status location: %s", sprint_path)

    # Step 1: Load existing sprint-status
    if sprint_path.exists():
        existing = parse_sprint_status(sprint_path)
        # Safety check: corrupted file detection
        if not existing.entries and sprint_path.stat().st_size > 0:
            logger.error(
                "Sprint-status file appears corrupted (has content but no entries). "
                "Aborting repair to prevent data loss: %s",
                sprint_path,
            )
            return RepairResult(errors=(f"Corrupted file: {sprint_path}",))
    else:
        existing = SprintStatus.empty(project=project_root.name)
        logger.info("Sprint-status not found, will create new: %s", sprint_path)

    existing_count = len(existing.entries)

    # Step 2: Generate entries from epic files
    generated = generate_from_epics(project_root, auto_exclude_legacy=effective_auto_exclude)

    # Step 3: Scan artifacts for evidence
    index = ArtifactIndex.scan(project_root)

    # Step 4: Reconcile using 3-way merge
    reconciliation_result = reconcile(existing, generated, index)
    reconciled = reconciliation_result.status
    changes_count = len(reconciliation_result.changes)

    # Step 5: Apply state sync if state provided
    if state is not None:
        reconciled, sync_result = sync_state_to_sprint(state, reconciled)
        # Add any additional changes from sync
        changes_count += sync_result.synced_stories + sync_result.synced_epics

    # Calculate divergence
    divergence_pct = _calculate_divergence(existing_count, changes_count)

    # Step 6: Check divergence for INTERACTIVE mode (AC3, AC5)
    was_interactive = mode == RepairMode.INTERACTIVE
    threshold = _get_divergence_threshold()
    threshold_pct = threshold * 100  # Convert to percentage for comparison

    if was_interactive and divergence_pct > threshold_pct:
        # AC5: Dialog appears only when divergence > threshold
        from bmad_assist.sprint.dialog import get_repair_dialog

        # Build summary from reconciliation result
        summary = _build_repair_summary(
            reconciliation_result,
            existing_count,
            changes_count,
            divergence_pct,
        )

        # Show dialog (AC2: Update/Cancel options, AC7: timeout)
        dialog = get_repair_dialog()
        dialog_result = dialog.show(summary)

        if not dialog_result.approved:
            # AC4: Cancel skips repair and continues with warning
            if dialog_result.timed_out:
                logger.warning(
                    "Sprint repair timed out after %.1fs, skipping repair",
                    dialog_result.elapsed_seconds,
                )
            else:
                logger.warning("Sprint repair cancelled by user, skipping repair")

            return RepairResult(
                changes_count=0,
                divergence_pct=divergence_pct,
                was_interactive=True,
                user_cancelled=True,
                errors=(),
            )

        # AC3: Update applies all repairs and continues
        logger.info("User approved repair after %.1fs", dialog_result.elapsed_seconds)

    # Step 7: Write result atomically
    write_sprint_status(reconciled, sprint_path, preserve_comments=True)

    # Log changes at INFO level (AC4)
    logger.info(
        "Sprint sync: %d changes (%.1f%% divergence)",
        changes_count,
        divergence_pct,
    )

    # Print NEW entries loudly to console (user visible)
    new_entries = [c for c in reconciliation_result.changes if c.old_status is None]
    if new_entries:
        print(f"\n[Sprint Repair] Adding {len(new_entries)} new entries:")
        for change in new_entries:
            print(f"  + {change.key} ({change.new_status})")
        print()

    # Log individual changes for debugging
    for change in reconciliation_result.changes:
        logger.debug("Change: %s", change.as_log_line())

    return RepairResult(
        changes_count=changes_count,
        divergence_pct=divergence_pct,
        was_interactive=was_interactive,
        user_cancelled=False,
        errors=(),
    )


# =============================================================================
# Sync Callback Support (Task 4)
# =============================================================================

# Module-level flag to prevent callback recursion
_sync_in_progress: bool = False


def _default_sync_callback(state: State, project_root: Path) -> None:
    """Trigger lightweight sync after state saves.

    Uses trigger_sync() (fast, ~10-50ms) NOT repair_sprint_status() (slow).
    Includes recursion guard to prevent re-entry during nested save_state calls.

    CRITICAL: This callback is fire-and-forget. It catches all exceptions
    and logs them at WARNING level, never propagating to the caller.

    Args:
        state: Current State instance.
        project_root: Project root directory.

    """
    global _sync_in_progress

    if _sync_in_progress:
        logger.debug("Sync callback skipped (already in progress)")
        return

    try:
        _sync_in_progress = True

        # Use lightweight trigger_sync, NOT full repair_sprint_status
        from bmad_assist.sprint.sync import trigger_sync

        result = trigger_sync(state, project_root)
        # AC4: Log format "Sprint sync: {changes_count} changes ({divergence_pct:.1f}% divergence)"
        # For lightweight sync, divergence is not computed (N/A)
        changes_count = result.synced_stories + result.synced_epics
        logger.info("Sprint sync: %d changes (N/A divergence)", changes_count)

    except Exception as e:
        # Fire-and-forget: never propagate exceptions
        logger.warning("Sprint sync callback failed (ignored): %s", e)
    finally:
        _sync_in_progress = False


def ensure_sprint_sync_callback() -> None:
    """Ensure default sprint sync callback is registered (idempotent).

    Registers the default sync callback if not already registered.
    Safe to call multiple times - uses callback identity check.

    This function should be called at loop startup to enable automatic
    sprint-status synchronization after state saves.

    Example:
        >>> ensure_sprint_sync_callback()
        >>> # Called again - no duplicate registration
        >>> ensure_sprint_sync_callback()

    """
    try:
        from bmad_assist.sprint.sync import (
            get_sync_callbacks,
            register_sync_callback,
        )

        if _default_sync_callback not in get_sync_callbacks():
            register_sync_callback(_default_sync_callback)
            logger.debug("Registered default sprint sync callback")
        else:
            logger.debug("Sprint sync callback already registered")

    except ImportError as e:
        logger.debug("Sprint module not available for callback registration: %s", e)
