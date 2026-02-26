"""Tests for Experiment Details API - Story 19.2: Run Details View.

Tests verify the experiment details endpoints for the dashboard:
- AC1: GET /api/experiments/runs/{run_id} returns full details
- AC2: Run lookup with path traversal validation
- AC3: Response models (PhaseDetails, ExperimentRunDetails)
- AC6: GET /api/experiments/runs/{run_id}/manifest returns raw manifest
- AC7: Error handling (400, 404, 500)
- AC8: Unit and integration tests
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.experiments import (
    ExperimentRunDetails,
    PhaseDetails,
    ResolvedDetails,
    clear_cache,
    get_run_by_id,
    manifest_to_details,
    validate_run_id,
)
from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.experiments import ExperimentStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_experiments_cache() -> None:
    """Clear the experiments cache before each test."""
    clear_cache()


def create_mock_manifest(
    run_id: str = "run-001",
    status: ExperimentStatus = ExperimentStatus.COMPLETED,
    started: datetime | None = None,
    completed: datetime | None = None,
    fixture: str = "minimal",
    config: str = "opus-solo",
    patch_set: str = "baseline",
    loop: str = "standard",
    stories_attempted: int | None = None,
    stories_completed: int | None = None,
    stories_failed: int | None = None,
    phases: list | None = None,
) -> MagicMock:
    """Create a mock manifest object with the given attributes."""
    mock = MagicMock()
    mock.run_id = run_id
    mock.status = status
    mock.started = started or datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)
    mock.completed = completed
    mock.input = MagicMock()
    mock.input.fixture = fixture
    mock.input.config = config
    mock.input.patch_set = patch_set
    mock.input.loop = loop
    if stories_attempted is not None:
        mock.results = MagicMock()
        mock.results.stories_attempted = stories_attempted
        mock.results.stories_completed = stories_completed or 0
        mock.results.stories_failed = stories_failed or 0
        mock.results.phases = phases or []
    else:
        mock.results = None
    mock.metrics = None

    # Resolved configuration (mocked as objects matching Resolved* models)
    mock.resolved = MagicMock()
    # ResolvedFixture: name, source, snapshot
    mock.resolved.fixture = MagicMock()
    mock.resolved.fixture.name = fixture
    mock.resolved.fixture.source = f"/path/to/{fixture}"
    mock.resolved.fixture.snapshot = f"snapshot/{fixture}"
    # ResolvedConfig: name, source, providers
    mock.resolved.config = MagicMock()
    mock.resolved.config.name = config
    mock.resolved.config.source = f"/path/to/{config}.yaml"
    mock.resolved.config.providers = {"master": {"provider": "claude", "model": "opus"}}
    # ResolvedPatchSet: name, source, workflow_overrides, patches
    mock.resolved.patch_set = MagicMock()
    mock.resolved.patch_set.name = patch_set
    mock.resolved.patch_set.source = f"/path/to/{patch_set}.yaml"
    mock.resolved.patch_set.workflow_overrides = {}
    mock.resolved.patch_set.patches = {}
    # ResolvedLoop: name, source, sequence
    mock.resolved.loop = MagicMock()
    mock.resolved.loop.name = loop
    mock.resolved.loop.source = f"/path/to/{loop}.yaml"
    mock.resolved.loop.sequence = ["create-story", "validate-story", "dev-story"]

    return mock


def create_mock_phase(
    phase: str = "create-story",
    story: str | None = "1-1",
    status: str = "completed",
    started: datetime | None = None,
    completed: datetime | None = None,
    tokens: int | None = 1000,
    cost: float | None = 0.01,
    error: str | None = None,
) -> MagicMock:
    """Create a mock phase result."""
    mock = MagicMock()
    mock.phase = phase
    mock.story = story
    mock.status = status
    mock.started = started or datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)
    mock.completed = completed or datetime(2026, 1, 10, 10, 5, 0, tzinfo=UTC)
    mock.tokens = tokens
    mock.cost = cost
    mock.error = error
    return mock


# =============================================================================
# Unit Tests: validate_run_id
# =============================================================================


class TestValidateRunId:
    """Tests for validate_run_id function (AC2)."""

    def test_valid_run_id_alphanumeric(self) -> None:
        """GIVEN alphanumeric run_id
        WHEN validating
        THEN returns True.
        """
        assert validate_run_id("run2026011001") is True

    def test_valid_run_id_with_hyphens(self) -> None:
        """GIVEN run_id with hyphens
        WHEN validating
        THEN returns True.
        """
        assert validate_run_id("run-2026-01-10-001") is True

    def test_valid_run_id_with_underscores(self) -> None:
        """GIVEN run_id with underscores
        WHEN validating
        THEN returns True.
        """
        assert validate_run_id("run_2026_01_10_001") is True

    def test_valid_run_id_mixed(self) -> None:
        """GIVEN run_id with mixed characters
        WHEN validating
        THEN returns True.
        """
        assert validate_run_id("Run-2026_01-Test_001") is True

    def test_invalid_run_id_with_slash(self) -> None:
        """GIVEN run_id with forward slash (path traversal)
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("../secret") is False
        assert validate_run_id("run/../../etc/passwd") is False

    def test_invalid_run_id_with_backslash(self) -> None:
        """GIVEN run_id with backslash
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("run\\..\\secret") is False

    def test_invalid_run_id_with_dots(self) -> None:
        """GIVEN run_id with dots (period)
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("..") is False
        assert validate_run_id("run.test") is False

    def test_invalid_run_id_with_spaces(self) -> None:
        """GIVEN run_id with spaces
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("run 001") is False

    def test_invalid_run_id_empty(self) -> None:
        """GIVEN empty run_id
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("") is False

    def test_invalid_run_id_special_chars(self) -> None:
        """GIVEN run_id with special characters
        WHEN validating
        THEN returns False.
        """
        assert validate_run_id("run@test") is False
        assert validate_run_id("run#001") is False
        assert validate_run_id("run$001") is False


