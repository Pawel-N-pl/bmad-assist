"""Tests for validator identity mapping utilities.

Story 23.8: Validator Identity Mapping

Tests cover:
- load_all_mappings() - loading from cache directory
- resolve_model_name() - extracting human-readable model names
- find_mapping_by_session_id() - session ID lookup
- build_validator_display_map() - building display lookup with disambiguation
- get_mapping_for_story() - full API wrapper
- API endpoint GET /api/mapping/{type}/{epic}/{story}
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from bmad_assist.dashboard.utils.validator_mapping import (
    build_validator_display_map,
    find_mapping_by_session_id,
    get_mapping_for_story,
    load_all_mappings,
    resolve_model_name,
)

# ==========================================
# Test Fixtures
# ==========================================


@pytest.fixture
def sample_mapping_data() -> dict[str, Any]:
    """Sample validation mapping data."""
    return {
        "session_id": "test-session-123",
        "timestamp": "2026-01-18T17:00:23.248619+00:00",
        "mapping": {
            "Validator A": {
                "provider": "gemini-gemini-3-flash-preview",
                "model": "gemini-3-flash-preview",
                "original_ref": "ref-a",
            },
            "Validator B": {
                "provider": "master-opus",
                "model": "opus",
                "original_ref": "ref-b",
            },
            "Validator C": {
                "provider": "claude-subprocess-glm-4.7",
                "model": "sonnet",
                "original_ref": "ref-c",
            },
            "Validator D": {
                "provider": "codex-gpt-4",
                "model": "gpt-4",
                "original_ref": "ref-d",
            },
        },
    }


@pytest.fixture
def sample_mapping_with_duplicates() -> dict[str, Any]:
    """Sample mapping with duplicate model names."""
    return {
        "session_id": "test-session-456",
        "timestamp": "2026-01-18T18:00:00.000000+00:00",
        "mapping": {
            "Validator A": {
                "provider": "gemini-gemini-3-flash-preview",
                "model": "gemini-3-flash-preview",
            },
            "Validator B": {
                "provider": "master-opus",
                "model": "opus",
            },
            "Validator C": {
                "provider": "gemini-gemini-3-flash-preview",
                "model": "gemini-3-flash-preview",
            },
            "Validator D": {
                "provider": "gemini-gemini-3-flash-preview",
                "model": "gemini-3-flash-preview",
            },
        },
    }


@pytest.fixture
def cache_dir_with_mappings(tmp_path: Path, sample_mapping_data: dict) -> Path:
    """Create cache directory with sample mapping files."""
    cache_dir = tmp_path / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True)

    # Write validation mapping
    validation_file = cache_dir / f"validation-mapping-{sample_mapping_data['session_id']}.json"
    validation_file.write_text(json.dumps(sample_mapping_data))

    # Write code-review mapping (same structure, different session)
    code_review_data = sample_mapping_data.copy()
    code_review_data["session_id"] = "code-review-session-789"
    code_review_file = cache_dir / f"code-review-mapping-{code_review_data['session_id']}.json"
    code_review_file.write_text(json.dumps(code_review_data))

    return tmp_path


# ==========================================
# Tests for resolve_model_name()
# ==========================================


class TestResolveModelName:
    """Tests for resolve_model_name() function."""

    def test_gemini_provider(self):
        """Test gemini-gemini-3-flash-preview -> gemini-3-flash-preview."""
        entry = {"provider": "gemini-gemini-3-flash-preview", "model": "gemini-3-flash-preview"}
        assert resolve_model_name(entry) == "gemini-3-flash-preview"

    def test_master_provider(self):
        """Test master-opus -> opus."""
        entry = {"provider": "master-opus", "model": "opus"}
        assert resolve_model_name(entry) == "opus"

    def test_claude_subprocess_provider(self):
        """Test claude-subprocess-glm-4.7 -> glm-4.7."""
        entry = {"provider": "claude-subprocess-glm-4.7", "model": "sonnet"}
        assert resolve_model_name(entry) == "glm-4.7"

    def test_claude_subprocess_short(self):
        """Test claude-subprocess (no model suffix) falls back to model field."""
        entry = {"provider": "claude-subprocess", "model": "sonnet"}
        assert resolve_model_name(entry) == "sonnet"

    def test_codex_provider(self):
        """Test codex-gpt-4 -> gpt-4."""
        entry = {"provider": "codex-gpt-4", "model": "gpt-4"}
        assert resolve_model_name(entry) == "gpt-4"

    def test_unknown_provider(self):
        """Test unknown provider falls back to model field."""
        entry = {"provider": "custom-provider", "model": "custom-model"}
        assert resolve_model_name(entry) == "custom-model"

    def test_no_provider(self):
        """Test missing provider falls back to model field."""
        entry = {"model": "sonnet"}
        assert resolve_model_name(entry) == "sonnet"

    def test_no_model(self):
        """Test missing model returns 'unknown'."""
        entry = {"provider": "gemini-test"}
        assert resolve_model_name(entry) == "test"

    def test_empty_entry(self):
        """Test empty entry returns 'unknown'."""
        assert resolve_model_name({}) == "unknown"


# ==========================================
# Tests for load_all_mappings()
# ==========================================


class TestLoadAllMappings:
    """Tests for load_all_mappings() function."""

    def test_load_valid_files(self, cache_dir_with_mappings: Path):
        """Test loading valid mapping files."""
        mappings = load_all_mappings(cache_dir_with_mappings)

        assert len(mappings) == 2
        assert "test-session-123" in mappings
        assert "code-review-session-789" in mappings

    def test_mapping_type_annotation(self, cache_dir_with_mappings: Path):
        """Test that type is annotated on loaded mappings."""
        mappings = load_all_mappings(cache_dir_with_mappings)

        assert mappings["test-session-123"]["type"] == "validation"
        assert mappings["code-review-session-789"]["type"] == "code-review"

    def test_empty_cache_dir(self, tmp_path: Path):
        """Test with empty cache directory."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        mappings = load_all_mappings(tmp_path)
        assert mappings == {}

    def test_missing_cache_dir(self, tmp_path: Path):
        """Test with missing cache directory."""
        mappings = load_all_mappings(tmp_path)
        assert mappings == {}

    def test_invalid_json_file(self, tmp_path: Path):
        """Test graceful handling of invalid JSON."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        invalid_file = cache_dir / "validation-mapping-invalid.json"
        invalid_file.write_text("not valid json {{{")

        mappings = load_all_mappings(tmp_path)
        assert mappings == {}

    def test_missing_session_id(self, tmp_path: Path):
        """Test graceful handling of missing session_id."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        no_session_file = cache_dir / "validation-mapping-no-session.json"
        no_session_file.write_text(json.dumps({"mapping": {}}))

        mappings = load_all_mappings(tmp_path)
        assert mappings == {}


