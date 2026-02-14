"""Tests for multi-project API routes.

Tests project management and loop control endpoints.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.manager import LoopState, ProjectRegistry
from bmad_assist.dashboard.manager.process_supervisor import ProcessSupervisor
from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.dashboard.sse_channel import SSEChannelManager


@pytest.fixture
def mock_registry(tmp_path: Path):
    """Create mock project registry."""
    config_dir = tmp_path / ".config"
    registry = ProjectRegistry(config_dir=config_dir)
    return registry


@pytest.fixture
def mock_supervisor():
    """Create mock process supervisor."""
    supervisor = MagicMock(spec=ProcessSupervisor)
    supervisor.spawn_subprocess = AsyncMock()
    supervisor.stop_subprocess = AsyncMock()
    supervisor.write_pause_flag = AsyncMock(return_value=True)
    supervisor.remove_pause_flag = AsyncMock(return_value=True)
    return supervisor


@pytest.fixture
def mock_sse_manager():
    """Create mock SSE channel manager."""
    manager = MagicMock(spec=SSEChannelManager)
    channel = MagicMock()
    channel.broadcast = AsyncMock()
    channel.broadcast_loop_status = AsyncMock()
    channel.broadcast_error = AsyncMock()
    manager.get_or_create.return_value = channel
    manager.get.return_value = channel
    return manager


@pytest.fixture
async def test_client(
    tmp_path: Path,
    mock_registry: ProjectRegistry,
    mock_supervisor: ProcessSupervisor,
    mock_sse_manager: SSEChannelManager,
):
    """Create test client with mocked dependencies."""
    # Create minimal sprint-status.yaml
    impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
    impl_dir.mkdir(parents=True, exist_ok=True)
    (impl_dir / "sprint-status.yaml").write_text("""
epics: [1]
current_epic: 1
current_story: 1
development_status: {}
""")

    server = DashboardServer(project_root=tmp_path)
    app = server.create_app()

    # Replace components with mocks
    app.state.project_registry = mock_registry
    app.state.process_supervisor = mock_supervisor
    app.state.sse_channel_manager = mock_sse_manager

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestProjectsListEndpoint:
    """Tests for GET /api/projects."""

    async def test_list_empty(self, test_client: AsyncClient):
        """Returns empty list when no projects registered."""
        response = await test_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["projects"] == []
        assert data["count"] == 0

    async def test_list_with_projects(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Returns registered projects."""
        # Register a project
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        mock_registry.register(project_path, display_name="Test Project")

        response = await test_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["projects"][0]["display_name"] == "Test Project"


class TestProjectsRegisterEndpoint:
    """Tests for POST /api/projects."""

    async def test_register_project(
        self,
        test_client: AsyncClient,
        tmp_path: Path,
    ):
        """Register new project returns 201."""
        project_path = tmp_path / "new-project"
        project_path.mkdir()

        response = await test_client.post(
            "/api/projects",
            json={"path": str(project_path), "name": "New Project"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "uuid" in data
        assert data["display_name"] == "New Project"

    async def test_register_missing_path(self, test_client: AsyncClient):
        """Register without path returns 400."""
        response = await test_client.post(
            "/api/projects",
            json={"name": "No Path"},
        )

        assert response.status_code == 400
        assert "path" in response.json()["error"].lower()

    async def test_register_nonexistent_path(self, test_client: AsyncClient):
        """Register nonexistent path returns 400."""
        response = await test_client.post(
            "/api/projects",
            json={"path": "/nonexistent/path"},
        )

        assert response.status_code == 400


class TestProjectsScanEndpoint:
    """Tests for POST /api/projects/scan."""

    async def test_scan_directory(
        self,
        test_client: AsyncClient,
        tmp_path: Path,
    ):
        """Scan finds projects with .bmad-assist/."""
        # Create some projects
        for i in range(2):
            project_path = tmp_path / "scan-test" / f"project-{i}"
            (project_path / ".bmad-assist").mkdir(parents=True)

        response = await test_client.post(
            "/api/projects/scan",
            json={"directory": str(tmp_path / "scan-test")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2

    async def test_scan_nonexistent_directory(self, test_client: AsyncClient):
        """Scan nonexistent directory returns 404."""
        response = await test_client.post(
            "/api/projects/scan",
            json={"directory": "/nonexistent"},
        )

        assert response.status_code == 404


class TestProjectDetailsEndpoint:
    """Tests for GET /api/projects/{id}."""

    async def test_get_project_details(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Get project returns details with logs."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)

        # Add some logs
        context = mock_registry.get(project_uuid)
        context.add_log("Test log line")

        response = await test_client.get(f"/api/projects/{project_uuid}")

        assert response.status_code == 200
        data = response.json()
        assert data["uuid"] == project_uuid
        assert "logs" in data

    async def test_get_nonexistent_project(self, test_client: AsyncClient):
        """Get nonexistent project returns 404."""
        response = await test_client.get("/api/projects/nonexistent-uuid")

        assert response.status_code == 404


class TestProjectDeleteEndpoint:
    """Tests for DELETE /api/projects/{id}."""

    async def test_delete_project(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Delete project returns 200."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)

        response = await test_client.delete(f"/api/projects/{project_uuid}")

        assert response.status_code == 200
        assert project_uuid not in mock_registry._projects

    async def test_delete_running_project(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Delete running project returns 409."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)
        mock_registry.get(project_uuid).state = LoopState.RUNNING

        response = await test_client.delete(f"/api/projects/{project_uuid}")

        assert response.status_code == 409


class TestProjectLoopStartEndpoint:
    """Tests for POST /api/projects/{id}/loop/start."""

    async def test_start_loop(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        mock_supervisor: ProcessSupervisor,
        tmp_path: Path,
    ):
        """Start loop returns 200."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/start")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("running", "queued")

    async def test_start_already_running(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Start running project returns 409."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)
        mock_registry.get(project_uuid).state = LoopState.RUNNING

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/start")

        assert response.status_code == 409


class TestProjectLoopPauseEndpoint:
    """Tests for POST /api/projects/{id}/loop/pause."""

    async def test_pause_loop(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Pause running loop returns 200."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)
        mock_registry.get(project_uuid).state = LoopState.RUNNING

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/pause")

        assert response.status_code == 200

    async def test_pause_idle(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Pause idle project returns 409."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/pause")

        assert response.status_code == 409


class TestProjectLoopStopEndpoint:
    """Tests for POST /api/projects/{id}/loop/stop."""

    async def test_stop_loop(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        mock_supervisor: ProcessSupervisor,
        tmp_path: Path,
    ):
        """Stop running loop returns 200."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)
        mock_registry.get(project_uuid).state = LoopState.RUNNING

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/stop")

        assert response.status_code == 200

    async def test_stop_queued(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        tmp_path: Path,
    ):
        """Stop queued project removes from queue."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        project_uuid = mock_registry.register(project_path)
        mock_registry.enqueue(project_uuid)

        response = await test_client.post(f"/api/projects/{project_uuid}/loop/stop")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"


class TestStopAllEndpoint:
    """Tests for POST /api/projects/control/stop-all."""

    async def test_stop_all(
        self,
        test_client: AsyncClient,
        mock_registry: ProjectRegistry,
        mock_supervisor: ProcessSupervisor,
        tmp_path: Path,
    ):
        """Stop all stops running projects."""
        # Register and start some projects
        for i in range(2):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            project_uuid = mock_registry.register(project_path)
            mock_registry.get(project_uuid).state = LoopState.RUNNING

        response = await test_client.post("/api/projects/control/stop-all")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
