"""Tests for Experiments Fixtures API - Story 19.3: Fixture Browser.

Tests verify the fixtures API endpoints for the dashboard:
- AC1: GET /api/experiments/fixtures returns list with filters and sorting
- AC2: GET /api/experiments/fixtures/{id} returns fixture details
- AC3: Fixture discovery with caching
- AC4: Run statistics calculation
- AC5: Filter implementation (tags, difficulty)
- AC8: Empty and error states
- AC9: Unit and integration tests
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.experiments import (
    FIXTURES_CACHE_TTL_SECONDS,
    FixtureDetails,
    FixtureRunInfo,
    FixtureStats,
    FixtureSummary,
    clear_fixtures_cache,
    discover_fixtures,
    get_fixture_run_stats,
)
from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.experiments import ExperimentStatus, FixtureEntry

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    """Clear the fixtures cache before each test."""
    clear_fixtures_cache()
    # Also clear runs cache
    from bmad_assist.dashboard.experiments import clear_cache

    clear_cache()


def create_mock_fixture(
    fixture_id: str = "minimal",
    name: str = "Minimal Fixture",
    description: str | None = "Test fixture",
    path: str = "./minimal",
    tags: list[str] | None = None,
    difficulty: str = "easy",
    estimated_cost: str = "$0.10",
) -> MagicMock:
    """Create a mock FixtureEntry."""
    mock = MagicMock(spec=FixtureEntry)
    mock.id = fixture_id
    mock.name = name
    mock.description = description
    mock.path = path
    mock.tags = tags if tags is not None else []
    mock.difficulty = difficulty
    mock.estimated_cost = estimated_cost
    return mock


def create_mock_run(
    run_id: str = "run-001",
    fixture: str = "minimal",
    config: str = "opus-solo",
    status: ExperimentStatus = ExperimentStatus.COMPLETED,
    started: datetime | None = None,
) -> MagicMock:
    """Create a mock RunManifest."""
    mock = MagicMock()
    mock.run_id = run_id
    mock.input = MagicMock()
    mock.input.fixture = fixture
    mock.input.config = config
    mock.status = status
    mock.started = started or datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)
    return mock


# =============================================================================
# Unit Tests: Response Models
# =============================================================================


class TestFixtureRunInfo:
    """Tests for FixtureRunInfo Pydantic model."""

    def test_model_creation(self) -> None:
        """GIVEN all fields provided
        WHEN FixtureRunInfo is created
        THEN model validates successfully.
        """
        info = FixtureRunInfo(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            config="opus-solo",
        )
        assert info.run_id == "run-001"
        assert info.status == "completed"
        assert info.config == "opus-solo"

    def test_model_is_frozen(self) -> None:
        """GIVEN FixtureRunInfo model
        WHEN attempting to modify after creation
        THEN raises error (frozen model).
        """
        info = FixtureRunInfo(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            config="opus-solo",
        )
        with pytest.raises(Exception):
            info.run_id = "changed"


class TestFixtureSummary:
    """Tests for FixtureSummary Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN FixtureSummary is created
        THEN model validates successfully.
        """
        summary = FixtureSummary(
            id="minimal",
            name="Minimal Fixture",
            description="Test fixture",
            path="./minimal",
            tags=["quick", "basic"],
            difficulty="easy",
            estimated_cost="$0.10",
            estimated_cost_value=0.10,
            run_count=5,
            last_run=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
        )
        assert summary.id == "minimal"
        assert summary.estimated_cost_value == 0.10
        assert summary.run_count == 5

    def test_model_with_optional_fields_none(self) -> None:
        """GIVEN optional fields as None
        WHEN FixtureSummary is created
        THEN model validates successfully.
        """
        summary = FixtureSummary(
            id="minimal",
            name="Minimal Fixture",
            description=None,
            path="./minimal",
            tags=[],
            difficulty="easy",
            estimated_cost="$0.10",
            estimated_cost_value=0.10,
            run_count=0,
            last_run=None,
        )
        assert summary.description is None
        assert summary.last_run is None


class TestFixtureDetails:
    """Tests for FixtureDetails Pydantic model."""

    def test_model_creation_with_recent_runs(self) -> None:
        """GIVEN all fields including recent_runs
        WHEN FixtureDetails is created
        THEN model validates successfully.
        """
        details = FixtureDetails(
            id="minimal",
            name="Minimal Fixture",
            description="Test fixture",
            path="./minimal",
            resolved_path="/abs/path/minimal",
            tags=["quick"],
            difficulty="easy",
            estimated_cost="$0.10",
            estimated_cost_value=0.10,
            run_count=2,
            last_run=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            recent_runs=[
                FixtureRunInfo(
                    run_id="run-001",
                    status="completed",
                    started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
                    config="opus-solo",
                ),
            ],
        )
        assert len(details.recent_runs) == 1
        assert details.resolved_path == "/abs/path/minimal"


# =============================================================================
# Unit Tests: Fixture Discovery
# =============================================================================


class TestDiscoverFixtures:
    """Tests for discover_fixtures function (auto-discovery API)."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_missing_fixtures_dir(self, tmp_path: Path) -> None:
        """GIVEN experiments dir without fixtures subdirectory
        WHEN discover_fixtures is called
        THEN returns empty list (new auto-discovery API).
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir()

        result = await discover_fixtures(experiments_dir)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_fixtures_for_directories(self, tmp_path: Path) -> None:
        """GIVEN experiments/fixtures with subdirectories
        WHEN discover_fixtures is called
        THEN returns list of FixtureEntry objects.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)
        (fixtures_dir / "minimal").mkdir()

        result = await discover_fixtures(tmp_path / "experiments")
        assert len(result) == 1
        assert result[0].id == "minimal"

    @pytest.mark.asyncio
    async def test_caches_result_within_ttl(self, tmp_path: Path) -> None:
        """GIVEN cached fixtures
        WHEN discover_fixtures is called within TTL
        THEN returns cached results.
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir()

        # First call
        result1 = await discover_fixtures(experiments_dir)
        assert result1 == []

        # Second call should use cache
        result2 = await discover_fixtures(experiments_dir)
        assert result2 == []


class TestCacheTTL:
    """Tests for cache TTL configuration."""

    def test_fixtures_cache_ttl_is_60_seconds(self) -> None:
        """GIVEN fixtures cache TTL constant
        WHEN checking value
        THEN is 60 seconds.
        """
        assert FIXTURES_CACHE_TTL_SECONDS == 60.0


# =============================================================================
# Unit Tests: Run Statistics
# =============================================================================


class TestGetFixtureRunStats:
    """Tests for get_fixture_run_stats function."""

    def test_calculates_run_count(self) -> None:
        """GIVEN fixtures and runs
        WHEN calculating stats
        THEN run_count is correct.
        """
        fixtures = [create_mock_fixture("minimal")]
        runs = [
            create_mock_run(
                run_id="run-001",
                fixture="minimal",
                started=datetime(2026, 1, 10, tzinfo=UTC),
            ),
            create_mock_run(
                run_id="run-002",
                fixture="minimal",
                started=datetime(2026, 1, 9, tzinfo=UTC),
            ),
        ]

        stats = get_fixture_run_stats(fixtures, runs)
        assert stats["minimal"].run_count == 2

    def test_calculates_last_run(self) -> None:
        """GIVEN fixtures and runs sorted desc
        WHEN calculating stats
        THEN last_run is most recent.
        """
        fixtures = [create_mock_fixture("minimal")]
        runs = [
            create_mock_run(
                run_id="run-001",
                fixture="minimal",
                started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            ),
            create_mock_run(
                run_id="run-002",
                fixture="minimal",
                started=datetime(2026, 1, 9, 10, 0, 0, tzinfo=UTC),
            ),
        ]

        stats = get_fixture_run_stats(fixtures, runs)
        assert stats["minimal"].last_run == datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)

    def test_limits_recent_runs_to_5(self) -> None:
        """GIVEN fixture with more than 5 runs
        WHEN calculating stats
        THEN recent_runs is limited to 5.
        """
        fixtures = [create_mock_fixture("minimal")]
        runs = [
            create_mock_run(
                run_id=f"run-00{i}",
                fixture="minimal",
                started=datetime(2026, 1, 10 - i, tzinfo=UTC),
            )
            for i in range(7)
        ]

        stats = get_fixture_run_stats(fixtures, runs)
        assert len(stats["minimal"].recent_runs) == 5

    def test_case_insensitive_matching(self) -> None:
        """GIVEN fixture with different case in runs
        WHEN calculating stats
        THEN matches case-insensitively.
        """
        fixtures = [create_mock_fixture("minimal")]
        runs = [
            create_mock_run(
                run_id="run-001",
                fixture="MINIMAL",  # Different case
            ),
        ]

        stats = get_fixture_run_stats(fixtures, runs)
        assert stats["minimal"].run_count == 1

    def test_handles_fixture_with_no_runs(self) -> None:
        """GIVEN fixture with no matching runs
        WHEN calculating stats
        THEN returns zero counts.
        """
        fixtures = [create_mock_fixture("minimal")]
        runs = [
            create_mock_run(
                run_id="run-001",
                fixture="complex",  # Different fixture
            ),
        ]

        stats = get_fixture_run_stats(fixtures, runs)
        assert stats["minimal"].run_count == 0
        assert stats["minimal"].last_run is None
        assert stats["minimal"].recent_runs == []


# =============================================================================
# API Integration Tests: Fixtures List
# =============================================================================


class TestFixturesEndpoint:
    """Tests for GET /api/experiments/fixtures endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_registry(self, tmp_path: Path) -> None:
        """GIVEN no fixtures registry
        WHEN GET /api/experiments/fixtures
        THEN returns empty list with total=0.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert data["fixtures"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_invalid_difficulty_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid difficulty filter
        WHEN GET /api/experiments/fixtures?difficulty=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=invalid")

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_difficulty"

    @pytest.mark.asyncio
    async def test_invalid_sort_by_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_by parameter
        WHEN GET /api/experiments/fixtures?sort_by=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?sort_by=invalid")

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_sort_by"

    @pytest.mark.asyncio
    async def test_invalid_sort_order_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_order parameter
        WHEN GET /api/experiments/fixtures?sort_order=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?sort_order=invalid")

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_sort_order"

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_easy(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=easy filter
        WHEN GET /api/experiments/fixtures?difficulty=easy
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=easy")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_medium(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=medium filter
        WHEN GET /api/experiments/fixtures?difficulty=medium
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=medium")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_hard(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=hard filter
        WHEN GET /api/experiments/fixtures?difficulty=hard
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=hard")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_sort_fields(self, tmp_path: Path) -> None:
        """GIVEN valid sort_by fields
        WHEN GET /api/experiments/fixtures with each sort_by
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        for sort_by in ["name", "difficulty", "estimated_cost", "run_count", "last_run"]:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/experiments/fixtures?sort_by={sort_by}")
            assert response.status_code == 200, f"Failed for sort_by={sort_by}"

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_trivial(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=trivial filter
        WHEN GET /api/experiments/fixtures?difficulty=trivial
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=trivial")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_simple(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=simple filter
        WHEN GET /api/experiments/fixtures?difficulty=simple
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=simple")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_complex(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=complex filter
        WHEN GET /api/experiments/fixtures?difficulty=complex
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=complex")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_difficulty_expert(self, tmp_path: Path) -> None:
        """GIVEN valid difficulty=expert filter
        WHEN GET /api/experiments/fixtures?difficulty=expert
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=expert")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accepts_valid_sort_orders(self, tmp_path: Path) -> None:
        """GIVEN valid sort_order values
        WHEN GET /api/experiments/fixtures with each sort_order
        THEN returns 200.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        for sort_order in ["asc", "desc"]:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/experiments/fixtures?sort_order={sort_order}")
            assert response.status_code == 200, f"Failed for sort_order={sort_order}"


class TestFixturesEndpointWithRegistry:
    """Tests for fixtures endpoint with actual registry file."""

    @pytest.mark.asyncio
    async def test_returns_fixtures_from_registry(self, tmp_path: Path) -> None:
        """GIVEN valid fixtures registry
        WHEN GET /api/experiments/fixtures
        THEN returns fixtures list.
        """
        # Create registry
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        registry_yaml = """fixtures:
  - id: minimal
    name: Minimal Fixture
    description: Single epic, 3 stories
    path: ./minimal
    tags:
      - quick
      - basic
    difficulty: easy
    estimated_cost: "$0.10"
  - id: complex
    name: Complex Fixture
    description: Multiple epics
    path: ./complex
    tags:
      - slow
    difficulty: hard
    estimated_cost: "$1.00"
"""
        (fixtures_dir / "registry.yaml").write_text(registry_yaml)

        # Create fixture directories (to avoid warnings)
        (fixtures_dir / "minimal").mkdir()
        (fixtures_dir / "complex").mkdir()

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["fixtures"]) == 2

        # Check fields
        fixture = data["fixtures"][0]  # Default sort by name asc -> complex first
        assert "id" in fixture
        assert "name" in fixture
        assert "estimated_cost_value" in fixture
        assert "run_count" in fixture

    @pytest.mark.asyncio
    async def test_filters_by_difficulty(self, tmp_path: Path) -> None:
        """GIVEN fixtures with different difficulties
        WHEN GET /api/experiments/fixtures?difficulty=easy
        THEN returns only easy fixtures.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directories with metadata (new auto-discovery API)
        minimal_dir = fixtures_dir / "minimal"
        minimal_dir.mkdir()
        (minimal_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Minimal
  tags: []
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        complex_dir = fixtures_dir / "complex"
        complex_dir.mkdir()
        (complex_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Complex
  tags: []
  difficulty: hard
  estimated_cost: "$1.00"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?difficulty=easy")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["fixtures"][0]["id"] == "minimal"

    @pytest.mark.asyncio
    async def test_filters_by_tags_and_logic(self, tmp_path: Path) -> None:
        """GIVEN fixtures with different tags
        WHEN GET /api/experiments/fixtures?tags=quick,basic
        THEN returns only fixtures with both tags (AND logic).
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directories with metadata (new auto-discovery API)
        minimal_dir = fixtures_dir / "minimal"
        minimal_dir.mkdir()
        (minimal_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Minimal
  tags:
    - quick
    - basic
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        quick_only_dir = fixtures_dir / "quick-only"
        quick_only_dir.mkdir()
        (quick_only_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Quick Only
  tags:
    - quick
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?tags=quick,basic")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["fixtures"][0]["id"] == "minimal"

    @pytest.mark.asyncio
    async def test_sorts_by_estimated_cost(self, tmp_path: Path) -> None:
        """GIVEN fixtures with different costs
        WHEN GET /api/experiments/fixtures?sort_by=estimated_cost&sort_order=desc
        THEN returns fixtures sorted by cost descending.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directories with metadata (new auto-discovery API)
        cheap_dir = fixtures_dir / "cheap"
        cheap_dir.mkdir()
        (cheap_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Cheap
  tags: []
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        expensive_dir = fixtures_dir / "expensive"
        expensive_dir.mkdir()
        (expensive_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Expensive
  tags: []
  difficulty: hard
  estimated_cost: "$5.00"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/experiments/fixtures?sort_by=estimated_cost&sort_order=desc"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["fixtures"][0]["id"] == "expensive"
        assert data["fixtures"][1]["id"] == "cheap"


# =============================================================================
# API Integration Tests: Fixture Details
# =============================================================================


class TestFixtureDetailsEndpoint:
    """Tests for GET /api/experiments/fixtures/{fixture_id} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_fixture(self, tmp_path: Path) -> None:
        """GIVEN no fixtures registry
        WHEN GET /api/experiments/fixtures/unknown
        THEN returns 404.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures/unknown")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_fixture_id(self, tmp_path: Path) -> None:
        """GIVEN invalid fixture_id format (contains spaces)
        WHEN GET /api/experiments/fixtures/invalid id
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # URL encode the space - invalid ID format
            response = await client.get("/api/experiments/fixtures/invalid%20id")

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "bad_request"

    @pytest.mark.asyncio
    async def test_returns_fixture_details(self, tmp_path: Path) -> None:
        """GIVEN valid fixture directory with metadata
        WHEN GET /api/experiments/fixtures/minimal
        THEN returns fixture details.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directory with metadata (new auto-discovery API)
        minimal_dir = fixtures_dir / "minimal"
        minimal_dir.mkdir()
        (minimal_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Minimal Fixture
  description: Single epic, 3 stories
  tags:
    - quick
    - basic
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures/minimal")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "minimal"
        assert data["name"] == "Minimal Fixture"
        assert data["description"] == "Single epic, 3 stories"
        assert data["difficulty"] == "easy"
        assert data["estimated_cost"] == "$0.10"
        assert data["estimated_cost_value"] == 0.10
        assert "resolved_path" in data
        assert data["run_count"] == 0
        assert data["last_run"] is None
        assert data["recent_runs"] == []

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_fixture(self, tmp_path: Path) -> None:
        """GIVEN fixture directory exists but requested fixture does not
        WHEN GET /api/experiments/fixtures/nonexistent
        THEN returns 404.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create a different fixture directory (new auto-discovery API)
        minimal_dir = fixtures_dir / "minimal"
        minimal_dir.mkdir()
        (minimal_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Minimal
  tags: []
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures/nonexistent")

        assert response.status_code == 404


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_handles_invalid_fixture_metadata(self, tmp_path: Path) -> None:
        """GIVEN invalid YAML in fixture metadata
        WHEN GET /api/experiments/fixtures
        THEN returns fixture with default metadata (graceful handling).
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directory with invalid metadata
        invalid_dir = fixtures_dir / "invalid"
        invalid_dir.mkdir()
        (invalid_dir / ".bmad-assist.yaml").write_text("invalid: yaml: content: [")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures")

        assert response.status_code == 200
        data = response.json()
        # Fixture discovered but with default metadata (id from directory name)
        assert data["total"] == 1
        assert data["fixtures"][0]["id"] == "invalid"

    @pytest.mark.asyncio
    async def test_filters_combine_with_and_logic(self, tmp_path: Path) -> None:
        """GIVEN multiple filters
        WHEN GET /api/experiments/fixtures?tags=quick&difficulty=easy
        THEN combines filters with AND logic.
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directories with metadata (new auto-discovery API)
        minimal_dir = fixtures_dir / "minimal"
        minimal_dir.mkdir()
        (minimal_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Minimal
  tags:
    - quick
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        quick_hard_dir = fixtures_dir / "quick-hard"
        quick_hard_dir.mkdir()
        (quick_hard_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Quick Hard
  tags:
    - quick
  difficulty: hard
  estimated_cost: "$1.00"
"""
        )

        slow_easy_dir = fixtures_dir / "slow-easy"
        slow_easy_dir.mkdir()
        (slow_easy_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Slow Easy
  tags:
    - slow
  difficulty: easy
  estimated_cost: "$0.50"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?tags=quick&difficulty=easy")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["fixtures"][0]["id"] == "minimal"

    @pytest.mark.asyncio
    async def test_empty_tags_returns_all(self, tmp_path: Path) -> None:
        """GIVEN empty tags filter
        WHEN GET /api/experiments/fixtures?tags=
        THEN returns all fixtures (no tag filtering).
        """
        fixtures_dir = tmp_path / "experiments" / "fixtures"
        fixtures_dir.mkdir(parents=True)

        # Create fixture directories with metadata (new auto-discovery API)
        one_dir = fixtures_dir / "one"
        one_dir.mkdir()
        (one_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: One
  tags: []
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        two_dir = fixtures_dir / "two"
        two_dir.mkdir()
        (two_dir / ".bmad-assist.yaml").write_text(
            """fixture:
  name: Two
  tags:
    - some-tag
  difficulty: easy
  estimated_cost: "$0.10"
"""
        )

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/fixtures?tags=")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2


class TestFixtureStats:
    """Tests for FixtureStats class."""

    def test_stats_initialization(self) -> None:
        """GIVEN FixtureStats class
        WHEN creating new instance
        THEN has expected default values.
        """
        stats = FixtureStats()
        assert stats.run_count == 0
        assert stats.last_run is None
        assert stats.recent_runs == []
