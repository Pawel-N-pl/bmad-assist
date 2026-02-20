"""Tests for Experiments Templates API - Story 19.5: Config/Loop/Patch-Set Browser.

Tests verify the templates API endpoints for the dashboard:
- AC1: GET /api/experiments/configs returns list with sorting
- AC2: GET /api/experiments/configs/{name} returns config details
- AC3: GET /api/experiments/loops returns list with sorting
- AC4: GET /api/experiments/loops/{name} returns loop details
- AC5: GET /api/experiments/patch-sets returns list with sorting
- AC6: GET /api/experiments/patch-sets/{name} returns patch-set details
- AC7: Template discovery with caching
- AC8: Run statistics calculation
- AC9: YAML content loading
- AC12: Empty and error states
- AC13: Unit and integration tests
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.experiments import (
    MAX_YAML_CONTENT_SIZE,
    ConfigSummary,
    LoopSummary,
    PatchSetSummary,
    TemplateRunInfo,
    TemplateStats,
    clear_configs_cache,
    clear_loops_cache,
    clear_patchsets_cache,
    discover_configs,
    discover_loops,
    discover_patchsets,
    get_config_run_stats,
    get_loop_run_stats,
    get_patchset_run_stats,
    get_yaml_content,
)
from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.experiments import ExperimentStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    """Clear all template caches before each test."""
    clear_configs_cache()
    clear_loops_cache()
    clear_patchsets_cache()
    # Also clear runs cache
    from bmad_assist.dashboard.experiments import clear_cache

    clear_cache()


def create_mock_run(
    run_id: str = "run-001",
    fixture: str = "minimal",
    config: str = "opus-solo",
    loop: str = "standard",
    patch_set: str = "baseline",
    status: ExperimentStatus = ExperimentStatus.COMPLETED,
    started: datetime | None = None,
) -> MagicMock:
    """Create a mock RunManifest."""
    mock = MagicMock()
    mock.run_id = run_id
    mock.input = MagicMock()
    mock.input.fixture = fixture
    mock.input.config = config
    mock.input.loop = loop
    mock.input.patch_set = patch_set
    mock.status = status
    mock.started = started or datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)
    return mock


# =============================================================================
# Unit Tests: Response Models
# =============================================================================


class TestTemplateRunInfo:
    """Tests for TemplateRunInfo Pydantic model."""

    def test_model_creation_with_fixture(self) -> None:
        """GIVEN fixture field provided
        WHEN TemplateRunInfo is created
        THEN model validates successfully.
        """
        info = TemplateRunInfo(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            fixture="minimal",
        )
        assert info.run_id == "run-001"
        assert info.status == "completed"
        assert info.fixture == "minimal"
        assert info.config is None

    def test_model_creation_with_config(self) -> None:
        """GIVEN config field provided
        WHEN TemplateRunInfo is created
        THEN model validates successfully.
        """
        info = TemplateRunInfo(
            run_id="run-001",
            status="completed",
            started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            config="opus-solo",
        )
        assert info.config == "opus-solo"
        assert info.fixture is None


class TestConfigSummary:
    """Tests for ConfigSummary Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN ConfigSummary is created
        THEN model validates successfully.
        """
        summary = ConfigSummary(
            name="opus-solo",
            description="Solo Opus configuration",
            source="/path/to/opus-solo.yaml",
            providers={"master": {"provider": "claude-sdk", "model": "opus"}, "multi": []},
            run_count=5,
            last_run=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
        )
        assert summary.name == "opus-solo"
        assert summary.run_count == 5

    def test_model_with_none_values(self) -> None:
        """GIVEN optional fields as None
        WHEN ConfigSummary is created
        THEN model validates successfully.
        """
        summary = ConfigSummary(
            name="opus-solo",
            description=None,
            source="/path/to/opus-solo.yaml",
            providers={"master": None, "multi": []},
            run_count=0,
            last_run=None,
        )
        assert summary.description is None
        assert summary.last_run is None


class TestLoopSummary:
    """Tests for LoopSummary Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN LoopSummary is created
        THEN model validates successfully.
        """
        summary = LoopSummary(
            name="standard",
            description="Standard development loop",
            source="/path/to/standard.yaml",
            sequence=[
                {"workflow": "create-story", "required": True},
                {"workflow": "dev-story", "required": True},
            ],
            step_count=2,
            run_count=3,
            last_run=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
        )
        assert summary.name == "standard"
        assert summary.step_count == 2


class TestPatchSetSummary:
    """Tests for PatchSetSummary Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all fields provided
        WHEN PatchSetSummary is created
        THEN model validates successfully.
        """
        summary = PatchSetSummary(
            name="baseline",
            description="Baseline patch-set",
            source="/path/to/baseline.yaml",
            patches={"create-story": "/path/to/patch.yaml"},
            workflow_overrides={},
            patch_count=1,
            override_count=0,
            run_count=2,
            last_run=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
        )
        assert summary.name == "baseline"
        assert summary.patch_count == 1


# =============================================================================
# Unit Tests: Template Stats
# =============================================================================


class TestTemplateStats:
    """Tests for TemplateStats class."""

    def test_stats_initialization(self) -> None:
        """GIVEN TemplateStats created
        WHEN initialized
        THEN has expected defaults.
        """
        stats = TemplateStats()
        assert stats.run_count == 0
        assert stats.last_run is None
        assert stats.recent_runs == []


class TestGetConfigRunStats:
    """Tests for get_config_run_stats function."""

    def test_empty_configs(self) -> None:
        """GIVEN empty config names list
        WHEN get_config_run_stats called
        THEN returns empty dict.
        """
        runs = [create_mock_run()]
        result = get_config_run_stats([], runs)
        assert result == {}

    def test_empty_runs(self) -> None:
        """GIVEN empty runs list
        WHEN get_config_run_stats called
        THEN returns stats with zero counts.
        """
        result = get_config_run_stats(["opus-solo"], [])
        assert "opus-solo" in result
        assert result["opus-solo"].run_count == 0
        assert result["opus-solo"].last_run is None

    def test_single_config_with_runs(self) -> None:
        """GIVEN config with matching runs
        WHEN get_config_run_stats called
        THEN returns correct count and last_run.
        """
        runs = [
            create_mock_run(
                run_id="run-001",
                config="opus-solo",
                started=datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC),
            ),
            create_mock_run(
                run_id="run-002",
                config="opus-solo",
                started=datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC),
            ),
        ]
        result = get_config_run_stats(["opus-solo"], runs)
        assert result["opus-solo"].run_count == 2
        # First run in list is last_run (runs are sorted desc)
        assert result["opus-solo"].last_run == datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)

    def test_case_insensitive_matching(self) -> None:
        """GIVEN runs with different case config names
        WHEN get_config_run_stats called
        THEN matches case-insensitively.
        """
        runs = [
            create_mock_run(run_id="run-001", config="Opus-Solo"),
        ]
        result = get_config_run_stats(["opus-solo"], runs)
        assert result["opus-solo"].run_count == 1

    def test_recent_runs_limited_to_five(self) -> None:
        """GIVEN more than 5 runs
        WHEN get_config_run_stats called
        THEN recent_runs limited to 5.
        """
        runs = [create_mock_run(run_id=f"run-{i:03d}", config="opus-solo") for i in range(10)]
        result = get_config_run_stats(["opus-solo"], runs)
        assert len(result["opus-solo"].recent_runs) == 5


class TestGetLoopRunStats:
    """Tests for get_loop_run_stats function."""

    def test_single_loop_with_runs(self) -> None:
        """GIVEN loop with matching runs
        WHEN get_loop_run_stats called
        THEN returns correct count.
        """
        runs = [
            create_mock_run(run_id="run-001", loop="standard"),
            create_mock_run(run_id="run-002", loop="standard"),
        ]
        result = get_loop_run_stats(["standard"], runs)
        assert result["standard"].run_count == 2


class TestGetPatchsetRunStats:
    """Tests for get_patchset_run_stats function."""

    def test_single_patchset_with_runs(self) -> None:
        """GIVEN patchset with matching runs
        WHEN get_patchset_run_stats called
        THEN returns correct count.
        """
        runs = [
            create_mock_run(run_id="run-001", patch_set="baseline"),
            create_mock_run(run_id="run-002", patch_set="baseline"),
        ]
        result = get_patchset_run_stats(["baseline"], runs)
        assert result["baseline"].run_count == 2

    def test_recent_runs_use_config_field(self) -> None:
        """GIVEN patchset with runs
        WHEN get_patchset_run_stats called
        THEN recent_runs use config field (not fixture).
        """
        runs = [
            create_mock_run(
                run_id="run-001", patch_set="baseline", config="opus-solo", fixture="minimal"
            ),
        ]
        result = get_patchset_run_stats(["baseline"], runs)
        assert result["baseline"].recent_runs[0].config == "opus-solo"
        assert result["baseline"].recent_runs[0].fixture is None


# =============================================================================
# Unit Tests: YAML Content Loading
# =============================================================================


class TestGetYamlContent:
    """Tests for get_yaml_content function."""

    @pytest.mark.asyncio
    async def test_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """GIVEN non-existent file path
        WHEN get_yaml_content called
        THEN returns None.
        """
        result = await get_yaml_content(str(tmp_path / "nonexistent.yaml"))
        assert result is None

    @pytest.mark.asyncio
    async def test_reads_yaml_content(self, tmp_path: Path) -> None:
        """GIVEN valid YAML file
        WHEN get_yaml_content called
        THEN returns file content.
        """
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: test\ndescription: Test file")
        result = await get_yaml_content(str(yaml_file))
        assert result == "name: test\ndescription: Test file"

    @pytest.mark.asyncio
    async def test_truncates_large_content(self, tmp_path: Path) -> None:
        """GIVEN YAML file exceeding size limit
        WHEN get_yaml_content called
        THEN returns truncated content with message.
        """
        yaml_file = tmp_path / "large.yaml"
        # Create content larger than 100KB
        large_content = "x" * (MAX_YAML_CONTENT_SIZE + 1000)
        yaml_file.write_text(large_content)
        result = await get_yaml_content(str(yaml_file))
        assert result is not None
        assert "Content truncated" in result
        assert len(result) < MAX_YAML_CONTENT_SIZE + 100  # Truncated + message


# =============================================================================
# Unit Tests: Template Discovery
# =============================================================================


class TestDiscoverConfigs:
    """Tests for discover_configs function."""

    @pytest.mark.asyncio
    async def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        """GIVEN experiments dir without configs/
        WHEN discover_configs is called
        THEN returns empty list.
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir()
        result = await discover_configs(experiments_dir)
        assert result == []


