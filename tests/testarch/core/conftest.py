"""Test fixtures for testarch.core module."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


@dataclass
class MockCompilerContext:
    """Mock CompilerContext for testing."""

    project_root: Path
    output_folder: Path
    project_knowledge: Path | None = None
    cwd: Path | None = None
    workflow_ir: Any = None
    patch_path: Path | None = None
    resolved_variables: dict[str, Any] = field(default_factory=dict)
    discovered_files: dict[str, list[Path]] = field(default_factory=dict)
    file_contents: dict[str, str] = field(default_factory=dict)
    links_only: bool = False


@pytest.fixture
def mock_context(tmp_path: Path) -> MockCompilerContext:
    """Create a mock compiler context with tmp_path as project root."""
    return MockCompilerContext(
        project_root=tmp_path,
        output_folder=tmp_path / "_bmad-output/implementation-artifacts",
    )


@pytest.fixture
def github_ci_project(tmp_path: Path) -> Path:
    """Create a project with GitHub Actions CI."""
    workflows_dir = tmp_path / ".github/workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "test.yml").write_text("name: Test\n")
    return tmp_path


@pytest.fixture
def gitlab_ci_project(tmp_path: Path) -> Path:
    """Create a project with GitLab CI."""
    (tmp_path / ".gitlab-ci.yml").write_text("stages:\n  - test\n")
    return tmp_path


@pytest.fixture
def circleci_project(tmp_path: Path) -> Path:
    """Create a project with CircleCI."""
    circleci_dir = tmp_path / ".circleci"
    circleci_dir.mkdir()
    (circleci_dir / "config.yml").write_text("version: 2.1\n")
    return tmp_path


@pytest.fixture
def azure_project(tmp_path: Path) -> Path:
    """Create a project with Azure Pipelines."""
    (tmp_path / "azure-pipelines.yml").write_text("trigger:\n  - main\n")
    return tmp_path


@pytest.fixture
def jenkins_project(tmp_path: Path) -> Path:
    """Create a project with Jenkins."""
    (tmp_path / "Jenkinsfile").write_text("pipeline {\n}\n")
    return tmp_path


@pytest.fixture
def no_ci_project(tmp_path: Path) -> Path:
    """Create a project with no CI."""
    return tmp_path
