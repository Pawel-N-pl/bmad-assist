"""Tests for ExperimentRunner module.

Tests cover:
- ExperimentInput validation and fields
- ExperimentOutput dataclass
- ExperimentStatus enum transitions
- ExperimentRunner initialization and lazy loading
- run() method orchestration
- Loop execution with phase mapping
- Patch application
- Cancellation support
- State isolation
"""

import signal
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import Config
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import Phase, State
from bmad_assist.experiments.runner import (
    WORKFLOW_TO_PHASE,
    ExperimentInput,
    ExperimentOutput,
    ExperimentRunner,
    ExperimentStatus,
)

# =============================================================================
# ExperimentStatus Tests
# =============================================================================


class TestExperimentStatus:
    """Tests for ExperimentStatus enum."""

    def test_status_values(self) -> None:
        """Test all expected status values exist."""
        assert ExperimentStatus.PENDING.value == "pending"
        assert ExperimentStatus.RUNNING.value == "running"
        assert ExperimentStatus.COMPLETED.value == "completed"
        assert ExperimentStatus.FAILED.value == "failed"
        assert ExperimentStatus.CANCELLED.value == "cancelled"

    def test_status_is_string_enum(self) -> None:
        """Test that ExperimentStatus is a string enum."""
        assert isinstance(ExperimentStatus.PENDING, str)
        assert ExperimentStatus.PENDING == "pending"

    def test_all_status_values(self) -> None:
        """Test we have exactly 5 status values."""
        assert len(ExperimentStatus) == 5


# =============================================================================
# ExperimentInput Tests
# =============================================================================


class TestExperimentInput:
    """Tests for ExperimentInput dataclass."""

    def test_create_valid_input(self) -> None:
        """Test creating a valid ExperimentInput."""
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )
        assert input.fixture == "minimal"
        assert input.config == "opus-solo"
        assert input.patch_set == "baseline"
        assert input.loop == "standard"
        assert input.run_id is None

    def test_create_with_run_id(self) -> None:
        """Test creating ExperimentInput with custom run_id."""
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
            run_id="run-2026-01-01-001",
        )
        assert input.run_id == "run-2026-01-01-001"

    def test_empty_fixture_rejected(self) -> None:
        """Test that empty fixture is rejected."""
        with pytest.raises(ValueError, match="fixture cannot be empty"):
            ExperimentInput(
                fixture="",
                config="opus-solo",
                patch_set="baseline",
                loop="standard",
            )

    def test_empty_config_rejected(self) -> None:
        """Test that empty config is rejected."""
        with pytest.raises(ValueError, match="config cannot be empty"):
            ExperimentInput(
                fixture="minimal",
                config="",
                patch_set="baseline",
                loop="standard",
            )

    def test_empty_patch_set_rejected(self) -> None:
        """Test that empty patch_set is rejected."""
        with pytest.raises(ValueError, match="patch_set cannot be empty"):
            ExperimentInput(
                fixture="minimal",
                config="opus-solo",
                patch_set="",
                loop="standard",
            )

    def test_empty_loop_rejected(self) -> None:
        """Test that empty loop is rejected."""
        with pytest.raises(ValueError, match="loop cannot be empty"):
            ExperimentInput(
                fixture="minimal",
                config="opus-solo",
                patch_set="baseline",
                loop="",
            )

    def test_whitespace_only_rejected(self) -> None:
        """Test that whitespace-only values are rejected."""
        with pytest.raises(ValueError, match="fixture cannot be empty"):
            ExperimentInput(
                fixture="   ",
                config="opus-solo",
                patch_set="baseline",
                loop="standard",
            )

    def test_immutability(self) -> None:
        """Test that ExperimentInput is immutable (frozen)."""
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )
        with pytest.raises(AttributeError):
            input.fixture = "other"  # type: ignore[misc]


# =============================================================================
# ExperimentOutput Tests
# =============================================================================


