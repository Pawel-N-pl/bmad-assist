"""Tests for Story Browser API endpoint (Story 24.5).

Tests the GET /api/story/{epic}/{story}/content endpoint and
related server methods.
"""

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from bmad_assist.dashboard.server import DashboardServer


class TestGetStoryFileContent:
    """Tests for DashboardServer.get_story_file_content() method."""

    def test_returns_content_when_story_file_exists(self, tmp_path: Path):
        """Test returns story content when file exists."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create story file
        story_content = "# Story 24.5: View Story Modal\n\nStatus: ready-for-dev\n\nSome content."
        story_file = impl_dir / "24-5-view-story-modal.md"
        story_file.write_text(story_content)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server
        server = DashboardServer(project_root=tmp_path)

        # Call method
        result = server.get_story_file_content("24", "5")

        # Verify
        assert result is not None
        assert result["content"] == story_content
        assert "24-5-view-story-modal.md" in result["file_path"]
        assert result["title"] == "View Story Modal"

    def test_returns_none_when_story_file_not_found(self, tmp_path: Path):
        """Test returns None when no matching story file exists."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server
        server = DashboardServer(project_root=tmp_path)

        # Call method
        result = server.get_story_file_content("99", "99")

        # Verify
        assert result is None

    def test_selects_most_recent_file_when_multiple_matches(self, tmp_path: Path):
        """Test selects file with most recent mtime when multiple matches exist."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create two story files
        old_content = "# Story 24.5: Old Title\n\nOld content."
        old_file = impl_dir / "24-5-old-story.md"
        old_file.write_text(old_content)

        new_content = "# Story 24.5: New Title\n\nNew content."
        new_file = impl_dir / "24-5-new-story.md"
        new_file.write_text(new_content)

        # Set modification times (old file older than new file)
        old_time = 1000000000.0
        new_time = 2000000000.0
        os.utime(old_file, (old_time, old_time))
        os.utime(new_file, (new_time, new_time))

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server
        server = DashboardServer(project_root=tmp_path)

        # Call method
        result = server.get_story_file_content("24", "5")

        # Verify - should select the newer file
        assert result is not None
        assert result["content"] == new_content
        assert "24-5-new-story.md" in result["file_path"]
        assert result["title"] == "New Title"

    def test_title_fallback_from_filename_slug(self, tmp_path: Path):
        """Test title extraction falls back to filename slug when no H1 heading."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create story file without H1 heading
        story_content = "Status: ready-for-dev\n\nSome content without heading."
        story_file = impl_dir / "24-5-view-story-modal.md"
        story_file.write_text(story_content)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server
        server = DashboardServer(project_root=tmp_path)

        # Call method
        result = server.get_story_file_content("24", "5")

        # Verify - should use filename slug as title
        assert result is not None
        assert result["title"] == "View Story Modal"

    def test_title_fallback_generic(self, tmp_path: Path):
        """Test title extraction falls back to generic title when no H1 and simple filename."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create story file with minimal filename
        story_content = "Some content."
        story_file = impl_dir / "24-5-.md"  # No slug part
        story_file.write_text(story_content)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server
        server = DashboardServer(project_root=tmp_path)

        # Call method
        result = server.get_story_file_content("24", "5")

        # Verify - should use generic fallback
        assert result is not None
        assert result["title"] == "Story 24.5"

    def test_title_extraction_from_h1_variants(self, tmp_path: Path):
        """Test title extraction handles various H1 heading formats."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Test case 1: "# Story X.Y: Title"
        story_file = impl_dir / "24-1-test.md"
        story_file.write_text("# Story 24.1: Test Title\n\nContent")
        server = DashboardServer(project_root=tmp_path)
        result = server.get_story_file_content("24", "1")
        assert result["title"] == "Test Title"

        # Test case 2: "# Title" (no Story prefix)
        story_file2 = impl_dir / "24-2-simple.md"
        story_file2.write_text("# Simple Title\n\nContent")
        result2 = server.get_story_file_content("24", "2")
        assert result2["title"] == "Simple Title"