class TestDiscoverLoops:
    """Tests for discover_loops function."""

    @pytest.mark.asyncio
    async def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        """GIVEN experiments dir without loops/
        WHEN discover_loops is called
        THEN returns empty list.
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir()
        result = await discover_loops(experiments_dir)
        assert result == []


class TestDiscoverPatchsets:
    """Tests for discover_patchsets function."""

    @pytest.mark.asyncio
    async def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        """GIVEN experiments dir without patch-sets/
        WHEN discover_patchsets is called
        THEN returns empty list.
        """
        experiments_dir = tmp_path / "experiments"
        experiments_dir.mkdir()
        result = await discover_patchsets(experiments_dir)
        assert result == []


# =============================================================================
# Integration Tests: Configs API
# =============================================================================


class TestConfigsEndpoint:
    """Tests for GET /api/experiments/configs endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_configs(self, tmp_path: Path) -> None:
        """GIVEN no configs directory
        WHEN GET /api/experiments/configs
        THEN returns empty list with total=0.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs")

        assert response.status_code == 200
        data = response.json()
        assert data["configs"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_invalid_sort_by_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_by parameter
        WHEN GET /api/experiments/configs?sort_by=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs?sort_by=invalid")

        assert response.status_code == 400
        assert "invalid_sort_by" in response.json()["error"]

    @pytest.mark.asyncio
    async def test_invalid_sort_order_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_order parameter
        WHEN GET /api/experiments/configs?sort_order=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs?sort_order=invalid")

        assert response.status_code == 400
        assert "invalid_sort_order" in response.json()["error"]


class TestConfigDetailsEndpoint:
    """Tests for GET /api/experiments/configs/{config_name} endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_name_format_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid config_name with special characters
        WHEN GET /api/experiments/configs/invalid..name
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs/invalid..name")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_config_returns_404(self, tmp_path: Path) -> None:
        """GIVEN valid config_name that doesn't exist
        WHEN GET /api/experiments/configs/nonexistent
        THEN returns 404.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs/nonexistent")

        assert response.status_code == 404


# =============================================================================
# Integration Tests: Loops API
# =============================================================================


class TestLoopsEndpoint:
    """Tests for GET /api/experiments/loops endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_loops(self, tmp_path: Path) -> None:
        """GIVEN no loops directory
        WHEN GET /api/experiments/loops
        THEN returns empty list with total=0.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops")

        assert response.status_code == 200
        data = response.json()
        assert data["loops"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_invalid_sort_by_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_by parameter
        WHEN GET /api/experiments/loops?sort_by=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops?sort_by=invalid")

        assert response.status_code == 400
        assert "invalid_sort_by" in response.json()["error"]


class TestLoopDetailsEndpoint:
    """Tests for GET /api/experiments/loops/{loop_name} endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_name_format_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid loop_name with special characters
        WHEN GET /api/experiments/loops/invalid..name
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops/invalid..name")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_loop_returns_404(self, tmp_path: Path) -> None:
        """GIVEN valid loop_name that doesn't exist
        WHEN GET /api/experiments/loops/nonexistent
        THEN returns 404.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops/nonexistent")

        assert response.status_code == 404


# =============================================================================
# Integration Tests: Patch-Sets API
# =============================================================================


class TestPatchSetsEndpoint:
    """Tests for GET /api/experiments/patch-sets endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_patchsets(self, tmp_path: Path) -> None:
        """GIVEN no patch-sets directory
        WHEN GET /api/experiments/patch-sets
        THEN returns empty list with total=0.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets")

        assert response.status_code == 200
        data = response.json()
        assert data["patch_sets"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_invalid_sort_by_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid sort_by parameter
        WHEN GET /api/experiments/patch-sets?sort_by=invalid
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets?sort_by=invalid")

        assert response.status_code == 400
        assert "invalid_sort_by" in response.json()["error"]


class TestPatchSetDetailsEndpoint:
    """Tests for GET /api/experiments/patch-sets/{patchset_name} endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_name_format_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid patchset_name with special characters
        WHEN GET /api/experiments/patch-sets/invalid..name
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets/invalid..name")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_patchset_returns_404(self, tmp_path: Path) -> None:
        """GIVEN valid patchset_name that doesn't exist
        WHEN GET /api/experiments/patch-sets/nonexistent
        THEN returns 404.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets/nonexistent")

        assert response.status_code == 404


# =============================================================================
# Integration Tests: With Real Templates
# =============================================================================


class TestRealTemplates:
    """Integration tests with real template files."""

    @pytest.fixture
    def setup_experiment_templates(self, tmp_path: Path) -> Path:
        """Create experiment directories with sample templates."""
        experiments_dir = tmp_path / "experiments"

        # Create configs
        configs_dir = experiments_dir / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "opus-solo.yaml").write_text(
            "name: opus-solo\n"
            "description: Solo Opus config\n"
            "providers:\n"
            "  master:\n"
            "    provider: claude-sdk\n"
            "    model: opus\n"
            "  multi: []\n"
        )

        # Create loops
        loops_dir = experiments_dir / "loops"
        loops_dir.mkdir(parents=True)
        (loops_dir / "standard.yaml").write_text(
            "name: standard\n"
            "description: Standard development loop\n"
            "sequence:\n"
            "  - workflow: create-story\n"
            "    required: true\n"
            "  - workflow: dev-story\n"
            "    required: true\n"
        )

        # Create patch-sets
        patchsets_dir = experiments_dir / "patch-sets"
        patchsets_dir.mkdir(parents=True)
        (patchsets_dir / "baseline.yaml").write_text(
            "name: baseline\ndescription: Baseline patch-set\npatches: {}\nworkflow_overrides: {}\n"
        )

        return tmp_path

    @pytest.mark.asyncio
    async def test_configs_list_with_templates(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid config templates
        WHEN GET /api/experiments/configs
        THEN returns list with config details.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["configs"][0]["name"] == "opus-solo"
        assert data["configs"][0]["description"] == "Solo Opus config"

    @pytest.mark.asyncio
    async def test_config_details(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid config template
        WHEN GET /api/experiments/configs/opus-solo
        THEN returns config details with YAML content.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs/opus-solo")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "opus-solo"
        assert data["yaml_content"] is not None
        assert "name: opus-solo" in data["yaml_content"]
        assert data["recent_runs"] == []

    @pytest.mark.asyncio
    async def test_loops_list_with_templates(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid loop templates
        WHEN GET /api/experiments/loops
        THEN returns list with loop details.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["loops"][0]["name"] == "standard"
        assert data["loops"][0]["step_count"] == 2

    @pytest.mark.asyncio
    async def test_loop_details(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid loop template
        WHEN GET /api/experiments/loops/standard
        THEN returns loop details with sequence.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/loops/standard")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "standard"
        assert len(data["sequence"]) == 2
        assert data["sequence"][0]["workflow"] == "create-story"

    @pytest.mark.asyncio
    async def test_patchsets_list_with_templates(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid patch-set templates
        WHEN GET /api/experiments/patch-sets
        THEN returns list with patch-set details.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["patch_sets"][0]["name"] == "baseline"
        assert data["patch_sets"][0]["patch_count"] == 0

    @pytest.mark.asyncio
    async def test_patchset_details(self, setup_experiment_templates: Path) -> None:
        """GIVEN valid patch-set template
        WHEN GET /api/experiments/patch-sets/baseline
        THEN returns patch-set details with YAML content.
        """
        server = DashboardServer(project_root=setup_experiment_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/patch-sets/baseline")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "baseline"
        assert data["yaml_content"] is not None
        assert data["patch_count"] == 0
        assert data["override_count"] == 0


# =============================================================================
# Integration Tests: Sorting
# =============================================================================


class TestSorting:
    """Tests for sorting functionality."""

    @pytest.fixture
    def setup_multiple_templates(self, tmp_path: Path) -> Path:
        """Create multiple templates for sorting tests."""
        experiments_dir = tmp_path / "experiments"

        # Create configs
        configs_dir = experiments_dir / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "alpha.yaml").write_text(
            "name: alpha\n"
            "description: Alpha config\n"
            "providers:\n"
            "  master:\n"
            "    provider: claude-sdk\n"
            "    model: opus\n"
            "  multi: []\n"
        )
        (configs_dir / "beta.yaml").write_text(
            "name: beta\n"
            "description: Beta config\n"
            "providers:\n"
            "  master:\n"
            "    provider: claude-sdk\n"
            "    model: opus\n"
            "  multi: []\n"
        )

        return tmp_path

    @pytest.mark.asyncio
    async def test_configs_sorted_by_name_asc(self, setup_multiple_templates: Path) -> None:
        """GIVEN multiple configs
        WHEN GET /api/experiments/configs?sort_by=name&sort_order=asc
        THEN returns configs sorted alphabetically.
        """
        server = DashboardServer(project_root=setup_multiple_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs?sort_by=name&sort_order=asc")

        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["configs"]]
        assert names == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_configs_sorted_by_name_desc(self, setup_multiple_templates: Path) -> None:
        """GIVEN multiple configs
        WHEN GET /api/experiments/configs?sort_by=name&sort_order=desc
        THEN returns configs sorted reverse alphabetically.
        """
        server = DashboardServer(project_root=setup_multiple_templates)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/configs?sort_by=name&sort_order=desc")

        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["configs"]]
        assert names == ["beta", "alpha"]