class TestExperimentOutput:
    """Tests for ExperimentOutput dataclass."""

    def test_create_output(self) -> None:
        """Test creating ExperimentOutput."""
        now = datetime.now(UTC)
        output = ExperimentOutput(
            run_id="run-2026-01-01-001",
            status=ExperimentStatus.COMPLETED,
            started=now,
            completed=now,
            duration_seconds=123.45,
            stories_attempted=3,
            stories_completed=3,
            stories_failed=0,
        )
        assert output.run_id == "run-2026-01-01-001"
        assert output.status == ExperimentStatus.COMPLETED
        assert output.duration_seconds == 123.45
        assert output.stories_attempted == 3
        assert output.stories_completed == 3
        assert output.stories_failed == 0
        assert output.error is None

    def test_create_failed_output(self) -> None:
        """Test creating failed ExperimentOutput with error."""
        now = datetime.now(UTC)
        output = ExperimentOutput(
            run_id="run-2026-01-01-001",
            status=ExperimentStatus.FAILED,
            started=now,
            completed=now,
            duration_seconds=10.0,
            stories_attempted=1,
            stories_completed=0,
            stories_failed=1,
            error="Phase failed",
        )
        assert output.status == ExperimentStatus.FAILED
        assert output.error == "Phase failed"

    def test_immutability(self) -> None:
        """Test that ExperimentOutput is immutable (frozen)."""
        now = datetime.now(UTC)
        output = ExperimentOutput(
            run_id="run-2026-01-01-001",
            status=ExperimentStatus.COMPLETED,
            started=now,
            completed=now,
            duration_seconds=0.0,
            stories_attempted=0,
            stories_completed=0,
            stories_failed=0,
        )
        with pytest.raises(AttributeError):
            output.status = ExperimentStatus.FAILED  # type: ignore[misc]


# =============================================================================
# WORKFLOW_TO_PHASE Mapping Tests
# =============================================================================


class TestWorkflowToPhase:
    """Tests for WORKFLOW_TO_PHASE mapping."""

    def test_all_phase_workflows_mapped(self) -> None:
        """Test that all expected workflows are mapped."""
        assert WORKFLOW_TO_PHASE["create-story"] == Phase.CREATE_STORY
        assert WORKFLOW_TO_PHASE["validate-story"] == Phase.VALIDATE_STORY
        assert WORKFLOW_TO_PHASE["validate-story-synthesis"] == Phase.VALIDATE_STORY_SYNTHESIS
        assert WORKFLOW_TO_PHASE["atdd"] == Phase.ATDD
        assert WORKFLOW_TO_PHASE["dev-story"] == Phase.DEV_STORY
        assert WORKFLOW_TO_PHASE["code-review"] == Phase.CODE_REVIEW
        assert WORKFLOW_TO_PHASE["code-review-synthesis"] == Phase.CODE_REVIEW_SYNTHESIS
        assert WORKFLOW_TO_PHASE["test-review"] == Phase.TEST_REVIEW
        assert WORKFLOW_TO_PHASE["retrospective"] == Phase.RETROSPECTIVE

    def test_unmapped_workflow(self) -> None:
        """Test that unmapped workflows return None via .get()."""
        assert WORKFLOW_TO_PHASE.get("test-design") is None
        assert WORKFLOW_TO_PHASE.get("unknown-workflow") is None


# =============================================================================
# ExperimentRunner Tests
# =============================================================================


class TestExperimentRunnerInit:
    """Tests for ExperimentRunner initialization."""

    def test_init_basic(self, tmp_path: Path) -> None:
        """Test basic initialization."""
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        runner = ExperimentRunner(exp_dir)

        assert runner._experiments_dir == exp_dir
        assert runner._project_root is None
        assert not runner._registries_initialized

    def test_init_with_project_root(self, tmp_path: Path) -> None:
        """Test initialization with project root."""
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        runner = ExperimentRunner(exp_dir, project_root)

        assert runner._project_root == project_root

    def test_registries_not_initialized_on_init(self, tmp_path: Path) -> None:
        """Test that registries are lazily initialized."""
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()

        runner = ExperimentRunner(exp_dir)

        assert runner._config_registry is None
        assert runner._loop_registry is None
        assert runner._patchset_registry is None
        assert runner._fixture_manager is None
        assert runner._isolator is None


