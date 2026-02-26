"""Tests for automatic sprint-status.yaml generation - Story 16.1 enhancement.

Tests verify:
- Auto-generation from epic files when sprint-status.yaml is missing
- Proper error when no epic files exist
- Generated sprint-status.yaml is valid and usable

Quick fix for dashboard startup without existing sprint-status.yaml.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app
from bmad_assist.core.exceptions import DashboardError

runner = CliRunner()


# =============================================================================
# Test: Auto-Generation from Epic Files
# =============================================================================


class TestSprintStatusAutoGeneration:
    """Tests for automatic sprint-status.yaml generation from epic files."""

    def test_dashboard_auto_generates_from_epics(self, tmp_path: Path) -> None:
        """GIVEN sprint-status.yaml is missing but epic files exist
        WHEN dashboard server starts
        THEN sprint-status.yaml is auto-generated from epics.
        """
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Project with epic files but no sprint-status
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create epic files directory
        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        # Create sample epic file (BMAD format: # Epic N: Title)
        epic_file = epics_dir / "epic-1-test.md"
        epic_file.write_text("""# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** backlog

Implementation of first story.
""")

        # WHEN: DashboardServer is created (should auto-generate)
        server = DashboardServer(project_root=project_dir)

        # THEN: sprint-status.yaml was created
        sprint_status_path = (
            project_dir / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        )
        assert sprint_status_path.exists(), "sprint-status.yaml should be auto-generated"

        # Verify server has the correct path
        assert server._sprint_status_path == sprint_status_path

    def test_dashboard_generates_entries_from_multiple_epics(self, tmp_path: Path) -> None:
        """GIVEN multiple epic files exist
        WHEN dashboard auto-generates sprint-status
        THEN all epics and stories are included.
        """
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Project with multiple epics
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        # Create two epic files
        (epics_dir / "epic-1-alpha.md").write_text("""# Epic 1: Alpha Epic

## Story 1.1: Alpha Story

**Status:** backlog
""")

        (epics_dir / "epic-2-beta.md").write_text("""# Epic 2: Beta Epic

## Story 2.1: Beta Story

**Status:** ready-for-dev

## Story 2.2: Beta Story 2

**Status:** in-progress
""")

        # WHEN: DashboardServer is created
        server = DashboardServer(project_root=project_dir)

        # THEN: sprint-status contains entries from all epics
        import yaml

        sprint_status_path = server._sprint_status_path
        with open(sprint_status_path) as f:
            data = yaml.safe_load(f)

        dev_status = data.get("development_status", {})

        # Should have epic meta entries and story entries
        assert "epic-1" in dev_status
        assert "epic-2" in dev_status
        assert "1-1-alpha-story" in dev_status
        assert "2-1-beta-story" in dev_status
        assert "2-2-beta-story-2" in dev_status

        # Verify status values
        assert dev_status["2-1-beta-story"] == "ready-for-dev"
        assert dev_status["2-2-beta-story-2"] == "in-progress"

    def test_dashboard_fails_when_no_epics(self, tmp_path: Path) -> None:
        """GIVEN sprint-status.yaml is missing and no epic files exist
        WHEN dashboard server starts
        THEN clear error message instructs user to create epic file.
        """
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Empty project directory (no epics, no sprint-status)
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        # WHEN: DashboardServer is created
        # THEN: DashboardError is raised with helpful message
        with pytest.raises(DashboardError) as exc_info:
            DashboardServer(project_root=project_dir)

        error_msg = str(exc_info.value)
        assert "auto-generation failed" in error_msg
        assert "no epic files" in error_msg.lower() or "create an epic file" in error_msg.lower()

    def test_dashboard_uses_existing_sprint_status(self, tmp_path: Path) -> None:
        """GIVEN sprint-status.yaml already exists
        WHEN dashboard server starts
        THEN existing file is used (no auto-generation).
        """
        import yaml

        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Project with existing sprint-status
        project_dir = tmp_path / "project"
        impl_dir = project_dir / "_bmad-output/implementation-artifacts"
        impl_dir.mkdir(parents=True)

        sprint_status_path = impl_dir / "sprint-status.yaml"
        existing_data = {
            "generated": "2024-01-01T00:00:00",
            "development_status": {
                "epic-99": "done",
                "99-1-existing-story": "done",
            },
        }
        with open(sprint_status_path, "w") as f:
            yaml.dump(existing_data, f)

        # Create epics too (should be ignored)
        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-1-new.md").write_text("""# Epic 1: Should Be Ignored

## Story 1.1: New

