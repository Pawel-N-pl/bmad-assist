"""Unit tests for ToolCallGuard — LLM tool call watchdog.

Tests cover all three detection mechanisms (budget, file interaction, rate),
file path extraction, retry behavior, guard stats, and edge cases.
"""

import dataclasses
import subprocess
import threading
import time

import pytest

from bmad_assist.providers.tool_guard import (
    GuardStats,
    GuardVerdict,
    ToolCallGuard,
    start_guard_monitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_read(path: str = "/src/foo.py") -> tuple[str, dict]:
    """Create a Read tool call tuple."""
    return ("Read", {"file_path": path})


def _make_write(path: str = "/src/foo.py") -> tuple[str, dict]:
    """Create a Write tool call tuple."""
    return ("Write", {"file_path": path})


def _make_edit(path: str = "/src/foo.py") -> tuple[str, dict]:
    """Create an Edit tool call tuple."""
    return ("Edit", {"file_path": path})


def _make_bash(cmd: str = "ls") -> tuple[str, dict]:
    """Create a Bash tool call tuple."""
    return ("Bash", {"command": cmd})


# ---------------------------------------------------------------------------
# TestGuardBudgetCap — AC-1
# ---------------------------------------------------------------------------


class TestGuardBudgetCap:
    """Budget cap fires at N+1, mixed tool types."""

    def test_fires_at_budget_plus_one(self):
        guard = ToolCallGuard(max_total_calls=5, max_interactions_per_file=100, max_calls_per_minute=100)
        for i in range(5):
            v = guard.check(*_make_read(f"/file{i}.py"))
            assert v.allowed, f"Call {i+1} should be allowed"

        v = guard.check(*_make_read("/file5.py"))
        assert not v.allowed
        assert "budget_exceeded" in v.reason
        assert "would_be_6/5" in v.reason

    def test_stats_accurate_after_budget(self):
        guard = ToolCallGuard(max_total_calls=5, max_interactions_per_file=100, max_calls_per_minute=100)
        for i in range(5):
            guard.check(*_make_read(f"/file{i}.py"))

        guard.check(*_make_read("/denied.py"))
        stats = guard.get_stats()
        assert stats.total_calls == 5  # denied call NOT counted
        assert stats.terminated

    def test_mixed_tool_types_count_toward_budget(self):
        guard = ToolCallGuard(max_total_calls=4, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_read())
        guard.check(*_make_bash())
        guard.check("Grep", {"pattern": "foo"})
        guard.check("Glob", {"pattern": "*.py"})

        v = guard.check(*_make_write())
        assert not v.allowed
        assert "budget_exceeded" in v.reason

    def test_non_file_tools_count(self):
        guard = ToolCallGuard(max_total_calls=3, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_bash())
        guard.check("WebSearch", {"query": "test"})
        guard.check("Grep", {"pattern": "x"})

        v = guard.check(*_make_bash("echo"))
        assert not v.allowed


# ---------------------------------------------------------------------------
# TestGuardFileInteractionCap — AC-2
# ---------------------------------------------------------------------------


class TestGuardFileInteractionCap:
    """Per-file cap, read+write combined, different files independent."""

    def test_fires_at_cap_plus_one(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=3, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_write("/a.py"))
        guard.check(*_make_edit("/a.py"))

        v = guard.check(*_make_read("/a.py"))
        assert not v.allowed
        assert "file_interaction_cap" in v.reason
        assert "would_be_4/3" in v.reason

    def test_different_files_independent(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=2, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))

        # /b.py is separate
        v = guard.check(*_make_read("/b.py"))
        assert v.allowed

    def test_combined_read_write_edit(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=3, max_calls_per_minute=100)
        guard.check(*_make_read("/x.py"))
        guard.check(*_make_write("/x.py"))
        guard.check(*_make_edit("/x.py"))

        v = guard.check(*_make_read("/x.py"))
        assert not v.allowed

    def test_denied_call_not_counted(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=2, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))  # denied

        assert guard._file_interactions["/a.py"] == 2


# ---------------------------------------------------------------------------
# TestGuardRateCap — AC-3, AC-3b
# ---------------------------------------------------------------------------