class TestExperimentRunnerGenerateRunId:
    """Tests for run ID generation."""

    def test_generate_run_id_empty_dir(self, tmp_path: Path) -> None:
        """Test run ID generation with empty runs directory."""
        exp_dir = tmp_path / "experiments"
        (exp_dir / "runs").mkdir(parents=True)

        runner = ExperimentRunner(exp_dir)
        run_id = runner._generate_run_id()

        # Should be run-YYYY-MM-DD-001
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert run_id == f"run-{today}-001"

    def test_generate_run_id_sequential(self, tmp_path: Path) -> None:
        """Test run ID generation increments sequentially."""
        exp_dir = tmp_path / "experiments"
        runs_dir = exp_dir / "runs"
        runs_dir.mkdir(parents=True)

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Create existing runs
        (runs_dir / f"run-{today}-001").mkdir()
        (runs_dir / f"run-{today}-002").mkdir()
        (runs_dir / f"run-{today}-003").mkdir()

        runner = ExperimentRunner(exp_dir)
        run_id = runner._generate_run_id()

        assert run_id == f"run-{today}-004"

    def test_generate_run_id_with_gaps(self, tmp_path: Path) -> None:
        """Test run ID finds max, not next available."""
        exp_dir = tmp_path / "experiments"
        runs_dir = exp_dir / "runs"
        runs_dir.mkdir(parents=True)

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Create runs with gap (001, 005)
        (runs_dir / f"run-{today}-001").mkdir()
        (runs_dir / f"run-{today}-005").mkdir()

        runner = ExperimentRunner(exp_dir)
        run_id = runner._generate_run_id()

        # Should be 006, not 002
        assert run_id == f"run-{today}-006"

    def test_generate_run_id_no_runs_dir(self, tmp_path: Path) -> None:
        """Test run ID generation when runs directory doesn't exist."""
        exp_dir = tmp_path / "experiments"
        exp_dir.mkdir()  # but no runs subdir

        runner = ExperimentRunner(exp_dir)
        run_id = runner._generate_run_id()

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert run_id == f"run-{today}-001"


