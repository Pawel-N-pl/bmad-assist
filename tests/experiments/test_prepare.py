"""Tests for experiment benchmark preparer module.

Tests cover:
- PrepareResult and RunData Pydantic models
- BenchmarkPreparer initialization and mode validation
- Project mode (backward compatible) benchmark preparation
- Experiments mode with fixture grouping
- File discovery patterns (primary and fallback locations)
- Model name resolution
- Summary schema compatibility
- Index file generation
- Error handling for missing/invalid files
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.experiments.prepare import (
    BenchmarkPreparer,
    PrepareResult,
    RunData,
    _build_model_lookup,
    _calculate_model_aggregates,
    _calculate_phase_aggregates,
    _calculate_rankings,
    _condense_story_data,
    _extract_essential_metrics,
    _find_project_files,
    _load_benchmark_record,
    _load_validation_mappings,
    _pearson,
    _resolve_model_name,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create temp project directory with required structure."""
    project = tmp_path / "test-project"
    project.mkdir()
    (project / "docs").mkdir()
    (project / "_bmad-output" / "implementation-artifacts" / "benchmarks" / "2026-01").mkdir(
        parents=True
    )
    (project / "_bmad-output" / "implementation-artifacts" / "code-reviews").mkdir(parents=True)
    (project / "_bmad-output" / "implementation-artifacts" / "story-validations").mkdir(
        parents=True
    )
    (project / ".bmad-assist" / "cache").mkdir(parents=True)
    return project


@pytest.fixture
def experiments_dir(tmp_path: Path) -> Path:
    """Create temp experiments directory with runs."""
    experiments = tmp_path / "experiments"
    runs_dir = experiments / "runs"
    runs_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def sample_benchmark_record() -> dict[str, Any]:
    """Sample benchmark evaluation record."""
    return {
        "evaluator": {
            "role": "validator",
            "role_id": "a",
            "session_id": "sess-123",
            "provider": "claude-subprocess-sonnet",
            "model": "sonnet",
        },
        "story": {
            "epic_num": 18,
            "story_num": 1,
        },
        "workflow": {
            "id": "validate-story",
        },
        "execution": {
            "duration_ms": 45000,
            "output_tokens": 2500,
        },
        "findings": {
            "total_count": 5,
            "by_severity": {
                "critical": 1,
                "warning": 3,
                "info": 1,
            },
        },
        "quality": {
            "actionable_ratio": 0.8,
            "specificity_score": 0.75,
            "evidence_quality": 0.9,
            "internal_consistency": 0.85,
        },
    }


@pytest.fixture
def sample_validation_mapping() -> dict[str, Any]:
    """Sample validation mapping JSON."""
    return {
        "session_id": "mapping-session-001",
        "mapping": {
            "Validator A": {
                "provider_session_id": "sess-123",
                "provider": "claude-subprocess-sonnet",
                "model": "sonnet",
            },
            "Validator B": {
                "provider_session_id": "sess-456",
                "provider": "gemini-gemini-2.5-flash",
                "model": "gemini-2.5-flash",
            },
        },
    }


@pytest.fixture
def sample_manifest_yaml() -> dict[str, Any]:
    """Sample run manifest YAML."""
    return {
        "run_id": "run-001",
        "started": "2026-01-07T15:30:00Z",
        "completed": "2026-01-07T16:45:00Z",
        "status": "completed",
        "schema_version": "1.0",
        "input": {
            "fixture": "minimal",
            "config": "opus-solo",
            "patch_set": "baseline",
            "loop": "standard",
        },
        "resolved": {
            "fixture": {
                "name": "minimal",
                "source": "/fixtures/minimal",
                "snapshot": "./fixture-snapshot",
            },
            "config": {
                "name": "opus-solo",
                "source": "/configs/opus-solo.yaml",
                "providers": {"master": {"provider": "claude", "model": "opus"}, "multi": []},
            },
            "patch_set": {
                "name": "baseline",
                "source": "/patch-sets/baseline.yaml",
                "workflow_overrides": {},
                "patches": {},
            },
            "loop": {
                "name": "standard",
                "source": "/loops/standard.yaml",
                "sequence": ["create-story", "dev-story"],
            },
        },
        "results": None,
        "metrics": None,
    }