class TestGuardRateCap:
    """Rate fires in burst, sliding window expires old calls."""

    def test_fires_in_burst(self):
        t = 1000.0
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=10,
            _clock=lambda: t,
        )
        for i in range(10):
            v = guard.check(*_make_bash(f"cmd{i}"))
            assert v.allowed

        v = guard.check(*_make_bash("overflow"))
        assert not v.allowed
        assert "rate_exceeded" in v.reason
        assert "would_be_11/10" in v.reason

    def test_sliding_window_expires(self):
        """AC-3b: Old calls expire after 60s."""
        t = [1000.0]
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=10,
            _clock=lambda: t[0],
        )
        # Make 9 calls at t=1000
        for _ in range(9):
            guard.check(*_make_bash())

        # Advance past 60s window
        t[0] = 1061.0

        # Should allow 9 more calls
        for _ in range(9):
            v = guard.check(*_make_bash())
            assert v.allowed

    def test_sliding_window_boundary(self):
        """TS-9: 59 calls at window end + more at next — no fixed-window bypass."""
        t = [1000.0]
        guard = ToolCallGuard(
            max_total_calls=1000,
            max_interactions_per_file=100,
            max_calls_per_minute=60,
            _clock=lambda: t[0],
        )
        # 59 calls at t=1000
        for _ in range(59):
            v = guard.check(*_make_bash())
            assert v.allowed

        # 1 more at t=1000 (total 60 in window)
        v = guard.check(*_make_bash())
        assert v.allowed

        # Next should fail (still within 60s window)
        t[0] = 1001.0
        v = guard.check(*_make_bash())
        assert not v.allowed


# ---------------------------------------------------------------------------
# TestGuardFilePathExtraction — AC-4, F8, F19, F20
# ---------------------------------------------------------------------------


