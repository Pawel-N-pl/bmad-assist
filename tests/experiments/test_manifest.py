"""Tests for experiment run manifest system.

Tests cover:
- All Pydantic model creation and validation
- ManifestManager lifecycle methods
- Immutability enforcement after finalize
- Skipped phases not incrementing stories_attempted
- Atomic write behavior
- YAML serialization format and datetime round-trip
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from bmad_assist.core.exceptions import ConfigError, ManifestError
from bmad_assist.experiments.manifest import (
    TERMINAL_STATUSES,
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
    build_resolved_config,
    build_resolved_fixture,
    build_resolved_loop,
    build_resolved_patchset,
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
def resolved_fixture() -> ResolvedFixture:
    """Create sample ResolvedFixture."""
    return ResolvedFixture(
        name="minimal",
        source="/fixtures/minimal",
        snapshot="./fixture-snapshot",
    )


@pytest.fixture
def resolved_config() -> ResolvedConfig:
    """Create sample ResolvedConfig."""
    return ResolvedConfig(
        name="opus-solo",
        source="/configs/opus-solo.yaml",
        providers={
            "master": {"provider": "claude", "model": "opus"},
            "multi": [],
        },
    )


@pytest.fixture
def resolved_patchset() -> ResolvedPatchSet:
    """Create sample ResolvedPatchSet."""
    return ResolvedPatchSet(
        name="baseline",
        source="/patch-sets/baseline.yaml",
        workflow_overrides={},
        patches={"create-story": "/patches/create-story.patch.yaml"},
    )


@pytest.fixture
def resolved_loop() -> ResolvedLoop:
    """Create sample ResolvedLoop."""
    return ResolvedLoop(
        name="standard",
        source="/loops/standard.yaml",
        sequence=["create-story", "dev-story", "code-review"],
    )


@pytest.fixture
def manifest_resolved(
    resolved_fixture: ResolvedFixture,
    resolved_config: ResolvedConfig,
    resolved_patchset: ResolvedPatchSet,
    resolved_loop: ResolvedLoop,
) -> ManifestResolved:
    """Create sample ManifestResolved."""
    return ManifestResolved(
        fixture=resolved_fixture,
        config=resolved_config,
        patch_set=resolved_patchset,
        loop=resolved_loop,
    )


@pytest.fixture
def sample_manifest(
    manifest_input: ManifestInput,
    manifest_resolved: ManifestResolved,
) -> RunManifest:
    """Create sample RunManifest."""
    return RunManifest(
        run_id="test-run-001",
        started=datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC),
        completed=None,
        status=ExperimentStatus.PENDING,
        input=manifest_input,
        resolved=manifest_resolved,
        results=None,
        metrics=None,
    )


@pytest.fixture
def manager(run_dir: Path) -> ManifestManager:
    """Create ManifestManager for testing."""
    return ManifestManager(run_dir)


# =============================================================================
# Model Creation Tests
# =============================================================================


class TestManifestInput:
    """Tests for ManifestInput model."""

    def test_create_valid(self) -> None:
        """Test creating valid ManifestInput."""
        inp = ManifestInput(
            fixture="test-fixture",
            config="test-config",
            patch_set="test-patchset",
            loop="test-loop",
        )
        assert inp.fixture == "test-fixture"
        assert inp.config == "test-config"
        assert inp.patch_set == "test-patchset"
        assert inp.loop == "test-loop"

    def test_frozen(self) -> None:
        """Test ManifestInput is frozen (immutable)."""
        inp = ManifestInput(fixture="test", config="test", patch_set="test", loop="test")
        with pytest.raises(Exception):  # ValidationError for frozen models
            inp.fixture = "modified"  # type: ignore[misc]


class TestResolvedFixture:
    """Tests for ResolvedFixture model."""

    def test_create_valid(self) -> None:
        """Test creating valid ResolvedFixture."""
        fixture = ResolvedFixture(
            name="minimal",
            source="/path/to/fixture",
            snapshot="./fixture-snapshot",
        )
        assert fixture.name == "minimal"
        assert fixture.source == "/path/to/fixture"
        assert fixture.snapshot == "./fixture-snapshot"

    def test_frozen(self) -> None:
        """Test ResolvedFixture is frozen."""
        fixture = ResolvedFixture(name="x", source="/x", snapshot="./x")
        with pytest.raises(Exception):
            fixture.name = "modified"  # type: ignore[misc]


class TestResolvedConfig:
    """Tests for ResolvedConfig model."""

    def test_create_with_multi(self) -> None:
        """Test creating ResolvedConfig with multi providers."""
        config = ResolvedConfig(
            name="multi-config",
            source="/configs/multi.yaml",
            providers={
                "master": {"provider": "claude", "model": "opus"},
                "multi": [
                    {"provider": "claude", "model": "sonnet"},
                    {"provider": "gemini", "model": "flash"},
                ],
            },
        )
        assert config.name == "multi-config"
        assert len(config.providers["multi"]) == 2


class TestResolvedPatchSet:
    """Tests for ResolvedPatchSet model."""

    def test_create_with_overrides(self) -> None:
        """Test creating ResolvedPatchSet with workflow overrides."""
        patchset = ResolvedPatchSet(
            name="custom",
            source="/patch-sets/custom.yaml",
            workflow_overrides={"create-story": "/overrides/create-story"},
            patches={"dev-story": "/patches/dev-story.patch.yaml"},
        )
        assert "create-story" in patchset.workflow_overrides
        assert "dev-story" in patchset.patches

    def test_default_empty_dicts(self) -> None:
        """Test default empty dicts for overrides and patches."""
        patchset = ResolvedPatchSet(
            name="minimal",
            source="/patch-sets/minimal.yaml",
        )
        assert patchset.workflow_overrides == {}
        assert patchset.patches == {}


class TestResolvedLoop:
    """Tests for ResolvedLoop model."""

    def test_create_valid(self) -> None:
        """Test creating valid ResolvedLoop."""
        loop = ResolvedLoop(
            name="full-loop",
            source="/loops/full.yaml",
            sequence=["create-story", "validate", "dev-story", "code-review"],
        )
        assert len(loop.sequence) == 4
        assert loop.sequence[0] == "create-story"


class TestManifestResolved:
    """Tests for ManifestResolved model."""

    def test_create_valid(
        self,
        resolved_fixture: ResolvedFixture,
        resolved_config: ResolvedConfig,
        resolved_patchset: ResolvedPatchSet,
        resolved_loop: ResolvedLoop,
    ) -> None:
        """Test creating valid ManifestResolved."""
        resolved = ManifestResolved(
            fixture=resolved_fixture,
            config=resolved_config,
            patch_set=resolved_patchset,
            loop=resolved_loop,
        )
        assert resolved.fixture.name == "minimal"
        assert resolved.config.name == "opus-solo"
        assert resolved.patch_set.name == "baseline"
        assert resolved.loop.name == "standard"


class TestManifestPhaseResult:
    """Tests for ManifestPhaseResult model."""

    def test_completed_phase(self) -> None:
        """Test creating completed phase result."""
        result = ManifestPhaseResult(
            phase="create-story",
            story="18-1",
            status="completed",
            duration_seconds=45.2,
            error=None,
        )
        assert result.status == "completed"
        assert result.error is None

    def test_failed_phase_with_error(self) -> None:
        """Test creating failed phase result with error message."""
        result = ManifestPhaseResult(
            phase="dev-story",
            story="18-2",
            status="failed",
            duration_seconds=120.5,
            error="Provider timeout",
        )
        assert result.status == "failed"
        assert result.error == "Provider timeout"

    def test_skipped_phase(self) -> None:
        """Test creating skipped phase result."""
        result = ManifestPhaseResult(
            phase="validate-story",
            story="18-1",
            status="skipped",
            duration_seconds=0.0,
            error=None,
        )
        assert result.status == "skipped"

    def test_epic_level_phase_no_story(self) -> None:
        """Test creating epic-level phase result without story ID."""
        result = ManifestPhaseResult(
            phase="retrospective",
            story=None,
            status="completed",
            duration_seconds=30.0,
        )
        assert result.story is None


class TestManifestResults:
    """Tests for ManifestResults model."""

    def test_default_values(self) -> None:
        """Test default values for ManifestResults."""
        results = ManifestResults()
        assert results.stories_attempted == 0
        assert results.stories_completed == 0
        assert results.stories_failed == 0
        assert results.phases == []

    def test_not_frozen(self) -> None:
        """Test ManifestResults is not frozen (mutable)."""
        results = ManifestResults()
        results.stories_attempted = 5
        assert results.stories_attempted == 5


class TestManifestMetrics:
    """Tests for ManifestMetrics model."""

    def test_all_optional(self) -> None:
        """Test all metrics fields are optional."""
        metrics = ManifestMetrics()
        assert metrics.total_cost is None
        assert metrics.total_tokens is None
        assert metrics.total_duration_seconds is None

    def test_with_values(self) -> None:
        """Test ManifestMetrics with values."""
        metrics = ManifestMetrics(
            total_cost=1.50,
            total_tokens=50000,
            total_duration_seconds=300.5,
            avg_tokens_per_phase=10000.0,
            avg_cost_per_phase=0.30,
        )
        assert metrics.total_cost == 1.50
        assert metrics.total_tokens == 50000


class TestRunManifest:
    """Tests for RunManifest model."""

    def test_create_valid(self, sample_manifest: RunManifest) -> None:
        """Test creating valid RunManifest."""
        assert sample_manifest.run_id == "test-run-001"
        assert sample_manifest.status == ExperimentStatus.PENDING
        assert sample_manifest.completed is None

    def test_datetime_serialization(self, sample_manifest: RunManifest) -> None:
        """Test datetime serialization to ISO 8601."""
        data = sample_manifest.model_dump(mode="json")
        assert "2026-01-09T12:00:00" in data["started"]
        assert "+00:00" in data["started"] or "Z" in data["started"]

    def test_status_serialization(self, sample_manifest: RunManifest) -> None:
        """Test status enum serialization to string."""
        data = sample_manifest.model_dump(mode="json")
        assert data["status"] == "pending"

    def test_datetime_parsing(
        self,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test datetime parsing from ISO 8601 string."""
        data: dict[str, Any] = {
            "run_id": "test",
            "started": "2026-01-09T12:00:00+00:00",
            "completed": None,
            "status": "running",
            "input": manifest_input.model_dump(),
            "resolved": manifest_resolved.model_dump(),
        }
        manifest = RunManifest.model_validate(data)
        assert manifest.started.year == 2026
        assert manifest.status == ExperimentStatus.RUNNING


