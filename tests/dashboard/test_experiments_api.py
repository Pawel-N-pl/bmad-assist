"""Tests for Experiments API - Story 19.1: Experiments List API + View.

Tests verify the experiments list endpoint for the dashboard:
- AC1: GET /api/experiments/runs returns list with pagination
- AC2: Filter by status, fixture, config, patch_set, loop
- AC3: Date range filtering (start_date, end_date)
- AC4: Sorting by started, completed, duration, status
- AC5: Pagination with offset/limit
- AC6: Empty results handling
- AC7: Invalid input validation (400 errors)
- AC8: Cache behavior (30-second TTL)
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.experiments import (
    CACHE_TTL_SECONDS,
    ExperimentRunSummary,
    PaginationInfo,
    clear_cache,
    discover_runs,
    filter_runs,
    format_duration,
    manifest_to_summary,
    sort_runs,
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
    else:
        mock.results = None
    mock.metrics = None
    return mock


@pytest.fixture
def mock_runs_list() -> list[MagicMock]:
    """Create a list of mock RunManifests for testing."""
    return [
        create_mock_manifest(
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
        ),
        create_mock_manifest(
            run_id="run-2026-01-09-002",
            status=ExperimentStatus.RUNNING,
            started=datetime(2026, 1, 9, 14, 0, 0, tzinfo=UTC),
            completed=None,
            fixture="complex",
            config="haiku-solo",
            patch_set="experimental",
            loop="fast",
        ),
        create_mock_manifest(
            run_id="run-2026-01-08-001",
            status=ExperimentStatus.FAILED,
            started=datetime(2026, 1, 8, 8, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 8, 8, 15, 0, tzinfo=UTC),
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
            stories_attempted=1,
            stories_completed=0,
            stories_failed=1,
        ),
    ]


# =============================================================================
# Unit Tests: Response Models
# =============================================================================


class TestExperimentRunSummary:
    """Tests for ExperimentRunSummary Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN ExperimentRunSummary is created
        THEN model validates successfully.
        """
        summary = ExperimentRunSummary(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=datetime(2026, 1, 10, 11, 0, 0, tzinfo=UTC),
            duration_seconds=3600.0,
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            results={"stories_attempted": 5, "stories_completed": 4, "stories_failed": 1},
            metrics={"total_cost": 1.5, "total_tokens": 10000},
        )
        assert summary.run_id == "run-001"
        assert summary.status == "completed"

    def test_model_with_optional_fields_none(self) -> None:
        """GIVEN optional fields as None
        WHEN ExperimentRunSummary is created
        THEN model validates successfully.
        """
        summary = ExperimentRunSummary(
            run_id="run-001",
            status="running",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
            duration_seconds=None,
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            results=None,
            metrics=None,
        )
        assert summary.completed is None
        assert summary.results is None
        assert summary.metrics is None

    def test_model_is_frozen(self) -> None:
        """GIVEN ExperimentRunSummary model
        WHEN attempting to modify after creation
        THEN raises error (frozen model).
        """
        summary = ExperimentRunSummary(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
            duration_seconds=None,
            input={
                "fixture": "minimal",
                "config": "opus-solo",
                "patch_set": "baseline",
                "loop": "standard",
            },
            results=None,
            metrics=None,
        )
        with pytest.raises(Exception):  # Pydantic ValidationError for frozen
            summary.run_id = "changed"


class TestPaginationInfo:
    """Tests for PaginationInfo model."""

    def test_pagination_info_creation(self) -> None:
        """GIVEN pagination parameters
        WHEN PaginationInfo is created
        THEN model contains correct values.
        """
        info = PaginationInfo(total=100, offset=20, limit=10, has_more=True)
        assert info.total == 100
        assert info.offset == 20
        assert info.limit == 10
        assert info.has_more is True

    def test_pagination_has_more_false_at_end(self) -> None:
        """GIVEN offset + limit >= total
        WHEN PaginationInfo is created with has_more=False
        THEN has_more is False.
        """
        info = PaginationInfo(total=25, offset=20, limit=10, has_more=False)
        assert info.has_more is False


# =============================================================================
# Unit Tests: Filtering
# =============================================================================


class TestFilterRuns:
    """Tests for filter_runs function."""

    def test_filter_by_status(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different statuses
        WHEN filtering by status='completed'
        THEN returns only completed runs.
        """
        result = filter_runs(mock_runs_list, status="completed")
        assert len(result) == 1
        assert result[0].status == ExperimentStatus.COMPLETED

    def test_filter_by_status_running(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different statuses
        WHEN filtering by status='running'
        THEN returns only running runs.
        """
        result = filter_runs(mock_runs_list, status="running")
        assert len(result) == 1
        assert result[0].status == ExperimentStatus.RUNNING

    def test_filter_by_invalid_status_raises(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN filtering by invalid status
        THEN raises ValueError.
        """
        with pytest.raises(ValueError, match="Invalid status"):
            filter_runs(mock_runs_list, status="invalid_status")

    def test_filter_by_fixture_case_insensitive(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different fixtures
        WHEN filtering by fixture (case-insensitive)
        THEN returns matching runs.
        """
        result = filter_runs(mock_runs_list, fixture="MINIMAL")
        assert len(result) == 2
        assert all(r.input.fixture == "minimal" for r in result)

    def test_filter_by_config(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different configs
        WHEN filtering by config
        THEN returns matching runs.
        """
        result = filter_runs(mock_runs_list, config="opus-solo")
        assert len(result) == 2
        assert all(r.input.config == "opus-solo" for r in result)

    def test_filter_by_patch_set(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different patch sets
        WHEN filtering by patch_set
        THEN returns matching runs.
        """
        result = filter_runs(mock_runs_list, patch_set="experimental")
        assert len(result) == 1
        assert result[0].input.patch_set == "experimental"

    def test_filter_by_loop(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different loops
        WHEN filtering by loop
        THEN returns matching runs.
        """
        result = filter_runs(mock_runs_list, loop="fast")
        assert len(result) == 1
        assert result[0].input.loop == "fast"

    def test_filter_by_start_date(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different start dates
        WHEN filtering by start_date
        THEN returns runs started on or after date.
        """
        result = filter_runs(mock_runs_list, start_date="2026-01-09")
        assert len(result) == 2
        for r in result:
            assert r.started >= datetime(2026, 1, 9, tzinfo=UTC)

    def test_filter_by_end_date(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different start dates
        WHEN filtering by end_date
        THEN returns runs started on or before date (includes entire day).
        """
        result = filter_runs(mock_runs_list, end_date="2026-01-09")
        assert len(result) == 2
        for r in result:
            assert r.started < datetime(2026, 1, 10, tzinfo=UTC)

    def test_filter_by_date_range(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different start dates
        WHEN filtering by start_date and end_date
        THEN returns runs in date range.
        """
        result = filter_runs(mock_runs_list, start_date="2026-01-09", end_date="2026-01-09")
        assert len(result) == 1
        assert result[0].run_id == "run-2026-01-09-002"

    def test_filter_invalid_start_date_format(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN filtering with invalid start_date format
        THEN raises ValueError.
        """
        with pytest.raises(ValueError, match="Invalid start_date format"):
            filter_runs(mock_runs_list, start_date="not-a-date")

    def test_filter_invalid_end_date_format(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN filtering with invalid end_date format
        THEN raises ValueError.
        """
        with pytest.raises(ValueError, match="Invalid end_date format"):
            filter_runs(mock_runs_list, end_date="not-a-date")

    def test_filter_start_after_end_raises(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN start_date is after end_date
        THEN raises ValueError.
        """
        with pytest.raises(ValueError, match="start_date must be before"):
            filter_runs(mock_runs_list, start_date="2026-01-15", end_date="2026-01-10")

    def test_filter_multiple_criteria_and_logic(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN filtering with multiple criteria
        THEN criteria combine with AND logic.
        """
        result = filter_runs(mock_runs_list, status="completed", fixture="minimal")
        assert len(result) == 1
        assert result[0].status == ExperimentStatus.COMPLETED
        assert result[0].input.fixture == "minimal"

    def test_filter_no_match_returns_empty(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN filter matches no runs
        THEN returns empty list.
        """
        result = filter_runs(mock_runs_list, fixture="nonexistent")
        assert result == []


# =============================================================================
# Unit Tests: Sorting
# =============================================================================


class TestSortRuns:
    """Tests for sort_runs function."""

    def test_sort_by_started_desc_default(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different start times
        WHEN sorting by started (default desc)
        THEN returns runs sorted by started descending.
        """
        result = sort_runs(mock_runs_list, sort_by="started", sort_order="desc")
        assert result[0].run_id == "run-2026-01-10-001"
        assert result[-1].run_id == "run-2026-01-08-001"

    def test_sort_by_started_asc(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different start times
        WHEN sorting by started ascending
        THEN returns runs sorted by started ascending.
        """
        result = sort_runs(mock_runs_list, sort_by="started", sort_order="asc")
        assert result[0].run_id == "run-2026-01-08-001"
        assert result[-1].run_id == "run-2026-01-10-001"

    def test_sort_by_completed_with_nulls(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with some completed=None
        WHEN sorting by completed
        THEN nulls are handled (last for asc, first for desc per AC4).
        """
        # Ascending: nulls last
        result_asc = sort_runs(mock_runs_list, sort_by="completed", sort_order="asc")
        assert result_asc[-1].completed is None

        # Descending: nulls first (per AC4 - active/incomplete runs at top)
        result_desc = sort_runs(mock_runs_list, sort_by="completed", sort_order="desc")
        assert result_desc[0].completed is None

    def test_sort_by_duration_with_nulls(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with some completed=None (no duration)
        WHEN sorting by duration
        THEN nulls are handled (last for asc, first for desc per AC4).
        """
        # Ascending: nulls last
        result_asc = sort_runs(mock_runs_list, sort_by="duration", sort_order="asc")
        assert result_asc[-1].completed is None  # No duration (running)

        # Descending: nulls first (per AC4 - active/incomplete runs at top)
        result_desc = sort_runs(mock_runs_list, sort_by="duration", sort_order="desc")
        assert result_desc[0].completed is None

    def test_sort_by_status(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs with different statuses
        WHEN sorting by status
        THEN returns runs sorted alphabetically by status value.
        """
        result = sort_runs(mock_runs_list, sort_by="status", sort_order="asc")
        statuses = [r.status.value for r in result]
        assert statuses == sorted(statuses)

    def test_sort_invalid_field_defaults_to_started(self, mock_runs_list: list[MagicMock]) -> None:
        """GIVEN runs list
        WHEN sorting by invalid field
        THEN defaults to sorting by started.
        """
        result = sort_runs(mock_runs_list, sort_by="invalid_field")
        # Should be same as started desc
        expected = sort_runs(mock_runs_list, sort_by="started", sort_order="desc")
        assert [r.run_id for r in result] == [r.run_id for r in expected]


# =============================================================================
# Unit Tests: Helper Functions
# =============================================================================


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_format_duration_none_returns_dash(self) -> None:
        """GIVEN None duration
        WHEN formatting
        THEN returns '-'.
        """
        assert format_duration(None) == "-"

    def test_format_duration_seconds_only(self) -> None:
        """GIVEN duration under 60 seconds
        WHEN formatting
        THEN returns Xs format.
        """
        assert format_duration(45.0) == "45s"

    def test_format_duration_minutes_and_seconds(self) -> None:
        """GIVEN duration under 1 hour
        WHEN formatting
        THEN returns Xm Ys format.
        """
        assert format_duration(125.0) == "2m 5s"

    def test_format_duration_hours_minutes_seconds(self) -> None:
        """GIVEN duration over 1 hour
        WHEN formatting
        THEN returns Xh Ym Zs format.
        """
        assert format_duration(3725.0) == "1h 2m 5s"


class TestManifestToSummary:
    """Tests for manifest_to_summary function."""

    def test_converts_completed_run(self) -> None:
        """GIVEN completed RunManifest (mock)
        WHEN converting to summary
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
        summary = manifest_to_summary(mock)
        assert summary.run_id == "run-2026-01-10-001"
        assert summary.status == "completed"
        assert summary.duration_seconds == 5400.0  # 1.5 hours
        assert summary.input["fixture"] == "minimal"
        assert summary.results is not None
        assert summary.results["stories_attempted"] == 5

    def test_converts_running_run(self) -> None:
        """GIVEN running RunManifest (no completed)
        WHEN converting to summary
        THEN duration_seconds is None.
        """
        mock = create_mock_manifest(
            run_id="run-001",
            status=ExperimentStatus.RUNNING,
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            completed=None,
        )
        summary = manifest_to_summary(mock)
        assert summary.duration_seconds is None
        assert summary.completed is None
        assert summary.results is None


# =============================================================================
# API Integration Tests
# =============================================================================


class TestExperimentsRunsEndpoint:
    """Tests for GET /api/experiments/runs endpoint."""

    @pytest.mark.asyncio
    async def test_get_experiments_runs_returns_200(self, tmp_path: Path) -> None:
        """GIVEN dashboard server with no experiments
        WHEN GET /api/experiments/runs is called
        THEN returns 200 with empty runs list.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs")

            assert response.status_code == 200
            data = response.json()
            assert "runs" in data
            assert "pagination" in data
            assert data["runs"] == []

    @pytest.mark.asyncio
    async def test_get_experiments_runs_returns_expected_structure(self, tmp_path: Path) -> None:
        """GIVEN dashboard server
        WHEN GET /api/experiments/runs is called
        THEN returns JSON with runs[] and pagination.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs")

            assert response.status_code == 200
            data = response.json()
            # Check pagination structure
            assert "total" in data["pagination"]
            assert "offset" in data["pagination"]
            assert "limit" in data["pagination"]
            assert "has_more" in data["pagination"]

    @pytest.mark.asyncio
    async def test_get_experiments_runs_pagination_defaults(self, tmp_path: Path) -> None:
        """GIVEN no pagination params
        WHEN GET /api/experiments/runs is called
        THEN uses default offset=0, limit=20.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs")

            data = response.json()
            assert data["pagination"]["offset"] == 0
            assert data["pagination"]["limit"] == 20

    @pytest.mark.asyncio
    async def test_get_experiments_runs_pagination_custom(self, tmp_path: Path) -> None:
        """GIVEN custom pagination params
        WHEN GET /api/experiments/runs?offset=10&limit=25
        THEN uses provided values.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?offset=10&limit=25")

            data = response.json()
            assert data["pagination"]["offset"] == 10
            assert data["pagination"]["limit"] == 25

    @pytest.mark.asyncio
    async def test_get_experiments_runs_invalid_offset_returns_400(self, tmp_path: Path) -> None:
        """GIVEN negative offset
        WHEN GET /api/experiments/runs?offset=-1
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?offset=-1")

            assert response.status_code == 400
            assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_get_experiments_runs_limit_capped_at_max(self, tmp_path: Path) -> None:
        """GIVEN limit exceeds maximum
        WHEN GET /api/experiments/runs?limit=1000
        THEN limit is capped to 100.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?limit=1000")

            assert response.status_code == 200
            data = response.json()
            assert data["pagination"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_get_experiments_runs_zero_limit_returns_400(self, tmp_path: Path) -> None:
        """GIVEN limit of 0
        WHEN GET /api/experiments/runs?limit=0
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?limit=0")

            assert response.status_code == 400
            assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_get_experiments_runs_invalid_status_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid status filter
        WHEN GET /api/experiments/runs?status=invalid
        THEN returns 400 with error message.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?status=invalid_status")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "filter_error"
            assert "Invalid status" in data["message"]

    @pytest.mark.asyncio
    async def test_get_experiments_runs_invalid_date_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid date format
        WHEN GET /api/experiments/runs?start_date=not-a-date
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/runs?start_date=not-a-date")

            assert response.status_code == 400
            assert "error" in response.json()


# =============================================================================
# Cache Tests
# =============================================================================


class TestDiscoverRunsCache:
    """Tests for discover_runs caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_returns_cached_results_within_ttl(self, tmp_path: Path) -> None:
        """GIVEN cached runs
        WHEN discover_runs is called within TTL
        THEN returns cached results without re-scanning.
        """
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"
        runs_dir.mkdir(parents=True)

        # First call
        result1 = await discover_runs(experiments_dir)
        assert result1 == []  # No manifests

    @pytest.mark.asyncio
    async def test_cache_ttl_is_30_seconds(self) -> None:
        """GIVEN cache TTL constant
        WHEN checking value
        THEN is 30 seconds.
        """
        assert CACHE_TTL_SECONDS == 30.0


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_nonexistent_runs_dir_returns_empty(self, tmp_path: Path) -> None:
        """GIVEN experiments directory without runs subdirectory
        WHEN discover_runs is called
        THEN returns empty list.
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir(parents=True)
        # No runs/ subdirectory

        result = await discover_runs(experiments_dir)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_runs_dir_returns_empty(self, tmp_path: Path) -> None:
        """GIVEN empty runs directory
        WHEN discover_runs is called
        THEN returns empty list.
        """
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"
        runs_dir.mkdir(parents=True)

        result = await discover_runs(experiments_dir)
        assert result == []

    @pytest.mark.asyncio
    async def test_run_dir_without_manifest_skipped(self, tmp_path: Path) -> None:
        """GIVEN run directory without manifest.yaml
        WHEN discover_runs is called
        THEN directory is skipped.
        """
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"
        run_dir = runs_dir / "run-no-manifest"
        run_dir.mkdir(parents=True)
        # No manifest.yaml

        result = await discover_runs(experiments_dir)
        assert result == []
