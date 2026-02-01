"""Tests for retrospective/reports.py extraction and persistence.

Bug Fix: Retrospective Report Persistence
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bmad_assist.retrospective.reports import (
    extract_retrospective_report,
    save_retrospective_report,
)


class TestExtractRetrospectiveReport:
    """Tests for extract_retrospective_report() function."""

    def test_extracts_between_markers(self):
        """AC1: Primary extraction using markers."""
        raw_output = '''Bob (Scrum Master): "Starting the retro..."

<!-- RETROSPECTIVE_REPORT_START -->
# Epic 21 Retrospective: Notification Format Enhancement

## Summary
Great work everyone!

## Key Takeaways
1. Notifications improved
2. Time formatting works
<!-- RETROSPECTIVE_REPORT_END -->

Bob: "Meeting adjourned!"'''

        result = extract_retrospective_report(raw_output)

        assert result.startswith("# Epic 21 Retrospective")
        assert "Great work everyone!" in result
        assert "Key Takeaways" in result
        assert "Meeting adjourned" not in result  # After end marker
        assert "Starting the retro" not in result  # Before start marker
        assert "RETROSPECTIVE_REPORT_START" not in result  # Markers stripped

    def test_extracts_without_end_marker(self):
        """Handles missing end marker gracefully."""
        raw_output = """<!-- RETROSPECTIVE_REPORT_START -->
# Epic 10 Retrospective

## Summary
Incomplete output"""

        result = extract_retrospective_report(raw_output)

        assert "# Epic 10 Retrospective" in result
        assert "Summary" in result

    def test_fallback_to_epic_header(self):
        """AC2: Fallback to header detection when no markers."""
        raw_output = """Some thinking output...

# Epic 15 Retrospective: Notifications System

## Summary
Notification system complete.

## Action Items
- Deploy to production"""

        result = extract_retrospective_report(raw_output)

        assert result.startswith("# Epic 15 Retrospective")
        assert "Summary" in result
        assert "Action Items" in result
        assert "Some thinking" not in result

    def test_fallback_to_retrospective_complete_section(self):
        """Fallback to RETROSPECTIVE COMPLETE section."""
        raw_output = """Tool calls and output...

═══════════════════════════════════════════════════════════
RETROSPECTIVE COMPLETE
═══════════════════════════════════════════════════════════

Epic 10 reviewed successfully.

## Key Takeaways
1. Great progress"""

        result = extract_retrospective_report(raw_output)

        assert "RETROSPECTIVE COMPLETE" in result
        assert "Key Takeaways" in result

    def test_returns_raw_when_no_pattern_found(self):
        """AC2 last resort: returns stripped raw output."""
        raw_output = "   Just some random text with no patterns   "

        result = extract_retrospective_report(raw_output)

        assert result == "Just some random text with no patterns"

    def test_strips_code_block_wrapper(self):
        """Handles markdown code block wrappers."""
        raw_output = """```markdown
<!-- RETROSPECTIVE_REPORT_START -->
# Epic 5 Retrospective
Content here
<!-- RETROSPECTIVE_REPORT_END -->
```"""

        result = extract_retrospective_report(raw_output)

        assert result.startswith("# Epic 5 Retrospective")
        assert "```" not in result

    def test_handles_duplicate_start_markers(self):
        """Handles LLM echoing start marker."""
        raw_output = """<!-- RETROSPECTIVE_REPORT_START -->
<!-- RETROSPECTIVE_REPORT_START -->
# Epic 7 Retrospective
Content
<!-- RETROSPECTIVE_REPORT_END -->"""

        result = extract_retrospective_report(raw_output)

        assert result.startswith("# Epic 7 Retrospective")
        assert "RETROSPECTIVE_REPORT_START" not in result

    def test_empty_input_returns_empty(self):
        """Empty input returns empty string."""
        result = extract_retrospective_report("")
        assert result == ""

    def test_case_insensitive_epic_header(self):
        """Epic header detection is case insensitive."""
        raw_output = """# EPIC 12 RETROSPECTIVE: Something

