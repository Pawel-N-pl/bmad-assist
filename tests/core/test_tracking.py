"""Tests for agent tracking (core/tracking.py)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.tracking import (
    _format_cli_params,
    reset_tracking_file,
    track_agent_end,
    track_agent_start,
)


@pytest.fixture()
def tracking_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enable tracking (without params) and provide a tmp project path."""
    monkeypatch.setenv("BMAD_TRACK_AGENTS", "1")
    monkeypatch.delenv("BMAD_TRACK_AGENTS_PARAMS", raising=False)
    return tmp_path


@pytest.fixture()
def tracking_env_with_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enable tracking WITH params and provide a tmp project path."""
    monkeypatch.setenv("BMAD_TRACK_AGENTS", "1")
    monkeypatch.setenv("BMAD_TRACK_AGENTS_PARAMS", "1")
    return tmp_path


@pytest.fixture()
def csv_path(tracking_env: Path) -> Path:
    return tracking_env / ".bmad-assist" / "agent-tracking.csv"


# ---------------------------------------------------------------------------
# _format_cli_params
# ---------------------------------------------------------------------------


class TestFormatCliParams:
    def test_none(self):
        assert _format_cli_params(None) == ""

    def test_empty(self):
        assert _format_cli_params({}) == ""

    def test_skips_none_and_false(self):
        result = _format_cli_params({"a": None, "b": False, "c": 42})
        assert result == "--c 42"

    def test_bool_true_flag(self):
        assert _format_cli_params({"verbose": True}) == "--verbose"

    def test_list_values(self):
        result = _format_cli_params({"allowed_tools": ["TodoWrite", "Read"]})
        assert result == "--allowed_tools TodoWrite,Read"

    def test_path_value(self):
        result = _format_cli_params({"cwd": Path("/tmp/proj")})
        assert result == "--cwd /tmp/proj"

    def test_sorted_keys(self):
        result = _format_cli_params({"z": 1, "a": 2})
        assert result == "--a 2 --z 1"


# ---------------------------------------------------------------------------
# reset_tracking_file
# ---------------------------------------------------------------------------


class TestResetTrackingFile:
    def test_deletes_existing_file(self, tracking_env: Path):
        # Create a tracking file first
        track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", "p")
        csv = tracking_env / ".bmad-assist" / "agent-tracking.csv"
        assert csv.exists()
        reset_tracking_file(tracking_env)
        assert not csv.exists()

    def test_noop_if_no_file(self, tmp_path: Path):
        """No error when file doesn't exist."""
        reset_tracking_file(tmp_path)  # should not raise

    def test_fresh_run_after_reset(self, tracking_env: Path):
        """After reset, new writes create a fresh file with header."""
        track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", "old")
        reset_tracking_file(tracking_env)
        track_agent_start(tracking_env, "2", "2.1", "dev", "claude", "opus", "new")
        csv = tracking_env / ".bmad-assist" / "agent-tracking.csv"
        content = csv.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2  # header + 1 row (not 3)
        assert "old" not in content


# ---------------------------------------------------------------------------
# track_agent_start
# ---------------------------------------------------------------------------


