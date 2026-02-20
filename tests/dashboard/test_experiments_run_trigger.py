"""Tests for Experiments Run Trigger API - Story 19.6: Run Trigger + Progress.

Tests verify the experiment run trigger endpoints for the dashboard:
- AC1: POST /api/experiments/run triggers new experiment run
- AC2: GET /api/experiments/run/{run_id}/status returns SSE progress stream
- AC3: POST /api/experiments/run/{run_id}/cancel cancels running experiment
- AC4: Validation of required fields
- AC5: Concurrent run prevention
- AC6: Template validation errors
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.experiments import (
    ExperimentCancelResponse,
    ExperimentProgressEvent,
    ExperimentRunRequest,
    ExperimentRunResponse,
    ExperimentStatusEvent,
)
from bmad_assist.dashboard.server import DashboardServer

# =============================================================================
# Unit Tests: Request/Response Models
# =============================================================================


class TestExperimentRunRequest:
    """Tests for ExperimentRunRequest Pydantic model."""

    def test_model_creation_with_all_fields(self) -> None:
        """GIVEN all required fields
        WHEN ExperimentRunRequest is created
        THEN model validates successfully.
        """
        request = ExperimentRunRequest(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )
        assert request.fixture == "minimal"
        assert request.config == "opus-solo"
        assert request.patch_set == "baseline"
        assert request.loop == "standard"

    def test_model_is_frozen(self) -> None:
        """GIVEN an ExperimentRunRequest
        WHEN trying to modify it
        THEN it should raise an error.
        """
        request = ExperimentRunRequest(
            fixture="minimal",
            config="opus-solo",
            patch_set="baseline",
            loop="standard",
        )
        with pytest.raises(Exception):  # ValidationError for frozen models
            request.fixture = "other"


class TestExperimentRunResponse:
    """Tests for ExperimentRunResponse Pydantic model."""

    def test_model_creation(self) -> None:
        """GIVEN all required fields
        WHEN ExperimentRunResponse is created
        THEN model validates successfully.
        """
        response = ExperimentRunResponse(
            run_id="run-2026-01-11-001",
            status="queued",
            message="Experiment queued for execution",
        )
        assert response.run_id == "run-2026-01-11-001"
        assert response.status == "queued"
        assert response.message == "Experiment queued for execution"


class TestExperimentCancelResponse:
    """Tests for ExperimentCancelResponse Pydantic model."""

    def test_model_creation(self) -> None:
        """GIVEN all required fields
        WHEN ExperimentCancelResponse is created
        THEN model validates successfully.
        """
        response = ExperimentCancelResponse(
            run_id="run-2026-01-11-001",
            status="cancelled",
            message="Experiment cancelled successfully",
        )
        assert response.run_id == "run-2026-01-11-001"
        assert response.status == "cancelled"
        assert response.message == "Experiment cancelled successfully"


class TestExperimentProgressEvent:
    """Tests for ExperimentProgressEvent Pydantic model."""

    def test_model_creation(self) -> None:
        """GIVEN all required fields
        WHEN ExperimentProgressEvent is created
        THEN model validates successfully.
        """
        event = ExperimentProgressEvent(
            run_id="run-2026-01-11-001",
            percent=50,
            stories_completed=2,
            stories_total=4,
        )
        assert event.run_id == "run-2026-01-11-001"
        assert event.percent == 50
        assert event.stories_completed == 2
        assert event.stories_total == 4


class TestExperimentStatusEvent:
    """Tests for ExperimentStatusEvent Pydantic model."""

    def test_model_creation_minimal(self) -> None:
        """GIVEN minimal required fields
        WHEN ExperimentStatusEvent is created
        THEN model validates successfully with defaults.
        """
        event = ExperimentStatusEvent(
            run_id="run-2026-01-11-001",
            status="running",
        )
        assert event.run_id == "run-2026-01-11-001"
        assert event.status == "running"
        assert event.phase is None
        assert event.story is None
        assert event.position is None

    def test_model_creation_full(self) -> None:
        """GIVEN all fields
        WHEN ExperimentStatusEvent is created
        THEN model validates successfully.
        """
        event = ExperimentStatusEvent(
            run_id="run-2026-01-11-001",
            status="running",
            phase="dev-story",
            story="1.1",
            position=2,
        )
        assert event.phase == "dev-story"
        assert event.story == "1.1"
        assert event.position == 2


# =============================================================================
# Integration Tests: API Endpoints
# =============================================================================


@pytest.fixture
def mock_server(tmp_path: Path) -> DashboardServer:
    """Create a mock DashboardServer for testing."""
    # Create sprint-status.yaml to satisfy server initialization
    impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
    impl_dir.mkdir(parents=True, exist_ok=True)
    (impl_dir / "sprint-status.yaml").write_text("epics: []")

    # Create experiments directory
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir(exist_ok=True)
    (experiments_dir / "runs").mkdir(exist_ok=True)

    return DashboardServer(project_root=tmp_path)


@pytest.fixture
def mock_templates() -> dict:
    """Create mock template discovery results."""
    return {
        "fixtures": [MagicMock(name="minimal"), MagicMock(name="complex")],
        "configs": [MagicMock(name="opus-solo"), MagicMock(name="haiku-solo")],
        "loops": [MagicMock(name="standard"), MagicMock(name="fast")],
        "patchsets": [MagicMock(name="baseline"), MagicMock(name="experimental")],
    }


class TestPostExperimentRun:
    """Tests for POST /api/experiments/run endpoint."""

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, mock_server: DashboardServer) -> None:
        """GIVEN a request with missing required fields
        WHEN POST /api/experiments/run is called
        THEN 400 Bad Request is returned.
        """
        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Missing all fields
            response = await client.post("/api/experiments/run", json={})
            assert response.status_code == 400
            data = response.json()
            assert "error" in data

            # Missing fixture
            response = await client.post(
                "/api/experiments/run",
                json={"config": "opus", "patch_set": "baseline", "loop": "standard"},
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_template_name(
        self, mock_server: DashboardServer, mock_templates: dict
    ) -> None:
        """GIVEN an invalid fixture/config name
        WHEN POST /api/experiments/run is called
        THEN 400 Bad Request is returned.
        """
        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        # Create mock fixture list (new auto-discovery API returns list)
        mock_fixture = MagicMock()
        mock_fixture.id = "minimal"

        async def mock_discover_fixtures(*args, **kwargs):
            return [mock_fixture]

        async def mock_discover_configs(*args, **kwargs):
            return [("opus-solo", MagicMock())]

        async def mock_discover_loops(*args, **kwargs):
            return [("standard", MagicMock())]

        async def mock_discover_patchsets(*args, **kwargs):
            return [("baseline", MagicMock())]

        with (
            patch(
                "bmad_assist.dashboard.experiments.discover_fixtures",
                side_effect=mock_discover_fixtures,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_configs",
                side_effect=mock_discover_configs,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_loops",
                side_effect=mock_discover_loops,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_patchsets",
                side_effect=mock_discover_patchsets,
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/experiments/run",
                    json={
                        "fixture": "nonexistent",
                        "config": "opus-solo",
                        "patch_set": "baseline",
                        "loop": "standard",
                    },
                )
                assert response.status_code == 400
                data = response.json()
                assert "error" in data
                assert "fixture" in data.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_successful_run_trigger_returns_not_implemented(
        self, mock_server: DashboardServer, mock_templates: dict
    ) -> None:
        """GIVEN valid template names
        WHEN POST /api/experiments/run is called
        THEN 501 Not Implemented is returned (experiment execution via dashboard not yet supported).

        Note: When experiment execution is implemented, this test should be updated
        to expect 202 Accepted with run_id.
        """
        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        # Create mock fixture list (new auto-discovery API returns list)
        mock_fixture = MagicMock()
        mock_fixture.id = "minimal"

        async def mock_discover_fixtures(*args, **kwargs):
            return [mock_fixture]

        async def mock_discover_configs(*args, **kwargs):
            return [("opus-solo", MagicMock())]

        async def mock_discover_loops(*args, **kwargs):
            return [("standard", MagicMock())]

        async def mock_discover_patchsets(*args, **kwargs):
            return [("baseline", MagicMock())]

        with (
            patch(
                "bmad_assist.dashboard.experiments.discover_fixtures",
                side_effect=mock_discover_fixtures,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_configs",
                side_effect=mock_discover_configs,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_loops",
                side_effect=mock_discover_loops,
            ),
            patch(
                "bmad_assist.dashboard.experiments.discover_patchsets",
                side_effect=mock_discover_patchsets,
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/experiments/run",
                    json={
                        "fixture": "minimal",
                        "config": "opus-solo",
                        "patch_set": "baseline",
                        "loop": "standard",
                    },
                )
                # Experiment execution via dashboard is not yet implemented
                assert response.status_code == 501
                data = response.json()
                assert data["error"] == "not_implemented"
                assert "not yet supported" in data["message"]

    @pytest.mark.asyncio
    async def test_concurrent_run_prevention(
        self, mock_server: DashboardServer, mock_templates: dict
    ) -> None:
        """GIVEN an experiment already running
        WHEN POST /api/experiments/run is called
        THEN 409 Conflict is returned.
        """
        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        # Simulate an active experiment
        mock_server._active_experiment_run_id = "run-2026-01-11-001"

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/experiments/run",
                json={
                    "fixture": "minimal",
                    "config": "opus-solo",
                    "patch_set": "baseline",
                    "loop": "standard",
                },
            )
            assert response.status_code == 409
            data = response.json()
            assert "conflict" in data.get("error", "").lower()


class TestPostExperimentRunCancel:
    """Tests for POST /api/experiments/run/{run_id}/cancel endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_active_run(self, mock_server: DashboardServer) -> None:
        """GIVEN an active experiment run
        WHEN POST /api/experiments/run/{run_id}/cancel is called
        THEN 200 OK is returned and experiment is cancelled.
        """
        import asyncio

        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        # Simulate an active experiment
        mock_server._active_experiment_run_id = "run-2026-01-11-001"
        mock_server._active_experiment_cancel_event = asyncio.Event()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/experiments/run/run-2026-01-11-001/cancel")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancelled"
            assert mock_server._active_experiment_cancel_event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_run(self, mock_server: DashboardServer) -> None:
        """GIVEN no active experiment
        WHEN POST /api/experiments/run/{run_id}/cancel is called
        THEN 404 Not Found is returned.
        """
        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/experiments/run/nonexistent/cancel")
            assert response.status_code == 404
            data = response.json()
            assert "not_found" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_cancel_wrong_run_id(self, mock_server: DashboardServer) -> None:
        """GIVEN an active experiment with different run_id
        WHEN POST /api/experiments/run/{run_id}/cancel is called with wrong id
        THEN 404 Not Found is returned.
        """
        import asyncio

        app = mock_server.create_app()
        transport = ASGITransport(app=app)

        # Simulate an active experiment with different ID
        mock_server._active_experiment_run_id = "run-2026-01-11-001"
        mock_server._active_experiment_cancel_event = asyncio.Event()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/experiments/run/run-2026-01-11-002/cancel")
            assert response.status_code == 404


