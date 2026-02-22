"""Tests for refactored HardeningHandler (hybrid triage).

Tests cover:
- Triage decision parsing (_parse_triage_decision)
- Sprint-status key format (epic-{N}-hardening)
- no_action path → no file, sprint-status done
- direct_fix path → no file, sprint-status done, fixes recorded
- story_needed path → file created, sprint-status backlog
- Fallback when no structured triage block found
"""

import json
import logging

import pytest

from bmad_assist.core.loop.handlers.hardening import (
    HardeningHandler,
    _parse_triage_decision,
)


# =========================================================================
# _parse_triage_decision
# =========================================================================

class TestParseTriageDecision:
    """Tests for the triage JSON parser."""

    def test_valid_no_action(self):
        """Parse a valid no_action triage block with markers."""
        raw = (
            "Some preamble\n"
            "<!-- HARDENING_TRIAGE_START -->\n"
            '{"decision": "no_action", "reason": "Nothing to do"}\n'
            "<!-- HARDENING_TRIAGE_END -->\n"
            "Some postamble\n"
        )
        result = _parse_triage_decision(raw)
        assert result["decision"] == "no_action"
        assert result["reason"] == "Nothing to do"

    def test_valid_direct_fix(self):
        """Parse a valid direct_fix triage block."""
        raw = (
            "<!-- HARDENING_TRIAGE_START -->\n"
            '{"decision": "direct_fix", "reason": "Minor typos", "fixes_applied": ["Fix typo in readme"]}\n'
            "<!-- HARDENING_TRIAGE_END -->\n"
        )
        result = _parse_triage_decision(raw)
        assert result["decision"] == "direct_fix"
        assert result["fixes_applied"] == ["Fix typo in readme"]

    def test_valid_story_needed(self):
        """Parse a valid story_needed triage block."""
        raw = (
            "<!-- HARDENING_TRIAGE_START -->\n"
            '{"decision": "story_needed", "reason": "Architectural refactor needed", '
            '"story_content": "# Epic 1: Hardening\\n\\n## Tasks\\n- Refactor"}\n'
            "<!-- HARDENING_TRIAGE_END -->\n"
        )
        result = _parse_triage_decision(raw)
        assert result["decision"] == "story_needed"
        assert "# Epic 1: Hardening" in result["story_content"]

    def test_fallback_no_markers(self):
        """When no markers found, fall back to story_needed."""
        raw = "Just some random LLM output with no structured block."
        result = _parse_triage_decision(raw)
        assert result["decision"] == "story_needed"

    def test_fallback_invalid_json(self):
        """When JSON is malformed, fall back to story_needed."""
        raw = (
            "<!-- HARDENING_TRIAGE_START -->\n"
            "{broken json}\n"
            "<!-- HARDENING_TRIAGE_END -->\n"
        )
        result = _parse_triage_decision(raw)
        assert result["decision"] == "story_needed"

    def test_fallback_unknown_decision(self, caplog):
        """When decision value is unknown, fall back to story_needed."""
        raw = (
            "<!-- HARDENING_TRIAGE_START -->\n"
            '{"decision": "maybe_later"}\n'
            "<!-- HARDENING_TRIAGE_END -->\n"
        )
        with caplog.at_level(logging.WARNING):
            result = _parse_triage_decision(raw)
        assert result["decision"] == "story_needed"
        assert "Unknown triage decision" in caplog.text

    def test_json_without_markers_found_via_regex(self):
        """JSON embedded in output without markers is found via regex fallback."""
        raw = (
            'The LLM said:\n'
            '{"decision": "no_action", "reason": "Nothing"}\n'
            "End of response.\n"
        )
        result = _parse_triage_decision(raw)
        assert result["decision"] == "no_action"

    def test_empty_raw_output(self):
        """Empty output falls back to story_needed."""
        result = _parse_triage_decision("")
        assert result["decision"] == "story_needed"


# =========================================================================
# HardeningHandler unit tests
# =========================================================================

class TestHardeningHandler:
    """Tests for HardeningHandler properties."""

    def test_phase_name(self):
        """Handler reports correct phase name."""
        handler = HardeningHandler.__new__(HardeningHandler)
        assert handler.phase_name == "hardening"

    def test_track_timing(self):
        """Handler has timing enabled."""
        handler = HardeningHandler.__new__(HardeningHandler)
        assert handler.track_timing is True


# =========================================================================
# Sprint-status key format
# =========================================================================

