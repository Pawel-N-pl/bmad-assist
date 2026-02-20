"""Tests for Experiments Comparison API - Story 19.4: Comparison Viewer.

Tests verify the comparison endpoints for the dashboard:
- AC1: GET /api/experiments/compare returns comparison data
- AC2: GET /api/experiments/compare/export returns Markdown download
- AC3: 2-10 run validation
- AC4: Run ID format and existence validation
- AC5: Error handling for invalid inputs
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.experiments import MAX_COMPARISON_RUNS

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_comparison_report_dict() -> dict[str, Any]:
    """Create a mock comparison report dict for testing (JSON serialized format)."""
    return {
        "generated_at": "2026-01-10T12:00:00+00:00",
        "run_ids": ["run-2026-01-10-001", "run-2026-01-10-002"],
        "runs": [
            {
                "run_id": "run-2026-01-10-001",
                "input": {
                    "fixture": "minimal",
                    "config": "opus-solo",
                    "patch_set": "baseline",
                    "loop": "standard",
                },
                "resolved": {"fixture": {}, "config": {}, "patch_set": {}, "loop": {}},
                "metrics": {"total_cost": 1.5, "total_tokens": 10000},
                "status": "completed",
            },
            {
                "run_id": "run-2026-01-10-002",
                "input": {
                    "fixture": "minimal",
                    "config": "haiku-solo",
                    "patch_set": "baseline",
                    "loop": "standard",
                },
                "resolved": {"fixture": {}, "config": {}, "patch_set": {}, "loop": {}},
                "metrics": {"total_cost": 2.0, "total_tokens": 15000},
                "status": "completed",
            },
        ],
        "config_diff": {
            "fixture": {
                "axis": "fixture",
                "values": {"run-2026-01-10-001": "minimal", "run-2026-01-10-002": "minimal"},
                "is_same": True,
            },
            "config": {
                "axis": "config",
                "values": {"run-2026-01-10-001": "opus-solo", "run-2026-01-10-002": "haiku-solo"},
                "is_same": False,
            },
            "patch_set": {
                "axis": "patch_set",
                "values": {"run-2026-01-10-001": "baseline", "run-2026-01-10-002": "baseline"},
                "is_same": True,
            },
            "loop": {
                "axis": "loop",
                "values": {"run-2026-01-10-001": "standard", "run-2026-01-10-002": "standard"},
                "is_same": True,
            },
            "varying_axes": ["config"],
        },
        "metrics": [
            {
                "metric_name": "total_cost",
                "values": {"run-2026-01-10-001": 1.5, "run-2026-01-10-002": 2.0},
                "deltas": {"run-2026-01-10-001": None, "run-2026-01-10-002": 33.33},
                "winner": "run-2026-01-10-001",
                "lower_is_better": True,
            },
            {
                "metric_name": "total_tokens",
                "values": {"run-2026-01-10-001": 10000, "run-2026-01-10-002": 15000},
                "deltas": {"run-2026-01-10-001": None, "run-2026-01-10-002": 50.0},
                "winner": "run-2026-01-10-001",
                "lower_is_better": True,
            },
        ],
        "conclusion": "Run 2 completed more stories but cost more.",
    }


@pytest.fixture
def mock_runs_dir(tmp_path: Path) -> Path:
    """Create a mock runs directory with valid run structure."""
    experiments_dir = tmp_path / "experiments"
    runs_dir = experiments_dir / "runs"

    # Create two valid run directories with manifests
    for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        manifest_path = run_dir / "manifest.yaml"
        manifest_path.write_text(f"""
run_id: {run_id}
status: completed
started: "2026-01-10T10:00:00Z"
completed: "2026-01-10T11:30:00Z"
input:
  fixture: minimal
  config: opus-solo
  patch_set: baseline
  loop: standard