# =============================================================================
# Unit Tests: Response Models (AC3)
# =============================================================================


class TestPhaseDetails:
    """Tests for PhaseDetails Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN PhaseDetails is created
        THEN model validates successfully.
        """
        phase = PhaseDetails(
            phase="create-story",
            story="1-1",
            status="completed",
            duration_seconds=300.0,
            duration_formatted="5m 0s",
            tokens=1500,
            cost=0.015,
            error=None,
        )
        assert phase.phase == "create-story"
        assert phase.story == "1-1"
        assert phase.status == "completed"
        assert phase.duration_seconds == 300.0

    def test_model_with_optional_fields_none(self) -> None:
        """GIVEN optional fields as None
        WHEN PhaseDetails is created
        THEN model validates successfully.
        """
        phase = PhaseDetails(
            phase="dev-story",
            story=None,
            status="skipped",
            duration_seconds=0.0,
            duration_formatted="0s",
            tokens=None,
            cost=None,
            error=None,
        )
        assert phase.story is None
        assert phase.tokens is None
        assert phase.cost is None

    def test_model_with_error(self) -> None:
        """GIVEN failed phase with error
        WHEN PhaseDetails is created
        THEN error field is populated.
        """
        phase = PhaseDetails(
            phase="validate-story",
            story="1-2",
            status="failed",
            duration_seconds=60.0,
            duration_formatted="1m 0s",
            tokens=500,
            cost=0.005,
            error="Validation failed: story context missing",
        )
        assert phase.status == "failed"
        assert "Validation failed" in phase.error

    def test_model_is_frozen(self) -> None:
        """GIVEN PhaseDetails model
        WHEN attempting to modify after creation
        THEN raises error (frozen model).
        """
        phase = PhaseDetails(
            phase="create-story",
            story="1-1",
            status="completed",
            duration_seconds=300.0,
            duration_formatted="5m 0s",
            tokens=None,
            cost=None,
            error=None,
        )
        with pytest.raises(Exception):  # Pydantic ValidationError for frozen
            phase.phase = "changed"


class TestResolvedDetails:
    """Tests for ResolvedDetails Pydantic model."""

    def test_model_creation(self) -> None:
        """GIVEN resolved configuration dicts
        WHEN ResolvedDetails is created
        THEN model validates successfully.
        """
        resolved = ResolvedDetails(
            fixture={"id": "minimal", "description": "Minimal test fixture"},
            config={"provider": "claude", "model": "opus"},
            patch_set={"name": "baseline"},
            loop={"name": "standard", "max_iterations": 3},
        )
        assert resolved.fixture["id"] == "minimal"
        assert resolved.config["provider"] == "claude"
        assert resolved.patch_set["name"] == "baseline"
        assert resolved.loop["max_iterations"] == 3