## Summary
Content"""

        result = extract_retrospective_report(raw_output)

        assert "EPIC 12 RETROSPECTIVE" in result


class TestSaveRetrospectiveReport:
    """Tests for save_retrospective_report() function."""

    def test_saves_report_to_correct_path(self, tmp_path: Path):
        """AC3: Saves to correct location with correct filename."""
        content = "# Epic 21 Retrospective\n\nContent here"
        retro_dir = tmp_path / "retrospectives"
        timestamp = datetime(2026, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = save_retrospective_report(
            content=content,
            epic_id=21,
            retrospectives_dir=retro_dir,
            timestamp=timestamp,
        )

        assert result == retro_dir / "epic-21-retro-20260111.md"
        assert result.exists()
        assert result.read_text() == content

    def test_creates_directory_if_missing(self, tmp_path: Path):
        """Creates retrospectives directory if it doesn't exist."""
        content = "# Epic 10 Retrospective"
        retro_dir = tmp_path / "nested" / "retrospectives"
        timestamp = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)

        result = save_retrospective_report(
            content=content,
            epic_id=10,
            retrospectives_dir=retro_dir,
            timestamp=timestamp,
        )

        assert result.exists()
        assert retro_dir.exists()

    def test_handles_string_epic_id(self, tmp_path: Path):
        """Handles string epic IDs like 'testarch'."""
        content = "# Testarch Module Retrospective"
        retro_dir = tmp_path / "retrospectives"
        timestamp = datetime(2026, 1, 5, 8, 30, 0, tzinfo=UTC)

        result = save_retrospective_report(
            content=content,
            epic_id="testarch",
            retrospectives_dir=retro_dir,
            timestamp=timestamp,
        )

        assert result.name == "epic-testarch-retro-20260105.md"
        assert result.exists()

    def test_overwrites_existing_file(self, tmp_path: Path):
        """AC4: Overwrites existing file on re-run."""
        retro_dir = tmp_path / "retrospectives"
        retro_dir.mkdir()
        timestamp = datetime(2026, 1, 11, 12, 0, 0, tzinfo=UTC)

        # First write
        existing_file = retro_dir / "epic-21-retro-20260111.md"
        existing_file.write_text("Old content")

        # Second write should overwrite
        result = save_retrospective_report(
            content="New content",
            epic_id=21,
            retrospectives_dir=retro_dir,
            timestamp=timestamp,
        )

        assert result.read_text() == "New content"

    def test_uses_current_time_if_no_timestamp(self, tmp_path: Path):
        """Uses current time if timestamp not provided."""
        content = "# Epic 5 Retrospective"
        retro_dir = tmp_path / "retrospectives"

        result = save_retrospective_report(
            content=content,
            epic_id=5,
            retrospectives_dir=retro_dir,
        )

        # Just verify file was created with today's date in name
        assert result.exists()
        today = datetime.now(UTC).strftime("%Y%m%d")
        assert today in result.name


class TestIntegration:
    """Integration tests for extract + save flow."""

    def test_full_extraction_and_save_flow(self, tmp_path: Path):
        """Full flow: extract from LLM output and save."""
        raw_llm_output = '''Bob (Scrum Master): "Let's begin the retrospective..."

<!-- RETROSPECTIVE_REPORT_START -->
# Epic 21 Retrospective: Notification Format Enhancement

## Summary
Epic 21 delivered 5 stories implementing notification formatting improvements.

## What Went Well
- Time formatting works great (47m, 2h17m, 1d5h)
- Workflow labels with emojis add clarity
- Integration with Telegram and Discord smooth

## What Could Be Improved
- Better error messages in formatter
- More comprehensive edge case testing

## Action Items
1. Add error message improvements to backlog
2. Document formatting patterns

## Metrics
- Stories: 5/5 completed
- Velocity: 12 SP
<!-- RETROSPECTIVE_REPORT_END -->

Bob: "Great session everyone!"'''

        # Extract
        extracted = extract_retrospective_report(raw_llm_output)

        # Save
        retro_dir = tmp_path / "retrospectives"
        timestamp = datetime(2026, 1, 11, 15, 39, 0, tzinfo=UTC)

        report_path = save_retrospective_report(
            content=extracted,
            epic_id=21,
            retrospectives_dir=retro_dir,
            timestamp=timestamp,
        )

        # Verify
        assert report_path.exists()
        saved_content = report_path.read_text()

        assert "# Epic 21 Retrospective" in saved_content
        assert "What Went Well" in saved_content
        assert "Action Items" in saved_content
        assert "Metrics" in saved_content
        assert "RETROSPECTIVE_REPORT_START" not in saved_content
        assert "Bob (Scrum Master)" not in saved_content