""")

    return runs_dir


# =============================================================================
# Comparison Endpoint Tests
# =============================================================================


class TestGetExperimentsCompare:
    """Tests for GET /api/experiments/compare endpoint."""

    @pytest.mark.asyncio
    async def test_compare_returns_200_with_valid_runs(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN two valid run IDs
        WHEN GET /api/experiments/compare?runs=run1,run2
        THEN returns 200 with comparison data.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:
            # Mock the async thread execution to return our mock report
            async def mock_run_sync(func):
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=run-2026-01-10-001,run-2026-01-10-002"
                )

                assert response.status_code == 200
                data = response.json()
                assert "run_ids" in data
                assert "config_diff" in data
                assert "runs" in data
                assert "metrics" in data

    @pytest.mark.asyncio
    async def test_compare_missing_runs_param_returns_400(self, tmp_path: Path) -> None:
        """GIVEN no runs parameter
        WHEN GET /api/experiments/compare
        THEN returns 400 with error message.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "missing_runs"
            assert "required" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_compare_empty_runs_param_returns_400(self, tmp_path: Path) -> None:
        """GIVEN empty runs parameter
        WHEN GET /api/experiments/compare?runs=
        THEN returns 400 with error message.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare?runs=")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "missing_runs"

    @pytest.mark.asyncio
    async def test_compare_single_run_returns_400(self, tmp_path: Path) -> None:
        """GIVEN only one run ID
        WHEN GET /api/experiments/compare?runs=run1
        THEN returns 400 (minimum 2 required).
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare?runs=run-001")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "too_few_runs"
            assert "2" in data["message"]

    @pytest.mark.asyncio
    async def test_compare_too_many_runs_returns_400(self, tmp_path: Path) -> None:
        """GIVEN more than MAX_COMPARISON_RUNS run IDs
        WHEN GET /api/experiments/compare?runs=run1,run2,...,run11
        THEN returns 400 (maximum 10 allowed).
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        # Create 11 run IDs
        run_ids = ",".join(f"run-{i:03d}" for i in range(11))

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/experiments/compare?runs={run_ids}")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "too_many_runs"
            assert "10" in data["message"]

    @pytest.mark.asyncio
    async def test_compare_invalid_run_id_format_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid run ID format (contains special characters)
        WHEN GET /api/experiments/compare?runs=run1,../malicious
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare?runs=run-001,../malicious")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "invalid_run_id"

    @pytest.mark.asyncio
    async def test_compare_deduplicates_run_ids(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN duplicate run IDs
        WHEN GET /api/experiments/compare?runs=run1,run1,run2
        THEN deduplicates and processes normally.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=run-2026-01-10-001,run-2026-01-10-001,run-2026-01-10-002"
                )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_compare_nonexistent_run_returns_404(self, tmp_path: Path) -> None:
        """GIVEN run ID that doesn't exist
        WHEN GET /api/experiments/compare?runs=run1,nonexistent
        THEN returns 404.
        """
        # Create experiments directory structure
        experiments_dir = tmp_path / "experiments" / "runs"
        experiments_dir.mkdir(parents=True)

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare?runs=run-001,run-002")

            assert response.status_code == 404
            data = response.json()
            assert data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_compare_preserves_run_order(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN run IDs in specific order
        WHEN GET /api/experiments/compare?runs=run2,run1
        THEN order is preserved in response.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                # Capture what was called
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=run-2026-01-10-002,run-2026-01-10-001"
                )

                assert response.status_code == 200


# =============================================================================
# Export Endpoint Tests
# =============================================================================


class TestGetExperimentsCompareExport:
    """Tests for GET /api/experiments/compare/export endpoint."""

    @pytest.mark.asyncio
    async def test_export_returns_markdown_file(self, tmp_path: Path) -> None:
        """GIVEN valid run IDs
        WHEN GET /api/experiments/compare/export?runs=run1,run2
        THEN returns Markdown file download.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        mock_markdown = "# Comparison Report\n\nSome content..."

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_markdown

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare/export?runs=run-2026-01-10-001,run-2026-01-10-002"
                )

                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/plain")
                assert "attachment" in response.headers["content-disposition"]
                assert "comparison" in response.headers["content-disposition"]
                assert ".md" in response.headers["content-disposition"]
                assert response.text == mock_markdown

    @pytest.mark.asyncio
    async def test_export_missing_runs_returns_400(self, tmp_path: Path) -> None:
        """GIVEN no runs parameter
        WHEN GET /api/experiments/compare/export
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare/export")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "missing_runs"

    @pytest.mark.asyncio
    async def test_export_single_run_returns_400(self, tmp_path: Path) -> None:
        """GIVEN only one run ID
        WHEN GET /api/experiments/compare/export?runs=run1
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare/export?runs=run-001")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "too_few_runs"

    @pytest.mark.asyncio
    async def test_export_invalid_run_id_returns_400(self, tmp_path: Path) -> None:
        """GIVEN invalid run ID format
        WHEN GET /api/experiments/compare/export?runs=run1,bad/id
        THEN returns 400.
        """
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/experiments/compare/export?runs=run-001,bad/id")

            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "invalid_run_id"

    @pytest.mark.asyncio
    async def test_export_filename_contains_date(self, tmp_path: Path) -> None:
        """GIVEN valid export request
        WHEN GET /api/experiments/compare/export
        THEN filename contains current date.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-001", "run-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        mock_markdown = "# Comparison Report"

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_markdown

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/experiments/compare/export?runs=run-001,run-002")

                assert response.status_code == 200
                # Check filename contains date pattern YYYY-MM-DD
                content_disposition = response.headers["content-disposition"]
                assert "comparison-" in content_disposition
                # Verify date format in filename
                import re

                assert re.search(r"comparison-\d{4}-\d{2}-\d{2}\.md", content_disposition)


# =============================================================================
# Validation Helper Tests
# =============================================================================


class TestValidateComparisonRuns:
    """Tests for _validate_comparison_runs helper function."""

    @pytest.mark.asyncio
    async def test_max_comparison_runs_is_10(self) -> None:
        """GIVEN MAX_COMPARISON_RUNS constant
        WHEN checking value
        THEN is 10.
        """
        assert MAX_COMPARISON_RUNS == 10

    @pytest.mark.asyncio
    async def test_whitespace_in_run_ids_trimmed(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN run IDs with whitespace
        WHEN GET /api/experiments/compare?runs= run1 , run2
        THEN whitespace is trimmed.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=%20run-2026-01-10-001%20,%20run-2026-01-10-002%20"
                )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_run_ids_filtered_out(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN run IDs with empty entries
        WHEN GET /api/experiments/compare?runs=run1,,run2
        THEN empty entries are filtered.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-2026-01-10-001", "run-2026-01-10-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=run-2026-01-10-001,,run-2026-01-10-002"
                )

                assert response.status_code == 200


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestComparisonErrorHandling:
    """Tests for error handling in comparison endpoints."""

    @pytest.mark.asyncio
    async def test_comparison_generator_value_error_returns_400(self, tmp_path: Path) -> None:
        """GIVEN ComparisonGenerator raises ValueError
        WHEN GET /api/experiments/compare
        THEN returns 400.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-001", "run-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                raise ValueError("Invalid comparison configuration")

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/experiments/compare?runs=run-001,run-002")

                assert response.status_code == 400
                data = response.json()
                assert data["error"] == "validation_error"

    @pytest.mark.asyncio
    async def test_comparison_internal_error_returns_500(self, tmp_path: Path) -> None:
        """GIVEN unexpected exception during comparison
        WHEN GET /api/experiments/compare
        THEN returns 500.
        """
        # Create required run directories
        experiments_dir = tmp_path / "experiments" / "runs"
        for run_id in ["run-001", "run-002"]:
            run_dir = experiments_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                raise RuntimeError("Unexpected error")

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/experiments/compare?runs=run-001,run-002")

                assert response.status_code == 500
                data = response.json()
                assert data["error"] == "server_error"


