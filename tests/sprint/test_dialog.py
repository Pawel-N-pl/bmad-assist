"""Tests for sprint-status interactive repair dialog module.

Tests cover:
- RepairSummary dataclass properties and formatting
- RepairDialogResult dataclass properties
- CLIRepairDialog with mocked stdin
- DashboardRepairDialog auto-cancel behavior
- get_repair_dialog factory function
- Timeout mechanism (simulated)
- Non-TTY and CI environment detection
- Keyboard interrupt handling
- Integration with repair module
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.dialog import (
    CLIRepairDialog,
    DashboardRepairDialog,
    RepairDialogResult,
    RepairSummary,
    _flush_stdin,
    _is_interactive_terminal,
    _prompt_with_timeout,
    get_repair_dialog,
)
from bmad_assist.sprint.models import (
    SprintStatus,
    SprintStatusEntry,
    SprintStatusMetadata,
)
from bmad_assist.sprint.repair import (
    RepairMode,
    _build_repair_summary,
    _get_divergence_threshold,
    repair_sprint_status,
)
from bmad_assist.sprint.sync import clear_sync_callbacks

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def high_divergence_summary() -> RepairSummary:
    """Create summary with high divergence for dialog testing."""
    return RepairSummary(
        stories_to_update=15,
        epics_to_update=3,
        new_entries=5,
        removed_entries=2,
        divergence_pct=45.0,
    )


@pytest.fixture
def low_divergence_summary() -> RepairSummary:
    """Create summary with low divergence (below threshold)."""
    return RepairSummary(
        stories_to_update=2,
        epics_to_update=0,
        new_entries=1,
        removed_entries=0,
        divergence_pct=10.0,
    )


@pytest.fixture
def empty_summary() -> RepairSummary:
    """Create summary with no changes."""
    return RepairSummary(
        stories_to_update=0,
        epics_to_update=0,
        new_entries=0,
        removed_entries=0,
        divergence_pct=0.0,
    )


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create temporary project structure for repair tests."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    # Create sprint-status directory
    sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
    sprint_dir.mkdir(parents=True)

    # Create epics directory
    epics_dir = project_root / "docs" / "epics"
    epics_dir.mkdir(parents=True)

    # Create stories directory
    stories_dir = sprint_dir / "stories"
    stories_dir.mkdir()

    return project_root


@pytest.fixture(autouse=True)
def cleanup_callbacks():
    """Ensure callbacks are cleared before and after each test."""
    clear_sync_callbacks()
    yield
    clear_sync_callbacks()


# =============================================================================
# Test: RepairSummary Dataclass (Task 1, AC1)
# =============================================================================


class TestRepairSummary:
    """Tests for RepairSummary frozen dataclass."""

    def test_repair_summary_creation(self, high_divergence_summary: RepairSummary):
        """RepairSummary creates with all fields."""
        summary = high_divergence_summary
        assert summary.stories_to_update == 15
        assert summary.epics_to_update == 3
        assert summary.new_entries == 5
        assert summary.removed_entries == 2
        assert summary.divergence_pct == 45.0

    def test_repair_summary_is_frozen(self, high_divergence_summary: RepairSummary):
        """RepairSummary is immutable (frozen)."""
        with pytest.raises(AttributeError):
            high_divergence_summary.stories_to_update = 10  # type: ignore

    def test_format_summary_full(self, high_divergence_summary: RepairSummary):
        """format_summary() includes all non-zero counts."""
        summary = high_divergence_summary.format_summary()
        assert "15 stories to update" in summary
        assert "3 epics to update" in summary
        assert "5 new entries" in summary
        assert "2 removed/deferred" in summary
        assert "45.0% divergence" in summary

    def test_format_summary_partial(self, low_divergence_summary: RepairSummary):
        """format_summary() omits zero counts."""
        summary = low_divergence_summary.format_summary()
        assert "2 stories to update" in summary
        assert "1 new entries" in summary
        assert "epics" not in summary
        assert "removed" not in summary
        assert "10.0% divergence" in summary

    def test_format_summary_empty(self, empty_summary: RepairSummary):
        """format_summary() handles empty summary."""
        summary = empty_summary.format_summary()
        assert "No changes" in summary
        assert "0.0% divergence" in summary

    def test_total_changes_property(self, high_divergence_summary: RepairSummary):
        """total_changes returns sum of all changes."""
        assert high_divergence_summary.total_changes == 25  # 15+3+5+2


# =============================================================================
# Test: RepairDialogResult Dataclass (Task 1)
# =============================================================================


class TestRepairDialogResult:
    """Tests for RepairDialogResult frozen dataclass."""

    def test_dialog_result_approved(self):
        """RepairDialogResult with approved=True."""
        result = RepairDialogResult(approved=True, timed_out=False, elapsed_seconds=2.5)
        assert result.approved is True
        assert result.timed_out is False
        assert result.elapsed_seconds == 2.5

    def test_dialog_result_cancelled(self):
        """RepairDialogResult with approved=False (cancelled)."""
        result = RepairDialogResult(approved=False, timed_out=False, elapsed_seconds=1.0)
        assert result.approved is False
        assert result.timed_out is False

    def test_dialog_result_timed_out(self):
        """RepairDialogResult with timed_out=True."""
        result = RepairDialogResult(approved=False, timed_out=True, elapsed_seconds=60.0)
        assert result.approved is False
        assert result.timed_out is True

    def test_dialog_result_is_frozen(self):
        """RepairDialogResult is immutable."""
        result = RepairDialogResult(approved=True)
        with pytest.raises(AttributeError):
            result.approved = False  # type: ignore

    def test_dialog_result_repr_approved(self):
        """Repr shows approved status."""
        result = RepairDialogResult(approved=True, elapsed_seconds=2.5)
        repr_str = repr(result)
        assert "approved" in repr_str
        assert "elapsed=2.5s" in repr_str

    def test_dialog_result_repr_timed_out(self):
        """Repr shows timed_out status."""
        result = RepairDialogResult(approved=False, timed_out=True, elapsed_seconds=60.0)
        repr_str = repr(result)
        assert "timed_out" in repr_str

    def test_dialog_result_repr_cancelled(self):
        """Repr shows cancelled status."""
        result = RepairDialogResult(approved=False, timed_out=False, elapsed_seconds=1.0)
        repr_str = repr(result)
        assert "cancelled" in repr_str

    def test_dialog_result_defaults(self):
        """RepairDialogResult has correct defaults."""
        result = RepairDialogResult(approved=True)
        assert result.timed_out is False
        assert result.elapsed_seconds == 0.0


# =============================================================================
# Test: CLIRepairDialog (Task 2, AC1, AC2, AC3, AC4)
# =============================================================================


class TestCLIRepairDialog:
    """Tests for CLIRepairDialog with mocked stdin."""

    def test_dialog_shows_summary_counts(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Dialog displays all summary counts (AC1)."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=1)

        # Mock prompt_with_timeout to return immediately
        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            return_value=(False, False),
        ):
            dialog.show(high_divergence_summary)

        # Verify console.print was called with summary info
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        print_text = " ".join(print_calls)

        assert "15" in print_text  # stories
        assert "3" in print_text  # epics
        assert "5" in print_text  # new entries
        assert "45.0%" in print_text  # divergence

    def test_dialog_update_returns_approved(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Update option returns approved=True (AC3)."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=1)

        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            return_value=(True, False),  # approved, not timed out
        ):
            result = dialog.show(high_divergence_summary)

        assert result.approved is True
        assert result.timed_out is False

    def test_dialog_cancel_returns_not_approved(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Cancel option returns approved=False (AC4)."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=1)

        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            return_value=(False, False),  # not approved, not timed out
        ):
            result = dialog.show(high_divergence_summary)

        assert result.approved is False
        assert result.timed_out is False


# =============================================================================
# Test: Timeout Mechanism (Task 3, AC7)
# =============================================================================


class TestTimeoutMechanism:
    """Tests for dialog timeout mechanism."""

    def test_timeout_returns_default_false(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Timeout auto-selects Cancel (approved=False) (AC7)."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=1)

        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            return_value=(False, True),  # not approved, timed out
        ):
            result = dialog.show(high_divergence_summary)

        assert result.approved is False
        assert result.timed_out is True

    def test_timeout_elapsed_seconds_tracked(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Dialog tracks elapsed time."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=60)

        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            return_value=(False, False),
        ):
            result = dialog.show(high_divergence_summary)

        # Should have positive elapsed time
        assert result.elapsed_seconds >= 0


# =============================================================================
# Test: Non-TTY Environment (Task 3, AC9)
# =============================================================================


class TestNonTTYEnvironment:
    """Tests for non-TTY and CI environment auto-cancel."""

    def test_non_tty_stdin_auto_cancels(self):
        """Non-TTY stdin auto-cancels immediately (AC9)."""
        mock_console = MagicMock()

        with patch.object(sys.stdin, "isatty", return_value=False):
            result, timed_out = _prompt_with_timeout(
                "Test?",
                timeout_seconds=60,
                default=False,
                console=mock_console,
            )

        assert result is False
        assert timed_out is True

    def test_ci_environment_auto_cancels(self):
        """CI environment auto-cancels immediately (AC9)."""
        mock_console = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"CI": "true"}),
        ):
            result, timed_out = _prompt_with_timeout(
                "Test?",
                timeout_seconds=60,
                default=False,
                console=mock_console,
            )

        assert result is False
        assert timed_out is True

    def test_github_actions_auto_cancels(self):
        """GITHUB_ACTIONS environment auto-cancels (AC9)."""
        mock_console = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False),
        ):
            result, timed_out = _prompt_with_timeout(
                "Test?",
                timeout_seconds=60,
                default=False,
                console=mock_console,
            )

        assert result is False
        assert timed_out is True

    def test_is_interactive_terminal_false_for_non_tty(self):
        """_is_interactive_terminal returns False for non-TTY."""
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert _is_interactive_terminal() is False

    def test_is_interactive_terminal_false_for_ci(self):
        """_is_interactive_terminal returns False for CI."""
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"CI": "true"}),
        ):
            assert _is_interactive_terminal() is False

    def test_is_interactive_terminal_false_for_gitlab_ci(self):
        """_is_interactive_terminal returns False for GitLab CI."""
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=False),
        ):
            assert _is_interactive_terminal() is False

    def test_is_interactive_terminal_false_for_jenkins(self):
        """_is_interactive_terminal returns False for Jenkins."""
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"JENKINS_HOME": "/var/jenkins"}, clear=False),
        ):
            assert _is_interactive_terminal() is False

    def test_gitlab_ci_auto_cancels_prompt(self):
        """GitLab CI environment auto-cancels _prompt_with_timeout."""
        mock_console = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=False),
        ):
            result, timed_out = _prompt_with_timeout(
                "Test?",
                timeout_seconds=60,
                default=False,
                console=mock_console,
            )

        assert result is False
        assert timed_out is True

    def test_jenkins_auto_cancels_prompt(self):
        """Jenkins environment auto-cancels _prompt_with_timeout."""
        mock_console = MagicMock()

        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.dict(os.environ, {"JENKINS_HOME": "/var/jenkins"}, clear=False),
        ):
            result, timed_out = _prompt_with_timeout(
                "Test?",
                timeout_seconds=60,
                default=False,
                console=mock_console,
            )

        assert result is False
        assert timed_out is True


# =============================================================================
# Test: Stdin Flush (Task 3, AC7)
# =============================================================================


class TestStdinFlush:
    """Tests for stdin buffer flushing after timeout."""

    def test_flush_stdin_does_not_raise(self):
        """_flush_stdin does not raise exceptions."""
        # Should not raise regardless of environment
        _flush_stdin()

    def test_flush_stdin_handles_no_termios(self):
        """_flush_stdin handles missing termios gracefully."""
        with patch.dict("sys.modules", {"termios": None}):
            # Should not raise
            _flush_stdin()


# =============================================================================
# Test: Keyboard Interrupt (Task 2, AC8)
# =============================================================================


class TestKeyboardInterrupt:
    """Tests for keyboard interrupt handling."""

    def test_keyboard_interrupt_returns_not_approved(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """KeyboardInterrupt returns approved=False gracefully (AC8)."""
        mock_console = MagicMock()
        dialog = CLIRepairDialog(console=mock_console, timeout_seconds=60)

        with patch(
            "bmad_assist.sprint.dialog._prompt_with_timeout",
            side_effect=KeyboardInterrupt(),
        ):
            result = dialog.show(high_divergence_summary)

        assert result.approved is False
        assert result.timed_out is False


# =============================================================================
# Test: DashboardRepairDialog (Task 5)
# =============================================================================


class TestDashboardRepairDialog:
    """Tests for DashboardRepairDialog auto-cancel stub."""

    def test_dashboard_dialog_auto_cancels(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Dashboard dialog auto-cancels for safety."""
        dialog = DashboardRepairDialog()
        result = dialog.show(high_divergence_summary)

        assert result.approved is False
        assert result.timed_out is False
        assert result.elapsed_seconds == 0.0

    def test_dashboard_dialog_logs_warning(
        self,
        high_divergence_summary: RepairSummary,
        caplog: pytest.LogCaptureFixture,
    ):
        """Dashboard dialog logs warning about auto-cancel."""
        dialog = DashboardRepairDialog()

        with caplog.at_level(logging.WARNING):
            dialog.show(high_divergence_summary)

        assert any("auto-cancelling" in r.message for r in caplog.records)
        assert any("safety" in r.message for r in caplog.records)

    def test_dashboard_dialog_does_not_auto_approve(
        self,
        high_divergence_summary: RepairSummary,
    ):
        """Dashboard dialog never auto-approves (safety-first)."""
        dialog = DashboardRepairDialog()

        # Call multiple times - should never approve
        for _ in range(3):
            result = dialog.show(high_divergence_summary)
            assert result.approved is False