class TestExperimentRunnerRun:
    """Tests for ExperimentRunner.run() method."""

    @pytest.fixture
    def full_experiments_dir(self, tmp_path: Path) -> Path:
        """Create complete experiments directory structure."""
        exp_dir = tmp_path / "experiments"

        # Create configs
        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "opus-solo.yaml").write_text("""\
name: opus-solo
description: "Test config"
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        # Create loops
        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "standard.yaml").write_text("""\
name: standard
description: "Standard loop"
sequence:
  - workflow: create-story
    required: true
  - workflow: dev-story
    required: true
""")

        # Create patch-sets
        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "baseline.yaml").write_text("""\
name: baseline
description: "Baseline patches"
patches: {}
""")

        # Create fixtures
        fixtures = exp_dir / "fixtures"
        minimal_docs = fixtures / "minimal" / "docs"
        minimal_docs.mkdir(parents=True)
        (minimal_docs / "prd.md").write_text("# Minimal PRD")
        # Add epics file with stories for iteration
        (minimal_docs / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.

## Story 1.2: Second Story

**Status:** ready-for-dev

Second story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "minimal" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
  1-2-second-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: minimal
    name: "Minimal"
    path: ./minimal
    tags: [quick]
    difficulty: easy
    estimated_cost: "$0.10"
""")

        # Create runs directory
        (exp_dir / "runs").mkdir()

        return exp_dir

    @pytest.fixture
    def experiment_input(self) -> ExperimentInput:
        """Valid experiment input for testing."""
        return ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )

    @pytest.fixture
    def mock_execute_phase(self) -> MagicMock:
        """Mock for execute_phase that returns success."""
        with patch("bmad_assist.experiments.runner.execute_phase") as mock:
            mock.return_value = PhaseResult.ok()
            yield mock

    @pytest.fixture
    def mock_init_handlers(self) -> MagicMock:
        """Mock for init_handlers."""
        with patch("bmad_assist.experiments.runner.init_handlers") as mock:
            yield mock

    def test_run_unknown_fixture_raises(
        self, full_experiments_dir: Path, mock_init_handlers: MagicMock
    ) -> None:
        """Test that unknown fixture raises ConfigError."""
        runner = ExperimentRunner(full_experiments_dir)
        input = ExperimentInput(
            fixture="nonexistent",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )

        with pytest.raises(ConfigError):
            runner.run(input)

    def test_run_unknown_config_raises(
        self, full_experiments_dir: Path, mock_init_handlers: MagicMock
    ) -> None:
        """Test that unknown config raises ConfigError."""
        runner = ExperimentRunner(full_experiments_dir)
        input = ExperimentInput(
            fixture="minimal",
            config="nonexistent",
            patch_set="baseline",
            loop="standard",
        )

        with pytest.raises(ConfigError):
            runner.run(input)

    def test_run_unknown_patchset_raises(
        self, full_experiments_dir: Path, mock_init_handlers: MagicMock
    ) -> None:
        """Test that unknown patch-set raises ConfigError."""
        runner = ExperimentRunner(full_experiments_dir)
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="nonexistent",
            loop="standard",
        )

        with pytest.raises(ConfigError):
            runner.run(input)

    def test_run_unknown_loop_raises(
        self, full_experiments_dir: Path, mock_init_handlers: MagicMock
    ) -> None:
        """Test that unknown loop raises ConfigError."""
        runner = ExperimentRunner(full_experiments_dir)
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="nonexistent",
        )

        with pytest.raises(ConfigError):
            runner.run(input)

    def test_run_success(
        self,
        full_experiments_dir: Path,
        experiment_input: ExperimentInput,
        mock_execute_phase: MagicMock,
        mock_init_handlers: MagicMock,
    ) -> None:
        """Test successful run execution with story iteration."""
        runner = ExperimentRunner(full_experiments_dir)
        output = runner.run(experiment_input)

        assert output.status == ExperimentStatus.COMPLETED
        assert output.stories_attempted == 2  # Two stories in fixture
        assert output.stories_completed == 2
        assert output.stories_failed == 0
        assert output.error is None
        # Retrospective is auto-triggered after all stories complete
        assert output.retrospective_completed is True

    def test_run_creates_directories(
        self,
        full_experiments_dir: Path,
        experiment_input: ExperimentInput,
        mock_execute_phase: MagicMock,
        mock_init_handlers: MagicMock,
    ) -> None:
        """Test that run creates run directory and subdirectories."""
        runner = ExperimentRunner(full_experiments_dir)
        output = runner.run(experiment_input)

        run_dir = full_experiments_dir / "runs" / output.run_id
        assert run_dir.exists()
        assert (run_dir / "output").exists()
        assert (run_dir / "fixture-snapshot").exists()

    def test_run_with_custom_run_id(
        self,
        full_experiments_dir: Path,
        mock_execute_phase: MagicMock,
        mock_init_handlers: MagicMock,
    ) -> None:
        """Test run with custom run_id."""
        input = ExperimentInput(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
            run_id="custom-run-id",
        )
        runner = ExperimentRunner(full_experiments_dir)
        output = runner.run(input)

        assert output.run_id == "custom-run-id"

    def test_run_creates_state_file(
        self,
        full_experiments_dir: Path,
        experiment_input: ExperimentInput,
        mock_execute_phase: MagicMock,
        mock_init_handlers: MagicMock,
    ) -> None:
        """Test that run creates experiment state file."""
        runner = ExperimentRunner(full_experiments_dir)
        output = runner.run(experiment_input)

        state_file = full_experiments_dir / "runs" / output.run_id / "state.yaml"
        assert state_file.exists()


class TestExperimentRunnerPhaseFailed:
    """Tests for phase failure handling."""

    @pytest.fixture
    def experiments_with_optional_step(self, tmp_path: Path) -> Path:
        """Create experiments dir with optional step in loop."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "opus-solo.yaml").write_text("""\
