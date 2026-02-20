"""Tests for notification message formatter.

Tests cover:
- AC1: Successful phase completion format
- AC2: Workflow failure format (two-line)
- AC3: Error message truncation (80 chars)
- AC4: Review issues format
- AC5-AC7: Future Story 21.4 integration (placeholder tests)
"""


from bmad_assist.core.state import Phase
from bmad_assist.notifications.events import (
    AnomalyDetectedPayload,
    CLICrashedPayload,
    ErrorOccurredPayload,
    EventPayload,
    EventType,
    FatalErrorPayload,
    PhaseCompletedPayload,
    QueueBlockedPayload,
    StoryCompletedPayload,
    StoryStartedPayload,
    TimeoutWarningPayload,
)
from bmad_assist.notifications.formatter import (
    MAX_ERROR_LENGTH,
    STATUS_ICONS,
    _extract_error_message,
    _extract_story_id,
    _format_error_line,
    _format_header,
    _get_status_icon,
    _phase_to_workflow_name,
    _sanitize_error_message,
    _truncate_message,
    format_notification,
)


class TestTruncateMessage:
    """Tests for _truncate_message helper."""

    def test_short_message_unchanged(self) -> None:
        """Test message shorter than limit is unchanged."""
        msg = "short message"
        assert _truncate_message(msg) == msg

    def test_exact_length_unchanged(self) -> None:
        """Test message exactly at limit is unchanged."""
        msg = "x" * 80
        assert _truncate_message(msg) == msg

    def test_long_message_truncated(self) -> None:
        """Test message over limit is truncated with ellipsis."""
        msg = "a" * 100
        result = _truncate_message(msg)
        assert len(result) == 80
        assert result.endswith("...")
        assert result == "a" * 77 + "..."

    def test_custom_max_length(self) -> None:
        """Test custom max_len parameter."""
        msg = "a" * 50
        result = _truncate_message(msg, max_len=30)
        assert len(result) == 30
        assert result == "a" * 27 + "..."

    def test_unicode_characters(self) -> None:
        """Test truncation with unicode characters."""
        msg = "日本語" * 30  # 90 characters
        result = _truncate_message(msg)
        assert len(result) == 80
        assert result.endswith("...")

    def test_emoji_truncation(self) -> None:
        """Test truncation with emoji characters."""
        msg = "🎉" * 100
        result = _truncate_message(msg)
        assert len(result) == 80
        assert result.endswith("...")


class TestSanitizeErrorMessage:
    """Tests for _sanitize_error_message helper."""

    def test_no_newlines_unchanged(self) -> None:
        """Test message without newlines is unchanged."""
        msg = "simple error message"
        assert _sanitize_error_message(msg) == msg

    def test_newlines_replaced(self) -> None:
        """Test newlines are replaced with ' | '."""
        msg = "error line 1\nerror line 2\nerror line 3"
        result = _sanitize_error_message(msg)
        assert result == "error line 1 | error line 2 | error line 3"

    def test_carriage_returns_removed(self) -> None:
        """Test carriage returns are removed."""
        msg = "line 1\r\nline 2\rline 3"
        result = _sanitize_error_message(msg)
        assert result == "line 1 | line 2line 3"

    def test_strips_whitespace(self) -> None:
        """Test leading/trailing whitespace is stripped."""
        msg = "  error message  "
        assert _sanitize_error_message(msg) == "error message"