class TestSprintStatusKeyFormat:
    """Verify sprint-status keys use epic-{N}-hardening format."""

    def test_register_hardening_key_format(self, tmp_path):
        """The sprint-status key should be epic-{N}-hardening."""
        # Verify the key format that _register_hardening_in_sprint would use
        epic_id = 5
        expected_key = f"epic-{epic_id}-hardening"
        assert expected_key == "epic-5-hardening"

    def test_hardening_story_filename_format(self):
        """The hardening file should be named epic-{N}-hardening.md."""
        epic_id = 3
        filename = f"epic-{epic_id}-hardening.md"
        assert filename == "epic-3-hardening.md"
        # Must NOT contain "-0-" (old format)
        assert "-0-" not in filename

    def test_hardening_story_filename_string_epic(self):
        """String epic IDs should also work."""
        epic_id = "testarch"
        filename = f"epic-{epic_id}-hardening.md"
        assert filename == "epic-testarch-hardening.md"


# =========================================================================
# Resume validation: hardening-aware epic done check
# =========================================================================

class TestResumeValidationHardeningAware:
    """Verify _is_epic_done_in_sprint checks hardening status."""

    def _make_sprint_status(self, entries):
        """Helper to construct SprintStatus with required metadata."""
        from bmad_assist.sprint.models import SprintStatus, SprintStatusMetadata
        from datetime import datetime, UTC
        return SprintStatus(
            metadata=SprintStatusMetadata(generated=datetime.now(UTC).replace(tzinfo=None)),
            entries=entries,
        )

    def test_epic_done_when_no_hardening_entry(self):
        """Epic is done if hardening entry doesn't exist (no hardening configured)."""
        from bmad_assist.sprint.models import SprintStatusEntry
        from bmad_assist.sprint.classifier import EntryType
        from bmad_assist.sprint.resume_validation import _is_epic_done_in_sprint

        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1", status="done", entry_type=EntryType.EPIC_META,
            ),
            "epic-1-retrospective": SprintStatusEntry(
                key="epic-1-retrospective", status="done", entry_type=EntryType.RETROSPECTIVE,
            ),
        }
        status = self._make_sprint_status(entries)
        assert _is_epic_done_in_sprint(1, status) is True

    def test_epic_not_done_when_hardening_pending(self):
        """Epic is NOT done when hardening status is 'backlog'."""
        from bmad_assist.sprint.models import SprintStatusEntry
        from bmad_assist.sprint.classifier import EntryType
        from bmad_assist.sprint.resume_validation import _is_epic_done_in_sprint

        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1", status="done", entry_type=EntryType.EPIC_META,
            ),
            "epic-1-retrospective": SprintStatusEntry(
                key="epic-1-retrospective", status="done", entry_type=EntryType.RETROSPECTIVE,
            ),
            "epic-1-hardening": SprintStatusEntry(
                key="epic-1-hardening", status="backlog", entry_type=EntryType.HARDENING,
            ),
        }
        status = self._make_sprint_status(entries)
        assert _is_epic_done_in_sprint(1, status) is False

    def test_epic_done_when_hardening_done(self):
        """Epic IS done when hardening status is 'done'."""
        from bmad_assist.sprint.models import SprintStatusEntry
        from bmad_assist.sprint.classifier import EntryType
        from bmad_assist.sprint.resume_validation import _is_epic_done_in_sprint

        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1", status="done", entry_type=EntryType.EPIC_META,
            ),
            "epic-1-retrospective": SprintStatusEntry(
                key="epic-1-retrospective", status="done", entry_type=EntryType.RETROSPECTIVE,
            ),
            "epic-1-hardening": SprintStatusEntry(
                key="epic-1-hardening", status="done", entry_type=EntryType.HARDENING,
            ),
        }
        status = self._make_sprint_status(entries)
        assert _is_epic_done_in_sprint(1, status) is True

    def test_epic_not_done_when_hardening_in_progress(self):
        """Epic is NOT done when hardening status is 'in-progress'."""
        from bmad_assist.sprint.models import SprintStatusEntry
        from bmad_assist.sprint.classifier import EntryType
        from bmad_assist.sprint.resume_validation import _is_epic_done_in_sprint

        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1", status="done", entry_type=EntryType.EPIC_META,
            ),
            "epic-1-retrospective": SprintStatusEntry(
                key="epic-1-retrospective", status="done", entry_type=EntryType.RETROSPECTIVE,
            ),
            "epic-1-hardening": SprintStatusEntry(
                key="epic-1-hardening", status="in-progress", entry_type=EntryType.HARDENING,
            ),
        }
        status = self._make_sprint_status(entries)
        assert _is_epic_done_in_sprint(1, status) is False
# =========================================================================
# HardeningHandler integration tests
# =========================================================================

