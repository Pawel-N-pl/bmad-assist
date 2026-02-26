"""Pytest fixtures for dashboard tests.

Provides shared fixtures for testing dashboard components:
- DashboardServer instance with temp project root
- AsyncClient for API testing
- Sample data fixtures for mocking

Story 16.10: Tests and Polish - Task 6.1
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

# Mock types for Task/TaskQueue fixtures (module doesn't exist yet)
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# Task and TaskQueue are not implemented yet (Epic 22 deferred)
# from bmad_assist.dashboard.queue import Task, TaskQueue
from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.dashboard.sse import SSEBroadcaster


class Task(MagicMock):
    """Mock Task type for fixtures."""

    pass


class TaskQueue(MagicMock):
    """Mock TaskQueue type for fixtures."""

    pass


@pytest.fixture(autouse=True)
def ensure_sprint_status(tmp_path: Path) -> None:
    """Auto-create sprint-status.yaml for all dashboard tests.

    This is required because DashboardServer now validates
    sprint-status.yaml exists at initialization.
    """
    impl_dir = tmp_path / "_bmad-output/implementation-artifacts"
    impl_dir.mkdir(parents=True, exist_ok=True)
    sprint_status = impl_dir / "sprint-status.yaml"
    if not sprint_status.exists():
        sprint_status.write_text("""
epics: [16]
current_epic: 16
current_story: 1
development_status:
  epic-16: in-progress
  16-1-cli-serve-command: done
""")


@pytest.fixture
def mock_sprint_status() -> dict[str, Any]:
    """Sample sprint status data for mocking."""
    return {
        "current_epic": 16,
        "current_story": "16.2",
        "epics": [
            {
                "id": 16,
                "title": "Real-time Dashboard",
                "status": "in-progress",
                "stories": [
                    {"id": "1", "title": "CLI Serve Command", "status": "done"},
                    {"id": "2", "title": "REST API Endpoints", "status": "in-progress"},
                ],
            }
        ],
    }


@pytest.fixture
def mock_stories_response() -> dict[str, Any]:
    """Sample stories response with phases."""
    return {
        "epics": [
            {
                "id": 16,
                "title": "Real-time Dashboard",
                "status": "in-progress",
                "stories": [
                    {
                        "id": "1",
                        "title": "CLI Serve Command",
                        "status": "done",
                        "phases": [
                            {"name": "create-story", "status": "completed"},
                            {"name": "validate", "status": "completed"},
                            {"name": "validation-synthesis", "status": "completed"},
                            {"name": "dev-story", "status": "completed"},
                            {"name": "code-review", "status": "completed"},
                            {"name": "review-synthesis", "status": "completed"},
                        ],
                    }
                ],
            }
        ]
    }


@pytest.fixture
async def dashboard_server(tmp_path: Path, ensure_sprint_status: None) -> DashboardServer:
    """Create DashboardServer with temp project root.

    Uses ensure_sprint_status autouse fixture for sprint-status.yaml.
    """
    server = DashboardServer(project_root=tmp_path)
    return server


@pytest.fixture
async def test_client(dashboard_server: DashboardServer) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client for API testing."""
    app = dashboard_server.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_task() -> Task:
    """Create a sample Task for testing."""
    return Task(
        id="task-1",
        workflow="dev-story",
        epic_num=16,
        story_num=10,
    )


@pytest.fixture
def task_queue() -> TaskQueue:
    """Create a fresh TaskQueue for testing."""
    return TaskQueue()


@pytest.fixture
def sse_broadcaster() -> SSEBroadcaster:
    """Create SSEBroadcaster with long heartbeat for testing."""
    return SSEBroadcaster(heartbeat_interval=60)