class TestPhaseToWorkflowName:
    """Tests for _phase_to_workflow_name helper."""

    def test_uppercase_snake_case(self) -> None:
        """Test UPPER_SNAKE_CASE conversion."""
        assert _phase_to_workflow_name("CREATE_STORY") == "create-story"
        assert _phase_to_workflow_name("DEV_STORY") == "dev-story"
        assert _phase_to_workflow_name("CODE_REVIEW") == "code-review"

    def test_lowercase_snake_case(self) -> None:
        """Test lowercase_snake_case conversion."""
        assert _phase_to_workflow_name("create_story") == "create-story"
        assert _phase_to_workflow_name("validate_story") == "validate-story"

    def test_phase_enum(self) -> None:
        """Test Phase enum conversion."""
        assert _phase_to_workflow_name(Phase.CREATE_STORY) == "create-story"
        assert _phase_to_workflow_name(Phase.DEV_STORY) == "dev-story"
        assert _phase_to_workflow_name(Phase.CODE_REVIEW) == "code-review"
        assert _phase_to_workflow_name(Phase.RETROSPECTIVE) == "retrospective"

    def test_all_phases(self) -> None:
        """Test all Phase enum values convert correctly."""
        expected = {
            Phase.CREATE_STORY: "create-story",
            Phase.VALIDATE_STORY: "validate-story",
            Phase.VALIDATE_STORY_SYNTHESIS: "validate-story-synthesis",
            Phase.ATDD: "atdd",
            Phase.DEV_STORY: "dev-story",
            Phase.CODE_REVIEW: "code-review",
            Phase.CODE_REVIEW_SYNTHESIS: "code-review-synthesis",
            Phase.TEST_REVIEW: "test-review",
            Phase.RETROSPECTIVE: "retrospective",
        }
        for phase, expected_name in expected.items():
            assert _phase_to_workflow_name(phase) == expected_name


