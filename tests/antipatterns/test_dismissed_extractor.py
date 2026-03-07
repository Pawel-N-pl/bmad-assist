"""Tests for dismissed findings extraction and file appending."""

from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.antipatterns.dismissed_extractor import (
    DISMISSED_ITEM_PATTERN,
    DISMISSED_SECTION_PATTERN,
    append_to_dismissed_findings_file,
    extract_and_append_dismissed_findings,
    extract_dismissed_findings,
)


class TestRegexPatterns:
    """Tests for regex patterns used in dismissed findings extraction."""

    def test_dismissed_section_pattern_basic(self):
        """Test extraction of Issues Dismissed section."""
        content = """
## Issues Verified (by severity)

### Critical
- **Issue**: Test | **Fix**: Done

## Issues Dismissed
- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A (CRITICAL), Validator B (CRITICAL) | **Dismissal Reason**: Intentionally deferred to Story 5.3

## Changes Applied
Some changes.
"""
        match = DISMISSED_SECTION_PATTERN.search(content)
        assert match is not None
        section = match.group(1)
        assert "AC6 not end-to-end" in section
        assert "Changes Applied" not in section

    def test_dismissed_section_pattern_ends_at_eof(self):
        """Test section extraction when at end of file."""
        content = """
## Issues Verified
### High
- **Issue**: Test | **Fix**: Done

## Issues Dismissed
- **Claimed Issue**: False positive | **Raised by**: Reviewer A | **Dismissal Reason**: Stale context
"""
        match = DISMISSED_SECTION_PATTERN.search(content)
        assert match is not None
        assert "False positive" in match.group(1)

    def test_dismissed_item_pattern_single(self):
        """Test matching a single dismissed item."""
        text = "- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A (CRITICAL), Validator B (CRITICAL) | **Dismissal Reason**: Intentionally deferred to Story 5.3"
        matches = list(DISMISSED_ITEM_PATTERN.finditer(text))
        assert len(matches) == 1
        assert "AC6 not end-to-end" in matches[0].group(1)
        assert "Validator A" in matches[0].group(2)
        assert "deferred to Story 5.3" in matches[0].group(3)

    def test_dismissed_item_pattern_multiple(self):
        """Test matching multiple dismissed items."""
        text = """- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A, B | **Dismissal Reason**: Deferred to Story 5.3
- **Claimed Issue**: P1-BOOK-012 sanitization | **Raised by**: Validator B | **Dismissal Reason**: False positive - stale context
"""
        matches = list(DISMISSED_ITEM_PATTERN.finditer(text))
        assert len(matches) == 2
        assert "AC6" in matches[0].group(1)
        assert "P1-BOOK-012" in matches[1].group(1)


class TestExtractDismissedFindings:
    """Tests for extract_dismissed_findings function."""

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.antipatterns.enabled = True
        return config

    @pytest.fixture
    def mock_config_disabled(self):
        config = MagicMock()
        config.antipatterns.enabled = False
        return config

    @pytest.fixture
    def synthesis_with_dismissals(self):
        return """
<!-- CODE_REVIEW_SYNTHESIS_START -->
## Synthesis Summary
2 issues verified, 3 false positives dismissed, 2 fixes applied

## Issues Verified (by severity)
### Critical
- **Issue**: Real bug | **Source**: Reviewer A | **Fix**: Fixed it

## Issues Dismissed
- **Claimed Issue**: AC6 not end-to-end | **Raised by**: Validator A (CRITICAL), Validator B (CRITICAL) | **Dismissal Reason**: Intentionally deferred to Story 5.3
- **Claimed Issue**: P1-BOOK-012 sanitization missing | **Raised by**: Validator B (HIGH) | **Dismissal Reason**: False positive - stale context, already fixed in commit abc123
- **Claimed Issue**: Missing WCAG contrast | **Raised by**: Reviewer C (MEDIUM) | **Dismissal Reason**: Design system enforces this at component level

## Changes Applied
Some changes listed here.
<!-- CODE_REVIEW_SYNTHESIS_END -->
"""

    def test_extract_all_dismissed_findings(self, mock_config, synthesis_with_dismissals):
        findings = extract_dismissed_findings(
            synthesis_with_dismissals, epic_id=5, story_id="5-1", config=mock_config
        )
        assert len(findings) == 3
        assert findings[0]["claimed_issue"] == "AC6 not end-to-end"
        assert "Validator A" in findings[0]["raised_by"]
        assert "deferred to Story 5.3" in findings[0]["dismissal_reason"]

    def test_extract_preserves_all_fields(self, mock_config, synthesis_with_dismissals):
        findings = extract_dismissed_findings(
            synthesis_with_dismissals, epic_id=5, story_id="5-1", config=mock_config
        )
        for f in findings:
            assert "claimed_issue" in f
            assert "raised_by" in f
            assert "dismissal_reason" in f
            assert f["claimed_issue"]
            assert f["dismissal_reason"]

    def test_disabled_config_returns_empty(self, mock_config_disabled):
        content = """
## Issues Dismissed
- **Claimed Issue**: Test | **Raised by**: A | **Dismissal Reason**: False positive
"""
        findings = extract_dismissed_findings(content, epic_id=5, story_id="5-1", config=mock_config_disabled)
        assert findings == []

    def test_empty_synthesis_returns_empty(self, mock_config):
        findings = extract_dismissed_findings("", epic_id=5, story_id="5-1", config=mock_config)
        assert findings == []

    def test_no_dismissed_section_returns_empty(self, mock_config):
        content = """
## Issues Verified
### Critical
- **Issue**: Real bug | **Fix**: Fixed
"""
        findings = extract_dismissed_findings(content, epic_id=5, story_id="5-1", config=mock_config)
        assert findings == []

    def test_no_false_positives_message_returns_empty(self, mock_config):
        content = """
## Issues Dismissed
No false positives identified.
"""
        findings = extract_dismissed_findings(content, epic_id=5, story_id="5-1", config=mock_config)
        assert findings == []

    def test_string_epic_id(self, mock_config):
        content = """
## Issues Dismissed
- **Claimed Issue**: Test issue | **Raised by**: Reviewer A | **Dismissal Reason**: Not a real bug
"""
        findings = extract_dismissed_findings(
            content, epic_id="testarch", story_id="testarch-01", config=mock_config
        )
        assert len(findings) == 1


