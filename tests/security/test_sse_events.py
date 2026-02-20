"""Tests for security review SSE dashboard events.

Tests the emit_security_review_started, emit_security_review_completed,
and emit_security_review_failed functions from dashboard_events.py.
Verifies correct JSON output via stdout markers and no-op behavior when
BMAD_DASHBOARD_MODE is not set.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from bmad_assist.core.loop.dashboard_events import (
    DASHBOARD_EVENT_MARKER,
    emit_security_review_completed,
    emit_security_review_failed,
    emit_security_review_started,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_event(captured_out: str) -> dict:
    """Extract and parse the JSON payload from captured stdout."""
    assert captured_out.startswith(DASHBOARD_EVENT_MARKER)
    json_str = captured_out[len(DASHBOARD_EVENT_MARKER) :].strip()
    return json.loads(json_str)


# ---------------------------------------------------------------------------
# Tests WITH dashboard mode enabled
# ---------------------------------------------------------------------------


@pytest.fixture
def _enable_dashboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable dashboard mode for tests that need it."""
    monkeypatch.setenv("BMAD_DASHBOARD_MODE", "1")


class TestEmitSecurityReviewStarted:
    """Tests for emit_security_review_started."""

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_emits_correct_event_type(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event type must be 'security_review_started'."""
        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=42,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["type"] == "security_review_started"

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_run_id_and_sequence_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event must contain run_id and sequence_id fields."""
        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=7,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["run_id"] == "run-20260206-120000-abcd1234"
        assert data["sequence_id"] == 7

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_valid_timestamp(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event must include a valid ISO 8601 timestamp."""
        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=1,
        )

        data = _parse_event(capsys.readouterr().out)
        assert "timestamp" in data
        # Should not raise
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_data_field_is_empty_dict(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The 'data' payload for started event should be an empty dict."""
        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=1,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"] == {}


class TestEmitSecurityReviewCompleted:
    """Tests for emit_security_review_completed."""

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_emits_correct_event_type(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event type must be 'security_review_completed'."""
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=5,
            severity_summary={"HIGH": 2, "MEDIUM": 3},
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["type"] == "security_review_completed"

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_finding_count(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Data must include finding_count."""
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=12,
            severity_summary={"HIGH": 4, "MEDIUM": 5, "LOW": 3},
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"]["finding_count"] == 12

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_severity_summary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Data must include severity_summary dict."""
        severity = {"HIGH": 2, "MEDIUM": 3, "LOW": 1}
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=6,
            severity_summary=severity,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"]["severity_summary"] == severity

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_timed_out_defaults_to_false(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """timed_out should default to False when not specified."""
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=0,
            severity_summary={},
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"]["timed_out"] is False

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_timed_out_true(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """timed_out=True should appear in the event data."""
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=3,
            severity_summary={"HIGH": 1},
            timed_out=True,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"]["timed_out"] is True

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_valid_timestamp(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event must include a valid ISO 8601 timestamp."""
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=43,
            finding_count=0,
            severity_summary={},
        )

        data = _parse_event(capsys.readouterr().out)
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))


class TestEmitSecurityReviewFailed:
    """Tests for emit_security_review_failed."""

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_emits_correct_event_type(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event type must be 'security_review_failed'."""
        emit_security_review_failed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=44,
            error="Provider timeout after 300s",
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["type"] == "security_review_failed"

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_error_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Data must include the error message string."""
        error_msg = "Provider timeout after 300s"
        emit_security_review_failed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=44,
            error=error_msg,
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["data"]["error"] == error_msg

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_run_id_and_sequence_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event must contain run_id and sequence_id fields."""
        emit_security_review_failed(
            run_id="run-20260206-120000-ffffffff",
            sequence_id=99,
            error="some error",
        )

        data = _parse_event(capsys.readouterr().out)
        assert data["run_id"] == "run-20260206-120000-ffffffff"
        assert data["sequence_id"] == 99

    @pytest.mark.usefixtures("_enable_dashboard")
    def test_includes_valid_timestamp(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Event must include a valid ISO 8601 timestamp."""
        emit_security_review_failed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=44,
            error="fail",
        )

        data = _parse_event(capsys.readouterr().out)
        datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Tests WITHOUT dashboard mode (no-op behaviour)
# ---------------------------------------------------------------------------


class TestNoOpWithoutDashboardMode:
    """All three functions must be silent no-ops when BMAD_DASHBOARD_MODE != 1."""

    def test_started_is_noop(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """emit_security_review_started should produce no output."""
        monkeypatch.delenv("BMAD_DASHBOARD_MODE", raising=False)

        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=1,
        )

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_completed_is_noop(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """emit_security_review_completed should produce no output."""
        monkeypatch.delenv("BMAD_DASHBOARD_MODE", raising=False)

        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=2,
            finding_count=5,
            severity_summary={"HIGH": 5},
        )

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_failed_is_noop(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """emit_security_review_failed should produce no output."""
        monkeypatch.delenv("BMAD_DASHBOARD_MODE", raising=False)

        emit_security_review_failed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=3,
            error="should not appear",
        )

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_noop_when_dashboard_mode_is_zero(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All functions should be no-ops when BMAD_DASHBOARD_MODE=0."""
        monkeypatch.setenv("BMAD_DASHBOARD_MODE", "0")

        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234", sequence_id=1
        )
        emit_security_review_completed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=2,
            finding_count=0,
            severity_summary={},
        )
        emit_security_review_failed(
            run_id="run-20260206-120000-abcd1234",
            sequence_id=3,
            error="nope",
        )

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_noop_when_dashboard_mode_is_arbitrary_string(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Functions should only emit when BMAD_DASHBOARD_MODE is exactly '1'."""
        monkeypatch.setenv("BMAD_DASHBOARD_MODE", "yes")

        emit_security_review_started(
            run_id="run-20260206-120000-abcd1234", sequence_id=1
        )

        captured = capsys.readouterr()
        assert captured.out == ""