# =============================================================================
# PrepareResult Model Tests
# =============================================================================


class TestPrepareResult:
    """Tests for PrepareResult Pydantic model."""

    def test_create_with_required_fields(self, tmp_path: Path) -> None:
        """Test creation with all required fields."""
        result = PrepareResult(
            fixture_or_project="test-project",
            output_path=tmp_path / "output.json",
            runs_processed=10,
            evals_count=50,
            total_time_minutes=45.5,
            models=["opus", "sonnet"],
            generated_at=datetime.now(UTC),
        )
        assert result.fixture_or_project == "test-project"
        assert result.runs_processed == 10
        assert result.evals_count == 50
        assert "opus" in result.models

    def test_model_is_frozen(self, tmp_path: Path) -> None:
        """Test that PrepareResult is immutable."""
        result = PrepareResult(
            fixture_or_project="test",
            output_path=tmp_path / "output.json",
            runs_processed=5,
            evals_count=20,
            total_time_minutes=10.0,
            models=["opus"],
            generated_at=datetime.now(UTC),
        )
        with pytest.raises(Exception):  # Pydantic ValidationError for frozen model
            result.runs_processed = 100  # type: ignore

    def test_serialization(self, tmp_path: Path) -> None:
        """Test model serializes correctly."""
        result = PrepareResult(
            fixture_or_project="test-project",
            output_path=tmp_path / "output.json",
            runs_processed=10,
            evals_count=50,
            total_time_minutes=45.5,
            models=["opus", "sonnet"],
            generated_at=datetime(2026, 1, 7, 15, 30, 0, tzinfo=UTC),
        )
        data = result.model_dump(mode="json")
        assert data["fixture_or_project"] == "test-project"
        assert isinstance(data["output_path"], str)
        assert data["generated_at"] == "2026-01-07T15:30:00+00:00"


# =============================================================================
# RunData Model Tests
# =============================================================================


class TestRunData:
    """Tests for RunData Pydantic model."""

    def test_create_with_required_fields(self, tmp_path: Path) -> None:
        """Test creation with required fields."""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text("# manifest")

        run_data = RunData(
            run_id="run-001",
            fixture="minimal",
            manifest_path=manifest_path,
        )
        assert run_data.run_id == "run-001"
        assert run_data.fixture == "minimal"
        assert run_data.metrics_path is None
        assert run_data.benchmark_files == []

    def test_create_with_all_fields(self, tmp_path: Path) -> None:
        """Test creation with all optional fields."""
        manifest_path = tmp_path / "manifest.yaml"
        metrics_path = tmp_path / "metrics.yaml"
        benchmark_files = [tmp_path / "eval-1.yaml", tmp_path / "eval-2.yaml"]

        run_data = RunData(
            run_id="run-002",
            fixture="complex",
            manifest_path=manifest_path,
            metrics_path=metrics_path,
            benchmark_files=benchmark_files,
            mapping_files=[tmp_path / "mapping.json"],
            code_review_syntheses=[tmp_path / "synthesis.md"],
            validation_syntheses=[tmp_path / "val-synthesis.md"],
        )
        assert run_data.fixture == "complex"
        assert len(run_data.benchmark_files) == 2
        assert len(run_data.mapping_files) == 1

    def test_model_is_frozen(self, tmp_path: Path) -> None:
        """Test that RunData is immutable."""
        run_data = RunData(
            run_id="run-001",
            fixture="minimal",
            manifest_path=tmp_path / "manifest.yaml",
        )
        with pytest.raises(Exception):
            run_data.fixture = "changed"  # type: ignore


# =============================================================================
# BenchmarkPreparer Initialization Tests
# =============================================================================