class TestTrackAgentStart:
    def test_disabled_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BMAD_TRACK_AGENTS", raising=False)
        result = track_agent_start(tmp_path, "1", "1.1", "dev", "claude", "opus", "hi")
        assert result is None
        assert not (tmp_path / ".bmad-assist" / "agent-tracking.csv").exists()

    def test_returns_datetime(self, tracking_env: Path):
        result = track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", "prompt")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_writes_header_and_row(self, tracking_env: Path, csv_path: Path):
        track_agent_start(tracking_env, "1", "1.2", "dev_story", "claude", "opus", "test prompt")
        content = csv_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
        # Verify header
        assert lines[0].startswith('"date"')
        assert '"cli_params"' in lines[0]
        # Verify row
        reader = csv.reader(io.StringIO(lines[1]))
        row = next(reader)
        assert row[1] == "1"  # epic
        assert row[2] == "1.2"  # story
        assert row[3] == "dev_story"  # phase
        assert row[4] == "claude"  # provider
        assert row[5] == "opus"  # model
        assert row[8] == "START"  # event

    def test_context_tokens(self, tracking_env: Path, csv_path: Path):
        prompt = "x" * 400  # 400 // 4 = 100 tokens
        track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", prompt)
        reader = csv.reader(io.StringIO(csv_path.read_text().split("\n")[1]))
        row = next(reader)
        # Header: date,epic,story,phase,provider,model,cli_params,
        #         context_tokens(7),event(8),elapsed(9)
        assert row[7] == "100"

    def test_timezone_in_date(self, tracking_env: Path, csv_path: Path):
        track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", "p")
        reader = csv.reader(io.StringIO(csv_path.read_text().split("\n")[1]))
        row = next(reader)
        date_str = row[0]
        assert "+00:00" in date_str or "Z" in date_str

    def test_cli_params_empty_without_params_flag(self, tracking_env: Path, csv_path: Path):
        """cli_params column is empty when BMAD_TRACK_AGENTS_PARAMS is not set."""
        track_agent_start(
            tracking_env, "1", "1.1", "dev", "claude", "opus", "p",
            cli_params={"model": "opus", "timeout": 300},
        )
        reader = csv.reader(io.StringIO(csv_path.read_text().split("\n")[1]))
        row = next(reader)
        assert row[6] == ""  # cli_params empty

    def test_cli_params_recorded_with_params_flag(
        self, tracking_env_with_params: Path,
    ):
        """cli_params column populated when BMAD_TRACK_AGENTS_PARAMS is set."""
        csv_file = tracking_env_with_params / ".bmad-assist" / "agent-tracking.csv"
        track_agent_start(
            tracking_env_with_params, "1", "1.1", "dev", "claude", "opus", "p",
            cli_params={"model": "opus", "timeout": 300},
        )
        reader = csv.reader(io.StringIO(csv_file.read_text().split("\n")[1]))
        row = next(reader)
        assert "--model opus" in row[6]
        assert "--timeout 300" in row[6]


# ---------------------------------------------------------------------------
# track_agent_end
# ---------------------------------------------------------------------------


class TestTrackAgentEnd:
    def test_disabled_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BMAD_TRACK_AGENTS", raising=False)
        start = datetime.now(UTC)
        track_agent_end(tmp_path, "1", "1.1", "dev", "claude", "opus", "p", start)
        assert not (tmp_path / ".bmad-assist" / "agent-tracking.csv").exists()

    def test_none_start_noop(self, tracking_env: Path, csv_path: Path):
        track_agent_end(tracking_env, "1", "1.1", "dev", "claude", "opus", "p", None)
        assert not csv_path.exists()

    def test_writes_end_with_elapsed(self, tracking_env: Path, csv_path: Path):
        start = datetime.now(UTC)
        # Simulate some elapsed time via mock
        future = start.replace(second=start.second + 5) if start.second < 55 else start
        with patch("bmad_assist.core.tracking.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            track_agent_end(
                tracking_env, "1", "1.1", "dev", "claude", "opus", "p", start,
            )
        content = csv_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        reader = csv.reader(io.StringIO(lines[1]))
        row = next(reader)
        assert row[8] == "END"
        # elapsed should be a number string
        assert row[9].isdigit()

    def test_cli_params_empty_without_params_flag(self, tracking_env: Path, csv_path: Path):
        """cli_params empty for END row when BMAD_TRACK_AGENTS_PARAMS not set."""
        start = datetime.now(UTC)
        track_agent_end(
            tracking_env, "1", "1.1", "dev", "claude", "opus", "p", start,
            cli_params={"model": "opus"},
        )
        reader = csv.reader(io.StringIO(csv_path.read_text().split("\n")[1]))
        row = next(reader)
        assert row[6] == ""

    def test_cli_params_recorded_with_params_flag(
        self, tracking_env_with_params: Path,
    ):
        """cli_params populated for END when BMAD_TRACK_AGENTS_PARAMS is set."""
        csv_file = tracking_env_with_params / ".bmad-assist" / "agent-tracking.csv"
        start = datetime.now(UTC)
        track_agent_end(
            tracking_env_with_params, "1", "1.1", "dev", "claude", "opus", "p",
            start, cli_params={"model": "opus"},
        )
        reader = csv.reader(io.StringIO(csv_file.read_text().split("\n")[1]))
        row = next(reader)
        assert "--model opus" in row[6]


# ---------------------------------------------------------------------------
# Paired START/END
# ---------------------------------------------------------------------------


class TestStartEndPairing:
    def test_paired_rows(self, tracking_env: Path, csv_path: Path):
        start = track_agent_start(
            tracking_env, "2", "2.1", "validate_story", "opencode", "gemini", "prompt",
        )
        track_agent_end(
            tracking_env, "2", "2.1", "validate_story", "opencode", "gemini", "prompt", start,
        )
        content = csv_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 3  # header + START + END
        reader = csv.reader(io.StringIO("\n".join(lines[1:])))
        rows = list(reader)
        assert rows[0][8] == "START"
        assert rows[0][9] == ""
        assert rows[1][8] == "END"
        assert int(rows[1][9]) >= 0

    def test_header_always_has_cli_params_column(self, tracking_env: Path, csv_path: Path):
        """Header includes cli_params even when params tracking is off."""
        track_agent_start(tracking_env, "1", "1.1", "dev", "claude", "opus", "p")
        header = csv_path.read_text().split("\n")[0]
        assert '"cli_params"' in header


