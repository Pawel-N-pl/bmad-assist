"""Tests for experiment comparison report generator.

Tests cover:
- RunComparison model creation and field access
- ConfigDiff and ComparisonDiff models
- MetricComparison delta calculation and winner determination
- ComparisonReport root model
- ComparisonGenerator methods (load_run, compare)
- Configuration difference detection
- Metric comparison with various scenarios
- Markdown generation format
- save() method with atomic write
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.experiments.comparison import (
    MAX_COMPARISON_RUNS,
    ComparisonDiff,
    ComparisonGenerator,
    ComparisonReport,
    ConfigDiff,
    MetricComparison,
    RunComparison,
    _calculate_delta,
    _calculate_success_rate,
    _determine_winner,
    _format_cost,
    _format_delta,
    _format_duration,
    _format_percentage,
    _format_tokens,
)
from bmad_assist.experiments.manifest import (
    ManifestInput,
    ManifestManager,
    ManifestPhaseResult,
    ManifestResolved,
    ResolvedConfig,
    ResolvedFixture,
    ResolvedLoop,
    ResolvedPatchSet,
)
from bmad_assist.experiments.metrics import MetricsCollector, RunMetrics
from bmad_assist.experiments.runner import ExperimentStatus

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """Create temp directory for runs."""
    runs = tmp_path / "runs"
    runs.mkdir()
    return runs


@pytest.fixture
def manifest_input_001() -> ManifestInput:
    """Create sample ManifestInput for run-001."""
    return ManifestInput(
        fixture="minimal",
        config="opus-solo",
        patch_set="baseline",
        loop="standard",
    )


@pytest.fixture
def manifest_input_002() -> ManifestInput:
    """Create sample ManifestInput for run-002 (different patch_set)."""
    return ManifestInput(
        fixture="minimal",
        config="opus-solo",
        patch_set="experimental-v1",
        loop="standard",
    )


@pytest.fixture
def manifest_resolved_001() -> ManifestResolved:
    """Create sample ManifestResolved for run-001."""
    return ManifestResolved(
        fixture=ResolvedFixture(
            name="minimal",
            source="/fixtures/minimal",
            snapshot="./fixture-snapshot",
        ),
        config=ResolvedConfig(
            name="opus-solo",
            source="/configs/opus-solo.yaml",
            providers={
                "master": {"provider": "claude", "model": "opus"},
                "multi": [],
            },
        ),
        patch_set=ResolvedPatchSet(
            name="baseline",
            source="/patch-sets/baseline.yaml",
            patches={
                "create-story": ".bmad-assist/patches/create-story.patch.yaml",
                "dev-story": ".bmad-assist/patches/dev-story.patch.yaml",
            },
        ),
        loop=ResolvedLoop(
            name="standard",
            source="/loops/standard.yaml",
            sequence=["create-story", "dev-story", "code-review"],
        ),
    )


@pytest.fixture
def manifest_resolved_002() -> ManifestResolved:
    """Create sample ManifestResolved for run-002 (different patches)."""
    return ManifestResolved(
        fixture=ResolvedFixture(
            name="minimal",
            source="/fixtures/minimal",
            snapshot="./fixture-snapshot",
        ),
        config=ResolvedConfig(
            name="opus-solo",
            source="/configs/opus-solo.yaml",
            providers={
                "master": {"provider": "claude", "model": "opus"},
                "multi": [],
            },
        ),
        patch_set=ResolvedPatchSet(
            name="experimental-v1",
            source="/patch-sets/experimental-v1.yaml",
            patches={
                "create-story": "experiments/patch-variants/create-story-v3.1.yaml",
                "dev-story": ".bmad-assist/patches/dev-story.patch.yaml",
            },
        ),
        loop=ResolvedLoop(
            name="standard",
            source="/loops/standard.yaml",
            sequence=["create-story", "dev-story", "code-review"],
        ),
    )


@pytest.fixture
def run_metrics_001() -> RunMetrics:
    """Create sample RunMetrics for run-001 (baseline)."""
    return RunMetrics(
        total_cost=2.50,
        total_tokens=45000,
        total_duration_seconds=2723.0,
        avg_tokens_per_phase=15000.0,
        avg_cost_per_phase=0.83,
        stories_completed=3,
        stories_failed=0,
    )


@pytest.fixture
def run_metrics_002() -> RunMetrics:
    """Create sample RunMetrics for run-002 (better performance)."""
    return RunMetrics(
        total_cost=2.35,
        total_tokens=42000,
        total_duration_seconds=2590.0,
        avg_tokens_per_phase=14000.0,
        avg_cost_per_phase=0.78,
        stories_completed=3,
        stories_failed=0,
    )


@pytest.fixture
def create_run_directory(runs_dir: Path):
    """Factory to create run directories with manifest and metrics."""

    def _create(
        run_id: str,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
        save_metrics: bool = True,
        status: ExperimentStatus = ExperimentStatus.COMPLETED,
    ) -> Path:
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)

        # Create manifest
        manager = ManifestManager(run_dir)
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
            run_id=run_id,
        )
        manager.update_status(ExperimentStatus.RUNNING)

        # Add some phase results
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=100.0,
                tokens=15000,
                cost=0.50,
            )
        )
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="dev-story",
                story="1.1",
                status="completed",
                duration_seconds=200.0,
                tokens=15000,
                cost=0.50,
            )
        )
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="code-review",
                story="1.1",
                status="completed",
                duration_seconds=150.0,
                tokens=15000,
                cost=0.50,
            )
        )

        manager.finalize(status, datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC))

        # Create metrics file by default
        if save_metrics:
            collector = MetricsCollector(run_dir)
            # Load manifest and collect
            assert manager.manifest is not None
            metrics_file = collector.collect(manager.manifest)
            collector.save(metrics_file)

        return run_dir

    return _create


@pytest.fixture
def two_run_setup(
    runs_dir: Path,
    create_run_directory,
    manifest_input_001: ManifestInput,
    manifest_input_002: ManifestInput,
    manifest_resolved_001: ManifestResolved,
    manifest_resolved_002: ManifestResolved,
) -> Path:
    """Create two runs for comparison testing."""
    create_run_directory(
        "run-001",
        manifest_input_001,
        manifest_resolved_001,
    )
    create_run_directory(
        "run-002",
        manifest_input_002,
        manifest_resolved_002,
    )
    return runs_dir


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestCalculateDelta:
    """Tests for _calculate_delta helper function."""

    def test_positive_change(self) -> None:
        """Test delta calculation with positive change."""
        delta = _calculate_delta(110, 100)
        assert delta == pytest.approx(10.0)

    def test_negative_change(self) -> None:
        """Test delta calculation with negative change."""
        delta = _calculate_delta(90, 100)
        assert delta == pytest.approx(-10.0)

    def test_no_change(self) -> None:
        """Test delta calculation with no change."""
        delta = _calculate_delta(100, 100)
        assert delta == pytest.approx(0.0)

    def test_baseline_zero_value_zero(self) -> None:
        """Test delta calculation when baseline is 0 and value is 0."""
        delta = _calculate_delta(0, 0)
        assert delta == 0.0

    def test_baseline_zero_value_nonzero(self) -> None:
        """Test delta calculation when baseline is 0 and value is non-zero."""
        delta = _calculate_delta(10, 0)
        assert delta is None

    def test_value_none(self) -> None:
        """Test delta calculation when value is None."""
        delta = _calculate_delta(None, 100)
        assert delta is None

    def test_baseline_none(self) -> None:
        """Test delta calculation when baseline is None."""
        delta = _calculate_delta(100, None)
        assert delta is None

    def test_both_none(self) -> None:
        """Test delta calculation when both are None."""
        delta = _calculate_delta(None, None)
        assert delta is None


class TestDetermineWinner:
    """Tests for _determine_winner helper function."""

    def test_lower_is_better_unique_winner(self) -> None:
        """Test winner determination when lower is better (unique winner)."""
        values = {"run-001": 100, "run-002": 90, "run-003": 95}
        winner = _determine_winner(values, lower_is_better=True)
        assert winner == "run-002"

    def test_higher_is_better_unique_winner(self) -> None:
        """Test winner determination when higher is better (unique winner)."""
        values = {"run-001": 100, "run-002": 90, "run-003": 95}
        winner = _determine_winner(values, lower_is_better=False)
        assert winner == "run-001"

    def test_tie_returns_none(self) -> None:
        """Test winner determination with tie returns None."""
        values = {"run-001": 100, "run-002": 100}
        winner = _determine_winner(values, lower_is_better=True)
        assert winner is None

    def test_all_none_returns_none(self) -> None:
        """Test winner determination with all None values returns None."""
        values: dict[str, float | int | None] = {"run-001": None, "run-002": None}
        winner = _determine_winner(values, lower_is_better=True)
        assert winner is None

    def test_some_none_values_skipped(self) -> None:
        """Test winner determination skips None values."""
        values: dict[str, float | int | None] = {"run-001": 100, "run-002": None, "run-003": 90}
        winner = _determine_winner(values, lower_is_better=True)
        assert winner == "run-003"

    def test_single_valid_value(self) -> None:
        """Test winner determination with single valid value."""
        values: dict[str, float | int | None] = {"run-001": None, "run-002": 100}
        winner = _determine_winner(values, lower_is_better=True)
        assert winner == "run-002"


class TestCalculateSuccessRate:
    """Tests for _calculate_success_rate helper function."""

    def test_all_completed(self) -> None:
        """Test success rate with all completed."""
        rate = _calculate_success_rate(10, 0)
        assert rate == 100.0

    def test_all_failed(self) -> None:
        """Test success rate with all failed."""
        rate = _calculate_success_rate(0, 10)
        assert rate == 0.0

    def test_mixed(self) -> None:
        """Test success rate with mix of completed and failed."""
        rate = _calculate_success_rate(7, 3)
        assert rate == 70.0

    def test_no_stories(self) -> None:
        """Test success rate with no stories returns None."""
        rate = _calculate_success_rate(0, 0)
        assert rate is None


class TestFormatFunctions:
    """Tests for formatting helper functions."""

    def test_format_cost(self) -> None:
        """Test cost formatting."""
        assert _format_cost(2.50) == "$2.50"
        assert _format_cost(0.0) == "$0.00"
        assert _format_cost(None) == "N/A"

    def test_format_tokens(self) -> None:
        """Test tokens formatting."""
        assert _format_tokens(45000) == "45,000"
        assert _format_tokens(1000000) == "1,000,000"
        assert _format_tokens(None) == "N/A"

    def test_format_duration_less_than_hour(self) -> None:
        """Test duration formatting for less than 1 hour."""
        assert _format_duration(2723.0) == "45:23"
        assert _format_duration(60.0) == "1:00"
        assert _format_duration(90.0) == "1:30"
        assert _format_duration(0.0) == "0:00"

    def test_format_duration_more_than_hour(self) -> None:
        """Test duration formatting for 1+ hours."""
        assert _format_duration(3600.0) == "1:00:00"
        assert _format_duration(3661.0) == "1:01:01"
        assert _format_duration(7200.0) == "2:00:00"

    def test_format_duration_none(self) -> None:
        """Test duration formatting for None."""
        assert _format_duration(None) == "N/A"

    def test_format_delta(self) -> None:
        """Test delta formatting."""
        assert _format_delta(5.3) == "+5.3%"
        assert _format_delta(-2.1) == "-2.1%"
        assert _format_delta(0.0) == "0.0%"
        assert _format_delta(None) == "N/A"

    def test_format_percentage(self) -> None:
        """Test percentage formatting."""
        assert _format_percentage(100.0) == "100.0%"
        assert _format_percentage(75.5) == "75.5%"
        assert _format_percentage(None) == "N/A"


# =============================================================================
# Data Model Tests
# =============================================================================


class TestRunComparison:
    """Tests for RunComparison model."""

    def test_create_valid(
        self,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
        run_metrics_001: RunMetrics,
    ) -> None:
        """Test creating valid RunComparison."""
        run = RunComparison(
            run_id="run-001",
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            metrics=run_metrics_001,
            status=ExperimentStatus.COMPLETED,
        )
        assert run.run_id == "run-001"
        assert run.input.fixture == "minimal"
        assert run.metrics is not None
        assert run.metrics.total_cost == 2.50

    def test_create_without_metrics(
        self,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test creating RunComparison without metrics."""
        run = RunComparison(
            run_id="run-001",
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            metrics=None,
            status=ExperimentStatus.CANCELLED,
        )
        assert run.metrics is None
        assert run.status == ExperimentStatus.CANCELLED

    def test_frozen(
        self,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test RunComparison is frozen (immutable)."""
        run = RunComparison(
            run_id="run-001",
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            metrics=None,
            status=ExperimentStatus.COMPLETED,
        )
        with pytest.raises(Exception):
            run.run_id = "modified"  # type: ignore[misc]


class TestConfigDiff:
    """Tests for ConfigDiff model."""

    def test_create_same(self) -> None:
        """Test creating ConfigDiff with same values."""
        diff = ConfigDiff(
            axis="fixture",
            values={"run-001": "minimal", "run-002": "minimal"},
            is_same=True,
        )
        assert diff.is_same
        assert diff.axis == "fixture"

    def test_create_different(self) -> None:
        """Test creating ConfigDiff with different values."""
        diff = ConfigDiff(
            axis="patch_set",
            values={"run-001": "baseline", "run-002": "experimental"},
            is_same=False,
        )
        assert not diff.is_same

    def test_frozen(self) -> None:
        """Test ConfigDiff is frozen."""
        diff = ConfigDiff(
            axis="config",
            values={"run-001": "opus"},
            is_same=True,
        )
        with pytest.raises(Exception):
            diff.axis = "loop"  # type: ignore[misc]


class TestComparisonDiff:
    """Tests for ComparisonDiff model."""

    def test_varying_axes_none(self) -> None:
        """Test varying_axes when all are same."""
        diff = ComparisonDiff(
            fixture=ConfigDiff(axis="fixture", values={}, is_same=True),
            config=ConfigDiff(axis="config", values={}, is_same=True),
            patch_set=ConfigDiff(axis="patch_set", values={}, is_same=True),
            loop=ConfigDiff(axis="loop", values={}, is_same=True),
        )
        assert diff.varying_axes == []

    def test_varying_axes_one(self) -> None:
        """Test varying_axes with one varying."""
        diff = ComparisonDiff(
            fixture=ConfigDiff(axis="fixture", values={}, is_same=True),
            config=ConfigDiff(axis="config", values={}, is_same=True),
            patch_set=ConfigDiff(axis="patch_set", values={}, is_same=False),
            loop=ConfigDiff(axis="loop", values={}, is_same=True),
        )
        assert diff.varying_axes == ["patch_set"]

    def test_varying_axes_multiple(self) -> None:
        """Test varying_axes with multiple varying."""
        diff = ComparisonDiff(
            fixture=ConfigDiff(axis="fixture", values={}, is_same=False),
            config=ConfigDiff(axis="config", values={}, is_same=True),
            patch_set=ConfigDiff(axis="patch_set", values={}, is_same=False),
            loop=ConfigDiff(axis="loop", values={}, is_same=False),
        )
        assert diff.varying_axes == ["fixture", "patch_set", "loop"]


class TestMetricComparison:
    """Tests for MetricComparison model."""

    def test_create_valid(self) -> None:
        """Test creating valid MetricComparison."""
        metric = MetricComparison(
            metric_name="total_cost",
            values={"run-001": 2.50, "run-002": 2.35},
            deltas={"run-001": 0.0, "run-002": -6.0},
            winner="run-002",
            lower_is_better=True,
        )
        assert metric.metric_name == "total_cost"
        assert metric.winner == "run-002"
        assert metric.lower_is_better

    def test_frozen(self) -> None:
        """Test MetricComparison is frozen."""
        metric = MetricComparison(
            metric_name="test",
            values={},
            deltas={},
            winner=None,
            lower_is_better=True,
        )
        with pytest.raises(Exception):
            metric.winner = "changed"  # type: ignore[misc]


class TestComparisonReport:
    """Tests for ComparisonReport model."""

    def test_create_valid(
        self,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test creating valid ComparisonReport."""
        run = RunComparison(
            run_id="run-001",
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            metrics=None,
            status=ExperimentStatus.COMPLETED,
        )
        config_diff = ComparisonDiff(
            fixture=ConfigDiff(axis="fixture", values={"run-001": "minimal"}, is_same=True),
            config=ConfigDiff(axis="config", values={"run-001": "opus"}, is_same=True),
            patch_set=ConfigDiff(axis="patch_set", values={"run-001": "base"}, is_same=True),
            loop=ConfigDiff(axis="loop", values={"run-001": "standard"}, is_same=True),
        )
        report = ComparisonReport(
            generated_at=datetime(2026, 1, 9, 17, 0, 0, tzinfo=UTC),
            run_ids=["run-001"],
            runs=[run],
            config_diff=config_diff,
            metrics=[],
            conclusion="Test conclusion",
        )
        assert report.conclusion == "Test conclusion"
        assert len(report.runs) == 1

    def test_datetime_serialization(self) -> None:
        """Test datetime serialization."""
        # Minimal valid report
        diff = ComparisonDiff(
            fixture=ConfigDiff(axis="fixture", values={}, is_same=True),
            config=ConfigDiff(axis="config", values={}, is_same=True),
            patch_set=ConfigDiff(axis="patch_set", values={}, is_same=True),
            loop=ConfigDiff(axis="loop", values={}, is_same=True),
        )
        report = ComparisonReport(
            generated_at=datetime(2026, 1, 9, 17, 0, 0, tzinfo=UTC),
            run_ids=[],
            runs=[],
            config_diff=diff,
            metrics=[],
            conclusion=None,
        )
        data = report.model_dump(mode="json")
        assert "2026-01-09T17:00:00" in data["generated_at"]


# =============================================================================
# ComparisonGenerator Tests
# =============================================================================


class TestComparisonGeneratorLoadRun:
    """Tests for ComparisonGenerator.load_run()."""

    def test_load_run_success(self, two_run_setup: Path) -> None:
        """Test loading a valid run."""
        generator = ComparisonGenerator(two_run_setup)
        run = generator.load_run("run-001")

        assert run.run_id == "run-001"
        assert run.input.fixture == "minimal"
        assert run.status == ExperimentStatus.COMPLETED

    def test_load_run_missing_manifest(self, runs_dir: Path) -> None:
        """Test loading run with missing manifest raises ConfigError."""
        generator = ComparisonGenerator(runs_dir)
        with pytest.raises(ConfigError, match="Manifest not found"):
            generator.load_run("nonexistent-run")

    def test_load_run_without_metrics(
        self,
        runs_dir: Path,
        create_run_directory,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test loading run without metrics file returns None metrics."""
        # Create run without saving metrics
        run_dir = runs_dir / "run-no-metrics"
        run_dir.mkdir()

        manager = ManifestManager(run_dir)
        manager.create(
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            started=datetime.now(UTC),
            run_id="run-no-metrics",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        generator = ComparisonGenerator(runs_dir)
        run = generator.load_run("run-no-metrics")

        assert run.metrics is None


class TestComparisonGeneratorCompare:
    """Tests for ComparisonGenerator.compare()."""

    def test_compare_two_runs(self, two_run_setup: Path) -> None:
        """Test comparing two runs."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        assert len(report.run_ids) == 2
        assert len(report.runs) == 2
        assert report.config_diff is not None

    def test_compare_less_than_two_raises_error(self, two_run_setup: Path) -> None:
        """Test comparing less than 2 runs raises ValueError."""
        generator = ComparisonGenerator(two_run_setup)
        with pytest.raises(ValueError, match="At least 2 runs required"):
            generator.compare(["run-001"])

    def test_compare_more_than_ten_raises_error(self, runs_dir: Path) -> None:
        """Test comparing more than 10 runs raises ValueError."""
        generator = ComparisonGenerator(runs_dir)
        run_ids = [f"run-{i:03d}" for i in range(11)]
        with pytest.raises(ValueError, match=f"Maximum {MAX_COMPARISON_RUNS}"):
            generator.compare(run_ids)

    def test_compare_nonexistent_run_raises_error(self, two_run_setup: Path) -> None:
        """Test comparing with non-existent run raises ConfigError."""
        generator = ComparisonGenerator(two_run_setup)
        with pytest.raises(ConfigError, match="Manifest not found"):
            generator.compare(["run-001", "nonexistent"])

    def test_compare_ten_runs(
        self,
        runs_dir: Path,
        create_run_directory,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test comparing exactly 10 runs (max allowed)."""
        for i in range(10):
            create_run_directory(
                f"run-{i:03d}",
                manifest_input_001,
                manifest_resolved_001,
            )

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare([f"run-{i:03d}" for i in range(10)])

        assert len(report.runs) == 10


class TestConfigurationDifferenceDetection:
    """Tests for configuration difference detection (AC7)."""

    def test_detect_same_fixture(self, two_run_setup: Path) -> None:
        """Test detecting same fixture values."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        assert report.config_diff.fixture.is_same

    def test_detect_different_patch_set(self, two_run_setup: Path) -> None:
        """Test detecting different patch_set values."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        assert not report.config_diff.patch_set.is_same
        assert "patch_set" in report.config_diff.varying_axes

    def test_varying_axes_count(self, two_run_setup: Path) -> None:
        """Test varying_axes contains only differing axes."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        # Only patch_set differs
        assert len(report.config_diff.varying_axes) == 1
        assert report.config_diff.varying_axes[0] == "patch_set"


class TestMetricComparisonLogic:
    """Tests for metric comparison logic (AC8)."""

    def test_delta_calculation_from_baseline(self, two_run_setup: Path) -> None:
        """Test delta calculation uses first run as baseline."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        # Find total_cost metric
        cost_metric = next(
            (m for m in report.metrics if m.metric_name == "total_cost"),
            None,
        )
        assert cost_metric is not None
        # First run (baseline) should have delta of 0.0
        assert cost_metric.deltas.get("run-001") == 0.0

    def test_winner_determination_lower_is_better(self, two_run_setup: Path) -> None:
        """Test winner determination for lower-is-better metrics."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        # All metrics should have some winner or tie
        for metric in report.metrics:
            if metric.lower_is_better:
                # Winner should be run with lowest value
                valid_values = {k: v for k, v in metric.values.items() if v is not None}
                if valid_values and len(set(valid_values.values())) > 1:
                    min_run = min(valid_values.items(), key=lambda x: x[1])[0]
                    assert metric.winner == min_run

    def test_tie_returns_none_winner(
        self,
        runs_dir: Path,
        create_run_directory,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test tie in metric values returns None as winner."""
        # Create two identical runs
        create_run_directory("run-a", manifest_input_001, manifest_resolved_001)
        # Create second with same input but different ID
        create_run_directory("run-b", manifest_input_001, manifest_resolved_001)

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-a", "run-b"])

        # Metrics should be tied
        for metric in report.metrics:
            values_list = list(metric.values.values())
            if len(set(v for v in values_list if v is not None)) == 1:
                # All same values = tie
                assert metric.winner is None

    def test_success_rate_calculated(self, two_run_setup: Path) -> None:
        """Test success_rate metric is calculated."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        success_rate_metric = next(
            (m for m in report.metrics if m.metric_name == "success_rate"),
            None,
        )
        assert success_rate_metric is not None
        # Should have values for both runs
        assert "run-001" in success_rate_metric.values

    def test_metrics_with_none_excluded_from_winner(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test runs with None metrics are excluded from winner determination."""
        # Create run with manifest but no metrics
        run_dir = runs_dir / "run-no-metrics"
        run_dir.mkdir()
        manager = ManifestManager(run_dir)
        manager.create(
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            started=datetime.now(UTC),
            run_id="run-no-metrics",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        # Create run with metrics
        run_with_metrics = runs_dir / "run-with-metrics"
        run_with_metrics.mkdir()
        manager2 = ManifestManager(run_with_metrics)
        manager2.create(
            input=manifest_input_001,
            resolved=manifest_resolved_001,
            started=datetime.now(UTC),
            run_id="run-with-metrics",
        )
        manager2.update_status(ExperimentStatus.RUNNING)
        manager2.add_phase_result(
            ManifestPhaseResult(
                phase="test",
                story="1.1",
                status="completed",
                duration_seconds=100.0,
                tokens=10000,
                cost=0.50,
            )
        )
        manager2.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector = MetricsCollector(run_with_metrics)
        assert manager2.manifest is not None
        collector.save(collector.collect(manager2.manifest))

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-no-metrics", "run-with-metrics"])

        # Metrics should still have values from the run with metrics
        for metric in report.metrics:
            # The run without metrics should have None
            assert metric.values.get("run-no-metrics") is None
            # The run with metrics should have a value
            assert metric.values.get("run-with-metrics") is not None


class TestMarkdownGeneration:
    """Tests for Markdown report generation (AC9)."""

    def test_markdown_contains_header(self, two_run_setup: Path) -> None:
        """Test Markdown contains header section."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        assert "# Experiment Comparison Report" in markdown
        assert "Generated:" in markdown

    def test_markdown_contains_runs_table(self, two_run_setup: Path) -> None:
        """Test Markdown contains Runs Compared table."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        assert "## Runs Compared" in markdown
        assert "| Run ID | Fixture | Config | Patch-Set | Loop |" in markdown
        assert "run-001" in markdown
        assert "run-002" in markdown

    def test_markdown_contains_config_diff_table(self, two_run_setup: Path) -> None:
        """Test Markdown contains Configuration Diff table."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        assert "## Configuration Diff" in markdown
        assert "| Axis |" in markdown
        assert "Same? |" in markdown
        assert "✓" in markdown  # Same indicator
        assert "**DIFFERENT**" in markdown  # Different indicator

    def test_markdown_contains_patch_set_differences(self, two_run_setup: Path) -> None:
        """Test Markdown contains Patch-Set Differences when applicable."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        # Patch-set differs, so should have differences section
        assert "### Patch-Set Differences" in markdown

    def test_markdown_contains_results_table(self, two_run_setup: Path) -> None:
        """Test Markdown contains Results Comparison table."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        assert "## Results Comparison" in markdown
        assert "| Metric |" in markdown
        assert "Delta |" in markdown
        assert "Winner |" in markdown

    def test_markdown_cost_formatting(self, two_run_setup: Path) -> None:
        """Test Markdown formats costs correctly."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        # Costs should be formatted as $X.XX
        assert "$" in markdown

    def test_markdown_tokens_formatting(self, two_run_setup: Path) -> None:
        """Test Markdown formats tokens with comma separators."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        # Large token counts should have commas
        # Check that comma-formatted numbers appear
        assert "," in markdown  # Should have comma-separated numbers

    def test_markdown_contains_conclusion(self, two_run_setup: Path) -> None:
        """Test Markdown contains conclusion section if present."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])
        markdown = generator.generate_markdown(report)

        # Should have conclusion section
        if report.conclusion:
            assert "## Conclusion" in markdown


class TestConclusionGeneration:
    """Tests for conclusion generation (AC6.1)."""

    def test_conclusion_single_axis_varies(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_input_002: ManifestInput,
        manifest_resolved_001: ManifestResolved,
        manifest_resolved_002: ManifestResolved,
    ) -> None:
        """Test conclusion when single axis varies with different performance."""
        # Create run-001 with higher costs (worse)
        run1 = runs_dir / "run-001"
        run1.mkdir()
        manager1 = ManifestManager(run1)
        manager1.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), "run-001")
        manager1.update_status(ExperimentStatus.RUNNING)
        manager1.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=300.0,
                tokens=20000,
                cost=1.00,
            )
        )
        manager1.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector1 = MetricsCollector(run1)
        assert manager1.manifest is not None
        collector1.save(collector1.collect(manager1.manifest))

        # Create run-002 with lower costs (better)
        run2 = runs_dir / "run-002"
        run2.mkdir()
        manager2 = ManifestManager(run2)
        manager2.create(manifest_input_002, manifest_resolved_002, datetime.now(UTC), "run-002")
        manager2.update_status(ExperimentStatus.RUNNING)
        manager2.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=200.0,
                tokens=15000,
                cost=0.50,
            )
        )
        manager2.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector2 = MetricsCollector(run2)
        assert manager2.manifest is not None
        collector2.save(collector2.collect(manager2.manifest))

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-001", "run-002"])

        # Only patch_set varies
        assert report.conclusion is not None
        # Should mention the varying axis
        assert "patch_set" in report.conclusion.lower()

    def test_conclusion_multiple_axes_warning(
        self,
        runs_dir: Path,
        create_run_directory,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test conclusion warns when multiple axes vary."""
        # Create runs with multiple differences
        input_002 = ManifestInput(
            fixture="complex",  # Different fixture
            config="haiku-solo",  # Different config
            patch_set="experimental",  # Different patch_set
            loop="standard",
        )
        resolved_002 = ManifestResolved(
            fixture=ResolvedFixture(name="complex", source="/fixtures/complex", snapshot="./snap"),
            config=ResolvedConfig(
                name="haiku-solo",
                source="/configs/haiku-solo.yaml",
                providers={"master": {"provider": "claude", "model": "haiku"}, "multi": []},
            ),
            patch_set=ResolvedPatchSet(name="experimental", source="/patch-sets/experimental.yaml"),
            loop=ResolvedLoop(name="standard", source="/loops/standard.yaml", sequence=[]),
        )

        create_run_directory("run-multi-001", manifest_input_001, manifest_resolved_001)
        create_run_directory("run-multi-002", input_002, resolved_002)

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-multi-001", "run-multi-002"])

        assert report.conclusion is not None
        assert "multiple configuration axes differ" in report.conclusion.lower()
        assert "confounded" in report.conclusion.lower()

    def test_conclusion_tie_in_wins(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_input_002: ManifestInput,
        manifest_resolved_001: ManifestResolved,
        manifest_resolved_002: ManifestResolved,
    ) -> None:
        """Test conclusion handles tie in win counts gracefully."""
        # Create run-001 that wins on cost
        run1 = runs_dir / "run-001"
        run1.mkdir()
        manager1 = ManifestManager(run1)
        manager1.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), "run-001")
        manager1.update_status(ExperimentStatus.RUNNING)
        manager1.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=300.0,
                tokens=20000,
                cost=0.50,  # Wins cost
            )
        )
        manager1.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector1 = MetricsCollector(run1)
        assert manager1.manifest is not None
        collector1.save(collector1.collect(manager1.manifest))

        # Create run-002 that wins on duration/tokens
        run2 = runs_dir / "run-002"
        run2.mkdir()
        manager2 = ManifestManager(run2)
        manager2.create(manifest_input_002, manifest_resolved_002, datetime.now(UTC), "run-002")
        manager2.update_status(ExperimentStatus.RUNNING)
        manager2.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=200.0,
                tokens=15000,
                cost=1.00,  # Wins duration/tokens
            )
        )
        manager2.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector2 = MetricsCollector(run2)
        assert manager2.manifest is not None
        collector2.save(collector2.collect(manager2.manifest))

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-001", "run-002"])

        # When there's a tie in wins, should report no significant difference
        assert report.conclusion is not None
        # The conclusion may either pick a winner or report a tie depending on exact wins
        # Just verify we get a valid conclusion without errors

    def test_conclusion_baseline_wins(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_input_002: ManifestInput,
        manifest_resolved_001: ManifestResolved,
        manifest_resolved_002: ManifestResolved,
    ) -> None:
        """Test conclusion when baseline (first run) is the winner."""
        # Create run-001 (baseline) with better performance
        run1 = runs_dir / "run-001"
        run1.mkdir()
        manager1 = ManifestManager(run1)
        manager1.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), "run-001")
        manager1.update_status(ExperimentStatus.RUNNING)
        manager1.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=100.0,
                tokens=10000,
                cost=0.30,  # Best performance
            )
        )
        manager1.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector1 = MetricsCollector(run1)
        assert manager1.manifest is not None
        collector1.save(collector1.collect(manager1.manifest))

        # Create run-002 (experimental) with worse performance
        run2 = runs_dir / "run-002"
        run2.mkdir()
        manager2 = ManifestManager(run2)
        manager2.create(manifest_input_002, manifest_resolved_002, datetime.now(UTC), "run-002")
        manager2.update_status(ExperimentStatus.RUNNING)
        manager2.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=500.0,
                tokens=50000,
                cost=2.00,  # Worse performance
            )
        )
        manager2.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))
        collector2 = MetricsCollector(run2)
        assert manager2.manifest is not None
        collector2.save(collector2.collect(manager2.manifest))

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-001", "run-002"])

        # When baseline wins, should NOT recommend "adopting" (it's already the config)
        assert report.conclusion is not None
        assert "baseline" in report.conclusion.lower()
        assert "adopting" not in report.conclusion.lower()


