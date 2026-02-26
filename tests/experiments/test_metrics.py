"""Tests for experiment metrics collection system.

Tests cover:
- PhaseMetrics model creation and conversion
- RunMetrics aggregation with various scenarios
- MetricsFile serialization/deserialization
- MetricsCollector methods (collect, save, load)
- Edge cases (None values, empty results, division by zero)
- Integration with ManifestManager.update_metrics()
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.experiments.manifest import (
    ManifestInput,
    ManifestManager,
    ManifestMetrics,
    ManifestPhaseResult,
    ManifestResolved,
    ManifestResults,
    ResolvedConfig,
    ResolvedFixture,
    ResolvedLoop,
    ResolvedPatchSet,
    RunManifest,
)
from bmad_assist.experiments.metrics import (
    MetricsCollector,
    MetricsFile,
    PhaseMetrics,
    RunMetrics,
)
from bmad_assist.experiments.runner import ExperimentStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """Create temporary run directory."""
    run = tmp_path / "runs" / "test-run-001"
    run.mkdir(parents=True)
    return run


@pytest.fixture
def manifest_input() -> ManifestInput:
    """Create sample ManifestInput."""
    return ManifestInput(
        fixture="minimal",
        config="opus-solo",
        patch_set="baseline",
        loop="standard",
    )


@pytest.fixture
def manifest_resolved() -> ManifestResolved:
    """Create sample ManifestResolved."""
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
        ),
        loop=ResolvedLoop(
            name="standard",
            source="/loops/standard.yaml",
            sequence=["create-story", "dev-story", "code-review"],
        ),
    )


@pytest.fixture
def manifest_with_full_metrics(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with phase results including full metrics."""
    return RunManifest(
        run_id="run-2026-01-09-001",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
        status=ExperimentStatus.COMPLETED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=ManifestResults(
            stories_attempted=3,
            stories_completed=3,
            stories_failed=0,
            phases=[
                ManifestPhaseResult(
                    phase="create-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=245.5,
                    tokens=12340,
                    cost=0.45,
                ),
                ManifestPhaseResult(
                    phase="dev-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=320.1,
                    tokens=18000,
                    cost=0.65,
                ),
                ManifestPhaseResult(
                    phase="code-review",
                    story="1.1",
                    status="completed",
                    duration_seconds=180.3,
                    tokens=14890,
                    cost=0.54,
                ),
            ],
        ),
        metrics=None,
    )