class TestAppendToDismissedFindingsFile:
    """Tests for append_to_dismissed_findings_file function."""

    @pytest.fixture
    def sample_findings(self):
        return [
            {
                "claimed_issue": "AC6 not end-to-end",
                "raised_by": "Validator A, B",
                "dismissal_reason": "Deferred to Story 5.3",
            },
            {
                "claimed_issue": "P1-BOOK-012 sanitization",
                "raised_by": "Validator B",
                "dismissal_reason": "False positive - stale context",
            },
        ]

    def test_creates_file_in_dismissed_findings_dir(self, tmp_path, sample_findings):
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_dismissed_findings_file(
                findings=sample_findings,
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
            )

        dismissed_dir = impl_artifacts / "dismissed-findings"
        assert dismissed_dir.exists()

        dismissed_file = dismissed_dir / "epic-5-dismissed-findings.md"
        assert dismissed_file.exists()

        content = dismissed_file.read_text()
        assert "CONTEXT FOR REVIEWERS" in content
        assert "Do NOT" in content
        assert "Story 5-1" in content
        assert "AC6 not end-to-end" in content
        assert "Deferred to Story 5.3" in content

    def test_table_format(self, tmp_path, sample_findings):
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_dismissed_findings_file(
                findings=sample_findings,
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
            )

        content = (impl_artifacts / "dismissed-findings" / "epic-5-dismissed-findings.md").read_text()
        assert "| Finding | Raised By | Dismissal Reason |" in content
        assert "|---------|-----------|------------------|" in content

    def test_append_to_existing_file(self, tmp_path, sample_findings):
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        dismissed_dir = impl_artifacts / "dismissed-findings"
        dismissed_dir.mkdir(parents=True)

        dismissed_file = dismissed_dir / "epic-5-dismissed-findings.md"
        initial_content = "# Epic 5 - Dismissed Findings\n\n## Story 5-1 (2026-03-01)\n\nExisting content"
        dismissed_file.write_text(initial_content)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_dismissed_findings_file(
                findings=sample_findings,
                epic_id=5,
                story_id="5-2",
                project_path=tmp_path,
            )

        content = dismissed_file.read_text()
        assert "Story 5-1" in content
        assert "Existing content" in content
        assert "Story 5-2" in content
        assert "AC6 not end-to-end" in content

    def test_empty_findings_skips(self, tmp_path):
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_dismissed_findings_file(
                findings=[],
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
            )

        dismissed_dir = impl_artifacts / "dismissed-findings"
        assert not dismissed_dir.exists()

    def test_pipe_characters_escaped(self, tmp_path):
        findings = [
            {
                "claimed_issue": "Issue with | pipe",
                "raised_by": "Reviewer A | B",
                "dismissal_reason": "Reason | with pipe",
            }
        ]

        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            append_to_dismissed_findings_file(
                findings=findings,
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
            )

        content = (impl_artifacts / "dismissed-findings" / "epic-5-dismissed-findings.md").read_text()
        assert "Issue with \\| pipe" in content
        assert "Reviewer A \\| B" in content


class TestExtractAndAppendDismissedFindings:
    """Tests for the convenience wrapper function."""

    def test_extract_and_append_full_pipeline(self, tmp_path):
        config = MagicMock()
        config.antipatterns.enabled = True

        synthesis = """
## Issues Dismissed
- **Claimed Issue**: Test false positive | **Raised by**: Reviewer A | **Dismissal Reason**: Not a real issue

## Changes Applied
None.
"""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            extract_and_append_dismissed_findings(
                synthesis_content=synthesis,
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
                config=config,
            )

        dismissed_file = impl_artifacts / "dismissed-findings" / "epic-5-dismissed-findings.md"
        assert dismissed_file.exists()
        content = dismissed_file.read_text()
        assert "Test false positive" in content
        assert "Not a real issue" in content

    def test_extract_and_append_no_findings_no_file(self, tmp_path):
        config = MagicMock()
        config.antipatterns.enabled = True

        synthesis = """
## Issues Dismissed
No false positives identified.
"""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)

        with patch("bmad_assist.antipatterns.dismissed_extractor.get_paths") as mock_paths:
            mock_paths.return_value.implementation_artifacts = impl_artifacts

            extract_and_append_dismissed_findings(
                synthesis_content=synthesis,
                epic_id=5,
                story_id="5-1",
                project_path=tmp_path,
                config=config,
            )

        dismissed_dir = impl_artifacts / "dismissed-findings"
        assert not dismissed_dir.exists()