class TestGetStatusIcon:
    """Tests for _get_status_icon helper."""

    def test_success_outcome(self) -> None:
        """Test success outcome returns checkmark."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="success",
        )
        assert _get_status_icon(EventType.STORY_COMPLETED, payload) == "✓"

    def test_failed_outcome(self) -> None:
        """Test failed outcome returns X icon."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="failed",
        )
        assert _get_status_icon(EventType.STORY_COMPLETED, payload) == "❌"

    def test_review_issues_outcome(self) -> None:
        """Test review_issues outcome returns warning icon."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="review_issues|missing tests|error handling",
        )
        assert _get_status_icon(EventType.STORY_COMPLETED, payload) == "⚠️"

    def test_high_priority_event(self) -> None:
        """Test high priority events return failure icon."""
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message="Something went wrong",
        )
        assert _get_status_icon(EventType.ERROR_OCCURRED, payload) == "❌"

    def test_story_started_event(self) -> None:
        """Test story_started event returns success icon."""
        payload = StoryStartedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
        )
        # STORY_STARTED has no status icon (story is just beginning, not completed)
        assert _get_status_icon(EventType.STORY_STARTED, payload) == ""

    def test_phase_completed_event(self) -> None:
        """Test phase_completed event returns success icon."""
        payload = PhaseCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
            next_phase="CODE_REVIEW",
        )
        assert _get_status_icon(EventType.PHASE_COMPLETED, payload) == "✓"


class TestExtractStoryId:
    """Tests for _extract_story_id helper."""

    def test_epic_and_story(self) -> None:
        """Test extraction with both epic and story."""
        payload = StoryStartedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            phase="DEV_STORY",
        )
        assert _extract_story_id(payload) == "12.Status codes"

    def test_string_epic(self) -> None:
        """Test extraction with string epic ID."""
        payload = StoryStartedPayload(
            project="proj",
            epic="testarch",
            story="1-1",
            phase="DEV_STORY",
        )
        assert _extract_story_id(payload) == "testarch.1-1"

    def test_epic_zero(self) -> None:
        """Test extraction with epic ID of 0 (valid integer ID)."""
        payload = StoryStartedPayload(
            project="proj",
            epic=0,
            story="zero-story",
            phase="DEV_STORY",
        )
        # Epic 0 should be included in result (not treated as falsy)
        result = _extract_story_id(payload)
        assert result == "0.zero-story"

    def test_story_only(self) -> None:
        """Test extraction with only story (no epic)."""

        class MinimalPayload(EventPayload):
            story: str = "orphan-story"

        payload = MinimalPayload(project="proj", epic="")  # Empty string epic
        result = _extract_story_id(payload)
        assert result == "orphan-story"

    def test_no_story_no_epic(self) -> None:
        """Test extraction with missing story and epic fields."""

        class BarePayload(EventPayload):
            pass

        payload = BarePayload(project="proj", epic="")
        result = _extract_story_id(payload)
        assert result == "Unknown"


class TestExtractErrorMessage:
    """Tests for _extract_error_message helper."""

    def test_success_outcome_returns_none(self) -> None:
        """Test success outcome returns None."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="success",
        )
        assert _extract_error_message(EventType.STORY_COMPLETED, payload) is None

    def test_failed_outcome_returns_none(self) -> None:
        """Test plain 'failed' outcome returns None (no descriptive message)."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="failed",
        )
        assert _extract_error_message(EventType.STORY_COMPLETED, payload) is None

    def test_descriptive_failure_returned(self) -> None:
        """Test descriptive failure outcome is returned."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="Missing acceptance_criteria in story file",
        )
        result = _extract_error_message(EventType.STORY_COMPLETED, payload)
        assert result == "Missing acceptance_criteria in story file"

    def test_review_issues_format(self) -> None:
        """Test review_issues format parses correctly."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="review_issues|missing tests|error handling|logging",
        )
        result = _extract_error_message(EventType.STORY_COMPLETED, payload)
        assert result == "3 issues: missing tests, error handling, logging"

    def test_review_issues_more_than_five(self) -> None:
        """Test review_issues with more than 5 issues shows count."""
        issues = "|".join(["issue" + str(i) for i in range(7)])
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome=f"review_issues|{issues}",
        )
        result = _extract_error_message(EventType.STORY_COMPLETED, payload)
        assert "7 issues:" in result
        assert "(+2 more)" in result

    def test_review_issues_empty(self) -> None:
        """Test review_issues with pipe but no actual issues returns None."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="review_issues|",
        )
        result = _extract_error_message(EventType.STORY_COMPLETED, payload)
        # Empty issues list should return None (no error line)
        assert result is None

    def test_review_issues_whitespace_only(self) -> None:
        """Test review_issues with only whitespace issues returns None."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="review_issues|  |  |  ",
        )
        result = _extract_error_message(EventType.STORY_COMPLETED, payload)
        # Whitespace-only issues should be filtered out
        assert result is None

    def test_error_occurred_payload(self) -> None:
        """Test ErrorOccurredPayload returns message."""
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message="Connection timeout",
        )
        result = _extract_error_message(EventType.ERROR_OCCURRED, payload)
        assert result == "Connection timeout"

    def test_anomaly_detected_payload(self) -> None:
        """Test AnomalyDetectedPayload returns context."""
        payload = AnomalyDetectedPayload(
            project="proj",
            epic=1,
            story="1-1",
            anomaly_type="infinite_loop",
            context="LLM stuck in loop generating same output",
            suggested_actions=["restart", "skip"],
        )
        result = _extract_error_message(EventType.ANOMALY_DETECTED, payload)
        assert result == "LLM stuck in loop generating same output"

    def test_queue_blocked_payload(self) -> None:
        """Test QueueBlockedPayload returns reason."""
        payload = QueueBlockedPayload(
            project="proj",
            epic=1,
            story="1-1",
            reason="Provider timeout after 3 retries",
            waiting_tasks=5,
        )
        result = _extract_error_message(EventType.QUEUE_BLOCKED, payload)
        assert result == "Provider timeout after 3 retries"


class TestFormatErrorLine:
    """Tests for _format_error_line helper."""

    def test_no_error_returns_none(self) -> None:
        """Test no error message returns None."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="success",
        )
        assert _format_error_line(EventType.STORY_COMPLETED, payload) is None

    def test_error_line_has_arrow_prefix(self) -> None:
        """Test error line has '→ ' prefix."""
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message="Something broke",
        )
        result = _format_error_line(EventType.ERROR_OCCURRED, payload)
        assert result is not None
        assert result.startswith("→ ")
        assert "Something broke" in result

    def test_error_line_truncation(self) -> None:
        """Test error line is truncated to 80 chars."""
        long_message = "a" * 100
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message=long_message,
        )
        result = _format_error_line(EventType.ERROR_OCCURRED, payload)
        assert result is not None
        # "→ " prefix + 80 chars max error
        assert len(result) == 2 + 80
        assert result.endswith("...")

    def test_newlines_sanitized(self) -> None:
        """Test newlines in error message are sanitized."""
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message="line 1\nline 2\nline 3",
        )
        result = _format_error_line(EventType.ERROR_OCCURRED, payload)
        assert result is not None
        assert "\n" not in result[2:]  # After "→ " prefix
        assert " | " in result