@pytest.fixture
def manifest_with_missing_metrics(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with some phases missing tokens/cost."""
    return RunManifest(
        run_id="run-2026-01-09-002",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
        status=ExperimentStatus.COMPLETED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=ManifestResults(
            stories_attempted=3,
            stories_completed=2,
            stories_failed=1,
            phases=[
                ManifestPhaseResult(
                    phase="create-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=245.5,
                    tokens=None,  # Missing
                    cost=None,  # Missing
                ),
                ManifestPhaseResult(
                    phase="dev-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=320.1,
                    tokens=18000,
                    cost=0.65,
                ),
                ManifestPhaseResult(
                    phase="code-review",
                    story="1.1",
                    status="failed",
                    duration_seconds=180.3,
                    tokens=None,
                    cost=None,
                    error="Provider timeout",
                ),
            ],
        ),
        metrics=None,
    )


@pytest.fixture
def manifest_with_all_none_metrics(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with all tokens/cost as None (MVP scenario)."""
    return RunManifest(
        run_id="run-2026-01-09-003",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
        status=ExperimentStatus.COMPLETED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=ManifestResults(
            stories_attempted=2,
            stories_completed=2,
            stories_failed=0,
            phases=[
                ManifestPhaseResult(
                    phase="create-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=100.0,
                    tokens=None,
                    cost=None,
                ),
                ManifestPhaseResult(
                    phase="dev-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=200.0,
                    tokens=None,
                    cost=None,
                ),
            ],
        ),
        metrics=None,
    )


@pytest.fixture
def manifest_with_mixed_phases(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with mix of completed, failed, and skipped phases."""
    return RunManifest(
        run_id="run-2026-01-09-004",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
        status=ExperimentStatus.COMPLETED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=ManifestResults(
            stories_attempted=3,  # 2 completed + 1 failed (skipped not counted)
            stories_completed=2,
            stories_failed=1,
            phases=[
                ManifestPhaseResult(
                    phase="create-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=100.0,
                    tokens=10000,
                    cost=0.30,
                ),
                ManifestPhaseResult(
                    phase="validate",
                    story="1.1",
                    status="skipped",
                    duration_seconds=0.0,
                    tokens=None,
                    cost=None,
                ),
                ManifestPhaseResult(
                    phase="dev-story",
                    story="1.1",
                    status="completed",
                    duration_seconds=200.0,
                    tokens=20000,
                    cost=0.60,
                ),
                ManifestPhaseResult(
                    phase="code-review",
                    story="1.1",
                    status="failed",
                    duration_seconds=50.0,
                    tokens=5000,
                    cost=0.15,
                    error="Model error",
                ),
            ],
        ),
        metrics=None,
    )


@pytest.fixture
def manifest_empty_results(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with no results (empty run)."""
    return RunManifest(
        run_id="run-2026-01-09-005",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 15, 30, 1, tzinfo=UTC),
        status=ExperimentStatus.CANCELLED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=None,
        metrics=None,
    )


@pytest.fixture
def manifest_zero_completed(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create manifest with zero completed phases (edge case)."""
    return RunManifest(
        run_id="run-2026-01-09-006",
        started=datetime(2026, 1, 9, 15, 30, 0, tzinfo=UTC),
        completed=datetime(2026, 1, 9, 15, 35, 0, tzinfo=UTC),
        status=ExperimentStatus.FAILED,
        input=manifest_input,
        resolved=manifest_resolved,
        results=ManifestResults(
            stories_attempted=1,
            stories_completed=0,
            stories_failed=1,
            phases=[
                ManifestPhaseResult(
                    phase="create-story",
                    story="1.1",
                    status="failed",
                    duration_seconds=60.0,
                    tokens=5000,
                    cost=0.15,
                    error="Failed immediately",
                ),
            ],
        ),
        metrics=None,
    )


# =============================================================================
# PhaseMetrics Tests
# =============================================================================


class TestPhaseMetrics:
    """Tests for PhaseMetrics model."""

    def test_create_valid(self) -> None:
        """Test creating valid PhaseMetrics."""
        phase = PhaseMetrics(
            phase="create-story",
            story="1.1",
            status="completed",
            duration_seconds=45.5,
            tokens=12340,
            cost=0.45,
            error=None,
        )
        assert phase.phase == "create-story"
        assert phase.story == "1.1"
        assert phase.status == "completed"
        assert phase.tokens == 12340
        assert phase.cost == 0.45

    def test_create_with_none_metrics(self) -> None:
        """Test creating PhaseMetrics with None tokens and cost."""
        phase = PhaseMetrics(
            phase="dev-story",
            story="1.2",
            status="completed",
            duration_seconds=100.0,
            tokens=None,
            cost=None,
        )
        assert phase.tokens is None
        assert phase.cost is None

    def test_create_failed_with_error(self) -> None:
        """Test creating failed PhaseMetrics with error message."""
        phase = PhaseMetrics(
            phase="code-review",
            story="1.3",
            status="failed",
            duration_seconds=30.0,
            tokens=5000,
            cost=0.15,
            error="Provider timeout",
        )
        assert phase.status == "failed"
        assert phase.error == "Provider timeout"

    def test_frozen(self) -> None:
        """Test PhaseMetrics is frozen (immutable)."""
        phase = PhaseMetrics(
            phase="test",
            story="1",
            status="completed",
            duration_seconds=1.0,
        )
        with pytest.raises(Exception):
            phase.phase = "modified"  # type: ignore[misc]

    def test_from_phase_result(self) -> None:
        """Test converting ManifestPhaseResult to PhaseMetrics."""
        result = ManifestPhaseResult(
            phase="create-story",
            story="1.1",
            status="completed",
            duration_seconds=245.5,
            tokens=12340,
            cost=0.45,
            error=None,
        )
        phase = PhaseMetrics.from_phase_result(result)

        assert phase.phase == result.phase
        assert phase.story == result.story
        assert phase.status == result.status
        assert phase.duration_seconds == result.duration_seconds
        assert phase.tokens == result.tokens
        assert phase.cost == result.cost
        assert phase.error == result.error

    def test_from_phase_result_with_none_metrics(self) -> None:
        """Test converting ManifestPhaseResult with None metrics."""
        result = ManifestPhaseResult(
            phase="dev-story",
            story="1.2",
            status="completed",
            duration_seconds=100.0,
            tokens=None,
            cost=None,
        )
        phase = PhaseMetrics.from_phase_result(result)

        assert phase.tokens is None
        assert phase.cost is None


# =============================================================================
# RunMetrics Tests
# =============================================================================


class TestRunMetrics:
    """Tests for RunMetrics model."""

    def test_create_valid(self) -> None:
        """Test creating valid RunMetrics."""
        metrics = RunMetrics(
            total_cost=2.34,
            total_tokens=45230,
            total_duration_seconds=745.9,
            avg_tokens_per_phase=15076.67,
            avg_cost_per_phase=0.78,
            stories_completed=3,
            stories_failed=0,
        )
        assert metrics.total_cost == 2.34
        assert metrics.total_tokens == 45230
        assert metrics.stories_completed == 3

    def test_frozen(self) -> None:
        """Test RunMetrics is frozen (immutable)."""
        metrics = RunMetrics(
            total_cost=1.0,
            total_tokens=1000,
            total_duration_seconds=100.0,
            avg_tokens_per_phase=1000.0,
            avg_cost_per_phase=1.0,
            stories_completed=1,
            stories_failed=0,
        )
        with pytest.raises(Exception):
            metrics.total_cost = 2.0  # type: ignore[misc]

    def test_to_manifest_metrics(self) -> None:
        """Test converting RunMetrics to ManifestMetrics."""
        run_metrics = RunMetrics(
            total_cost=2.34,
            total_tokens=45230,
            total_duration_seconds=745.9,
            avg_tokens_per_phase=15076.67,
            avg_cost_per_phase=0.78,
            stories_completed=3,
            stories_failed=0,
        )
        manifest_metrics = run_metrics.to_manifest_metrics()

        assert isinstance(manifest_metrics, ManifestMetrics)
        assert manifest_metrics.total_cost == 2.34
        assert manifest_metrics.total_tokens == 45230
        assert manifest_metrics.total_duration_seconds == 745.9
        assert manifest_metrics.avg_tokens_per_phase == 15076.67
        assert manifest_metrics.avg_cost_per_phase == 0.78


# =============================================================================
# MetricsFile Tests
# =============================================================================


class TestMetricsFile:
    """Tests for MetricsFile model."""

    def test_create_valid(self) -> None:
        """Test creating valid MetricsFile."""
        summary = RunMetrics(
            total_cost=1.0,
            total_tokens=10000,
            total_duration_seconds=100.0,
            avg_tokens_per_phase=10000.0,
            avg_cost_per_phase=1.0,
            stories_completed=1,
            stories_failed=0,
        )
        phases = [
            PhaseMetrics(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=100.0,
                tokens=10000,
                cost=1.0,
            )
        ]
        metrics = MetricsFile(
            run_id="run-2026-01-09-001",
            collected_at=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
            summary=summary,
            phases=phases,
        )
        assert metrics.run_id == "run-2026-01-09-001"
        assert len(metrics.phases) == 1

    def test_datetime_serialization(self) -> None:
        """Test datetime serialization to ISO 8601."""
        summary = RunMetrics(
            total_cost=0.0,
            total_tokens=0,
            total_duration_seconds=0.0,
            avg_tokens_per_phase=0.0,
            avg_cost_per_phase=0.0,
            stories_completed=0,
            stories_failed=0,
        )
        metrics = MetricsFile(
            run_id="test",
            collected_at=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
            summary=summary,
            phases=[],
        )
        data = metrics.model_dump(mode="json")

        assert "2026-01-09T16:45:00" in data["collected_at"]
        assert "+00:00" in data["collected_at"]

    def test_serialization_round_trip(self) -> None:
        """Test MetricsFile survives serialization round-trip."""
        summary = RunMetrics(
            total_cost=2.34,
            total_tokens=45230,
            total_duration_seconds=745.9,
            avg_tokens_per_phase=15076.67,
            avg_cost_per_phase=0.78,
            stories_completed=3,
            stories_failed=0,
        )
        phases = [
            PhaseMetrics(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=245.5,
                tokens=12340,
                cost=0.45,
            ),
            PhaseMetrics(
                phase="dev-story",
                story="1.1",
                status="completed",
                duration_seconds=320.1,
                tokens=18000,
                cost=0.65,
            ),
        ]
        original = MetricsFile(
            run_id="run-2026-01-09-001",
            collected_at=datetime(2026, 1, 9, 16, 45, 0, tzinfo=UTC),
            summary=summary,
            phases=phases,
        )

        # Serialize and deserialize
        data = original.model_dump(mode="json")
        loaded = MetricsFile.model_validate(data)

        assert loaded.run_id == original.run_id
        assert loaded.summary.total_cost == original.summary.total_cost
        assert len(loaded.phases) == len(original.phases)
        assert loaded.phases[0].tokens == original.phases[0].tokens


# =============================================================================
# MetricsCollector Tests
# =============================================================================


class TestMetricsCollectorCollect:
    """Tests for MetricsCollector.collect()."""

    def test_collect_full_metrics(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test collecting metrics from manifest with full metrics."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)

        assert metrics.run_id == "run-2026-01-09-001"
        assert metrics.summary.total_tokens == 12340 + 18000 + 14890  # 45230
        assert metrics.summary.total_cost == 0.45 + 0.65 + 0.54  # 1.64
        assert metrics.summary.total_duration_seconds == 245.5 + 320.1 + 180.3
        assert metrics.summary.stories_completed == 3
        assert metrics.summary.stories_failed == 0
        assert len(metrics.phases) == 3

    def test_collect_with_missing_metrics(
        self,
        run_dir: Path,
        manifest_with_missing_metrics: RunManifest,
    ) -> None:
        """Test collecting metrics when some phases have None tokens/cost."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_missing_metrics)

        # Only one phase has tokens/cost
        assert metrics.summary.total_tokens == 18000
        assert metrics.summary.total_cost == 0.65
        # Duration includes all phases
        assert metrics.summary.total_duration_seconds == 245.5 + 320.1 + 180.3
        # Averages use stories_completed as denominator
        assert metrics.summary.avg_tokens_per_phase == 18000 / 2
        assert metrics.summary.avg_cost_per_phase == 0.65 / 2

    def test_collect_all_none_metrics(
        self,
        run_dir: Path,
        manifest_with_all_none_metrics: RunManifest,
    ) -> None:
        """Test collecting metrics when all tokens/cost are None (MVP)."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_all_none_metrics)

        assert metrics.summary.total_tokens == 0
        assert metrics.summary.total_cost == 0.0
        assert metrics.summary.total_duration_seconds == 100.0 + 200.0
        assert metrics.summary.avg_tokens_per_phase == 0.0
        assert metrics.summary.avg_cost_per_phase == 0.0

    def test_collect_mixed_phases(
        self,
        run_dir: Path,
        manifest_with_mixed_phases: RunManifest,
    ) -> None:
        """Test collecting metrics with completed, failed, and skipped phases."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_mixed_phases)

        # Tokens/cost from completed and failed phases
        assert metrics.summary.total_tokens == 10000 + 20000 + 5000  # 35000
        assert metrics.summary.total_cost == pytest.approx(1.05)
        # Duration from all phases including skipped
        assert metrics.summary.total_duration_seconds == 100.0 + 0.0 + 200.0 + 50.0
        # Counts exclude skipped
        assert metrics.summary.stories_completed == 2
        assert metrics.summary.stories_failed == 1
        # Average uses stories_completed
        assert metrics.summary.avg_tokens_per_phase == 35000 / 2
        assert metrics.summary.avg_cost_per_phase == pytest.approx(1.05 / 2)

    def test_collect_empty_results(
        self,
        run_dir: Path,
        manifest_empty_results: RunManifest,
    ) -> None:
        """Test collecting metrics from manifest with no results."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_empty_results)

        assert metrics.summary.total_tokens == 0
        assert metrics.summary.total_cost == 0.0
        assert metrics.summary.total_duration_seconds == 0.0
        assert metrics.summary.stories_completed == 0
        assert metrics.summary.stories_failed == 0
        assert len(metrics.phases) == 0

    def test_collect_zero_completed_no_division_error(
        self,
        run_dir: Path,
        manifest_zero_completed: RunManifest,
    ) -> None:
        """Test collecting metrics with zero completed phases (no division by zero)."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_zero_completed)

        assert metrics.summary.stories_completed == 0
        assert metrics.summary.stories_failed == 1
        # Averages should be 0.0, not raise ZeroDivisionError
        assert metrics.summary.avg_tokens_per_phase == 0.0
        assert metrics.summary.avg_cost_per_phase == 0.0
        # Totals should still be calculated
        assert metrics.summary.total_tokens == 5000
        assert metrics.summary.total_cost == 0.15


class TestMetricsCollectorSave:
    """Tests for MetricsCollector.save()."""

    def test_save_creates_file(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test save creates metrics.yaml file."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        saved_path = collector.save(metrics)

        assert saved_path == run_dir / "metrics.yaml"
        assert saved_path.exists()

    def test_save_yaml_format(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test saved YAML has expected format."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        collector.save(metrics)

        with (run_dir / "metrics.yaml").open("r") as f:
            data = yaml.safe_load(f)

        assert data["run_id"] == "run-2026-01-09-001"
        assert "collected_at" in data
        assert "summary" in data
        assert "phases" in data
        assert data["summary"]["total_tokens"] == 45230
        assert len(data["phases"]) == 3

    def test_save_atomic_no_temp_file(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test atomic save leaves no temp file."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        collector.save(metrics)

        temp_path = run_dir / "metrics.yaml.tmp"
        assert not temp_path.exists()

    def test_save_creates_directory(
        self,
        tmp_path: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test save creates directory if it doesn't exist."""
        new_run_dir = tmp_path / "nonexistent" / "run-001"
        collector = MetricsCollector(new_run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        collector.save(metrics)

        assert new_run_dir.exists()
        assert (new_run_dir / "metrics.yaml").exists()

    def test_save_failure_raises_config_error(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test save failure raises ConfigError."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)

        with patch("os.replace", side_effect=OSError("Permission denied")):
            with pytest.raises(ConfigError, match="Failed to save metrics"):
                collector.save(metrics)


class TestMetricsCollectorLoad:
    """Tests for MetricsCollector.load()."""

    def test_load_existing_metrics(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test loading existing metrics file."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        collector.save(metrics)

        # Load in new collector instance
        new_collector = MetricsCollector(run_dir)
        loaded = new_collector.load()

        assert loaded.run_id == metrics.run_id
        assert loaded.summary.total_tokens == metrics.summary.total_tokens
        assert len(loaded.phases) == len(metrics.phases)

    def test_load_nonexistent_raises_error(self, run_dir: Path) -> None:
        """Test loading non-existent metrics file raises ConfigError."""
        collector = MetricsCollector(run_dir)
        with pytest.raises(ConfigError, match="Metrics file not found"):
            collector.load()

    def test_load_invalid_yaml_raises_error(self, run_dir: Path) -> None:
        """Test loading invalid YAML raises ConfigError."""
        metrics_path = run_dir / "metrics.yaml"
        metrics_path.write_text("invalid: yaml: content: [")

        collector = MetricsCollector(run_dir)
        with pytest.raises(ConfigError, match="Invalid YAML"):
            collector.load()

    def test_load_invalid_schema_raises_error(self, run_dir: Path) -> None:
        """Test loading YAML with invalid schema raises ConfigError."""
        metrics_path = run_dir / "metrics.yaml"
        metrics_path.write_text("run_id: test\nmissing_fields: true")

        collector = MetricsCollector(run_dir)
        with pytest.raises(ConfigError, match="Metrics validation failed"):
            collector.load()


class TestMetricsCollectorProperties:
    """Tests for MetricsCollector properties."""

    def test_metrics_path_property(self, run_dir: Path) -> None:
        """Test metrics_path property returns correct path."""
        collector = MetricsCollector(run_dir)
        assert collector.metrics_path == run_dir / "metrics.yaml"


# =============================================================================
# Integration Tests
# =============================================================================


class TestMetricsManifestIntegration:
    """Tests for MetricsCollector integration with ManifestManager."""

    def test_update_manifest_with_collected_metrics(
        self,
        run_dir: Path,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating manifest with collected metrics."""
        # Create manifest
        manager = ManifestManager(run_dir)
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)

        # Add phase results
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="1.1",
                status="completed",
                duration_seconds=100.0,
                tokens=10000,
                cost=0.30,
            )
        )
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="dev-story",
                story="1.1",
                status="completed",
                duration_seconds=200.0,
                tokens=20000,
                cost=0.60,
            )
        )

        # Finalize
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        # Collect metrics
        collector = MetricsCollector(run_dir)
        assert manager.manifest is not None
        metrics = collector.collect(manager.manifest)
        collector.save(metrics)

        # Update manifest with metrics
        manager.update_metrics(metrics.summary.to_manifest_metrics())

        # Verify manifest has metrics
        assert manager.manifest.metrics is not None
        assert manager.manifest.metrics.total_tokens == 30000
        assert manager.manifest.metrics.total_cost == pytest.approx(0.90)


class TestManifestPhaseResultBackwardCompatibility:
    """Tests for backward compatibility of ManifestPhaseResult."""

    def test_load_manifest_without_tokens_cost(self, run_dir: Path) -> None:
        """Test loading manifest from Story 18.7 without tokens/cost fields."""
        # Write a manifest in the old format (no tokens/cost)
        old_manifest = {
            "run_id": "old-run-001",
            "started": "2026-01-09T12:00:00+00:00",
            "completed": "2026-01-09T13:00:00+00:00",
            "status": "completed",
            "schema_version": "1.0",
            "input": {
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            "resolved": {
                "fixture": {"name": "minimal", "source": "/fixtures", "snapshot": "./snap"},
                "config": {"name": "opus", "source": "/configs", "providers": {}},
                "patch_set": {"name": "baseline", "source": "/patches"},
                "loop": {"name": "standard", "source": "/loops", "sequence": []},
            },
            "results": {
                "stories_attempted": 1,
                "stories_completed": 1,
                "stories_failed": 0,
                "phases": [
                    {
                        "phase": "create-story",
                        "story": "1.1",
                        "status": "completed",
                        "duration_seconds": 100.0,
                        # No tokens or cost fields
                    }
                ],
            },
            "metrics": None,
        }

        manifest_path = run_dir / "manifest.yaml"
        with manifest_path.open("w") as f:
            yaml.dump(old_manifest, f)

        # Load and verify it works
        manager = ManifestManager(run_dir)
        manifest = manager.load()

        assert manifest.run_id == "old-run-001"
        assert manifest.results is not None
        assert len(manifest.results.phases) == 1
        # New fields should default to None
        assert manifest.results.phases[0].tokens is None
        assert manifest.results.phases[0].cost is None


class TestMetricsYAMLFormat:
    """Tests for metrics.yaml output format."""

    def test_yaml_format_matches_schema(
        self,
        run_dir: Path,
        manifest_with_full_metrics: RunManifest,
    ) -> None:
        """Test metrics.yaml matches expected schema from AC9."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_full_metrics)
        collector.save(metrics)

        with (run_dir / "metrics.yaml").open("r") as f:
            data = yaml.safe_load(f)

        # Top-level fields
        assert "run_id" in data
        assert "collected_at" in data
        assert "summary" in data
        assert "phases" in data

        # Summary fields
        summary = data["summary"]
        assert "total_cost" in summary
        assert "total_tokens" in summary
        assert "total_duration_seconds" in summary
        assert "avg_tokens_per_phase" in summary
        assert "avg_cost_per_phase" in summary
        assert "stories_completed" in summary
        assert "stories_failed" in summary

        # Phase fields
        phase = data["phases"][0]
        assert "phase" in phase
        assert "story" in phase
        assert "status" in phase
        assert "duration_seconds" in phase
        assert "tokens" in phase
        assert "cost" in phase
        assert "error" in phase

    def test_null_values_in_yaml(
        self,
        run_dir: Path,
        manifest_with_all_none_metrics: RunManifest,
    ) -> None:
        """Test None values are serialized as null in YAML."""
        collector = MetricsCollector(run_dir)
        metrics = collector.collect(manifest_with_all_none_metrics)
        collector.save(metrics)

        # Read raw YAML to check null representation
        content = (run_dir / "metrics.yaml").read_text()

        # Null values should be present in phases
        with (run_dir / "metrics.yaml").open("r") as f:
            data = yaml.safe_load(f)

        for phase in data["phases"]:
            assert phase["tokens"] is None
            assert phase["cost"] is None