class TestExperimentRunDetails:
    """Tests for ExperimentRunDetails Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN ExperimentRunDetails is created
        THEN model validates successfully.
        """
        details = ExperimentRunDetails(
            run_id="run-2026-01-10-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 11, 30, 0, tzinfo=UTC),
            duration_seconds=5400.0,
            duration_formatted="1h 30m 0s",
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            resolved=ResolvedDetails(
                fixture={"id": "minimal"},
                config={"provider": "claude"},
                patch_set={"name": "baseline"},
                loop={"name": "standard"},
            ),
            results={"stories_attempted": 5, "stories_completed": 4, "stories_failed": 1},
            metrics={"total_cost": 1.5, "total_tokens": 10000},
            phases=[
                PhaseDetails(
                    phase="create-story",
                    story="1-1",
                    status="completed",
                    duration_seconds=300.0,
                    duration_formatted="5m 0s",
                    tokens=1000,
                    cost=0.01,
                    error=None,
                )
            ],
        )
        assert details.run_id == "run-2026-01-10-001"
        assert details.status == "completed"
        assert details.duration_seconds == 5400.0
        assert len(details.phases) == 1

    def test_model_with_optional_fields_none(self) -> None:
        """GIVEN running experiment with optional fields as None
        WHEN ExperimentRunDetails is created
        THEN model validates successfully.
        """
        details = ExperimentRunDetails(
            run_id="run-001",
            status="running",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
            duration_seconds=None,
            duration_formatted="-",
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            resolved=ResolvedDetails(
                fixture={},
                config={},
                patch_set={},
                loop={},
            ),
            results=None,
            metrics=None,
            phases=[],
        )
        assert details.completed is None
        assert details.duration_seconds is None
        assert details.results is None
        assert details.metrics is None

    def test_model_is_frozen(self) -> None:
        """GIVEN ExperimentRunDetails model
        WHEN attempting to modify after creation
        THEN raises error (frozen model).
        """
        details = ExperimentRunDetails(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
            duration_seconds=None,
            duration_formatted="-",
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            resolved=ResolvedDetails(fixture={}, config={}, patch_set={}, loop={}),
            results=None,
            metrics=None,
            phases=[],
        )
        with pytest.raises(Exception):  # Pydantic ValidationError for frozen
            details.run_id = "changed"


# =============================================================================
# Unit Tests: manifest_to_details
# =============================================================================


class TestManifestToDetails:
    """Tests for manifest_to_details function."""

    def test_converts_completed_run(self) -> None:
        """GIVEN completed RunManifest
        WHEN converting to details
        THEN all fields populated correctly.
        """
        mock = create_mock_manifest(
            run_id="run-2026-01-10-001",
            status=ExperimentStatus.COMPLETED,
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 11, 30, 0, tzinfo=UTC),
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
            stories_attempted=5,
            stories_completed=4,
            stories_failed=1,
        )
        details = manifest_to_details(mock)
        assert details.run_id == "run-2026-01-10-001"
        assert details.status == "completed"
        assert details.duration_seconds == 5400.0  # 1.5 hours
        assert details.duration_formatted == "1h 30m 0s"
        assert details.input["fixture"] == "minimal"
        assert details.results is not None
        assert details.results["stories_attempted"] == 5

    def test_converts_running_run(self) -> None:
        """GIVEN running RunManifest
        WHEN converting to details
        THEN duration is None.
        """
        mock = create_mock_manifest(
            run_id="run-001",
            status=ExperimentStatus.RUNNING,
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
        )
        details = manifest_to_details(mock)
        assert details.duration_seconds is None
        assert details.duration_formatted == "-"
        assert details.completed is None
        assert details.results is None

    def test_converts_resolved_configuration(self) -> None:
        """GIVEN manifest with resolved config
        WHEN converting to details
        THEN resolved fields are populated.
        """
        mock = create_mock_manifest(
            run_id="run-001",
            status=ExperimentStatus.COMPLETED,
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 11, 0, 0, tzinfo=UTC),
        )
        details = manifest_to_details(mock)
        # Check resolved structure matches Resolved* models
        assert details.resolved.fixture["name"] == "minimal"
        assert details.resolved.config["name"] == "opus-solo"
        assert "providers" in details.resolved.config
        assert details.resolved.patch_set["name"] == "baseline"
        assert details.resolved.loop["name"] == "standard"

    def test_converts_phases(self) -> None:
        """GIVEN manifest with phases
        WHEN converting to details
        THEN phases are converted to PhaseDetails.
        """
        phase1 = create_mock_phase(
            phase="create-story",
            story="1-1",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 10, 5, 0, tzinfo=UTC),
            tokens=1000,
            cost=0.01,
        )
        phase2 = create_mock_phase(
            phase="dev-story",
            story="1-1",
            status="failed",
            started=datetime(2026, 1, 10, 10, 5, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 10, 10, 0, tzinfo=UTC),
            tokens=500,
            cost=0.005,
            error="Dev failed",
        )
        mock = create_mock_manifest(
            run_id="run-001",
            status=ExperimentStatus.FAILED,
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 10, 10, 0, tzinfo=UTC),
            stories_attempted=1,
            stories_completed=0,
            stories_failed=1,
            phases=[phase1, phase2],
        )
        details = manifest_to_details(mock)
        assert len(details.phases) == 2
        assert details.phases[0].phase == "create-story"
        assert details.phases[0].status == "completed"
        assert details.phases[1].status == "failed"
        assert details.phases[1].error == "Dev failed"

    def test_handles_none_resolved(self) -> None:
        """GIVEN manifest with None resolved sections
        WHEN converting to details
        THEN resolved contains dicts with None values for required fields.
        """
        mock = create_mock_manifest(run_id="run-001")
        mock.resolved = None
        details = manifest_to_details(mock)
        # When resolved is None, helper functions return dicts with None values
        assert details.resolved.fixture == {"name": None, "source": None, "snapshot": None}
        assert details.resolved.config == {"name": None, "source": None, "providers": {}}
        assert details.resolved.patch_set == {
            "name": None,
            "source": None,
            "workflow_overrides": {},
            "patches": {},
        }
        assert details.resolved.loop == {"name": None, "source": None, "sequence": []}