class TestGuardFilePathExtraction:
    """File path extraction and normalization."""

    def test_dict_key_order_independence(self):
        """AC-4: Different key ordering produces same path."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=2, max_calls_per_minute=100)
        guard.check("Read", {"file_path": "/a.py", "limit": 50})
        guard.check("Read", {"limit": 50, "file_path": "/a.py"})

        assert guard._file_interactions["/a.py"] == 2

    def test_normpath_handles_dots(self):
        """F19/F8: ./foo/../bar normalizes."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Read", {"file_path": "/src/./foo/../bar.py"})

        assert "/src/bar.py" in guard._file_interactions

    def test_normpath_double_slashes(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Read", {"file_path": "/src//bar.py"})

        assert "/src/bar.py" in guard._file_interactions

    def test_vendor_tool_names(self):
        """F20: read_file, write_file, file_read recognized."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)

        guard.check("read_file", {"path": "/a.py"})
        assert "/a.py" in guard._file_interactions

        guard.check("file_write", {"file_path": "/b.py"})
        assert "/b.py" in guard._file_interactions

        guard.check("edit_file", {"file": "/c.py"})
        assert "/c.py" in guard._file_interactions

    def test_non_file_tools_no_file_tracking(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Bash", {"command": "ls"})
        guard.check("Grep", {"pattern": "foo"})
        guard.check("WebSearch", {"query": "test"})

        assert len(guard._file_interactions) == 0

    def test_missing_path_keys(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Read", {"content": "no path here"})

        assert len(guard._file_interactions) == 0

    def test_none_tool_input(self):
        """F19: None tool_input treated as non-file."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        v = guard.check("Read", None)
        assert v.allowed
        assert len(guard._file_interactions) == 0

    def test_file_path_priority(self):
        """file_path takes priority over path."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Read", {"file_path": "/primary.py", "path": "/secondary.py"})

        assert "/primary.py" in guard._file_interactions
        assert "/secondary.py" not in guard._file_interactions


# ---------------------------------------------------------------------------
# TestGuardRetry — AC-5
# ---------------------------------------------------------------------------


class TestGuardRetry:
    """reset_for_retry() preserves counters, clears rate deque."""

    def test_preserves_counters(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_bash())

        guard.reset_for_retry()

        assert guard._total_calls == 3
        assert guard._file_interactions["/a.py"] == 2
        assert len(guard._call_timestamps) == 0

    def test_clears_termination_state(self):
        guard = ToolCallGuard(max_total_calls=2, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_bash())
        guard.check(*_make_bash())
        guard.check(*_make_bash())  # triggers

        assert guard.is_triggered
        guard.reset_for_retry()
        assert not guard.is_triggered

    def test_counters_survive_retry(self):
        """TS-10: Budget/file counters survive retry, rate clears."""
        guard = ToolCallGuard(max_total_calls=5, max_interactions_per_file=100, max_calls_per_minute=100)
        for _ in range(3):
            guard.check(*_make_bash())

        guard.reset_for_retry()

        # Budget at 3, need 2 more to exhaust
        guard.check(*_make_bash())
        guard.check(*_make_bash())

        v = guard.check(*_make_bash())
        assert not v.allowed
        assert "would_be_6/5" in v.reason


# ---------------------------------------------------------------------------
# TestGuardStats — F17
# ---------------------------------------------------------------------------


class TestGuardStats:
    """get_stats() accuracy, terminated flag, serialization."""

    def test_stats_accuracy(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/b.py"))

        stats = guard.get_stats()
        assert stats.total_calls == 3
        assert stats.max_file == ("/a.py", 2)
        assert not stats.terminated
        assert stats.terminated_reason is None

    def test_terminated_stats(self):
        guard = ToolCallGuard(max_total_calls=1, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_bash())
        guard.check(*_make_bash())  # triggers

        stats = guard.get_stats()
        assert stats.terminated
        assert "budget_exceeded" in stats.terminated_reason

    def test_rate_triggered_flag(self):
        t = 1000.0
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=2,
            _clock=lambda: t,
        )
        guard.check(*_make_bash())
        guard.check(*_make_bash())
        guard.check(*_make_bash())  # triggers rate

        stats = guard.get_stats()
        assert stats.rate_triggered

    def test_dataclasses_asdict(self):
        """F17: GuardStats serializes via dataclasses.asdict()."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))

        stats = guard.get_stats()
        d = dataclasses.asdict(stats)

        assert isinstance(d, dict)
        assert d["total_calls"] == 1
        assert d["max_file"] == ("/a.py", 1)  # tuple preserved by asdict
        assert d["terminated"] is False

    def test_max_file_none_when_no_file_tools(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_bash())

        stats = guard.get_stats()
        assert stats.max_file is None


# ---------------------------------------------------------------------------
# TestGuardEdgeCases
# ---------------------------------------------------------------------------


class TestGuardEdgeCases:
    """Zero calls, empty inputs, is_triggered property."""

    def test_zero_calls(self):
        guard = ToolCallGuard()
        stats = guard.get_stats()
        assert stats.total_calls == 0
        assert not guard.is_triggered

    def test_already_terminated_returns_denied(self):
        guard = ToolCallGuard(max_total_calls=1, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_bash())
        guard.check(*_make_bash())  # triggers

        v = guard.check(*_make_bash())  # already terminated
        assert not v.allowed
        assert "already_terminated" in v.reason

    def test_empty_file_path_string(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check("Read", {"file_path": ""})
        assert len(guard._file_interactions) == 0

    def test_non_dict_tool_input(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        v = guard.check("Read", "not a dict")  # type: ignore[arg-type]
        assert v.allowed
        assert len(guard._file_interactions) == 0


# ---------------------------------------------------------------------------
# TestGuardCounting — F11
# ---------------------------------------------------------------------------


class TestGuardCounting:
    """Denied calls do NOT increment any counter."""

    def test_denied_budget_not_counted(self):
        guard = ToolCallGuard(max_total_calls=3, max_interactions_per_file=100, max_calls_per_minute=100)
        for _ in range(3):
            guard.check(*_make_bash())

        guard.check(*_make_bash())  # denied
        guard.check(*_make_bash())  # denied again

        assert guard._total_calls == 3

    def test_denied_file_cap_not_counted(self):
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=2, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))
        guard.check(*_make_read("/a.py"))  # denied

        assert guard._file_interactions["/a.py"] == 2
        assert guard._total_calls == 2

    def test_denied_rate_not_counted(self):
        t = 1000.0
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=2,
            _clock=lambda: t,
        )
        guard.check(*_make_bash())
        guard.check(*_make_bash())
        guard.check(*_make_bash())  # denied

        assert guard._total_calls == 2
        assert len(guard._call_timestamps) == 2


# ---------------------------------------------------------------------------
# TestGuardMonitorHelper — F6
# ---------------------------------------------------------------------------