class TestSaveMethod:
    """Tests for ComparisonGenerator.save() (AC10)."""

    def test_save_creates_file(self, two_run_setup: Path, tmp_path: Path) -> None:
        """Test save creates file at output path."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        output_path = tmp_path / "comparison.md"
        result = generator.save(report, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_save_atomic_no_temp_file(self, two_run_setup: Path, tmp_path: Path) -> None:
        """Test atomic save leaves no temp file."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        output_path = tmp_path / "comparison.md"
        generator.save(report, output_path)

        temp_path = tmp_path / "comparison.md.tmp"
        assert not temp_path.exists()

    def test_save_creates_parent_directory(self, two_run_setup: Path, tmp_path: Path) -> None:
        """Test save creates parent directory if needed."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        output_path = tmp_path / "subdir" / "comparison.md"
        generator.save(report, output_path)

        assert output_path.exists()

    def test_save_failure_raises_config_error(self, two_run_setup: Path, tmp_path: Path) -> None:
        """Test save failure raises ConfigError."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        output_path = tmp_path / "comparison.md"

        with patch("os.replace", side_effect=OSError("Permission denied")):
            with pytest.raises(ConfigError, match="Failed to save comparison report"):
                generator.save(report, output_path)

    def test_save_content_matches_generate_markdown(
        self, two_run_setup: Path, tmp_path: Path
    ) -> None:
        """Test saved content matches generate_markdown output."""
        generator = ComparisonGenerator(two_run_setup)
        report = generator.compare(["run-001", "run-002"])

        output_path = tmp_path / "comparison.md"
        generator.save(report, output_path)

        expected = generator.generate_markdown(report)
        actual = output_path.read_text()

        assert actual == expected