# =============================================================================
# Unit Tests: get_run_by_id
# =============================================================================


class TestGetRunById:
    """Tests for get_run_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_run(self, tmp_path: Path) -> None:
        """GIVEN experiments directory without the run
        WHEN get_run_by_id is called
        THEN returns None.
        """
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"
        runs_dir.mkdir(parents=True)

        result = await get_run_by_id("nonexistent-run", experiments_dir)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_run_without_manifest(self, tmp_path: Path) -> None:
        """GIVEN run directory without manifest.yaml
        WHEN get_run_by_id is called
        THEN returns None.
        """
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"
        run_dir = runs_dir / "run-001"
        run_dir.mkdir(parents=True)
        # No manifest.yaml

        result = await get_run_by_id("run-001", experiments_dir)
        assert result is None


# =============================================================================
# API Integration Tests: GET /api/experiments/runs/{run_id}
# =============================================================================


class TestGetExperimentRunEndpoint:
    """Tests for GET /api/experiments/runs/{run_id} endpoint (AC1)."""

    @pytest.mark.asyncio
    async def test_invalid_run_id_with_special_chars_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid run_id format with special characters
        WHEN GET /api/experiments/runs/run@test
        THEN returns 400 Bad Request.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs/run@test")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "bad_request"
            assert "Invalid run_id format" in data["message"]

    @pytest.mark.asyncio
    async def test_invalid_run_id_with_dots_returns_400(self, tmp_path: Path) -> None:
        """GIVEN run_id with dots
        WHEN GET /api/experiments/runs/run.test
        THEN returns 400 Bad Request.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs/run.test")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "bad_request"

    @pytest.mark.asyncio
    async def test_nonexistent_run_returns_404(self, tmp_path: Path) -> None:
        """GIVEN valid run_id that doesn't exist
        WHEN GET /api/experiments/runs/nonexistent-run
        THEN returns 404 Not Found.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        # Create experiments directory structure
        experiments_dir = tmp_path / "experiments" / "runs"
        experiments_dir.mkdir(parents=True)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs/nonexistent-run")

            assert response.status_code == 404
            data = response.json()
            assert data["error"] == "not_found"
            assert "not found" in data["message"].lower()


# =============================================================================
# API Integration Tests: GET /api/experiments/runs/{run_id}/manifest
# =============================================================================


class TestGetExperimentManifestEndpoint:
    """Tests for GET /api/experiments/runs/{run_id}/manifest endpoint (AC6)."""

    @pytest.mark.asyncio
    async def test_invalid_run_id_with_special_chars_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid run_id format with special characters
        WHEN GET /api/experiments/runs/run@test/manifest
        THEN returns 400 Bad Request.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs/run@test/manifest")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "bad_request"

    @pytest.mark.asyncio
    async def test_nonexistent_run_returns_404(self, tmp_path: Path) -> None:
        """GIVEN valid run_id that doesn't exist
        WHEN GET /api/experiments/runs/nonexistent-run/manifest
        THEN returns 404 Not Found.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        # Create experiments directory structure
        experiments_dir = tmp_path / "experiments" / "runs"
        experiments_dir.mkdir(parents=True)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs/nonexistent-run/manifest")

            assert response.status_code == 404
            data = response.json()
            assert data["error"] == "not_found"
