"""Tests for CI platform detection.

Tests the detect_ci_platform() function that auto-detects
CI/CD platform from project structure.
"""

from pathlib import Path

import pytest


class TestDetectCIPlatform:
    """Tests for detect_ci_platform()."""

    def test_github_actions_with_yml(self, github_ci_project: Path) -> None:
        """Should detect GitHub Actions with .yml files."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(github_ci_project)
        assert result == "github"

    def test_github_actions_with_yaml(self, tmp_path: Path) -> None:
        """Should detect GitHub Actions with .yaml files."""
        from bmad_assist.testarch.core import detect_ci_platform

        workflows_dir = tmp_path / ".github/workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "ci.yaml").write_text("name: CI\n")

        result = detect_ci_platform(tmp_path)
        assert result == "github"

    def test_github_empty_workflows_dir(self, tmp_path: Path) -> None:
        """Should not detect GitHub if workflows dir exists but is empty."""
        from bmad_assist.testarch.core import detect_ci_platform

        workflows_dir = tmp_path / ".github/workflows"
        workflows_dir.mkdir(parents=True)
        # No workflow files

        result = detect_ci_platform(tmp_path)
        assert result == "unknown"

    def test_gitlab_ci(self, gitlab_ci_project: Path) -> None:
        """Should detect GitLab CI."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(gitlab_ci_project)
        assert result == "gitlab"

    def test_circleci(self, circleci_project: Path) -> None:
        """Should detect CircleCI."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(circleci_project)
        assert result == "circleci"

    def test_azure_pipelines(self, azure_project: Path) -> None:
        """Should detect Azure Pipelines."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(azure_project)
        assert result == "azure"

    def test_jenkins(self, jenkins_project: Path) -> None:
        """Should detect Jenkins."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(jenkins_project)
        assert result == "jenkins"

    def test_no_ci(self, no_ci_project: Path) -> None:
        """Should return 'unknown' when no CI detected."""
        from bmad_assist.testarch.core import detect_ci_platform

        result = detect_ci_platform(no_ci_project)
        assert result == "unknown"

    def test_priority_order(self, tmp_path: Path) -> None:
        """Should check GitHub first when multiple CI configs exist."""
        from bmad_assist.testarch.core import detect_ci_platform

        # Create both GitHub and GitLab configs
        workflows_dir = tmp_path / ".github/workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "test.yml").write_text("name: Test\n")
        (tmp_path / ".gitlab-ci.yml").write_text("stages:\n")

        # GitHub should be detected first
        result = detect_ci_platform(tmp_path)
        assert result == "github"


class TestCIPlatformEnum:
    """Tests for CIPlatform enum."""

    def test_enum_values(self) -> None:
        """Should have correct string values."""
        from bmad_assist.testarch.core import CIPlatform

        assert CIPlatform.GITHUB.value == "github"
        assert CIPlatform.GITLAB.value == "gitlab"
        assert CIPlatform.CIRCLECI.value == "circleci"
        assert CIPlatform.AZURE.value == "azure"
        assert CIPlatform.JENKINS.value == "jenkins"
        assert CIPlatform.UNKNOWN.value == "unknown"

    def test_enum_count(self) -> None:
        """Should have exactly 6 CI platforms."""
        from bmad_assist.testarch.core import CIPlatform

        assert len(CIPlatform) == 6