class TestGetExperimentRunStatus:
    """Tests for GET /api/experiments/run/{run_id}/status SSE endpoint."""

    def test_sse_endpoint_exists(self, mock_server: DashboardServer) -> None:
        """GIVEN a DashboardServer
        WHEN create_app is called
        THEN the SSE endpoint route exists in API_ROUTES.
        """
        from bmad_assist.dashboard.routes import API_ROUTES

        # Verify the route exists
        route_paths = [r.path for r in API_ROUTES]
        assert "/api/experiments/run/{run_id}/status" in route_paths


# =============================================================================
# Server State Tests
# =============================================================================


class TestDashboardServerExperimentState:
    """Tests for DashboardServer experiment state management."""

    def test_server_has_experiment_lock(self, mock_server: DashboardServer) -> None:
        """GIVEN a DashboardServer instance
        THEN it should have an experiment lock for concurrency control.
        """
        assert hasattr(mock_server, "_experiment_lock")
        import asyncio

        assert isinstance(mock_server._experiment_lock, asyncio.Lock)

    def test_server_has_active_experiment_tracking(self, mock_server: DashboardServer) -> None:
        """GIVEN a DashboardServer instance
        THEN it should have active experiment tracking attributes.
        """
        assert hasattr(mock_server, "_active_experiment_run_id")
        assert hasattr(mock_server, "_active_experiment_cancel_event")
        assert mock_server._active_experiment_run_id is None
        assert mock_server._active_experiment_cancel_event is None

    def test_server_has_execute_experiment_method(self, mock_server: DashboardServer) -> None:
        """GIVEN a DashboardServer instance
        THEN it should have an execute_experiment method.
        """
        assert hasattr(mock_server, "execute_experiment")
        assert callable(mock_server.execute_experiment)