name: opus-solo
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "with-optional.yaml").write_text("""\
name: with-optional
sequence:
  - workflow: create-story
    required: true
  - workflow: validate-story
    required: false
  - workflow: dev-story
    required: true
""")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "baseline.yaml").write_text("name: baseline\npatches: {}")

        fixtures = exp_dir / "fixtures"
        (fixtures / "minimal" / "docs").mkdir(parents=True)
        (fixtures / "minimal" / "docs" / "prd.md").write_text("# PRD")
        # Add epics file with stories for iteration
        (fixtures / "minimal" / "docs" / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "minimal" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: minimal
    name: Minimal
    path: ./minimal
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_required_step_failure_stops_with_fail_fast(
        self, experiments_with_optional_step: Path
    ) -> None:
        """Test that required=true step failure stops execution with --fail-fast."""
        call_count = 0

        def mock_phase(state: State) -> PhaseResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First step (create-story) fails
                return PhaseResult.fail("Phase failed")
            return PhaseResult.ok()

        with patch("bmad_assist.experiments.runner.execute_phase", side_effect=mock_phase):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_optional_step)
                input = ExperimentInput(
                    fixture="minimal",
                    config="opus-solo",
                    patch_set="baseline",
                    loop="with-optional",
                    fail_fast=True,  # Enable fail-fast
                )
                output = runner.run(input)

        assert output.status == ExperimentStatus.FAILED
        assert output.stories_failed == 1
        assert output.stories_attempted == 1  # Stopped after first failure
        assert "failed at" in output.error  # Error format: "Story X.X failed at phase"

    def test_required_step_failure_continues_without_fail_fast(
        self, experiments_with_optional_step: Path
    ) -> None:
        """Test that required step failure continues to next story without --fail-fast."""
        call_count = 0

        def mock_phase(state: State) -> PhaseResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First step (create-story) fails
                return PhaseResult.fail("Phase failed")
            return PhaseResult.ok()

        with patch("bmad_assist.experiments.runner.execute_phase", side_effect=mock_phase):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_optional_step)
                input = ExperimentInput(
                    fixture="minimal",
                    config="opus-solo",
                    patch_set="baseline",
                    loop="with-optional",
                    fail_fast=False,  # Default: continue on failure
                )
                output = runner.run(input)

        # With one story and fail_fast=False, the story fails but run completes
        assert output.status == ExperimentStatus.COMPLETED
        assert output.stories_failed == 1
        assert output.stories_attempted == 1

    def test_optional_step_failure_continues(self, experiments_with_optional_step: Path) -> None:
        """Test that required=false step failure continues execution."""
        call_count = 0

        def mock_phase(state: State) -> PhaseResult:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Second step (validate-story, optional) fails
                return PhaseResult.fail("Optional failed")
            return PhaseResult.ok()

        with patch("bmad_assist.experiments.runner.execute_phase", side_effect=mock_phase):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_optional_step)
                input = ExperimentInput(
                    fixture="minimal",
                    config="opus-solo",
                    patch_set="baseline",
                    loop="with-optional",
                )
                output = runner.run(input)

        # Optional step failure within a story doesn't count as story failure
        # Loop has: create-story (ok) -> validate (fail, optional) -> dev-story (ok)
        # That's one story completing with some phases failing
        assert output.status == ExperimentStatus.COMPLETED
        assert output.stories_completed == 1  # One story in fixture
        assert output.stories_attempted == 1


class TestExperimentRunnerCancellation:
    """Tests for cancellation support."""

    @pytest.fixture
    def simple_experiments_dir(self, tmp_path: Path) -> Path:
        """Create minimal experiments directory."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "test.yaml").write_text("""\