class TestRetrospectiveHandlerIntegration:
    """Integration tests for RetrospectiveHandler._save_retrospective_report().

    Bug Fix: Retrospective Report Persistence - Handler integration tests.
    """

    def test_handler_saves_report_on_success(self, tmp_path: Path):
        """Handler extracts and saves report when execute succeeds."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.core.loop.handlers.retrospective import RetrospectiveHandler
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.paths import init_paths, _reset_paths
        from bmad_assist.core.state import Phase, State

        # Setup paths singleton for test
        _reset_paths()
        init_paths(tmp_path)

        try:
            # Create mock config
            mock_config = MagicMock()
            mock_config.testarch = MagicMock()
            mock_config.testarch.trace_on_epic_complete = "off"

            handler = RetrospectiveHandler(mock_config, tmp_path)
            state = State(
                current_epic=21,
                current_story="21-5",
                current_phase=Phase.RETROSPECTIVE,
            )

            # LLM output with markers
            llm_output = """<!-- RETROSPECTIVE_REPORT_START -->
# Epic 21 Retrospective: Test

## Summary
Test content
<!-- RETROSPECTIVE_REPORT_END -->"""

            # Mock the parent execute to return success with response
            parent_result = PhaseResult.ok({"response": llm_output})

            with patch.object(RetrospectiveHandler, "execute", wraps=handler.execute):
                # Mock parent's execute (BaseHandler.execute)
                with patch(
                    "bmad_assist.core.loop.handlers.base.BaseHandler.execute",
                    return_value=parent_result,
                ):
                    result = handler.execute(state)

            # Verify report was saved
            assert result.success
            assert "report_file" in result.outputs
            report_path = Path(result.outputs["report_file"])
            assert report_path.exists()
            assert "# Epic 21 Retrospective" in report_path.read_text()
        finally:
            _reset_paths()

    def test_handler_graceful_on_save_failure(self, tmp_path: Path):
        """Handler continues even if save fails (AC #5 graceful degradation)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.core.loop.handlers.retrospective import RetrospectiveHandler
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.paths import init_paths, _reset_paths
        from bmad_assist.core.state import Phase, State

        _reset_paths()
        init_paths(tmp_path)

        try:
            mock_config = MagicMock()
            mock_config.testarch = MagicMock()
            mock_config.testarch.trace_on_epic_complete = "off"

            handler = RetrospectiveHandler(mock_config, tmp_path)
            state = State(
                current_epic=21,
                current_story="21-5",
                current_phase=Phase.RETROSPECTIVE,
            )

            parent_result = PhaseResult.ok({"response": "some output"})

            with patch(
                "bmad_assist.core.loop.handlers.base.BaseHandler.execute",
                return_value=parent_result,
            ):
                # Make save fail
                with patch(
                    "bmad_assist.retrospective.reports.atomic_write",
                    side_effect=OSError("Disk full"),
                ):
                    result = handler.execute(state)

            # Should still succeed (graceful degradation)
            assert result.success
            # report_file should NOT be in outputs since save failed
            assert "report_file" not in result.outputs
        finally:
            _reset_paths()

    def test_handler_skips_save_when_no_response(self, tmp_path: Path):
        """Handler skips save when no response in outputs."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.core.loop.handlers.retrospective import RetrospectiveHandler
        from bmad_assist.core.loop.types import PhaseResult
        from bmad_assist.core.paths import init_paths, _reset_paths
        from bmad_assist.core.state import Phase, State

        _reset_paths()
        init_paths(tmp_path)

        try:
            mock_config = MagicMock()
            mock_config.testarch = MagicMock()
            mock_config.testarch.trace_on_epic_complete = "off"

            handler = RetrospectiveHandler(mock_config, tmp_path)
            state = State(
                current_epic=21,
                current_story="21-5",
                current_phase=Phase.RETROSPECTIVE,
            )

            # No response in outputs
            parent_result = PhaseResult.ok({})

            with patch(
                "bmad_assist.core.loop.handlers.base.BaseHandler.execute",
                return_value=parent_result,
            ):
                result = handler.execute(state)

            assert result.success
            assert "report_file" not in result.outputs
        finally:
            _reset_paths()