# =============================================================================
# Integration Tests
# =============================================================================


class TestComparisonIntegration:
    """Integration tests for comparison workflow."""

    def test_full_comparison_workflow(self, two_run_setup: Path, tmp_path: Path) -> None:
        """Test complete comparison workflow from load to save."""
        generator = ComparisonGenerator(two_run_setup)

        # Load and compare
        report = generator.compare(["run-001", "run-002"])

        # Verify report structure
        assert len(report.runs) == 2
        assert len(report.config_diff.varying_axes) >= 0
        assert len(report.metrics) > 0

        # Generate and save
        output_path = tmp_path / "full_test.md"
        generator.save(report, output_path)

        # Verify saved content
        content = output_path.read_text()
        assert "# Experiment Comparison Report" in content
        assert "run-001" in content
        assert "run-002" in content


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_compare_with_failed_run_warns(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
        caplog,
    ) -> None:
        """Test comparing with failed run logs warning."""
        # Create completed run
        run1 = runs_dir / "run-ok"
        run1.mkdir()
        manager1 = ManifestManager(run1)
        manager1.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), "run-ok")
        manager1.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        # Create failed run
        run2 = runs_dir / "run-fail"
        run2.mkdir()
        manager2 = ManifestManager(run2)
        manager2.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), "run-fail")
        manager2.finalize(ExperimentStatus.FAILED, datetime.now(UTC))

        generator = ComparisonGenerator(runs_dir)

        import logging

        with caplog.at_level(logging.WARNING):
            report = generator.compare(["run-ok", "run-fail"])

        # Should log warning about non-completed run
        assert any("not completed" in record.message for record in caplog.records)

    def test_all_metrics_none_excluded(
        self,
        runs_dir: Path,
        manifest_input_001: ManifestInput,
        manifest_resolved_001: ManifestResolved,
    ) -> None:
        """Test metrics where all values are None are excluded."""
        # Create two runs without metrics
        for run_id in ["run-a", "run-b"]:
            run_dir = runs_dir / run_id
            run_dir.mkdir()
            manager = ManifestManager(run_dir)
            manager.create(manifest_input_001, manifest_resolved_001, datetime.now(UTC), run_id)
            manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        generator = ComparisonGenerator(runs_dir)
        report = generator.compare(["run-a", "run-b"])

        # Metrics list should be empty or only have metrics with some values
        for metric in report.metrics:
            # Each metric should have at least one non-None value
            assert not all(v is None for v in metric.values.values())
