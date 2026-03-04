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