class TestFormatHeader:
    """Tests for _format_header helper."""

    def test_success_format(self) -> None:
        """Test successful completion format includes checkmark."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            duration_ms=180_000,
            outcome="success",
        )
        result = _format_header(EventType.STORY_COMPLETED, payload)
        # Should contain workflow icon, label, checkmark, story ID, time
        assert "✓" in result
        assert "12.Status codes" in result
        assert "3m" in result

    def test_failure_format(self) -> None:
        """Test failure format (failure icon replaces workflow icon per AC2)."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            duration_ms=180_000,
            outcome="failed",
        )
        result = _format_header(EventType.STORY_COMPLETED, payload)
        # Should contain failure icon at start (replaces workflow icon per AC2)
        assert "❌" in result
        assert "✓" not in result
        assert "12.Status codes" in result
        assert "3m" in result

    def test_story_started_with_phase(self) -> None:
        """Test story_started event uses phase for workflow lookup."""
        payload = StoryStartedPayload(
            project="proj",
            epic=5,
            story="5-1",
            phase="DEV_STORY",
        )
        result = _format_header(EventType.STORY_STARTED, payload)
        # Should include Develop workflow label (per unified phase naming)
        assert "Develop" in result
        # Story "5-1" with epic 5 becomes "5.1" (no duplication)
        assert "5.1" in result

    def test_missing_timing_graceful(self) -> None:
        """Test missing duration_ms is handled gracefully."""
        payload = StoryStartedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="CREATE_STORY",
        )
        # StoryStartedPayload has no duration_ms
        result = _format_header(EventType.STORY_STARTED, payload)
        # Should format without timing - story "1-1" with epic 1 becomes "1.1"
        assert "1.1" in result
        # No "m" suffix for time
        assert result.count("m") == 0 or "m" not in result.split()[-1]

    def test_none_payload_warning(self) -> None:
        """Test None payload logs warning and returns fallback."""
        result = _format_header(EventType.STORY_STARTED, None)  # type: ignore
        assert "Unknown" in result