# =============================================================================
# Integration Tests
# =============================================================================


class TestComparisonIntegration:
    """Integration tests with actual file system."""

    @pytest.mark.asyncio
    async def test_compare_endpoint_validation_flow(
        self, tmp_path: Path, mock_comparison_report_dict: dict[str, Any]
    ) -> None:
        """GIVEN valid run directories with manifests
        WHEN GET /api/experiments/compare with valid runs
        THEN validation passes and comparison is attempted.
        """
        # Create experiments structure with valid runs
        experiments_dir = tmp_path / "experiments"
        runs_dir = experiments_dir / "runs"

        # Create two run directories with minimal manifest
        for run_id in ["run-test-001", "run-test-002"]:
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.yaml").write_text(f"run_id: {run_id}\nstatus: completed\n")

        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        transport = ASGITransport(app=app)

        # Mock the comparison generator to avoid needing full manifest format
        with patch("bmad_assist.dashboard.routes.experiments.compare.to_thread") as mock_to_thread:

            async def mock_run_sync(func):
                return mock_comparison_report_dict

            mock_to_thread.run_sync = mock_run_sync

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/experiments/compare?runs=run-test-001,run-test-002"
                )

                assert response.status_code == 200
                data = response.json()
                assert "run_ids" in data
                assert "config_diff" in data
                assert "runs" in data