# ==========================================
# Tests for find_mapping_by_session_id()
# ==========================================


class TestFindMappingBySessionId:
    """Tests for find_mapping_by_session_id() function."""

    def test_find_existing_session(self, sample_mapping_data: dict):
        """Test finding existing session."""
        mappings = {"test-session-123": sample_mapping_data}
        result = find_mapping_by_session_id("test-session-123", mappings)

        assert result is not None
        assert result["session_id"] == "test-session-123"

    def test_find_missing_session(self, sample_mapping_data: dict):
        """Test finding non-existent session."""
        mappings = {"test-session-123": sample_mapping_data}
        result = find_mapping_by_session_id("not-a-session", mappings)

        assert result is None

    def test_find_in_empty_mappings(self):
        """Test finding in empty mappings dict."""
        result = find_mapping_by_session_id("any-session", {})
        assert result is None


# ==========================================
# Tests for build_validator_display_map()
# ==========================================


class TestBuildValidatorDisplayMap:
    """Tests for build_validator_display_map() function."""

    def test_build_unique_models(self, sample_mapping_data: dict):
        """Test building map with unique model names."""
        result = build_validator_display_map(sample_mapping_data)

        assert result["Validator A"] == "gemini-3-flash-preview"
        assert result["Validator B"] == "opus"
        assert result["Validator C"] == "glm-4.7"
        assert result["Validator D"] == "gpt-4"

    def test_build_duplicate_models(self, sample_mapping_with_duplicates: dict):
        """Test disambiguation for duplicate model names (AC6)."""
        result = build_validator_display_map(sample_mapping_with_duplicates)

        # Unique model should not have suffix
        assert result["Validator B"] == "opus"

        # Duplicate models should have letter suffix
        assert result["Validator A"] == "gemini-3-flash-preview (A)"
        assert result["Validator C"] == "gemini-3-flash-preview (C)"
        assert result["Validator D"] == "gemini-3-flash-preview (D)"

    def test_build_empty_mapping(self):
        """Test with empty mapping."""
        result = build_validator_display_map({})
        assert result == {}

    def test_build_missing_mapping_field(self):
        """Test with missing mapping field."""
        result = build_validator_display_map({"session_id": "test"})
        assert result == {}


# ==========================================
# Tests for get_mapping_for_story()
# ==========================================