class TestGuardMonitorHelper:
    """start_guard_monitor() kills on signal, cleans up."""

    def test_kills_on_signal(self):
        """Monitor kills process when kill_event is set."""
        process = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        kill_event = threading.Event()
        done_event = threading.Event()

        monitor = start_guard_monitor(process, kill_event, done_event)

        # Signal guard trigger
        kill_event.set()
        time.sleep(1.0)

        # Process should be dead
        assert process.poll() is not None

        done_event.set()
        monitor.join(timeout=2.0)
        assert not monitor.is_alive()

    def test_cleans_up_on_done(self):
        """Monitor exits cleanly when done_event is set."""
        process = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        kill_event = threading.Event()
        done_event = threading.Event()

        monitor = start_guard_monitor(process, kill_event, done_event)

        # Signal normal completion
        process.kill()
        process.wait()
        done_event.set()
        monitor.join(timeout=2.0)

        assert not monitor.is_alive()


# ---------------------------------------------------------------------------
# TestGuardInjectableClock — F21
# ---------------------------------------------------------------------------


class TestGuardInjectableClock:
    """Custom clock function for deterministic rate tests."""

    def test_controllable_clock(self):
        """TS-19: Injectable clock controls rate window."""
        t = [0.0]
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=5,
            _clock=lambda: t[0],
        )

        # 5 calls at t=0
        for _ in range(5):
            v = guard.check(*_make_bash())
            assert v.allowed

        # 6th at t=0 should fail
        v = guard.check(*_make_bash())
        assert not v.allowed

    def test_clock_advances_expire_window(self):
        t = [0.0]
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=100,
            max_calls_per_minute=3,
            _clock=lambda: t[0],
        )

        guard.check(*_make_bash())
        guard.check(*_make_bash())
        guard.check(*_make_bash())

        # Advance clock past 60s
        t[0] = 61.0

        # Window expired — should allow again
        v = guard.check(*_make_bash())
        assert v.allowed


# ---------------------------------------------------------------------------
# TestGuardRoundRobin — GL-8
# ---------------------------------------------------------------------------


class TestGuardRoundRobin:
    """Round-robin patterns caught by rate cap or budget."""

    def test_three_file_round_robin(self):
        """TS-6: A,B,C,A,B,C... caught by budget."""
        guard = ToolCallGuard(max_total_calls=10, max_interactions_per_file=100, max_calls_per_minute=100)
        files = ["/a.py", "/b.py", "/c.py"]

        allowed_count = 0
        for i in range(15):
            v = guard.check(*_make_read(files[i % 3]))
            if v.allowed:
                allowed_count += 1
            else:
                break

        assert allowed_count == 10

    def test_single_file_thrash(self):
        """TS-7: Tight loop on single file caught by file cap."""
        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=10, max_calls_per_minute=100)

        allowed_count = 0
        for _ in range(15):
            v = guard.check(*_make_read("/hot.py"))
            if v.allowed:
                allowed_count += 1
            else:
                break

        assert allowed_count == 10


# ---------------------------------------------------------------------------
# TestProviderResultIntegration
# ---------------------------------------------------------------------------


class TestProviderResultIntegration:
    """Guard stats in ProviderResult fields."""

    def test_guard_none_produces_none_fields(self):
        """AC-13: guard=None → termination_info=None, termination_reason=None."""
        from bmad_assist.providers.base import ProviderResult

        result = ProviderResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="test",
            command=("test",),
        )
        assert result.termination_info is None
        assert result.termination_reason is None

    def test_guard_stats_in_result(self):
        """Guard stats can be attached to ProviderResult."""
        from bmad_assist.providers.base import ProviderResult

        guard = ToolCallGuard(max_total_calls=100, max_interactions_per_file=100, max_calls_per_minute=100)
        guard.check(*_make_read("/a.py"))

        stats = guard.get_stats()
        result = ProviderResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="test",
            command=("test",),
            termination_info=dataclasses.asdict(stats),
            termination_reason=None,
        )
        assert result.termination_info["total_calls"] == 1


# ---------------------------------------------------------------------------
# TestPhaseEventIntegration
# ---------------------------------------------------------------------------