class TestBenchmarkPreparerInit:
    """Tests for BenchmarkPreparer initialization."""

    def test_init_with_valid_path(self, project_dir: Path) -> None:
        """Test initialization with valid directory."""
        preparer = BenchmarkPreparer(project_dir, mode="project")
        assert preparer.mode == "project"
        assert preparer.base_dir == project_dir

    def test_init_with_nonexistent_path(self, tmp_path: Path) -> None:
        """Test initialization fails with nonexistent path."""
        with pytest.raises(ConfigError, match="does not exist"):
            BenchmarkPreparer(tmp_path / "nonexistent")

    def test_init_default_mode(self, project_dir: Path) -> None:
        """Test default mode is project."""
        preparer = BenchmarkPreparer(project_dir)
        assert preparer.mode == "project"

    def test_init_experiments_mode(self, experiments_dir: Path) -> None:
        """Test experiments mode initialization."""
        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        assert preparer.mode == "experiments"


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestResolveModelName:
    """Tests for _resolve_model_name function."""

    def test_resolve_claude_subprocess(self) -> None:
        """Test resolving claude-subprocess provider."""
        entry = {"provider": "claude-subprocess-glm-4.7", "model": "sonnet"}
        assert _resolve_model_name(entry) == "glm-4.7"

    def test_resolve_gemini_provider(self) -> None:
        """Test resolving gemini provider."""
        entry = {"provider": "gemini-gemini-2.5-flash", "model": "gemini-2.5-flash"}
        assert _resolve_model_name(entry) == "gemini-2.5-flash"

    def test_resolve_unknown_provider(self) -> None:
        """Test fallback to model field for unknown provider."""
        entry = {"provider": "unknown", "model": "custom-model"}
        assert _resolve_model_name(entry) == "custom-model"

    def test_resolve_empty_provider(self) -> None:
        """Test fallback when provider is empty."""
        entry = {"provider": "", "model": "default-model"}
        assert _resolve_model_name(entry) == "default-model"


class TestBuildModelLookup:
    """Tests for _build_model_lookup function."""

    def test_build_lookup_from_mapping(self, sample_validation_mapping: dict[str, Any]) -> None:
        """Test building model lookup from validation mappings."""
        mappings = {"mapping-session-001": sample_validation_mapping}
        lookup = _build_model_lookup(mappings)

        assert "sess-123" in lookup
        assert lookup["sess-123"]["model"] == "sonnet"
        assert "sess-456" in lookup
        assert lookup["sess-456"]["model"] == "gemini-2.5-flash"

    def test_empty_mappings(self) -> None:
        """Test with empty mappings."""
        lookup = _build_model_lookup({})
        assert lookup == {}


class TestLoadBenchmarkRecord:
    """Tests for _load_benchmark_record function."""

    def test_load_valid_record(
        self, tmp_path: Path, sample_benchmark_record: dict[str, Any]
    ) -> None:
        """Test loading valid benchmark record."""
        path = tmp_path / "eval-18-1.yaml"
        path.write_text(yaml.dump(sample_benchmark_record))

        record = _load_benchmark_record(path)
        assert record is not None
        assert record["evaluator"]["role"] == "validator"

    def test_skip_index_file(self, tmp_path: Path) -> None:
        """Test that index.yaml is skipped."""
        path = tmp_path / "index.yaml"
        path.write_text("entries: []")

        record = _load_benchmark_record(path)
        assert record is None

    def test_skip_non_eval_file(self, tmp_path: Path) -> None:
        """Test that non-eval files are skipped."""
        path = tmp_path / "summary.yaml"
        path.write_text("summary: data")

        record = _load_benchmark_record(path)
        assert record is None

    def test_skip_invalid_yaml(self, tmp_path: Path) -> None:
        """Test handling invalid YAML."""
        path = tmp_path / "eval-bad.yaml"
        path.write_text("invalid: yaml: content: [")

        record = _load_benchmark_record(path)
        assert record is None


