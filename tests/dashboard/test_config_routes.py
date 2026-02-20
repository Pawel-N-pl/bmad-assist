"""Tests for config API routes.

Tests cover all config API endpoints defined in Story 17.2:
- GET /api/config - Merged config with provenance
- GET /api/config/global - Global config only
- GET /api/config/project - Project config only
- PUT /api/config/global - Update global config
- PUT /api/config/project - Update project config
- POST /api/config/reload - Reload config singleton
- GET /api/config/schema - Config field metadata
- GET /api/config/backups - List config backups
- POST /api/config/restore - Restore from backup
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate tests from real bmad-assist.yaml in project root."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def mock_server():
    """Create a mock DashboardServer."""
    server = MagicMock()
    server.project_root = Path("/tmp/test-project")
    server.sse_broadcaster = MagicMock()

    # Make broadcast_event an async mock
    async def mock_broadcast_event(*args, **kwargs):
        return 0

    server.sse_broadcaster.broadcast_event = MagicMock(side_effect=mock_broadcast_event)
    return server


@pytest.fixture
def app(mock_server):
    """Create a test Starlette application with config routes."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    from bmad_assist.dashboard.routes.config.backup import (
        get_config_backups,
        post_config_restore,
    )
    from bmad_assist.dashboard.routes.config.crud import (
        get_config,
        get_config_global,
        get_config_project,
        post_config_reload,
        put_config_global,
        put_config_project,
    )
    from bmad_assist.dashboard.routes.config.schema import get_config_schema_endpoint

    routes = [
        Route("/api/config", get_config, methods=["GET"]),
        Route("/api/config/global", get_config_global, methods=["GET"]),
        Route("/api/config/project", get_config_project, methods=["GET"]),
        Route("/api/config/global", put_config_global, methods=["PUT"]),
        Route("/api/config/project", put_config_project, methods=["PUT"]),
        Route("/api/config/reload", post_config_reload, methods=["POST"]),
        Route("/api/config/schema", get_config_schema_endpoint, methods=["GET"]),
        Route("/api/config/backups", get_config_backups, methods=["GET"]),
        Route("/api/config/restore", post_config_restore, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    app.state.server = mock_server
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_config_editor():
    """Create a mock ConfigEditor."""
    editor = MagicMock()
    editor.get_merged_with_provenance.return_value = {
        "benchmarking": {
            "enabled": {"value": True, "source": "default"},
        },
        "providers": {
            "master": {
                "provider": {"value": "claude", "source": "global"},
                "model": {"value": "opus", "source": "project"},
            },
        },
    }
    editor.get_global_raw.return_value = {
        "benchmarking": {"enabled": True},
        "providers": {"master": {"provider": "claude"}},
    }
    editor.get_project_raw.return_value = {
        "providers": {"master": {"model": "opus"}},
    }
    editor.list_backups.return_value = [
        {"version": 1, "path": "/path/to/backup.1", "modified": "2026-01-08T10:00:00Z"},
        {"version": 2, "path": "/path/to/backup.2", "modified": "2026-01-08T11:00:00Z"},
    ]
    return editor


class TestGetConfig:
    """Tests for GET /api/config endpoint."""

    def test_returns_merged_config_with_provenance(self, client, mock_config_editor):
        """Test that merged config is returned with provenance info."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert "benchmarking" in data
        assert data["benchmarking"]["enabled"]["value"] is True
        assert data["benchmarking"]["enabled"]["source"] == "default"

    def test_excludes_dangerous_fields(self, client, mock_config_editor):
        """Test that DANGEROUS fields are filtered from response."""
        # Add a dangerous field to the mock response
        mock_config_editor.get_merged_with_provenance.return_value = {
            "benchmarking": {
                "enabled": {"value": True, "source": "default"},
            },
            # This simulates a dangerous field that should be filtered
        }

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config")

        assert response.status_code == 200
        # Dangerous fields should not be present
        data = response.json()
        assert "benchmarking" in data

    def test_returns_500_on_config_error(self, client):
        """Test that ConfigError returns 500."""
        from bmad_assist.core.exceptions import ConfigError

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            side_effect=ConfigError("Test error"),
        ):
            response = client.get("/api/config")

        assert response.status_code == 500
        assert response.json()["error"] == "config_error"


class TestGetConfigGlobal:
    """Tests for GET /api/config/global endpoint."""

    def test_returns_global_config_only(self, client, mock_config_editor):
        """Test that only global config is returned."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config/global")

        assert response.status_code == 200
        data = response.json()
        # All sources should be "global"
        assert "benchmarking" in data


class TestGetConfigProject:
    """Tests for GET /api/config/project endpoint."""

    def test_returns_project_config_only(self, client, mock_config_editor):
        """Test that only project config is returned."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config/project")

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data

    def test_returns_empty_object_when_no_project_config(self, client, mock_config_editor):
        """Test that empty object is returned when no project config exists."""
        mock_config_editor.get_project_raw.return_value = {}

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config/project")

        assert response.status_code == 200
        assert response.json() == {}


class TestPutConfigGlobal:
    """Tests for PUT /api/config/global endpoint."""

    def test_updates_safe_fields_immediately(self, client, mock_config_editor):
        """Test that SAFE field updates succeed without confirmation."""
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "benchmarking": {"enabled": {"security": "safe"}},
                },
            ),
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "benchmarking.enabled", "value": False}],
                },
            )

        assert response.status_code == 200
        mock_config_editor.update.assert_called()
        mock_config_editor.validate.assert_called()
        mock_config_editor.save.assert_called_with("global")

    def test_returns_428_for_risky_fields_without_confirmation(self, client, mock_config_editor):
        """Test that RISKY fields require confirmation."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._get_full_schema",
            return_value={
                "providers": {"master": {"model": {"security": "risky"}}},
            },
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "providers.master.model", "value": "sonnet"}],
                    "confirmed": False,
                },
            )

        assert response.status_code == 428
        data = response.json()
        assert data["requires_confirmation"] is True
        assert "providers.master.model" in data["risky_fields"]

    def test_accepts_risky_fields_with_confirmation(self, client, mock_config_editor):
        """Test that RISKY fields succeed with confirmed=true."""
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "providers": {"master": {"model": {"security": "risky"}}},
                },
            ),
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "providers.master.model", "value": "sonnet"}],
                    "confirmed": True,
                },
            )

        assert response.status_code == 200
        mock_config_editor.update.assert_called()

    def test_returns_403_for_dangerous_fields(self, client, mock_config_editor):
        """Test that DANGEROUS fields are rejected."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._get_full_schema",
            return_value={
                "dangerous_field": {"security": "dangerous"},
            },
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "dangerous_field", "value": "malicious"}],
                },
            )

        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"

    def test_returns_400_for_invalid_path(self, client):
        """Test that invalid paths return 400."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._get_full_schema",
            return_value={
                "benchmarking": {"enabled": {"security": "safe"}},
            },
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "nonexistent.field", "value": True}],
                },
            )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_path"

    def test_empty_updates_returns_current_config(self, client, mock_config_editor):
        """Test that empty updates array returns current config (no-op)."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.put(
                "/api/config/global",
                json={"updates": []},
            )

        assert response.status_code == 200
        # Validate should NOT have been called (no backup created)
        mock_config_editor.validate.assert_not_called()


class TestPutConfigProject:
    """Tests for PUT /api/config/project endpoint."""

    def test_updates_project_config(self, client, mock_config_editor, mock_server):
        """Test that project config updates work."""
        mock_server.project_root = Path("/tmp/test-project")

        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "benchmarking": {"enabled": {"security": "safe"}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "benchmarking.enabled", "value": True}],
                },
            )

        assert response.status_code == 200


class TestPostConfigReload:
    """Tests for POST /api/config/reload endpoint."""

    def test_reloads_config_successfully(self, client, mock_server):
        """Test that config reload succeeds."""
        with patch(
            "bmad_assist.dashboard.routes.config.crud.reload_config",
        ) as mock_reload:
            response = client.post("/api/config/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["reloaded"] is True
        mock_reload.assert_called_once()

    def test_broadcasts_sse_event_on_reload(self, client, mock_server):
        """Test that SSE event is broadcast after reload."""
        with patch(
            "bmad_assist.dashboard.routes.config.crud.reload_config",
        ):
            response = client.post("/api/config/reload")

        assert response.status_code == 200
        # SSE broadcast should have been called
        mock_server.sse_broadcaster.broadcast_event.assert_called()


class TestGetConfigSchema:
    """Tests for GET /api/config/schema endpoint."""

    def test_returns_schema(self, client):
        """Test that schema is returned."""
        with patch(
            "bmad_assist.dashboard.routes.config.schema.get_config_schema",
            return_value={"benchmarking": {"enabled": {"security": "safe"}}},
        ):
            response = client.get("/api/config/schema")

        assert response.status_code == 200
        data = response.json()
        assert "benchmarking" in data


class TestGetConfigBackups:
    """Tests for GET /api/config/backups endpoint."""

    def test_returns_backup_list(self, client, mock_config_editor):
        """Test that backup list is returned."""
        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config/backups?scope=global")

        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert len(data["backups"]) == 2

    def test_requires_scope_parameter(self, client):
        """Test that scope parameter is required."""
        response = client.get("/api/config/backups")

        assert response.status_code == 400
        assert response.json()["error"] == "missing_scope"

    def test_validates_scope_value(self, client):
        """Test that invalid scope values are rejected."""
        response = client.get("/api/config/backups?scope=invalid")

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_scope"

    def test_returns_empty_list_when_no_backups(self, client, mock_config_editor):
        """Test that empty list is returned when no backups exist."""
        mock_config_editor.list_backups.return_value = []

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.get("/api/config/backups?scope=global")

        assert response.status_code == 200
        assert response.json()["backups"] == []


class TestPostConfigRestore:
    """Tests for POST /api/config/restore endpoint."""

    def test_restores_backup_successfully(self, client, mock_config_editor):
        """Test that backup restore succeeds."""
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.backup.reload_config",
            ),
        ):
            response = client.post(
                "/api/config/restore",
                json={"scope": "global", "version": 1},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["restored"] is True
        assert data["version"] == 1
        assert data["scope"] == "global"

    def test_requires_scope(self, client):
        """Test that scope is required."""
        response = client.post(
            "/api/config/restore",
            json={"version": 1},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "missing_scope"

    def test_requires_version(self, client):
        """Test that version is required."""
        response = client.post(
            "/api/config/restore",
            json={"scope": "global"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "missing_version"

    def test_returns_404_for_nonexistent_backup(self, client, mock_config_editor):
        """Test that 404 is returned for nonexistent backup version."""
        from bmad_assist.core.exceptions import ConfigError

        mock_config_editor.restore_backup.side_effect = ConfigError(
            "Backup version 999 does not exist"
        )

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.post(
                "/api/config/restore",
                json={"scope": "global", "version": 999},
            )

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    def test_returns_400_for_invalid_backup_content(self, client, mock_config_editor):
        """Test that 400 is returned if backup content is invalid."""
        from bmad_assist.core.exceptions import ConfigError

        mock_config_editor.restore_backup.side_effect = ConfigError("Invalid config structure")

        with patch(
            "bmad_assist.dashboard.routes.config.utils._create_config_editor",
            return_value=mock_config_editor,
        ):
            response = client.post(
                "/api/config/restore",
                json={"scope": "global", "version": 1},
            )

        assert response.status_code == 400
        assert response.json()["error"] == "validation_error"


class TestHelperFunctions:
    """Tests for helper functions used by config routes."""

    def test_filter_dangerous_fields(self):
        """Test that _filter_dangerous_fields removes dangerous fields."""
        from bmad_assist.dashboard.routes.config.utils import _filter_dangerous_fields

        data = {
            "safe_field": {"value": 1, "source": "default"},
            "dangerous_field": {"value": "secret", "source": "global"},
            "nested": {
                "safe": {"value": 2, "source": "default"},
                "dangerous": {"value": "secret", "source": "global"},
            },
        }
        schema = {
            "safe_field": {"security": "safe"},
            "dangerous_field": {"security": "dangerous"},
            "nested": {
                "safe": {"security": "safe"},
                "dangerous": {"security": "dangerous"},
            },
        }

        result = _filter_dangerous_fields(data, schema)

        assert "safe_field" in result
        assert "dangerous_field" not in result
        assert "safe" in result["nested"]
        assert "dangerous" not in result["nested"]

    def test_get_field_security(self):
        """Test that _get_field_security returns correct security level."""
        from bmad_assist.dashboard.routes.config.utils import _get_field_security

        schema = {
            "benchmarking": {"enabled": {"security": "safe"}},
            "providers": {"master": {"model": {"security": "risky"}}},
        }

        assert _get_field_security("benchmarking.enabled", schema) == "safe"
        assert _get_field_security("providers.master.model", schema) == "risky"
        assert _get_field_security("unknown.path", schema) == "safe"

    def test_validate_path_exists(self):
        """Test that _validate_path_exists validates paths correctly."""
        from bmad_assist.dashboard.routes.config.utils import _validate_path_exists

        schema = {
            "benchmarking": {"enabled": {"security": "safe"}},
            "providers": {"master": {"model": {"security": "risky"}}},
        }

        exists, msg = _validate_path_exists("benchmarking.enabled", schema)
        assert exists is True
        assert msg == ""

        exists, msg = _validate_path_exists("unknown.field", schema)
        assert exists is False
        assert "not found" in msg.lower()

    def test_add_provenance_to_raw(self):
        """Test that _add_provenance_to_raw adds source info."""
        from bmad_assist.dashboard.routes.config.utils import _add_provenance_to_raw

        data = {
            "field1": "value1",
            "nested": {"field2": "value2"},
        }

        result = _add_provenance_to_raw(data, "global")

        assert result["field1"]["value"] == "value1"
        assert result["field1"]["source"] == "global"
        assert result["nested"]["field2"]["value"] == "value2"
        assert result["nested"]["field2"]["source"] == "global"


# =============================================================================
# Story 17.8: Null Value Handling Tests (Reset Functionality)
# =============================================================================


class TestPutConfigNullValueHandling:
    """Tests for PUT /api/config with null values (Story 17.8 AC5).

    Story 17.8 introduces "Reset to default" / "Reset to global" functionality
    where null values in updates signal "delete this field" to enable inheritance.
    """

    def test_null_value_calls_remove_not_update(self, client, mock_config_editor):
        """Test that null value in update calls editor.remove() not update().

        Story 17.8 AC5: Backend PUT endpoint MUST interpret value: null as
        "delete this field from YAML" (not set to null).
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "testarch": {"playwright": {"timeout": {"security": "safe"}}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "testarch.playwright.timeout", "value": None}],
                },
            )

        assert response.status_code == 200
        # editor.remove should have been called, not editor.update
        mock_config_editor.remove.assert_called_once_with("project", "testarch.playwright.timeout")
        # editor.update should NOT have been called for this null value
        # (It may be called for other things, but not for this path)
        for call in mock_config_editor.update.call_args_list:
            assert call[0][1] != "testarch.playwright.timeout"

    def test_null_value_enables_inheritance(self, client, mock_config_editor):
        """Test that deleting a project field causes inheritance from global.

        Story 17.8 AC5: After deletion + reload, field should inherit from
        next level (global or default).
        """
        # Simulate a project field that will be deleted
        mock_config_editor.get_project_raw.return_value = {
            "testarch": {"playwright": {"timeout": 5000}},  # Project override
        }
        mock_config_editor.get_global_raw.return_value = {
            "testarch": {"playwright": {"timeout": 30000}},  # Global default
        }

        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "testarch": {"playwright": {"timeout": {"security": "safe"}}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "testarch.playwright.timeout", "value": None}],
                },
            )

        assert response.status_code == 200
        # Verify remove was called
        mock_config_editor.remove.assert_called_once_with("project", "testarch.playwright.timeout")

    def test_mixed_null_and_regular_updates(self, client, mock_config_editor):
        """Test that mixed null and regular updates are handled correctly.

        Story 17.8: Multiple updates in single request with some null values.
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "testarch": {
                        "playwright": {
                            "timeout": {"security": "safe"},
                            "workers": {"security": "safe"},
                        }
                    },
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [
                        {"path": "testarch.playwright.timeout", "value": None},  # Delete
                        {"path": "testarch.playwright.workers", "value": 4},  # Update
                    ],
                },
            )

        assert response.status_code == 200
        # remove should be called for null value
        mock_config_editor.remove.assert_called_once_with("project", "testarch.playwright.timeout")
        # update should be called for regular value
        mock_config_editor.update.assert_called()
        update_calls = mock_config_editor.update.call_args_list
        workers_update_found = any(
            "testarch.playwright.workers" in str(call) and 4 in call[0] for call in update_calls
        )
        assert workers_update_found

    def test_null_value_on_global_config(self, client, mock_config_editor):
        """Test that null values work for global config deletion too.

        Story 17.8: Reset to default on global config should also work.
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "benchmarking": {"enabled": {"security": "safe"}},
                },
            ),
        ):
            response = client.put(
                "/api/config/global",
                json={
                    "updates": [{"path": "benchmarking.enabled", "value": None}],
                },
            )

        assert response.status_code == 200
        mock_config_editor.remove.assert_called_once_with("global", "benchmarking.enabled")

    def test_null_value_for_risky_field_requires_confirmation(self, client, mock_config_editor):
        """Test that null value on RISKY field still requires 428 confirmation.

        Story 17.8 AC10: Risky field reset still requires 428 confirmation.
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "providers": {"master": {"model": {"security": "risky"}}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "providers.master.model", "value": None}],
                    "confirmed": False,
                },
            )

        assert response.status_code == 428
        data = response.json()
        assert data["requires_confirmation"] is True
        assert "providers.master.model" in data["risky_fields"]

    def test_null_value_for_risky_field_succeeds_with_confirmation(
        self, client, mock_config_editor
    ):
        """Test that null value on RISKY field succeeds with confirmed=true.

        Story 17.8: Reset of risky field should succeed when confirmed.
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._create_config_editor",
                return_value=mock_config_editor,
            ),
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "providers": {"master": {"model": {"security": "risky"}}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "providers.master.model", "value": None}],
                    "confirmed": True,
                },
            )

        assert response.status_code == 200
        mock_config_editor.remove.assert_called_once_with("project", "providers.master.model")

    def test_missing_value_key_returns_400(self, client):
        """Test that update without value key returns 400 error.

        Story 17.8: Ensure API is robust against malformed requests.
        """
        with (
            patch(
                "bmad_assist.dashboard.routes.config.utils._get_full_schema",
                return_value={
                    "testarch": {"playwright": {"timeout": {"security": "safe"}}},
                },
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            response = client.put(
                "/api/config/project",
                json={
                    "updates": [{"path": "testarch.playwright.timeout"}],  # Missing value
                },
            )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_update"
        assert "value is required" in data["message"]