class TestPhaseEventIntegration:
    """termination_metadata field in PhaseEvent."""

    def test_phase_event_accepts_metadata(self):
        from datetime import UTC, datetime

        from bmad_assist.core.loop.run_tracking import PhaseEvent, PhaseEventType

        event = PhaseEvent(
            event_type=PhaseEventType.COMPLETED,
            phase="dev_story",
            timestamp=datetime.now(UTC),
            provider="claude",
            model="opus",
            termination_metadata={"total_calls": 42, "terminated": False},
        )
        assert event.termination_metadata["total_calls"] == 42

    def test_phase_event_none_by_default(self):
        from datetime import UTC, datetime

        from bmad_assist.core.loop.run_tracking import PhaseEvent, PhaseEventType

        event = PhaseEvent(
            event_type=PhaseEventType.STARTED,
            phase="dev_story",
            timestamp=datetime.now(UTC),
            provider="claude",
            model="opus",
        )
        assert event.termination_metadata is None


# ---------------------------------------------------------------------------
# Elevated per-file cap for budget-trimmed files (Fix #6)
# ---------------------------------------------------------------------------


class TestGuardElevatedFileCap:
    """Files in elevated_file_paths get a higher per-file interaction cap.

    Trimmed files were dropped from the prompt context, so the model must
    read them via tool calls. A flat cap punishes that legitimate use.
    """

    def test_elevated_file_uses_higher_cap(self) -> None:
        """A file in elevated_file_paths can exceed the base cap."""
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=3,
            max_calls_per_minute=100,
            elevated_file_paths={"/src/big.py"},
            max_interactions_per_file_elevated=6,
        )
        # 6 reads on big.py — would exceed base cap of 3, must succeed
        # because big.py is in the elevated set.
        for i in range(6):
            v = guard.check(*_make_read("/src/big.py"))
            assert v.allowed, f"Call {i+1} on elevated file should be allowed"
        # 7th call exceeds elevated cap — must fail
        v = guard.check(*_make_read("/src/big.py"))
        assert not v.allowed
        assert "elevated" in v.reason
        assert "would_be_7/6" in v.reason

    def test_non_elevated_file_uses_base_cap(self) -> None:
        """Non-elevated files still hit the base cap."""
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=2,
            max_calls_per_minute=100,
            elevated_file_paths={"/src/elevated.py"},
            max_interactions_per_file_elevated=10,
        )
        guard.check(*_make_read("/src/normal.py"))
        guard.check(*_make_read("/src/normal.py"))
        v = guard.check(*_make_read("/src/normal.py"))
        assert not v.allowed
        assert "base" in v.reason
        assert "would_be_3/2" in v.reason

    def test_auto_elevated_cap_is_double_base(self) -> None:
        """When max_interactions_per_file_elevated is None, default = 2x base."""
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=4,
            max_calls_per_minute=100,
            elevated_file_paths={"/src/auto.py"},
            # max_interactions_per_file_elevated NOT specified
        )
        assert guard.max_interactions_per_file_elevated == 8
        for _ in range(8):
            assert guard.check(*_make_read("/src/auto.py")).allowed
        v = guard.check(*_make_read("/src/auto.py"))
        assert not v.allowed
        assert "would_be_9/8" in v.reason

    def test_explicit_elevated_below_base_is_clamped_up(self) -> None:
        """Elevated cap can't be lower than base — clamped up at construction."""
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=10,
            max_calls_per_minute=100,
            elevated_file_paths={"/x.py"},
            max_interactions_per_file_elevated=2,  # absurdly low
        )
        # Should be silently clamped to base (10), never below.
        assert guard.max_interactions_per_file_elevated == 10

    def test_empty_elevated_set_does_not_log_elevation(self) -> None:
        """No elevated paths → constructor logs the legacy single-cap message."""
        # Just make sure construction succeeds and uses base cap.
        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=3,
            max_calls_per_minute=100,
            elevated_file_paths=set(),
        )
        assert guard.elevated_file_paths == set()
        # Default elevated cap still computed but unused.
        assert guard.max_interactions_per_file_elevated == 6

    def test_elevated_paths_normalized_to_realpath(self) -> None:
        """Elevated paths are normalized via realpath at construction.

        Ensures lookups match whatever path the file tools pass in (which
        the guard also normalizes the same way).
        """
        import os

        guard = ToolCallGuard(
            max_total_calls=100,
            max_interactions_per_file=2,
            max_calls_per_minute=100,
            # Pass relative-style path with redundant components
            elevated_file_paths={"/src/./../src/foo.py"},
        )
        # Realpath resolves to /src/foo.py
        assert os.path.realpath("/src/foo.py") in guard.elevated_file_paths

    def test_elevated_cap_validation_rejects_zero(self) -> None:
        """max_interactions_per_file_elevated < 1 raises."""
        with pytest.raises(ValueError, match="elevated"):
            ToolCallGuard(
                max_total_calls=100,
                max_interactions_per_file=5,
                max_calls_per_minute=100,
                elevated_file_paths={"/x.py"},
                max_interactions_per_file_elevated=0,
            )