class TestStoryContentEndpoint:
    """Tests for GET /api/story/{epic}/{story}/content endpoint."""

    @pytest.fixture
    def server_with_story(self, tmp_path: Path):
        """Create a server with a story file."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create story file
        story_content = "# Story 24.5: View Story Modal\n\nStatus: ready-for-dev\n\nContent here."
        story_file = impl_dir / "24-5-view-story-modal.md"
        story_file.write_text(story_content)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server and app
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        return TestClient(app)

    def test_endpoint_returns_json_on_success(self, server_with_story):
        """Test endpoint returns proper JSON structure on success."""
        response = server_with_story.get("/api/story/24/5/content")

        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "file_path" in data
        assert "title" in data
        assert data["title"] == "View Story Modal"
        assert "# Story 24.5" in data["content"]

    def test_endpoint_returns_404_when_not_found(self, tmp_path: Path):
        """Test endpoint returns 404 when story file not found."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server and app
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        client = TestClient(app)

        response = client.get("/api/story/99/99/content")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "99.99" in data["error"]

    def test_endpoint_handles_string_epic_ids(self, tmp_path: Path):
        """Test endpoint handles string epic IDs like 'testarch'."""
        # Create implementation-artifacts directory
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True, exist_ok=True)

        # Create story file with string epic ID
        story_content = "# Story testarch.1: Config Schema\n\nContent"
        story_file = impl_dir / "testarch-1-config-schema.md"
        story_file.write_text(story_content)

        # Create sprint-status.yaml
        sprint_status = impl_dir / "sprint-status.yaml"
        sprint_status.write_text("entries: {}")

        # Create server and app
        server = DashboardServer(project_root=tmp_path)
        app = server.create_app()
        client = TestClient(app)

        response = client.get("/api/story/testarch/1/content")

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Config Schema"


@pytest.mark.skip(reason="Frontend spec - requires E2E/Playwright testing")
class TestContextMenuViewStoryAction:
    """Frontend specification tests for View Story action in context menu.

    These tests document expected frontend behavior. They are SKIPPED because:
    - Python unit tests cannot verify JavaScript behavior
    - Actual verification requires E2E testing with Playwright/Selenium

    See context-menu.js:getStoryActions() for implementation.
    """

    def test_view_story_action_first_in_all_statuses(self):
        """Specification: View Story should be first action for all story statuses.

        Expected statuses: backlog, ready-for-dev, in-progress, review, done
        Expected action object: { icon: '📄', label: 'View Story', action: 'view-story-modal' }
        """
        pass

    def test_view_story_modal_action_fetches_before_opening(self):
        """Specification: viewStoryModal should fetch content before opening modal.

        Fetch-first pattern: Do NOT open modal until fetch completes successfully.
        """
        pass


@pytest.mark.skip(reason="Frontend spec - requires E2E/Playwright testing")
class TestContentModalBrowserState:
    """Frontend specification tests for contentModal browser state.

    These tests document expected frontend behavior. They are SKIPPED because:
    - Python unit tests cannot verify JavaScript behavior
    - Actual verification requires E2E testing with Playwright/Selenium

    See modals.js:contentModal and context-menu.js:viewStoryModal() for implementation.
    """

    def test_content_modal_has_browser_field(self):
        """Specification: contentModal should have browser field initialized to null."""
        pass

    def test_browser_state_created_for_story_view(self):
        """Specification: viewStoryModal should create browser state on success."""
        pass

    def test_browser_state_reset_on_modal_close(self):
        """Specification: contentModal.browser should reset to null on close."""
        pass

    def test_raw_rendered_toggle_responds_quickly(self):
        """Specification: Toggle should respond within 100ms (synchronous)."""
        pass

    def test_copy_button_copies_raw_content(self):
        """Specification: Copy button always copies raw content regardless of view mode."""
        pass