class TestGetMappingForStory:
    """Tests for get_mapping_for_story() function."""

    def test_get_by_session_id(self, cache_dir_with_mappings: Path):
        """Test direct lookup by session_id."""
        result = get_mapping_for_story(
            cache_dir_with_mappings,
            "validation",
            "23",
            "8",
            session_id="test-session-123",
        )

        assert result is not None
        assert result["session_id"] == "test-session-123"
        assert "Validator A" in result["validators"]

    def test_get_by_session_id_not_found(self, cache_dir_with_mappings: Path):
        """Test session_id lookup with non-existent ID."""
        result = get_mapping_for_story(
            cache_dir_with_mappings,
            "validation",
            "23",
            "8",
            session_id="non-existent",
        )

        assert result is None

    def test_get_without_session_id(self, cache_dir_with_mappings: Path):
        """Test fallback to most recent mapping."""
        result = get_mapping_for_story(
            cache_dir_with_mappings,
            "validation",
            "23",
            "8",
        )

        # Should find the validation mapping
        assert result is not None
        assert "validators" in result

    def test_get_code_review_type(self, cache_dir_with_mappings: Path):
        """Test getting code-review type mapping."""
        result = get_mapping_for_story(
            cache_dir_with_mappings,
            "code-review",
            "23",
            "8",
        )

        assert result is not None
        assert "validators" in result

    def test_get_no_mappings(self, tmp_path: Path):
        """Test with no mapping files."""
        result = get_mapping_for_story(
            tmp_path,
            "validation",
            "23",
            "8",
        )

        assert result is None


# ==========================================
# Tests for API Endpoint
# ==========================================


@pytest.fixture
def mock_server(tmp_path: Path):
    """Create a mock DashboardServer."""
    server = MagicMock()
    server.project_root = tmp_path
    return server


@pytest.fixture
def app(mock_server):
    """Create a test Starlette application with mapping route."""
    from bmad_assist.dashboard.routes.content import get_reviewer_mapping

    routes = [
        Route("/api/mapping/{type}/{epic}/{story}", get_reviewer_mapping, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.state.server = mock_server
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestMappingAPIEndpoint:
    """Tests for GET /api/mapping/{type}/{epic}/{story} endpoint."""

    def test_mapping_found(self, client: TestClient, mock_server, sample_mapping_data: dict):
        """Test successful mapping retrieval (AC5)."""
        # Create cache with mapping file
        cache_dir = mock_server.project_root / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        mapping_file = cache_dir / f"validation-mapping-{sample_mapping_data['session_id']}.json"
        mapping_file.write_text(json.dumps(sample_mapping_data))

        response = client.get("/api/mapping/validation/23/8")

        assert response.status_code == 200
        data = response.json()
        assert "validators" in data
        assert "Validator A" in data["validators"]

    def test_mapping_not_found(self, client: TestClient):
        """Test 404 for missing mapping."""
        response = client.get("/api/mapping/validation/99/99")

        assert response.status_code == 404
        assert "error" in response.json()

    def test_invalid_mapping_type(self, client: TestClient):
        """Test 400 for invalid mapping type."""
        response = client.get("/api/mapping/invalid/23/8")

        assert response.status_code == 400
        assert "Invalid mapping type" in response.json()["error"]

    def test_with_session_id(self, client: TestClient, mock_server, sample_mapping_data: dict):
        """Test direct lookup with session_id query param."""
        cache_dir = mock_server.project_root / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        mapping_file = cache_dir / f"validation-mapping-{sample_mapping_data['session_id']}.json"
        mapping_file.write_text(json.dumps(sample_mapping_data))

        response = client.get(
            f"/api/mapping/validation/23/8?session_id={sample_mapping_data['session_id']}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_mapping_data["session_id"]

    def test_code_review_type(self, client: TestClient, mock_server, sample_mapping_data: dict):
        """Test code-review mapping type."""
        cache_dir = mock_server.project_root / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Create code-review mapping
        sample_mapping_data["session_id"] = "code-review-test"
        mapping_file = cache_dir / f"code-review-mapping-{sample_mapping_data['session_id']}.json"
        mapping_file.write_text(json.dumps(sample_mapping_data))

        response = client.get("/api/mapping/code-review/23/8")

        assert response.status_code == 200
        data = response.json()
        assert "validators" in data


# ==========================================
# Integration Tests
# ==========================================


class TestValidatorMappingIntegration:
    """Integration tests for validator mapping workflow."""

    def test_full_workflow(self, cache_dir_with_mappings: Path, sample_mapping_data: dict):
        """Test complete workflow: load -> find -> build."""
        # Load all mappings
        mappings = load_all_mappings(cache_dir_with_mappings)
        assert len(mappings) > 0

        # Find specific session
        found = find_mapping_by_session_id(sample_mapping_data["session_id"], mappings)
        assert found is not None

        # Build display map
        display_map = build_validator_display_map(found)
        assert "Validator A" in display_map
        assert display_map["Validator C"] == "glm-4.7"

    def test_graceful_degradation(self, tmp_path: Path):
        """Test graceful fallback when mapping unavailable (AC4)."""
        # No cache directory exists
        result = get_mapping_for_story(tmp_path, "validation", "1", "1")
        assert result is None

        # Build map from empty result
        display_map = build_validator_display_map({})
        assert display_map == {}