class TestToolGuardConfigDefaults:
    """ToolGuardConfig defaults include the new elevated-cap field."""

    def test_default_max_interactions_per_file_is_40(self) -> None:
        """Default file cap is 40 (matches code, not stale "15" docstring)."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig()
        assert cfg.max_interactions_per_file == 40

    def test_default_trimmed_cap_is_none_meaning_auto(self) -> None:
        """trimmed cap default is None (interpreted as 2x base via helper)."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig()
        assert cfg.max_interactions_per_file_trimmed is None
        assert cfg.get_elevated_file_cap() == 80  # 2x default 40

    def test_explicit_trimmed_cap_used(self) -> None:
        """Explicit trimmed cap is returned by helper."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig(max_interactions_per_file_trimmed=120)
        assert cfg.get_elevated_file_cap() == 120


class TestToolGuardConfigPerPhaseBudget:
    """ToolGuardConfig.get_max_total_calls honors per-phase overrides."""

    def test_no_override_returns_global_default(self) -> None:
        """No per_phase config → global max_total_calls applies."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig()
        assert cfg.get_max_total_calls("dev_story") == 300  # default
        assert cfg.get_max_total_calls("code_review") == 300

    def test_explicit_phase_override_used(self) -> None:
        """Per-phase override replaces global for that phase only."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig(
            max_total_calls=300,
            max_total_calls_per_phase={"dev_story": 600, "create_story": 400},
        )
        assert cfg.get_max_total_calls("dev_story") == 600
        assert cfg.get_max_total_calls("create_story") == 400
        # Other phases still use global default
        assert cfg.get_max_total_calls("code_review") == 300
        assert cfg.get_max_total_calls("validate_story") == 300

    def test_hyphen_normalized_to_underscore(self) -> None:
        """``dev-story`` and ``dev_story`` are treated as the same phase."""
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig(
            max_total_calls_per_phase={"dev_story": 800},
        )
        assert cfg.get_max_total_calls("dev-story") == 800
        assert cfg.get_max_total_calls("dev_story") == 800

    def test_zero_or_negative_override_falls_back_to_default(self) -> None:
        """Misconfigured 0 or negative → fall back to global default.

        Protects the run from a yaml typo that would otherwise crash the
        guard constructor (which requires max_total_calls >= 1).
        """
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig(
            max_total_calls=300,
            max_total_calls_per_phase={"dev_story": 0, "atdd": -5},
        )
        assert cfg.get_max_total_calls("dev_story") == 300
        assert cfg.get_max_total_calls("atdd") == 300

    def test_per_phase_budget_flows_through_to_guard_construction(
        self,
    ) -> None:
        """ToolCallGuard constructed with the per-phase resolved value.

        Regression guard for base.py wiring: phase-aware caller uses
        ``get_max_total_calls(phase)`` not the raw ``max_total_calls``.
        """
        from bmad_assist.core.config.models.features import ToolGuardConfig

        cfg = ToolGuardConfig(
            max_total_calls=300,
            max_total_calls_per_phase={"dev_story": 700},
        )
        # Simulate what base.py does
        dev_story_cap = cfg.get_max_total_calls("dev_story")
        review_cap = cfg.get_max_total_calls("code_review")

        dev_guard = ToolCallGuard(max_total_calls=dev_story_cap)
        review_guard = ToolCallGuard(max_total_calls=review_cap)

        assert dev_guard.max_total_calls == 700
        assert review_guard.max_total_calls == 300