class TestFormatNotificationSuccess:
    """Tests for format_notification with successful events (AC1)."""

    def test_success_single_line(self) -> None:
        """Test successful completion is single line with checkmark."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            duration_ms=180_000,
            outcome="success",
        )
        result = format_notification(EventType.STORY_COMPLETED, payload)
        # Single line (no newline)
        assert "\n" not in result
        # Contains checkmark
        assert "✓" in result
        # Contains story ID
        assert "12.Status codes" in result
        # Contains time
        assert "3m" in result

    def test_story_started_single_line(self) -> None:
        """Test story_started is single line."""
        payload = StoryStartedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
        )
        result = format_notification(EventType.STORY_STARTED, payload)
        # STORY_STARTED without story_title is single line, no checkmark
        assert "\n" not in result
        assert "✓" not in result  # No checkmark for story starting

    def test_story_started_with_title_two_lines(self) -> None:
        """Test story_started with story_title shows title on second line."""
        payload = StoryStartedPayload(
            project="proj",
            epic=2,
            story="2-1",
            phase="CREATE_STORY",
            story_title="CSS Design Tokens And Typography",
        )
        result = format_notification(EventType.STORY_STARTED, payload)
        # STORY_STARTED with story_title has two lines
        assert "\n" in result
        lines = result.split("\n")
        assert len(lines) == 2
        assert "2.1" in lines[0] or "2-1" in lines[0]  # Story ID in first line
        assert "CSS Design Tokens And Typography" in lines[1]  # Title in second line
        assert "✓" not in result  # No checkmark

    def test_phase_completed_single_line(self) -> None:
        """Test phase_completed is single line."""
        payload = PhaseCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
            next_phase="CODE_REVIEW",
        )
        result = format_notification(EventType.PHASE_COMPLETED, payload)
        assert "\n" not in result
        assert "✓" in result


class TestFormatNotificationFailure:
    """Tests for format_notification with failure events (AC2)."""

    def test_failure_two_lines(self) -> None:
        """Test workflow failure has two lines."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            duration_ms=180_000,
            outcome="Missing acceptance_criteria in story file",
        )
        result = format_notification(EventType.STORY_COMPLETED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # Second line has arrow prefix
        assert lines[1].startswith("→ ")
        assert "Missing acceptance_criteria" in lines[1]

    def test_error_occurred_two_lines(self) -> None:
        """Test error_occurred has two lines."""
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message="Connection timeout",
        )
        result = format_notification(EventType.ERROR_OCCURRED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "→ Connection timeout" in lines[1]

    def test_anomaly_detected_two_lines(self) -> None:
        """Test anomaly_detected has two lines."""
        payload = AnomalyDetectedPayload(
            project="proj",
            epic=1,
            story="1-1",
            anomaly_type="infinite_loop",
            context="LLM stuck in loop",
            suggested_actions=["restart"],
        )
        result = format_notification(EventType.ANOMALY_DETECTED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "→ LLM stuck in loop" in lines[1]

    def test_queue_blocked_two_lines(self) -> None:
        """Test queue_blocked has two lines."""
        payload = QueueBlockedPayload(
            project="proj",
            epic=1,
            story="1-1",
            reason="Provider timeout",
            waiting_tasks=5,
        )
        result = format_notification(EventType.QUEUE_BLOCKED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "→ Provider timeout" in lines[1]


class TestFormatNotificationTruncation:
    """Tests for error message truncation (AC3)."""

    def test_long_error_truncated(self) -> None:
        """Test error message over 80 chars is truncated."""
        long_message = "a" * 100
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message=long_message,
        )
        result = format_notification(EventType.ERROR_OCCURRED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        error_line = lines[1]
        # "→ " prefix + truncated message (77 chars + "...")
        assert len(error_line) == 2 + 80
        assert error_line.endswith("...")

    def test_exact_80_chars_not_truncated(self) -> None:
        """Test error message exactly 80 chars is not truncated."""
        exact_message = "x" * 80
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message=exact_message,
        )
        result = format_notification(EventType.ERROR_OCCURRED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        error_line = lines[1]
        # "→ " prefix + exact message
        assert error_line == "→ " + exact_message
        assert not error_line.endswith("...")

    def test_unicode_truncation(self) -> None:
        """Test unicode error message truncation."""
        unicode_message = "日本語エラー" * 20  # 120 chars
        payload = ErrorOccurredPayload(
            project="proj",
            epic=1,
            story="1-1",
            error_type="RuntimeError",
            message=unicode_message,
        )
        result = format_notification(EventType.ERROR_OCCURRED, payload)
        lines = result.split("\n")
        error_line = lines[1]
        # Should be truncated
        assert error_line.endswith("...")


class TestFormatNotificationReviewIssues:
    """Tests for review issues format (AC4)."""

    def test_review_issues_format(self) -> None:
        """Test review issues with pipe-delimited format."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=12,
            story="Status codes",
            duration_ms=480_000,
            outcome="review_issues|missing tests|error handling|logging",
        )
        result = format_notification(EventType.STORY_COMPLETED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # Check for warning icon in header (workflow icon from workflow_labels)
        # Check second line has issues
        assert "3 issues:" in lines[1]
        assert "missing tests" in lines[1]
        assert "error handling" in lines[1]
        assert "logging" in lines[1]

    def test_review_issues_single_issue(self) -> None:
        """Test review issues with single issue."""
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome="review_issues|missing tests",
        )
        result = format_notification(EventType.STORY_COMPLETED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "1 issue: missing tests" in lines[1]

    def test_review_issues_many_issues(self) -> None:
        """Test review issues with more than 5 issues."""
        issues = "issue1|issue2|issue3|issue4|issue5|issue6|issue7"
        payload = StoryCompletedPayload(
            project="proj",
            epic=1,
            story="1-1",
            duration_ms=1000,
            outcome=f"review_issues|{issues}",
        )
        result = format_notification(EventType.STORY_COMPLETED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "7 issues:" in lines[1]
        assert "(+2 more)" in lines[1]
        # Only first 5 issues shown
        assert "issue1" in lines[1]
        assert "issue5" in lines[1]
        assert "issue6" not in lines[1]


class TestFormatNotificationMissingFields:
    """Tests for graceful degradation with missing fields."""

    def test_missing_duration_graceful(self) -> None:
        """Test missing duration_ms is handled gracefully."""
        payload = StoryStartedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
        )
        result = format_notification(EventType.STORY_STARTED, payload)
        # Should format without errors
        assert "1.1" in result
        # No time component at end
        assert not result.rstrip().endswith("m")

    def test_missing_phase_uses_event_type(self) -> None:
        """Test missing phase falls back to event type."""
        # PhaseCompletedPayload has phase, but let's simulate missing

        class NoPhasePayload(EventPayload):
            pass

        payload = NoPhasePayload(project="proj", epic=1)
        result = format_notification(EventType.STORY_STARTED, payload)
        # Should still work
        assert "1" in result


class TestFormatNotificationUnknownEventType:
    """Tests for unknown event types (AC7 placeholder)."""

    def test_unknown_event_type_fallback(self) -> None:
        """Test unknown event type uses fallback formatting."""
        # Currently all EventType values are known, but test the fallback path
        payload = StoryStartedPayload(
            project="proj",
            epic=1,
            story="1-1",
            phase="DEV_STORY",
        )
        # Using a known event type but verifying it formats
        result = format_notification(EventType.STORY_STARTED, payload)
        assert "1.1" in result


class TestStatusIconsConstant:
    """Tests for STATUS_ICONS constant."""

    def test_success_icon_defined(self) -> None:
        """Test success icon is defined."""
        assert "success" in STATUS_ICONS
        assert STATUS_ICONS["success"] == "✓"

    def test_failed_icon_defined(self) -> None:
        """Test failed icon is defined."""
        assert "failed" in STATUS_ICONS
        assert STATUS_ICONS["failed"] == "❌"

    def test_review_issues_icon_defined(self) -> None:
        """Test review_issues icon is defined."""
        assert "review_issues" in STATUS_ICONS
        assert STATUS_ICONS["review_issues"] == "⚠️"


class TestMaxErrorLengthConstant:
    """Tests for MAX_ERROR_LENGTH constant."""

    def test_max_error_length_is_80(self) -> None:
        """Test MAX_ERROR_LENGTH is 80."""
        assert MAX_ERROR_LENGTH == 80


class TestModuleExports:
    """Tests for module exports."""

    def test_format_notification_exported(self) -> None:
        """Test format_notification is exported from module."""
        from bmad_assist.notifications import format_notification as fn

        assert fn is format_notification

    def test_format_notification_in_all(self) -> None:
        """Test format_notification is in __all__."""
        from bmad_assist.notifications import __all__

        assert "format_notification" in __all__


# ============================================================================
# Infrastructure Event Formatter Tests (Story 21.4)
# ============================================================================


class TestInfrastructureStatusIcons:
    """Tests for Story 21.4 AC6: Infrastructure status icons."""

    def test_timeout_warning_icon_defined(self) -> None:
        """Test timeout_warning icon is defined."""
        assert "timeout_warning" in STATUS_ICONS
        assert STATUS_ICONS["timeout_warning"] == "⚡"

    def test_cli_crashed_icon_defined(self) -> None:
        """Test cli_crashed icon is defined."""
        assert "cli_crashed" in STATUS_ICONS
        assert STATUS_ICONS["cli_crashed"] == "💀"

    def test_cli_recovered_icon_defined(self) -> None:
        """Test cli_recovered icon is defined."""
        assert "cli_recovered" in STATUS_ICONS
        assert STATUS_ICONS["cli_recovered"] == "🔄"

    def test_fatal_icon_defined(self) -> None:
        """Test fatal icon is defined."""
        assert "fatal" in STATUS_ICONS
        assert STATUS_ICONS["fatal"] == "☠️"


class TestGetStatusIconInfrastructure:
    """Tests for _get_status_icon with infrastructure events."""

    def test_timeout_warning_icon(self) -> None:
        """Test TIMEOUT_WARNING returns ⚡ icon."""
        payload = TimeoutWarningPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            elapsed_ms=3000000,
            limit_ms=3600000,
            remaining_ms=600000,
        )
        result = _get_status_icon(EventType.TIMEOUT_WARNING, payload)
        assert result == "⚡"

    def test_cli_crashed_not_recovered_icon(self) -> None:
        """Test CLI_CRASHED with recovered=False returns 💀 icon."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            signal=9,
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = _get_status_icon(EventType.CLI_CRASHED, payload)
        assert result == "💀"

    def test_cli_crashed_recovered_icon(self) -> None:
        """Test CLI_CRASHED with recovered=True returns 🔄 icon."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            signal=9,
            attempt=2,
            max_attempts=3,
            recovered=True,
        )
        result = _get_status_icon(EventType.CLI_CRASHED, payload)
        assert result == "🔄"

    def test_cli_recovered_icon(self) -> None:
        """Test CLI_RECOVERED returns 🔄 icon."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            signal=9,
            attempt=2,
            max_attempts=3,
            recovered=True,
        )
        result = _get_status_icon(EventType.CLI_RECOVERED, payload)
        assert result == "🔄"

    def test_fatal_error_icon(self) -> None:
        """Test FATAL_ERROR returns ☠️ icon."""
        payload = FatalErrorPayload(
            project="proj",
            epic=1,
            story="1-1",
            exception_type="KeyError",
            message="test error",
            location="state.py:142",
        )
        result = _get_status_icon(EventType.FATAL_ERROR, payload)
        assert result == "☠️"


class TestExtractErrorMessageInfrastructure:
    """Tests for _extract_error_message with infrastructure events."""

    def test_timeout_warning_format(self) -> None:
        """Test timeout warning error message format."""
        payload = TimeoutWarningPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            elapsed_ms=3000000,
            limit_ms=3600000,
            remaining_ms=600000,
        )
        result = _extract_error_message(EventType.TIMEOUT_WARNING, payload)
        assert result is not None
        assert "claude-code:" in result
        assert "until timeout" in result
        assert "limit:" in result
        # Check time formatting: 600000ms = 10m, 3600000ms = 1h
        assert "10m" in result
        assert "1h" in result

    def test_cli_crashed_recovered_format(self) -> None:
        """Test CLI crashed and recovered error message format."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="gemini",
            signal=15,
            attempt=2,
            max_attempts=3,
            recovered=True,
        )
        result = _extract_error_message(EventType.CLI_CRASHED, payload)
        assert result is not None
        assert "gemini crashed, resumed" in result
        assert "(2/3)" in result

    def test_cli_crashed_dead_with_signal_format(self) -> None:
        """Test CLI dead with signal error message format."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="claude-code",
            signal=9,
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = _extract_error_message(EventType.CLI_CRASHED, payload)
        assert result is not None
        assert "claude-code:" in result
        assert "3/3 failed" in result
        assert "SIGKILL" in result

    def test_cli_crashed_dead_with_exit_code_format(self) -> None:
        """Test CLI dead with exit code error message format."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="codex",
            exit_code=1,
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = _extract_error_message(EventType.CLI_CRASHED, payload)
        assert result is not None
        assert "codex:" in result
        assert "3/3 failed" in result
        assert "exit 1" in result

    def test_cli_crashed_dead_with_unknown_signal_format(self) -> None:
        """Test CLI dead with unknown signal shows signal number."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="gemini",
            signal=99,  # Unknown signal
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = _extract_error_message(EventType.CLI_CRASHED, payload)
        assert result is not None
        assert "signal 99" in result

    def test_cli_crashed_dead_unknown_reason_format(self) -> None:
        """Test CLI dead with unknown reason (no signal or exit code)."""
        payload = CLICrashedPayload(
            project="proj",
            epic=1,
            story="1-1",
            tool_name="gemini",
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = _extract_error_message(EventType.CLI_CRASHED, payload)
        assert result is not None
        assert "gemini:" in result
        assert "unknown" in result

    def test_fatal_error_format(self) -> None:
        """Test fatal error error message format."""
        payload = FatalErrorPayload(
            project="proj",
            epic=1,
            story="1-1",
            exception_type="KeyError",
            message="'current_story' not found",
            location="state.py:142",
        )
        result = _extract_error_message(EventType.FATAL_ERROR, payload)
        assert result is not None
        assert "bmad-assist:" in result
        assert "KeyError" in result
        assert "state.py:142" in result


class TestFormatNotificationInfrastructure:
    """Tests for format_notification with infrastructure events."""

    def test_timeout_warning_notification(self) -> None:
        """Test full timeout warning notification format."""
        payload = TimeoutWarningPayload(
            project="proj",
            epic=12,
            story="12-4",
            tool_name="claude-code",
            elapsed_ms=3000000,  # 50m
            limit_ms=3600000,  # 1h
            remaining_ms=600000,  # 10m
        )
        result = format_notification(EventType.TIMEOUT_WARNING, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # First line has ⚡ icon
        assert "⚡" in lines[0]
        assert "12.4" in lines[0]
        # Second line has error message
        assert "→" in lines[1]
        assert "claude-code:" in lines[1]
        assert "until timeout" in lines[1]

    def test_cli_recovered_notification(self) -> None:
        """Test CLI recovered notification format."""
        payload = CLICrashedPayload(
            project="proj",
            epic=12,
            story="12-4",
            tool_name="gemini",
            signal=15,
            attempt=2,
            max_attempts=3,
            recovered=True,
        )
        result = format_notification(EventType.CLI_RECOVERED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # First line has 🔄 icon
        assert "🔄" in lines[0]
        assert "12.4" in lines[0]
        # Second line has error message
        assert "→" in lines[1]
        assert "gemini crashed, resumed" in lines[1]
        assert "(2/3)" in lines[1]

    def test_cli_crashed_notification(self) -> None:
        """Test CLI crashed (dead) notification format."""
        payload = CLICrashedPayload(
            project="proj",
            epic=12,
            story="12-4",
            tool_name="claude-code",
            signal=9,
            attempt=3,
            max_attempts=3,
            recovered=False,
        )
        result = format_notification(EventType.CLI_CRASHED, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # First line has 💀 icon
        assert "💀" in lines[0]
        assert "12.4" in lines[0]
        # Second line has error message
        assert "→" in lines[1]
        assert "claude-code:" in lines[1]
        assert "3/3 failed" in lines[1]
        assert "SIGKILL" in lines[1]

    def test_fatal_error_notification(self) -> None:
        """Test fatal error notification format."""
        payload = FatalErrorPayload(
            project="proj",
            epic=12,
            story="12-4",
            exception_type="StateError",
            message="State file corrupted",
            location="state.py:142",
        )
        result = format_notification(EventType.FATAL_ERROR, payload)
        lines = result.split("\n")
        assert len(lines) == 2
        # First line has ☠️ icon
        assert "☠️" in lines[0]
        assert "12.4" in lines[0]
        # Second line has error message
        assert "→" in lines[1]
        assert "bmad-assist:" in lines[1]
        assert "StateError" in lines[1]
        assert "state.py:142" in lines[1]


class TestModuleExportsInfrastructure:
    """Tests for infrastructure event exports."""

    def test_infrastructure_payloads_exported(self) -> None:
        """Test infrastructure payload classes are exported."""
        from bmad_assist.notifications import (
            CLICrashedPayload,
            FatalErrorPayload,
            TimeoutWarningPayload,
        )

        assert TimeoutWarningPayload is not None
        assert CLICrashedPayload is not None
        assert FatalErrorPayload is not None

    def test_get_signal_name_exported(self) -> None:
        """Test get_signal_name is exported."""
        from bmad_assist.notifications import get_signal_name

        assert callable(get_signal_name)

    def test_signal_names_exported(self) -> None:
        """Test SIGNAL_NAMES is exported."""
        from bmad_assist.notifications import SIGNAL_NAMES

        assert isinstance(SIGNAL_NAMES, dict)