# ---------------------------------------------------------------------------
# Concurrency safety (basic: no interleaving)
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_multiple_appends_no_corruption(self, tracking_env: Path, csv_path: Path):
        """Multiple sequential writes produce valid CSV."""
        for i in range(10):
            track_agent_start(
                tracking_env, "1", str(i), "dev", "claude", "opus", f"prompt{i}",
            )
        content = csv_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 11  # header + 10 rows
        # All rows parseable
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 11


# ---------------------------------------------------------------------------
# CSV escaping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase coverage: verify all tracked phases produce valid rows
# ---------------------------------------------------------------------------


class TestPhaseCoverage:
    """Verify tracking works for all instrumented phases."""

    ALL_PHASES = [
        # base.py execute() phases
        "create_story",
        "dev_story",
        "retrospective",
        # synthesis phases
        "validate_story_synthesis",
        "code_review_synthesis",
        # orchestrator phases (per-provider)
        "validate_story",
        "code_review",
        # QA phases
        "qa_plan_generate",
        "qa_plan_execute",
        "qa_plan_execute_batch",
        "qa_summary",
        # testarch phases
        "atdd",
        "test_review",
        "trace",
    ]

    @pytest.mark.parametrize("phase", ALL_PHASES)
    def test_phase_produces_valid_start_end(
        self, tracking_env: Path, phase: str,
    ):
        """Each phase name produces parseable START/END CSV rows."""
        csv_file = tracking_env / ".bmad-assist" / "agent-tracking.csv"
        start = track_agent_start(
            tracking_env, "1", "1.1", phase, "claude", "opus", "test",
            cli_params={"model": "opus", "timeout": 300},
        )
        track_agent_end(
            tracking_env, "1", "1.1", phase, "claude", "opus", "test", start,
            cli_params={"model": "opus", "timeout": 300},
        )
        content = csv_file.read_text()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 3  # header + START + END
        assert rows[1][3] == phase
        assert rows[1][8] == "START"
        assert rows[2][3] == phase
        assert rows[2][8] == "END"
        assert rows[2][9].isdigit()
        # Clean up for next parametrize run
        csv_file.unlink()

    def test_multiple_phases_in_sequence(self, tracking_env: Path):
        """Simulate a real run with multiple phases appending to same file."""
        csv_file = tracking_env / ".bmad-assist" / "agent-tracking.csv"
        phases_to_write = ["create_story", "dev_story", "validate_story", "validate_story"]
        for phase in phases_to_write:
            s = track_agent_start(
                tracking_env, "1", "1.1", phase, "claude", "opus", "p",
            )
            track_agent_end(
                tracking_env, "1", "1.1", phase, "claude", "opus", "p", s,
            )
        content = csv_file.read_text()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        # header + 4 START + 4 END = 9
        assert len(rows) == 9
        # All rows parseable with 10 columns
        for row in rows:
            assert len(row) == 10

    def test_qa_phases_with_empty_story(self, tracking_env: Path):
        """QA phases use empty string for story — verify that works."""
        csv_file = tracking_env / ".bmad-assist" / "agent-tracking.csv"
        s = track_agent_start(
            tracking_env, "1", "", "qa_plan_generate", "claude", "opus", "p",
        )
        track_agent_end(
            tracking_env, "1", "", "qa_plan_generate", "claude", "opus", "p", s,
        )
        reader = csv.reader(io.StringIO(csv_file.read_text()))
        rows = list(reader)
        assert rows[1][2] == ""  # story is empty
        assert rows[1][3] == "qa_plan_generate"


# ---------------------------------------------------------------------------
# CSV escaping
# ---------------------------------------------------------------------------


class TestCsvEscaping:
    def test_quotes_in_cli_params(
        self, tracking_env_with_params: Path,
    ):
        csv_file = tracking_env_with_params / ".bmad-assist" / "agent-tracking.csv"
        track_agent_start(
            tracking_env_with_params, "1", "1.1", "dev", "claude", "opus", "p",
            cli_params={"settings_file": Path('/tmp/a "b" c.json')},
        )
        content = csv_file.read_text()
        # Should be parseable despite quotes in value
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2