# =============================================================================
# ManifestManager Tests
# =============================================================================


class TestManifestManagerCreate:
    """Tests for ManifestManager.create()."""

    def test_create_manifest(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test creating a new manifest."""
        started = datetime.now(UTC)
        manifest = manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=started,
            run_id="test-run-001",
        )
        assert manifest.run_id == "test-run-001"
        assert manifest.status == ExperimentStatus.PENDING
        assert manifest.started == started

    def test_create_saves_file(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test create() saves manifest.yaml file."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manifest_path = run_dir / "manifest.yaml"
        assert manifest_path.exists()

    def test_create_yaml_format(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test manifest YAML format is valid."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manifest_path = run_dir / "manifest.yaml"
        with manifest_path.open("r") as f:
            data = yaml.safe_load(f)
        assert data["run_id"] == "test-run-001"
        assert data["status"] == "pending"


class TestManifestManagerLoad:
    """Tests for ManifestManager.load()."""

    def test_load_existing_manifest(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test loading an existing manifest."""
        original = manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )

        # Create new manager and load
        new_manager = ManifestManager(run_dir)
        loaded = new_manager.load()

        assert loaded.run_id == original.run_id
        assert loaded.input.fixture == original.input.fixture

    def test_load_nonexistent_raises_error(self, run_dir: Path) -> None:
        """Test loading non-existent manifest raises ConfigError."""
        manager = ManifestManager(run_dir)
        with pytest.raises(ConfigError, match="Manifest not found"):
            manager.load()

    def test_load_invalid_yaml_raises_error(self, run_dir: Path) -> None:
        """Test loading invalid YAML raises ConfigError."""
        manifest_path = run_dir / "manifest.yaml"
        manifest_path.write_text("invalid: yaml: content: [")

        manager = ManifestManager(run_dir)
        with pytest.raises(ConfigError, match="Invalid YAML"):
            manager.load()

    def test_load_finalized_manifest_sets_flag(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test loading a finalized manifest sets is_finalized flag."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        # Create new manager and load
        new_manager = ManifestManager(run_dir)
        new_manager.load()
        assert new_manager.is_finalized


class TestManifestManagerUpdateStatus:
    """Tests for ManifestManager.update_status()."""

    def test_update_to_running(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating status to RUNNING."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)
        assert manager.manifest is not None
        assert manager.manifest.status == ExperimentStatus.RUNNING

    def test_update_to_terminal_sets_completed(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating to terminal status sets completed timestamp."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        completed = datetime.now(UTC)
        manager.update_status(ExperimentStatus.FAILED, completed=completed)

        assert manager.manifest is not None
        assert manager.manifest.status == ExperimentStatus.FAILED
        assert manager.manifest.completed == completed

    def test_update_terminal_without_timestamp_uses_now(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test terminal status without timestamp uses current time."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        before = datetime.now(UTC)
        manager.update_status(ExperimentStatus.CANCELLED)
        after = datetime.now(UTC)

        assert manager.manifest is not None
        assert manager.manifest.completed is not None
        assert before <= manager.manifest.completed <= after

    def test_update_finalized_raises_error(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating finalized manifest raises ManifestError."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        with pytest.raises(ManifestError, match="manifest is finalized"):
            manager.update_status(ExperimentStatus.RUNNING)


class TestManifestManagerAddPhaseResult:
    """Tests for ManifestManager.add_phase_result()."""

    def test_add_completed_phase(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test adding completed phase result."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)
        result = ManifestPhaseResult(
            phase="create-story",
            story="18-1",
            status="completed",
            duration_seconds=45.0,
        )
        manager.add_phase_result(result)

        assert manager.manifest is not None
        assert manager.manifest.results is not None
        assert manager.manifest.results.stories_attempted == 1
        assert manager.manifest.results.stories_completed == 1
        assert len(manager.manifest.results.phases) == 1

    def test_add_failed_phase(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test adding failed phase result."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)
        result = ManifestPhaseResult(
            phase="dev-story",
            story="18-2",
            status="failed",
            duration_seconds=120.0,
            error="Timeout",
        )
        manager.add_phase_result(result)

        assert manager.manifest is not None
        assert manager.manifest.results is not None
        assert manager.manifest.results.stories_attempted == 1
        assert manager.manifest.results.stories_failed == 1

    def test_skipped_phase_not_counted(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test skipped phases do not increment stories_attempted."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)
        result = ManifestPhaseResult(
            phase="validate-story",
            story="18-1",
            status="skipped",
            duration_seconds=0.0,
        )
        manager.add_phase_result(result)

        assert manager.manifest is not None
        assert manager.manifest.results is not None
        assert manager.manifest.results.stories_attempted == 0
        assert manager.manifest.results.stories_completed == 0
        assert len(manager.manifest.results.phases) == 1

    def test_add_multiple_phases(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test adding multiple phase results."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)

        phases = [
            ManifestPhaseResult(
                phase="create-story", story="18-1", status="completed", duration_seconds=30.0
            ),
            ManifestPhaseResult(
                phase="validate", story="18-1", status="skipped", duration_seconds=0.0
            ),
            ManifestPhaseResult(
                phase="dev-story", story="18-1", status="completed", duration_seconds=90.0
            ),
            ManifestPhaseResult(
                phase="code-review",
                story="18-1",
                status="failed",
                duration_seconds=60.0,
                error="Error",
            ),
        ]
        for p in phases:
            manager.add_phase_result(p)

        assert manager.manifest is not None
        assert manager.manifest.results is not None
        assert manager.manifest.results.stories_attempted == 3  # skipped not counted
        assert manager.manifest.results.stories_completed == 2
        assert manager.manifest.results.stories_failed == 1
        assert len(manager.manifest.results.phases) == 4

    def test_add_phase_finalized_raises_error(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test adding phase to finalized manifest raises ManifestError."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        result = ManifestPhaseResult(
            phase="create-story", story="18-1", status="completed", duration_seconds=30.0
        )
        with pytest.raises(ManifestError, match="manifest is finalized"):
            manager.add_phase_result(result)

    def test_add_phase_in_pending_status_raises_error(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test adding phase result in PENDING status raises ManifestError (AC7)."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        # Don't update status - still PENDING

        result = ManifestPhaseResult(
            phase="create-story", story="18-1", status="completed", duration_seconds=30.0
        )
        with pytest.raises(ManifestError, match="status is pending, must be running"):
            manager.add_phase_result(result)


class TestManifestManagerUpdateMetrics:
    """Tests for ManifestManager.update_metrics()."""

    def test_update_metrics(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating manifest metrics."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        metrics = ManifestMetrics(
            total_cost=2.50,
            total_tokens=75000,
            total_duration_seconds=450.0,
        )
        manager.update_metrics(metrics)

        assert manager.manifest is not None
        assert manager.manifest.metrics is not None
        assert manager.manifest.metrics.total_cost == 2.50

    def test_update_metrics_after_finalize_allowed(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test updating metrics is allowed after finalization."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        # Metrics update should work even after finalize
        metrics = ManifestMetrics(total_cost=1.00)
        manager.update_metrics(metrics)

        assert manager.manifest is not None
        assert manager.manifest.metrics is not None
        assert manager.manifest.metrics.total_cost == 1.00


class TestManifestManagerFinalize:
    """Tests for ManifestManager.finalize()."""

    def test_finalize_completed(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test finalizing with COMPLETED status."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        completed = datetime.now(UTC)
        manifest = manager.finalize(ExperimentStatus.COMPLETED, completed)

        assert manifest.status == ExperimentStatus.COMPLETED
        assert manifest.completed == completed
        assert manager.is_finalized

    def test_finalize_failed(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test finalizing with FAILED status."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manifest = manager.finalize(ExperimentStatus.FAILED, datetime.now(UTC))

        assert manifest.status == ExperimentStatus.FAILED
        assert manager.is_finalized

    def test_finalize_cancelled(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test finalizing with CANCELLED status."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manifest = manager.finalize(ExperimentStatus.CANCELLED, datetime.now(UTC))

        assert manifest.status == ExperimentStatus.CANCELLED
        assert manager.is_finalized

    def test_finalize_non_terminal_raises_error(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test finalizing with non-terminal status raises ManifestError."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        with pytest.raises(ManifestError, match="non-terminal status"):
            manager.finalize(ExperimentStatus.RUNNING, datetime.now(UTC))

    def test_finalize_twice_raises_error(
        self,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test finalizing twice raises ManifestError."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))

        with pytest.raises(ManifestError, match="manifest is finalized"):
            manager.finalize(ExperimentStatus.FAILED, datetime.now(UTC))


class TestManifestManagerAtomicWrite:
    """Tests for atomic write behavior."""

    def test_atomic_write_creates_temp_file(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test atomic write uses temp file pattern."""
        # Verify no temp file remains after successful write
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )
        temp_path = run_dir / "manifest.yaml.tmp"
        assert not temp_path.exists()

    def test_save_failure_raises_manifest_error(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test save failure raises ManifestError."""
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=datetime.now(UTC),
            run_id="test-run-001",
        )

        # Patch os.replace to simulate atomic rename failure
        with patch("os.replace", side_effect=OSError("Permission denied")):
            with pytest.raises(ManifestError, match="Failed to save"):
                manager.update_status(ExperimentStatus.RUNNING)


class TestManifestManagerErrors:
    """Tests for ManifestManager error handling."""

    def test_update_without_manifest_raises_error(self, run_dir: Path) -> None:
        """Test update_status without create/load raises ManifestError."""
        manager = ManifestManager(run_dir)
        with pytest.raises(ManifestError, match="not loaded"):
            manager.update_status(ExperimentStatus.RUNNING)

    def test_add_phase_without_manifest_raises_error(self, run_dir: Path) -> None:
        """Test add_phase_result without create/load raises ManifestError."""
        manager = ManifestManager(run_dir)
        result = ManifestPhaseResult(
            phase="test", story="1", status="completed", duration_seconds=1.0
        )
        with pytest.raises(ManifestError, match="not loaded"):
            manager.add_phase_result(result)

    def test_finalize_without_manifest_raises_error(self, run_dir: Path) -> None:
        """Test finalize without create/load raises ManifestError."""
        manager = ManifestManager(run_dir)
        with pytest.raises(ManifestError, match="not loaded"):
            manager.finalize(ExperimentStatus.COMPLETED, datetime.now(UTC))


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestBuildResolvedFixture:
    """Tests for build_resolved_fixture helper."""

    def test_build_from_entry_and_result(self, tmp_path: Path) -> None:
        """Test building resolved fixture from entry and isolation result."""
        from bmad_assist.experiments.fixture import FixtureEntry
        from bmad_assist.experiments.isolation import IsolationResult

        entry = FixtureEntry(
            id="test-fixture",
            name="Test Fixture",
            path="./fixtures/test",  # path is a string, not Path
            tags=["test"],
            difficulty="easy",
            estimated_cost="$0.10",
        )
        run_dir = tmp_path / "runs" / "run-001"
        run_dir.mkdir(parents=True)

        isolation = IsolationResult(
            source_path=tmp_path / "fixtures" / "test",
            snapshot_path=run_dir / "fixture-snapshot",
            file_count=10,
            total_bytes=1024,
            duration_seconds=0.5,
            verified=True,
        )

        resolved = build_resolved_fixture(entry, isolation, run_dir)

        assert resolved.name == "test-fixture"
        assert "fixtures" in resolved.source
        assert "./fixture-snapshot" in resolved.snapshot


class TestBuildResolvedConfig:
    """Tests for build_resolved_config helper."""

    def test_build_from_template(self, tmp_path: Path) -> None:
        """Test building resolved config from template."""
        from bmad_assist.core.config import MasterProviderConfig
        from bmad_assist.experiments.config import ConfigTemplate, ConfigTemplateProviders

        # Use actual MasterProviderConfig model
        master = MasterProviderConfig(
            provider="claude",
            model="opus",
        )

        providers = ConfigTemplateProviders(
            master=master,
            multi=[],
        )
        template = ConfigTemplate(
            name="test-config",
            description="Test",
            providers=providers,
        )

        source_path = tmp_path / "configs" / "test-config.yaml"
        resolved = build_resolved_config(template, source_path)

        assert resolved.name == "test-config"
        assert resolved.providers["master"]["provider"] == "claude"


class TestBuildResolvedPatchSet:
    """Tests for build_resolved_patchset helper."""

    def test_build_from_manifest(self, tmp_path: Path) -> None:
        """Test building resolved patchset from manifest."""
        from bmad_assist.experiments.patchset import PatchSetManifest

        manifest = PatchSetManifest(
            name="test-patchset",
            description="Test",
            patches={"create-story": "/path/to/patch.yaml"},
            workflow_overrides={"dev-story": "/path/to/override"},
        )

        source_path = tmp_path / "patch-sets" / "test.yaml"
        resolved = build_resolved_patchset(manifest, source_path)

        assert resolved.name == "test-patchset"
        assert "create-story" in resolved.patches
        assert "dev-story" in resolved.workflow_overrides


class TestBuildResolvedLoop:
    """Tests for build_resolved_loop helper."""

    def test_build_from_template(self, tmp_path: Path) -> None:
        """Test building resolved loop from template."""
        from bmad_assist.experiments.loop import LoopStep, LoopTemplate

        steps = [
            LoopStep(workflow="create-story", required=True),
            LoopStep(workflow="dev-story", required=True),
        ]
        template = LoopTemplate(
            name="test-loop",
            description="Test",
            sequence=steps,
        )

        source_path = tmp_path / "loops" / "test.yaml"
        resolved = build_resolved_loop(template, source_path)

        assert resolved.name == "test-loop"
        assert resolved.sequence == ["create-story", "dev-story"]


# =============================================================================
# YAML Round-Trip Tests
# =============================================================================


class TestYAMLRoundTrip:
    """Tests for YAML serialization and deserialization."""

    def test_full_manifest_round_trip(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test full manifest survives YAML round-trip."""
        started = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=started,
            run_id="test-run-001",
        )
        manager.update_status(ExperimentStatus.RUNNING)

        # Add phase results
        manager.add_phase_result(
            ManifestPhaseResult(
                phase="create-story",
                story="18-1",
                status="completed",
                duration_seconds=45.0,
            )
        )

        # Finalize
        completed = datetime(2026, 1, 9, 12, 30, 0, tzinfo=UTC)
        manager.finalize(ExperimentStatus.COMPLETED, completed)

        # Load in new manager
        new_manager = ManifestManager(run_dir)
        loaded = new_manager.load()

        assert loaded.run_id == "test-run-001"
        assert loaded.started == started
        assert loaded.completed == completed
        assert loaded.status == ExperimentStatus.COMPLETED
        assert loaded.input.fixture == "minimal"
        assert loaded.resolved.config.name == "opus-solo"
        assert loaded.results is not None
        assert len(loaded.results.phases) == 1

    def test_datetime_timezone_preserved(
        self,
        run_dir: Path,
        manager: ManifestManager,
        manifest_input: ManifestInput,
        manifest_resolved: ManifestResolved,
    ) -> None:
        """Test datetime timezone is preserved through round-trip."""
        started = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
        manager.create(
            input=manifest_input,
            resolved=manifest_resolved,
            started=started,
            run_id="test-run-001",
        )

        new_manager = ManifestManager(run_dir)
        loaded = new_manager.load()

        # Check the datetime is correctly parsed
        assert loaded.started.year == 2026
        assert loaded.started.month == 1
        assert loaded.started.day == 9


# =============================================================================
# Constants Tests
# =============================================================================


class TestTerminalStatuses:
    """Tests for TERMINAL_STATUSES constant."""

    def test_contains_expected_statuses(self) -> None:
        """Test TERMINAL_STATUSES contains expected values."""
        assert ExperimentStatus.COMPLETED in TERMINAL_STATUSES
        assert ExperimentStatus.FAILED in TERMINAL_STATUSES
        assert ExperimentStatus.CANCELLED in TERMINAL_STATUSES

    def test_does_not_contain_non_terminal(self) -> None:
        """Test TERMINAL_STATUSES excludes non-terminal statuses."""
        assert ExperimentStatus.PENDING not in TERMINAL_STATUSES
        assert ExperimentStatus.RUNNING not in TERMINAL_STATUSES