class TestExtractEssentialMetrics:
    """Tests for _extract_essential_metrics function."""

    def test_extract_all_fields(self, sample_benchmark_record: dict[str, Any]) -> None:
        """Test extracting all metrics fields."""
        metrics = _extract_essential_metrics(sample_benchmark_record)

        assert metrics["role"] == "validator"
        assert metrics["role_id"] == "a"
        assert metrics["dur_ms"] == 45000
        assert metrics["tokens"] == 2500
        assert metrics["findings"]["total"] == 5
        assert "quality" not in metrics

    def test_extract_minimal_record(self) -> None:
        """Test extracting from minimal record."""
        record = {
            "evaluator": {"role": "synthesizer"},
            "execution": {},
        }
        metrics = _extract_essential_metrics(record)

        assert metrics["role"] == "synthesizer"
        assert metrics["dur_ms"] == 0
        assert "findings" not in metrics


class TestCalculateAggregates:
    """Tests for aggregate calculation functions."""

    def test_model_aggregates_with_data(self) -> None:
        """Test model aggregate calculation."""
        models_raw = {
            "opus": [
                {"dur_ms": 100, "tokens": 1000},
                {"dur_ms": 200, "tokens": 2000},
            ],
            "sonnet": [
                {"dur_ms": 50, "tokens": 500},
            ],
        }
        aggs = _calculate_model_aggregates(models_raw)

        assert aggs["opus"]["evals"] == 2
        assert aggs["opus"]["dur_avg"] == 150
        assert aggs["opus"]["tokens_total"] == 3000
        assert aggs["sonnet"]["evals"] == 1

    def test_phase_aggregates(self) -> None:
        """Test phase aggregate calculation."""
        phases_raw = {
            "create-story": [1000, 2000, 3000],
            "dev-story": [5000, 6000],
        }
        aggs = _calculate_phase_aggregates(phases_raw)

        assert aggs["create-story"]["count"] == 3
        assert aggs["create-story"]["total_ms"] == 6000
        assert aggs["dev-story"]["count"] == 2

    def test_rankings_calculation(self) -> None:
        """Test model rankings calculation."""
        model_aggs = {
            "opus": {"dur_avg": 100, "quality_avg": {"actionable": 0.9}},
            "sonnet": {"dur_avg": 200, "quality_avg": {"actionable": 0.8}},
        }
        rankings = _calculate_rankings(model_aggs)

        assert rankings["speed"][0] == "opus"  # Faster
        assert rankings["quality"][0] == "opus"  # Higher quality


class TestPearsonCorrelation:
    """Tests for _pearson correlation function."""

    def test_perfect_positive(self) -> None:
        """Test perfect positive correlation."""
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        assert _pearson(x, y) == 1.0

    def test_perfect_negative(self) -> None:
        """Test perfect negative correlation."""
        x = [1, 2, 3, 4, 5]
        y = [10, 8, 6, 4, 2]
        assert _pearson(x, y) == -1.0

    def test_no_correlation(self) -> None:
        """Test zero correlation with constant values."""
        x = [1, 1, 1]
        y = [2, 2, 2]
        assert _pearson(x, y) == 0.0

    def test_insufficient_data(self) -> None:
        """Test with single data point."""
        x = [1]
        y = [2]
        assert _pearson(x, y) == 0.0


class TestCondenseStoryData:
    """Tests for _condense_story_data function."""

    def test_condense_validators(self) -> None:
        """Test condensing validator records."""
        records = [
            {
                "role": "validator",
                "role_id": "a",
                "model_resolved": "opus",
                "dur_ms": 1000,
                "tokens": 500,
                "quality": {"actionable": 0.8},
                "findings": {"total": 3, "by_sev": {"critical": 1}},
            },
        ]
        condensed = _condense_story_data(records)

        assert "v" in condensed
        assert "a" in condensed["v"]
        assert condensed["v"]["a"]["model"] == "opus"
        assert condensed["v"]["a"]["findings"] == 3

    def test_condense_synthesizer(self) -> None:
        """Test condensing synthesizer record."""
        records = [
            {
                "role": "synthesizer",
                "model_resolved": "opus",
                "dur_ms": 2000,
                "tokens": 1000,
                "consensus": {"agreed": 5, "disputed": 1},
            },
        ]
        condensed = _condense_story_data(records)

        assert "s" in condensed
        assert condensed["s"]["model"] == "opus"
        assert condensed["s"]["consensus"]["agreed"] == 5