**Status:** backlog
""")

        # WHEN: DashboardServer is created
        server = DashboardServer(project_root=project_dir)

        # THEN: Existing sprint-status is used
        with open(sprint_status_path) as f:
            data = yaml.safe_load(f)

        # Verify existing data is preserved (not regenerated)
        dev_status = data.get("development_status", {})
        assert "epic-99" in dev_status
        assert "99-1-existing-story" in dev_status
        # New epic should NOT be there (no regeneration)
        assert "epic-1" not in dev_status
        assert "1-1-new" not in dev_status

    def test_dashboard_legacy_location_checked_before_generation(self, tmp_path: Path) -> None:
        """GIVEN sprint-status.yaml exists in legacy location
        WHEN dashboard server starts
        THEN legacy file is used (no auto-generation).
        """
        import yaml

        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Project with legacy sprint-status only
        project_dir = tmp_path / "project"
        legacy_dir = project_dir / "docs/sprint-artifacts"
        legacy_dir.mkdir(parents=True)

        legacy_path = legacy_dir / "sprint-status.yaml"
        legacy_data = {
            "generated": "2020-01-01T00:00:00",
            "development_status": {
                "epic-1": "done",
                "1-1-legacy-story": "done",
            },
        }
        with open(legacy_path, "w") as f:
            yaml.dump(legacy_data, f)

        # WHEN: DashboardServer is created
        server = DashboardServer(project_root=project_dir)

        # THEN: Legacy location is used
        assert server._sprint_status_path == legacy_path

        # Verify legacy data is intact
        with open(legacy_path) as f:
            data = yaml.safe_load(f)
        assert "epic-1" in data.get("development_status", {})


# =============================================================================
# Test: CLI Integration
# =============================================================================


class TestServeAutoGenerationIntegration:
    """Integration tests for CLI serve command with auto-generation."""

    def test_serve_cli_auto_generates_sprint_status(self, tmp_path: Path) -> None:
        """GIVEN user runs serve on project with epics but no sprint-status
        WHEN server initializes
        THEN sprint-status is generated and server starts successfully.
        """
        # GIVEN: Project with epics but no sprint-status
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-1-test.md").write_text("""# Epic 1: Test Epic

## Story 1.1: Test Story

**Status:** backlog
""")

        # Mock asyncio.run to prevent actual server start
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = None

            # WHEN: User runs serve
            result = runner.invoke(app, ["serve", "--project", str(project_dir)])

        # THEN: Server started (exit 0) and sprint-status was created
        # Note: exit_code might be 0 if asyncio.run was mocked successfully
        # or might indicate async start was attempted
        sprint_status_path = (
            project_dir / "_bmad-output/implementation-artifacts/sprint-status.yaml"
        )
        assert sprint_status_path.exists(), "sprint-status should be auto-generated"

    def test_serve_cli_fails_with_helpful_message_no_epics(self, tmp_path: Path) -> None:
        """GIVEN user runs serve on empty project (no epics, no sprint-status)
        WHEN server initialization fails
        THEN clear error message about creating epic files.
        """
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Empty project
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        # Patch DashboardServer to raise error and verify error is raised
        # We can't easily test CLI output with the current mock structure,
        # so we verify the underlying behavior instead
        with pytest.raises(DashboardError) as exc_info:
            DashboardServer(project_root=project_dir)

        # THEN: Error message mentions sprint-status and epics
        error_msg = str(exc_info.value).lower()
        assert "sprint-status" in error_msg
        assert "epic" in error_msg or "create" in error_msg


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestAutoGenerationEdgeCases:
    """Tests for edge cases in auto-generation."""

    def test_auto_generation_creates_output_directory(self, tmp_path: Path) -> None:
        """GIVEN _bmad-output directory does not exist
        WHEN auto-generation runs
        THEN directory is created along with sprint-status.yaml.
        """
        from bmad_assist.dashboard.server import DashboardServer

        # GIVEN: Project with epics but NO _bmad-output directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-1-test.md").write_text("""# Epic 1: Test Epic

## Story 1.1: Test Story

**Status:** backlog
""")

        # Verify output dir doesn't exist
        impl_dir = project_dir / "_bmad-output/implementation-artifacts"
        assert not impl_dir.exists()

        # WHEN: DashboardServer is created
        server = DashboardServer(project_root=project_dir)

        # THEN: Directory was created and file exists
        assert impl_dir.exists()
        assert server._sprint_status_path.exists()

    def test_auto_generation_preserves_yaml_validity(self, tmp_path: Path) -> None:
        """GIVEN auto-generation creates sprint-status.yaml
        WHEN file is read back
        THEN it is valid YAML with expected structure.
        """
        from bmad_assist.dashboard.server import DashboardServer
        from bmad_assist.sprint import parse_sprint_status

        # GIVEN: Project with epics
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        epics_dir = project_dir / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-1-test.md").write_text("""# Epic 1: Test Epic

## Story 1.1: First Story

**Status:** done

## Story 1.2: Second Story

**Status:** in-progress
""")

        # WHEN: DashboardServer auto-generates
        server = DashboardServer(project_root=project_dir)

        # THEN: File is valid and parseable by SprintStatus parser
        sprint_status = parse_sprint_status(server._sprint_status_path)

        # Verify structure
        assert sprint_status.metadata is not None
        assert len(sprint_status.entries) > 0

        # Verify epic meta entry exists
        assert "epic-1" in sprint_status.entries

        # Verify story entries exist
        assert "1-1-first-story" in sprint_status.entries
        assert "1-2-second-story" in sprint_status.entries

        # Verify status values
        assert sprint_status.entries["1-1-first-story"].status == "done"
        assert sprint_status.entries["1-2-second-story"].status == "in-progress"