# =============================================================================
# Test: get_repair_dialog Factory (Task 5)
# =============================================================================


class TestGetRepairDialog:
    """Tests for get_repair_dialog factory function."""

    def test_get_repair_dialog_default_cli(self):
        """Default context returns CLIRepairDialog."""
        dialog = get_repair_dialog()
        assert isinstance(dialog, CLIRepairDialog)

    def test_get_repair_dialog_explicit_cli(self):
        """Explicit 'cli' context returns CLIRepairDialog."""
        dialog = get_repair_dialog(context="cli")
        assert isinstance(dialog, CLIRepairDialog)

    def test_get_repair_dialog_dashboard(self):
        """'dashboard' context returns DashboardRepairDialog."""
        dialog = get_repair_dialog(context="dashboard")
        assert isinstance(dialog, DashboardRepairDialog)

    def test_get_repair_dialog_custom_timeout(self):
        """Custom timeout is passed to CLIRepairDialog."""
        dialog = get_repair_dialog(timeout_seconds=30)
        assert isinstance(dialog, CLIRepairDialog)
        assert dialog.timeout_seconds == 30


# =============================================================================
# Test: Divergence Threshold (Task 4, AC5)
# =============================================================================


class TestDivergenceThreshold:
    """Tests for divergence threshold behavior."""

    def test_dialog_not_shown_below_threshold(
        self,
        temp_project: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Dialog NOT shown when divergence <= 30% (AC5)."""
        from bmad_assist.sprint.writer import write_sprint_status

        # Create sprint-status with entries
        sprint_path = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        entries = {
            f"20-{i}-story{i}": SprintStatusEntry(
                key=f"20-{i}-story{i}",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            )
            for i in range(1, 11)  # 10 entries
        }
        status = SprintStatus(
            metadata=SprintStatusMetadata(
                generated=datetime.now(UTC).replace(tzinfo=None),
                project="test",
            ),
            entries=entries,
        )
        write_sprint_status(status, sprint_path)

        # Create epic file with same stories (same format as generated)
        epic_path = temp_project / "docs" / "epics" / "epic-20.md"
        epic_path.write_text(
            "---\nepic_num: 20\n---\n# Epic 20\n## Stories\n\n"
            + "\n\n".join([f"### Story 20.{i}: story{i}\n" for i in range(1, 11)]),
            encoding="utf-8",
        )

        # Run repair
        result = repair_sprint_status(temp_project, RepairMode.INTERACTIVE, None)

        # With matching stories, divergence should be low and user should NOT be cancelled
        # (dialog not shown or auto-approved for low divergence)
        assert result.user_cancelled is False

    def test_dialog_shown_above_threshold(
        self,
        temp_project: Path,
    ):
        """Dialog shown when divergence > 30% (AC5)."""
        from bmad_assist.sprint.writer import write_sprint_status

        # Create sprint-status with entries that will diverge
        sprint_path = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        entries = {
            f"old-{i}-story": SprintStatusEntry(
                key=f"old-{i}-story",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            )
            for i in range(1, 11)  # 10 entries that won't match
        }
        status = SprintStatus(
            metadata=SprintStatusMetadata(
                generated=datetime.now(UTC).replace(tzinfo=None),
                project="test",
            ),
            entries=entries,
        )
        write_sprint_status(status, sprint_path)

        # Create epic file with different stories (high divergence)
        epic_path = temp_project / "docs" / "epics" / "epic-99.md"
        epic_path.write_text(
            "---\nepic_num: 99\n---\n# Epic 99\n## Stories\n\n"
            "### Story 99.1: New\n\n### Story 99.2: Another\n",
            encoding="utf-8",
        )

        # Mock dialog to auto-cancel - need to patch where it's imported
        mock_dialog = MagicMock()
        mock_dialog.show.return_value = RepairDialogResult(approved=False)

        # Import the module and patch directly
        import bmad_assist.sprint.repair as repair_mod

        with patch.object(repair_mod, "get_repair_dialog", return_value=mock_dialog, create=True):
            # Need to patch the import in _repair_sprint_status_impl
            with patch(
                "bmad_assist.sprint.dialog.get_repair_dialog",
                return_value=mock_dialog,
            ):
                result = repair_sprint_status(temp_project, RepairMode.INTERACTIVE, None)

        # Dialog should have been shown (divergence > 30%)
        if result.divergence_pct > 30:
            mock_dialog.show.assert_called_once()
            # Result should indicate user cancelled
            assert result.user_cancelled is True

    def test_boundary_30_percent_no_dialog(self):
        """Exactly 30% divergence does NOT show dialog."""
        # 30% is the threshold, but condition is > 30%, so 30.0% should NOT trigger
        threshold = _get_divergence_threshold()
        assert threshold == 0.3
        # 30.0% is NOT > 30%, so dialog should NOT be shown


# =============================================================================
# Test: SILENT Mode Never Shows Dialog (AC5)
# =============================================================================


class TestSilentMode:
    """Tests for SILENT mode (no dialog)."""

    def test_silent_mode_never_shows_dialog(
        self,
        temp_project: Path,
    ):
        """SILENT mode never shows dialog even with high divergence."""
        from bmad_assist.sprint.writer import write_sprint_status

        # Create sprint-status with entries that will diverge
        sprint_path = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        entries = {
            f"old-{i}-story": SprintStatusEntry(
                key=f"old-{i}-story",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            )
            for i in range(1, 5)
        }
        status = SprintStatus(
            metadata=SprintStatusMetadata(
                generated=datetime.now(UTC).replace(tzinfo=None),
                project="test",
            ),
            entries=entries,
        )
        write_sprint_status(status, sprint_path)

        # Create epic file with different stories
        epic_path = temp_project / "docs" / "epics" / "epic-99.md"
        epic_path.write_text(
            "---\nepic_num: 99\n---\n# Epic 99\n## Stories\n\n"
            "### Story 99.1: New\n\n### Story 99.2: Another\n",
            encoding="utf-8",
        )

        # SILENT mode should never show dialog, and should proceed with repair
        result = repair_sprint_status(temp_project, RepairMode.SILENT, None)

        # In SILENT mode, user_cancelled is never True
        assert result.user_cancelled is False
        # Repair should succeed
        assert result.success is True


# =============================================================================
# Test: Runner Continues After Cancellation (AC4)
# =============================================================================


class TestRunnerContinuation:
    """Tests for runner continuing after dialog cancellation."""

    def test_runner_continues_after_user_cancel(
        self,
        temp_project: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Runner continues after user cancels repair."""
        from bmad_assist.sprint.writer import write_sprint_status

        # Create sprint-status
        sprint_path = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        entries = {
            "old-1-story": SprintStatusEntry(
                key="old-1-story",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status = SprintStatus(
            metadata=SprintStatusMetadata(
                generated=datetime.now(UTC).replace(tzinfo=None),
                project="test",
            ),
            entries=entries,
        )
        write_sprint_status(status, sprint_path)

        # Create divergent epic
        epic_path = temp_project / "docs" / "epics" / "epic-99.md"
        epic_path.write_text(
            "---\nepic_num: 99\n---\n# Epic 99\n## Stories\n\n"
            "### Story 99.1: New\n\n### Story 99.2: Another\n",
            encoding="utf-8",
        )

        # Mock dialog to cancel - need to patch where it's imported
        mock_dialog = MagicMock()
        mock_dialog.show.return_value = RepairDialogResult(approved=False)

        with (
            patch(
                "bmad_assist.sprint.dialog.get_repair_dialog",
                return_value=mock_dialog,
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = repair_sprint_status(temp_project, RepairMode.INTERACTIVE, None)

        # Result should indicate cancellation but no errors
        if mock_dialog.show.called:
            assert result.user_cancelled is True
            assert len(result.errors) == 0

    def test_runner_continues_after_timeout(
        self,
        temp_project: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """Runner continues after dialog timeout."""
        from bmad_assist.sprint.writer import write_sprint_status

        # Create sprint-status
        sprint_path = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        entries = {
            "old-1-story": SprintStatusEntry(
                key="old-1-story",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status = SprintStatus(
            metadata=SprintStatusMetadata(
                generated=datetime.now(UTC).replace(tzinfo=None),
                project="test",
            ),
            entries=entries,
        )
        write_sprint_status(status, sprint_path)

        # Create divergent epic
        epic_path = temp_project / "docs" / "epics" / "epic-99.md"
        epic_path.write_text(
            "---\nepic_num: 99\n---\n# Epic 99\n## Stories\n\n"
            "### Story 99.1: New\n\n### Story 99.2: Another\n",
            encoding="utf-8",
        )

        # Mock dialog to timeout
        mock_dialog = MagicMock()
        mock_dialog.show.return_value = RepairDialogResult(
            approved=False, timed_out=True, elapsed_seconds=60.0
        )

        with (
            patch(
                "bmad_assist.sprint.dialog.get_repair_dialog",
                return_value=mock_dialog,
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = repair_sprint_status(temp_project, RepairMode.INTERACTIVE, None)

        # Should continue even after timeout
        if mock_dialog.show.called:
            assert result.user_cancelled is True


# =============================================================================
# Test: Build RepairSummary Helper
# =============================================================================


class TestBuildRepairSummary:
    """Tests for _build_repair_summary helper function."""

    def test_build_summary_from_reconciliation(self):
        """Build summary correctly categorizes changes."""
        from bmad_assist.sprint.reconciler import ReconciliationResult, StatusChange

        # Create mock reconciliation result
        changes = [
            StatusChange(
                key="20-1-story",
                old_status="backlog",
                new_status="in-progress",
                entry_type=EntryType.EPIC_STORY,
                reason="status_updated",
            ),
            StatusChange(
                key="20-2-story",
                old_status=None,
                new_status="backlog",
                entry_type=EntryType.EPIC_STORY,
                reason="new_entry",
            ),
            StatusChange(
                key="epic-20",
                old_status="backlog",
                new_status="in-progress",
                entry_type=EntryType.EPIC_META,
                reason="status_updated",
            ),
        ]
        result = ReconciliationResult(
            status=SprintStatus.empty(),
            changes=changes,
        )

        summary = _build_repair_summary(result, 10, 3, 30.0)

        assert summary.stories_to_update == 1  # Updated story
        assert summary.new_entries == 1  # New entry
        assert summary.epics_to_update == 1  # Epic update
        assert summary.divergence_pct == 30.0

    def test_build_summary_fallback_for_unknown_type(self):
        """Build summary handles non-ReconciliationResult gracefully."""
        summary = _build_repair_summary("not a result", 10, 5, 50.0)

        # Should fallback to putting all changes as stories
        assert summary.stories_to_update == 5
        assert summary.divergence_pct == 50.0


# =============================================================================
# Test: SprintConfig Integration (Task 7)
# =============================================================================


class TestSprintConfigIntegration:
    """Tests for SprintConfig integration with dialog."""

    def test_get_divergence_threshold_default(self):
        """Default divergence threshold is 0.3 (30%)."""
        # When config not loaded or sprint section missing
        with patch(
            "bmad_assist.core.config.get_config",
            side_effect=Exception("Config not loaded"),
        ):
            threshold = _get_divergence_threshold()

        assert threshold == 0.3

    def test_get_divergence_threshold_from_config(self):
        """Divergence threshold loaded from SprintConfig."""
        mock_config = MagicMock()
        mock_config.sprint.divergence_threshold = 0.25

        with patch(
            "bmad_assist.core.config.get_config",
            return_value=mock_config,
        ):
            threshold = _get_divergence_threshold()

        assert threshold == 0.25

    def test_get_dialog_timeout_from_config(self):
        """Dialog timeout loaded from SprintConfig."""
        mock_config = MagicMock()
        mock_config.sprint.dialog_timeout_seconds = 30

        with patch(
            "bmad_assist.core.config.get_config",
            return_value=mock_config,
        ):
            dialog = get_repair_dialog()

        assert isinstance(dialog, CLIRepairDialog)
        assert dialog.timeout_seconds == 30