# =============================================================================
# Project Mode Tests
# =============================================================================


class TestProjectMode:
    """Tests for project mode benchmark preparation."""

    def test_prepare_empty_project(self, tmp_path: Path) -> None:
        """Test prepare_project with no benchmark files."""
        project = tmp_path / "empty-project"
        project.mkdir()

        preparer = BenchmarkPreparer(project, mode="project")
        with pytest.raises(ConfigError, match="No benchmark or synthesis files"):
            preparer.prepare_project()

    def test_prepare_with_benchmark_files(
        self, project_dir: Path, sample_benchmark_record: dict[str, Any]
    ) -> None:
        """Test prepare_project with benchmark files."""
        # Create benchmark file
        benchmark_path = (
            project_dir
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
            / "eval-18-1-validator-a-12345.yaml"
        )
        benchmark_path.write_text(yaml.dump(sample_benchmark_record))

        preparer = BenchmarkPreparer(project_dir, mode="project")
        result = preparer.prepare_project()

        assert result.fixture_or_project == project_dir.name
        assert result.runs_processed > 0
        assert result.output_path.exists()

    def test_prepare_stdout_mode(
        self,
        project_dir: Path,
        sample_benchmark_record: dict[str, Any],
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Test prepare_project with stdout output."""
        benchmark_path = (
            project_dir
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
            / "eval-18-1-validator-a-12345.yaml"
        )
        benchmark_path.write_text(yaml.dump(sample_benchmark_record))

        preparer = BenchmarkPreparer(project_dir, mode="project")
        result = preparer.prepare_project(stdout=True)

        captured = capsys.readouterr()
        # Output should contain valid JSON (may have log messages before it)
        output = captured.out
        json_start = output.find("{")
        if json_start == -1:
            pytest.fail(f"No JSON object found in output: {output}")
        output_data = json.loads(output[json_start:])
        assert "meta" in output_data


# =============================================================================
# Experiments Mode Tests
# =============================================================================


class TestExperimentsMode:
    """Tests for experiments mode benchmark preparation."""

    def test_prepare_no_runs(self, experiments_dir: Path) -> None:
        """Test prepare_experiments with no runs."""
        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        results = preparer.prepare_experiments()
        assert results == {}

    def test_discover_runs(self, experiments_dir: Path) -> None:
        """Test run discovery."""
        runs_dir = experiments_dir / "experiments" / "runs"
        (runs_dir / "run-001").mkdir()
        (runs_dir / "run-002").mkdir()

        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        runs = preparer._discover_runs()
        assert len(runs) == 2

    def test_load_run_data_invalid_manifest(self, experiments_dir: Path) -> None:
        """Test loading run with invalid manifest."""
        run_dir = experiments_dir / "experiments" / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        # No manifest.yaml

        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        run_data = preparer._load_run_data(run_dir)
        assert run_data is None

    def test_load_run_data_valid_manifest(
        self, experiments_dir: Path, sample_manifest_yaml: dict[str, Any]
    ) -> None:
        """Test loading run with valid manifest."""
        run_dir = experiments_dir / "experiments" / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        manifest_path = run_dir / "manifest.yaml"
        manifest_path.write_text(yaml.dump(sample_manifest_yaml))

        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        run_data = preparer._load_run_data(run_dir)

        assert run_data is not None
        assert run_data.run_id == "run-001"
        assert run_data.fixture == "minimal"

    def test_group_by_fixture(self, tmp_path: Path) -> None:
        """Test fixture grouping logic."""
        runs = [
            RunData(
                run_id="run-001",
                fixture="minimal",
                manifest_path=tmp_path / "m1.yaml",
            ),
            RunData(
                run_id="run-002",
                fixture="minimal",
                manifest_path=tmp_path / "m2.yaml",
            ),
            RunData(
                run_id="run-003",
                fixture="complex",
                manifest_path=tmp_path / "m3.yaml",
            ),
        ]

        preparer = BenchmarkPreparer(tmp_path, mode="experiments")
        grouped = preparer._group_by_fixture(runs)

        assert len(grouped) == 2
        assert len(grouped["minimal"]) == 2
        assert len(grouped["complex"]) == 1

    def test_prepare_experiments_with_runs(
        self,
        experiments_dir: Path,
        sample_manifest_yaml: dict[str, Any],
        sample_benchmark_record: dict[str, Any],
    ) -> None:
        """Test full experiments mode preparation."""
        # Create run-001
        run_dir = experiments_dir / "experiments" / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.yaml").write_text(yaml.dump(sample_manifest_yaml))

        # Create benchmark files in fixture-snapshot (fallback location)
        benchmark_dir = (
            run_dir
            / "fixture-snapshot"
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
        )
        benchmark_dir.mkdir(parents=True)
        (benchmark_dir / "eval-18-1-validator-a-12345.yaml").write_text(
            yaml.dump(sample_benchmark_record)
        )

        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        results = preparer.prepare_experiments()

        assert "minimal" in results
        assert results["minimal"].runs_processed == 1


# =============================================================================
# Index Generation Tests
# =============================================================================


class TestIndexGeneration:
    """Tests for index file generation."""

    def test_generate_experiments_index(self, tmp_path: Path) -> None:
        """Test index generation for experiments mode."""
        results = {
            "minimal": PrepareResult(
                fixture_or_project="minimal",
                output_path=tmp_path / "benchmark-minimal.json",
                runs_processed=2,
                evals_count=20,
                total_time_minutes=15.0,
                models=["opus", "sonnet"],
                generated_at=datetime.now(UTC),
            ),
            "complex": PrepareResult(
                fixture_or_project="complex",
                output_path=tmp_path / "benchmark-complex.json",
                runs_processed=1,
                evals_count=10,
                total_time_minutes=25.0,
                models=["opus"],
                generated_at=datetime.now(UTC),
            ),
        }

        summaries = {
            "minimal": {"meta": {"stories": 5}},
            "complex": {"meta": {"stories": 3}},
        }

        preparer = BenchmarkPreparer(tmp_path, mode="experiments")
        index = preparer._generate_index(results, tmp_path, "20260107T120000", summaries)

        assert index["mode"] == "experiments"
        assert index["aggregate"]["fixtures"] == 2
        assert index["aggregate"]["runs"] == 3
        assert index["aggregate"]["evals"] == 30
        assert "minimal" in index["fixtures"]
        assert "complex" in index["fixtures"]


# =============================================================================
# File Discovery Tests
# =============================================================================


class TestFileDiscovery:
    """Tests for file discovery patterns."""

    def test_find_project_files(self, project_dir: Path) -> None:
        """Test finding files in project structure."""
        # Create test files
        benchmark_path = (
            project_dir
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
            / "eval-test.yaml"
        )
        benchmark_path.write_text("test: data")

        mapping_path = project_dir / ".bmad-assist" / "cache" / "validation-mapping-test.json"
        mapping_path.write_text('{"session_id": "test"}')

        benchmark_files, mapping_files, cr_files, val_files = _find_project_files(project_dir)

        assert len(benchmark_files) == 1
        assert len(mapping_files) == 1

    def test_find_files_empty_project(self, tmp_path: Path) -> None:
        """Test finding files in empty project."""
        project = tmp_path / "empty"
        project.mkdir()

        benchmark_files, mapping_files, cr_files, val_files = _find_project_files(project)

        assert benchmark_files == []
        assert mapping_files == []


# =============================================================================
# Validation Mapping Tests
# =============================================================================


class TestValidationMappings:
    """Tests for validation mapping loading."""

    def test_load_valid_mappings(
        self, tmp_path: Path, sample_validation_mapping: dict[str, Any]
    ) -> None:
        """Test loading valid mapping files."""
        mapping_path = tmp_path / "mapping.json"
        mapping_path.write_text(json.dumps(sample_validation_mapping))

        mappings = _load_validation_mappings([mapping_path])
        assert "mapping-session-001" in mappings

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        """Test handling invalid JSON mapping files."""
        mapping_path = tmp_path / "bad-mapping.json"
        mapping_path.write_text("not valid json {")

        mappings = _load_validation_mappings([mapping_path])
        assert mappings == {}

    def test_load_missing_session_id(self, tmp_path: Path) -> None:
        """Test handling mapping without session_id."""
        mapping_path = tmp_path / "no-session.json"
        mapping_path.write_text('{"mapping": {}}')

        mappings = _load_validation_mappings([mapping_path])
        assert mappings == {}


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_invalid_base_dir(self, tmp_path: Path) -> None:
        """Test ConfigError for invalid base directory."""
        with pytest.raises(ConfigError, match="does not exist"):
            BenchmarkPreparer(tmp_path / "nonexistent")

    def test_corrupt_benchmark_file(self, project_dir: Path) -> None:
        """Test handling corrupt benchmark files gracefully."""
        benchmark_path = (
            project_dir
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
            / "eval-corrupt.yaml"
        )
        benchmark_path.write_text("invalid: yaml: [")

        # Should not raise, just skip the corrupt file
        benchmark_files, _, _, _ = _find_project_files(project_dir)
        for bf in benchmark_files:
            record = _load_benchmark_record(bf)
            # Corrupt files return None


# =============================================================================
# Schema Compatibility Tests
# =============================================================================


class TestSchemaCompatibility:
    """Tests for output schema compatibility."""

    def test_project_mode_schema(
        self, project_dir: Path, sample_benchmark_record: dict[str, Any]
    ) -> None:
        """Test project mode output matches expected schema."""
        benchmark_path = (
            project_dir
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
            / "eval-18-1-validator-a-12345.yaml"
        )
        benchmark_path.write_text(yaml.dump(sample_benchmark_record))

        preparer = BenchmarkPreparer(project_dir, mode="project")
        result = preparer.prepare_project()

        # Load and verify schema
        with open(result.output_path) as f:
            data = json.load(f)

        # Required top-level keys
        assert "meta" in data
        assert "phases" in data
        assert "models" in data
        assert "stories" in data
        assert "rankings" in data

        # Meta structure
        assert "project" in data["meta"]
        assert "stories" in data["meta"]
        assert "evals" in data["meta"]
        assert "total_time_min" in data["meta"]
        assert "models" in data["meta"]

    def test_experiments_mode_schema(
        self,
        experiments_dir: Path,
        sample_manifest_yaml: dict[str, Any],
        sample_benchmark_record: dict[str, Any],
    ) -> None:
        """Test experiments mode output has extended schema."""
        # Create run
        run_dir = experiments_dir / "experiments" / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.yaml").write_text(yaml.dump(sample_manifest_yaml))

        benchmark_dir = (
            run_dir
            / "fixture-snapshot"
            / "_bmad-output"
            / "implementation-artifacts"
            / "benchmarks"
            / "2026-01"
        )
        benchmark_dir.mkdir(parents=True)
        (benchmark_dir / "eval-18-1-validator-a-12345.yaml").write_text(
            yaml.dump(sample_benchmark_record)
        )

        preparer = BenchmarkPreparer(experiments_dir, mode="experiments")
        results = preparer.prepare_experiments()

        # Load and verify extended schema
        output_path = results["minimal"].output_path
        with open(output_path) as f:
            data = json.load(f)

        # Extended meta keys for experiments mode
        assert "fixture" in data["meta"]
        assert "run_count" in data["meta"]

        # Stories have runs nested
        if data["stories"]:
            first_story = list(data["stories"].values())[0]
            assert "runs" in first_story