name: test
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "test.yaml").write_text("""\
name: test
sequence:
  - workflow: create-story
    required: true
  - workflow: dev-story
    required: true
  - workflow: code-review
    required: true
""")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "test.yaml").write_text("name: test\npatches: {}")

        fixtures = exp_dir / "fixtures"
        (fixtures / "test" / "docs").mkdir(parents=True)
        (fixtures / "test" / "docs" / "prd.md").write_text("# Test")
        # Add epics file with stories for iteration
        (fixtures / "test" / "docs" / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.

## Story 1.2: Second Story

**Status:** ready-for-dev

Second story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "test" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
  1-2-second-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: test
    name: Test
    path: ./test
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_cancellation_sets_status(self, simple_experiments_dir: Path) -> None:
        """Test that cancellation sets status to CANCELLED."""
        call_count = 0

        def mock_phase(state: State) -> PhaseResult:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Simulate signal after first phase of first story
                from bmad_assist.core.loop.signals import request_shutdown

                request_shutdown(signal.SIGINT)
            return PhaseResult.ok()

        with patch("bmad_assist.experiments.runner.execute_phase", side_effect=mock_phase):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(simple_experiments_dir)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="test",
                    loop="test",
                )
                output = runner.run(input)

        assert output.status == ExperimentStatus.CANCELLED
        # Cancellation during first story means no stories completed
        assert output.stories_attempted >= 0


class TestExperimentRunnerUnmappedWorkflows:
    """Tests for handling workflows without Phase mappings."""

    @pytest.fixture
    def experiments_with_unmapped(self, tmp_path: Path) -> Path:
        """Create experiments dir with unmapped workflow in loop."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "test.yaml").write_text("""\
name: test
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "with-unmapped.yaml").write_text("""\
name: with-unmapped
sequence:
  - workflow: test-design
    required: true
  - workflow: create-story
    required: true
""")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "test.yaml").write_text("name: test\npatches: {}")

        fixtures = exp_dir / "fixtures"
        (fixtures / "test" / "docs").mkdir(parents=True)
        (fixtures / "test" / "docs" / "prd.md").write_text("# Test")
        # Add epics file with one story for iteration
        (fixtures / "test" / "docs" / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "test" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: test
    name: Test
    path: ./test
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_unmapped_workflow_skipped(self, experiments_with_unmapped: Path) -> None:
        """Test that unmapped workflows are skipped and not counted."""
        with patch("bmad_assist.experiments.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_unmapped)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="test",
                    loop="with-unmapped",
                )
                output = runner.run(input)

        # One story should be executed (test-design is skipped as unmapped)
        assert output.stories_attempted == 1
        assert output.stories_completed == 1


class TestExperimentRunnerPatchApplication:
    """Tests for patch application."""

    @pytest.fixture
    def experiments_with_patches(self, tmp_path: Path) -> Path:
        """Create experiments dir with patch files."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "test.yaml").write_text("""\
name: test
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "test.yaml").write_text("""\
name: test
sequence:
  - workflow: create-story
    required: true
""")

        # Create patch file
        patches = exp_dir / "patches"
        patches.mkdir()
        (patches / "create-story.patch.yaml").write_text("# Test patch")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "with-patches.yaml").write_text(f"""\
name: with-patches
patches:
  create-story: {exp_dir}/patches/create-story.patch.yaml
""")

        fixtures = exp_dir / "fixtures"
        (fixtures / "test" / "docs").mkdir(parents=True)
        (fixtures / "test" / "docs" / "prd.md").write_text("# Test")
        # Add epics file with one story for iteration
        (fixtures / "test" / "docs" / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "test" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: test
    name: Test
    path: ./test
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_patch_copied_to_snapshot(self, experiments_with_patches: Path) -> None:
        """Test that patches are copied to snapshot directory."""
        with patch("bmad_assist.experiments.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_patches)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="with-patches",
                    loop="test",
                )
                output = runner.run(input)

        # Check patch was copied
        snapshot_patch = (
            experiments_with_patches
            / "runs"
            / output.run_id
            / "fixture-snapshot"
            / ".bmad-assist"
            / "patches"
            / "create-story.patch.yaml"
        )
        assert snapshot_patch.exists()
        assert snapshot_patch.read_text() == "# Test patch"

    @pytest.fixture
    def experiments_with_workflow_override(self, tmp_path: Path) -> Path:
        """Create experiments dir with workflow override."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "test.yaml").write_text("""\
name: test
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "test.yaml").write_text("""\
name: test
sequence:
  - workflow: create-story
    required: true
""")

        # Create workflow override directory
        overrides = exp_dir / "overrides" / "create-story"
        overrides.mkdir(parents=True)
        (overrides / "instructions.xml").write_text("<workflow>Custom</workflow>")
        (overrides / "config.yaml").write_text("name: custom-create-story")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "with-override.yaml").write_text(f"""\
name: with-override
patches: {{}}
workflow_overrides:
  create-story: {exp_dir}/overrides/create-story
""")

        fixtures = exp_dir / "fixtures"
        (fixtures / "test" / "docs").mkdir(parents=True)
        (fixtures / "test" / "docs" / "prd.md").write_text("# Test")
        # Add epics file with one story for iteration
        (fixtures / "test" / "docs" / "epics.md").write_text("""\
# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** ready-for-dev

First story description.
""")
        # Add sprint-status.yaml for story discovery
        impl_artifacts = fixtures / "test" / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text("""\
development_status:
  1-1-first-story: ready-for-dev
""")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: test
    name: Test
    path: ./test
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_workflow_override_copied_to_snapshot(
        self, experiments_with_workflow_override: Path
    ) -> None:
        """Test that workflow overrides are copied to snapshot directory."""
        with patch("bmad_assist.experiments.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(experiments_with_workflow_override)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="with-override",
                    loop="test",
                )
                output = runner.run(input)

        # Check workflow override was copied
        override_dir = (
            experiments_with_workflow_override
            / "runs"
            / output.run_id
            / "fixture-snapshot"
            / ".bmad-assist"
            / "overrides"
            / "create-story"
        )
        assert override_dir.exists()
        assert (override_dir / "instructions.xml").exists()
        assert (override_dir / "config.yaml").exists()
        assert (override_dir / "instructions.xml").read_text() == "<workflow>Custom</workflow>"