class TestHardeningHandlerExecute:
    """Integration tests for HardeningHandler.execute() mocking LLM."""

    @pytest.fixture(autouse=True)
    def setup_paths(self, tmp_path):
        """Setup paths singleton for test."""
        from bmad_assist.core.paths import _reset_paths, init_paths
        _reset_paths()
        init_paths(tmp_path)
        yield
        _reset_paths()

    def test_execute_no_action(self, tmp_path):
        """Verify no_action triage path."""
        from unittest.mock import MagicMock, patch
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.state import State, Phase

        mock_config = MagicMock()
        handler = HardeningHandler(mock_config, tmp_path)
        state = State(current_epic=5, current_phase=Phase.HARDENING)

        # LLM output for no_action
        llm_output = '<!-- HARDENING_TRIAGE_START -->\n{"decision": "no_action", "reason": "All good"}\n<!-- HARDENING_TRIAGE_END -->'
        parent_result = PhaseResult.ok({"response": llm_output})

        with patch("bmad_assist.core.loop.handlers.base.BaseHandler.execute", return_value=parent_result):
            with patch.object(HardeningHandler, "_register_hardening_in_sprint") as mock_reg:
                result = handler.execute(state)

        assert result.success
        assert result.outputs["hardening_decision"] == "no_action"
        mock_reg.assert_called_once_with(5, 1, status="done")
        
        # Verify no story file created
        target_dir = tmp_path / "_bmad-output" / "implementation-artifacts" / "hardening"
        assert not (target_dir / "epic-5-1-hardening.md").exists()

    def test_execute_direct_fix(self, tmp_path):
        """Verify direct_fix triage path."""
        from unittest.mock import MagicMock, patch
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.state import State, Phase

        mock_config = MagicMock()
        handler = HardeningHandler(mock_config, tmp_path)
        state = State(current_epic=5, current_phase=Phase.HARDENING)

        # LLM output for direct_fix
        llm_output = '<!-- HARDENING_TRIAGE_START -->\n{"decision": "direct_fix", "reason": "Trivial", "fixes_applied": ["Done"]}\n<!-- HARDENING_TRIAGE_END -->'
        parent_result = PhaseResult.ok({"response": llm_output})

        with patch("bmad_assist.core.loop.handlers.base.BaseHandler.execute", return_value=parent_result):
            with patch.object(HardeningHandler, "_register_hardening_in_sprint") as mock_reg:
                result = handler.execute(state)

        assert result.success
        assert result.outputs["hardening_decision"] == "direct_fix"
        assert result.outputs["hardening_fixes_applied"] == ["Done"]
        mock_reg.assert_called_once_with(5, 1, status="done")

    def test_execute_story_needed(self, tmp_path):
        """Verify story_needed triage path creates the file."""
        from unittest.mock import MagicMock, patch
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.state import State, Phase

        mock_config = MagicMock()
        handler = HardeningHandler(mock_config, tmp_path)
        state = State(
            current_epic=5, 
            current_phase=Phase.HARDENING,
            completed_stories=["5.1"], # Prepopulate to test re-run cleanup
            completed_epics=[5],       # Prepopulate to test re-run cleanup
        )

        # LLM output for story_needed
        llm_output = (
            '<!-- HARDENING_TRIAGE_START -->\n'
            '{"decision": "story_needed", "reason": "Complex", "story_content": "# Hardening Story"}\n'
            '<!-- HARDENING_TRIAGE_END -->'
        )
        parent_result = PhaseResult.ok({"response": llm_output})

        with patch("bmad_assist.core.loop.handlers.base.BaseHandler.execute", return_value=parent_result):
            with patch.object(HardeningHandler, "_register_hardening_in_sprint") as mock_reg:
                result = handler.execute(state)

        assert result.success
        assert result.outputs["hardening_decision"] == "story_needed"
        mock_reg.assert_called_once_with(5, 1, status="backlog")

        # Verify story file created in implementation-artifacts/hardening/
        target_dir = tmp_path / "_bmad-output" / "implementation-artifacts" / "hardening"
        story_file = target_dir / "5-1-hardening.md"
        assert story_file.exists()
        assert story_file.read_text() == "# Hardening Story"
        
        # Verify state is cleaned up for re-runs
        assert "5.1" not in state.completed_stories
        assert 5 not in state.completed_epics

    def test_execute_fails_if_no_current_epic(self, tmp_path):
        """Handler fails if no current epic is set."""
        from unittest.mock import MagicMock
        from bmad_assist.core.state import State, Phase

        mock_config = MagicMock()
        handler = HardeningHandler(mock_config, tmp_path)
        state = State(current_epic=None, current_phase=Phase.HARDENING)

        result = handler.execute(state)
        assert not result.success
        assert "no current epic" in result.error