class TestExperimentRunnerStateIsolation:
    """Tests for state isolation."""

    @pytest.fixture
    def simple_experiments(self, tmp_path: Path) -> Path:
        """Create simple experiments dir."""
        exp_dir = tmp_path / "experiments"

        configs = exp_dir / "configs"
        configs.mkdir(parents=True)
        (configs / "test.yaml").write_text("""\
name: test
providers:
  master:
    provider: claude
    model: opus
  multi: []
""")

        loops = exp_dir / "loops"
        loops.mkdir()
        (loops / "test.yaml").write_text("""\
name: test
sequence:
  - workflow: create-story
    required: true
""")

        patchsets = exp_dir / "patch-sets"
        patchsets.mkdir()
        (patchsets / "test.yaml").write_text("name: test\npatches: {}")

        fixtures = exp_dir / "fixtures"
        (fixtures / "test" / "docs").mkdir(parents=True)
        (fixtures / "test" / "docs" / "prd.md").write_text("# Test")
        (fixtures / "registry.yaml").write_text("""\
fixtures:
  - id: test
    name: Test
    path: ./test
    tags: []
    difficulty: easy
    estimated_cost: "$0.00"
""")

        (exp_dir / "runs").mkdir()
        return exp_dir

    def test_state_file_in_run_dir(self, simple_experiments: Path) -> None:
        """Test that state file is in run directory, not project."""
        with patch("bmad_assist.experiments.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.experiments.runner.init_handlers"):
                runner = ExperimentRunner(simple_experiments)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="test",
                    loop="test",
                )
                output = runner.run(input)

        state_file = simple_experiments / "runs" / output.run_id / "state.yaml"
        assert state_file.exists()

        # Verify it contains expected content
        content = state_file.read_text()
        assert "current_phase" in content

    def test_handlers_initialized_with_snapshot_path(self, simple_experiments: Path) -> None:
        """Test that handlers are initialized with snapshot path."""
        init_calls = []

        def capture_init(config: Config, path: Path) -> None:
            init_calls.append(path)

        with patch("bmad_assist.experiments.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.experiments.runner.init_handlers", side_effect=capture_init):
                runner = ExperimentRunner(simple_experiments)
                input = ExperimentInput(
                    fixture="test",
                    config="test",
                    patch_set="test",
                    loop="test",
                )
                runner.run(input)

        assert len(init_calls) == 1
        # Should be fixture-snapshot path, not project root
        assert "fixture-snapshot" in str(init_calls[0])
