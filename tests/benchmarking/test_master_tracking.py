"""Tests for master_tracking module.

Tests timing tracking for Master LLM workflows (create-story, dev-story).
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.benchmarking.master_tracking import (
    _analyze_output,
    create_master_record,
    save_master_timing,
)
from bmad_assist.benchmarking.schema import EvaluatorRole

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_output() -> str:
    """Sample LLM output with markdown structure."""
    return """# Story 1.2: User Authentication

## Overview

This story implements user authentication.

## Tasks

- Task 1: Create login form
  - Subtask 1.1: Design UI
  - Subtask 1.2: Add validation
- Task 2: Implement backend
- Task 3: Write tests

## Acceptance Criteria

```python
def test_login():
    assert login("user", "pass") == True
```

## Notes

Additional implementation notes here.
"""


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    from bmad_assist.core.paths import init_paths

    project = tmp_path / "test-project"
    project.mkdir()
    # Initialize git repo for commit hash extraction
    (project / ".git").mkdir()
    # Initialize paths singleton for this test
    paths = init_paths(project)
    paths.ensure_directories()
    return project


# =============================================================================
# Tests for _analyze_output
# =============================================================================


class TestAnalyzeOutput:
    """Tests for output analysis helper."""

    def test_char_count(self, sample_output: str) -> None:
        """Test character count is accurate."""
        result = _analyze_output(sample_output)
        assert result.char_count == len(sample_output)

    def test_heading_count(self, sample_output: str) -> None:
        """Test heading detection."""
        result = _analyze_output(sample_output)
        # # Story, ## Overview, ## Tasks, ## Acceptance Criteria, ## Notes
        assert result.heading_count == 5

    def test_code_block_count(self, sample_output: str) -> None:
        """Test code block detection."""
        result = _analyze_output(sample_output)
        assert result.code_block_count == 1

    def test_list_depth_max(self, sample_output: str) -> None:
        """Test nested list depth detection."""
        result = _analyze_output(sample_output)
        # - Task 1 (depth 1), then - Subtask 1.1 (depth 2)
        assert result.list_depth_max == 2

    def test_sections_detected(self, sample_output: str) -> None:
        """Test level-2 heading extraction."""
        result = _analyze_output(sample_output)
        assert "Overview" in result.sections_detected
        assert "Tasks" in result.sections_detected
        assert "Acceptance Criteria" in result.sections_detected
        assert "Notes" in result.sections_detected

    def test_empty_output(self) -> None:
        """Test handling of empty output."""
        result = _analyze_output("")
        assert result.char_count == 0
        assert result.heading_count == 0
        assert result.code_block_count == 0
        assert result.list_depth_max == 0
        assert result.sections_detected == []

    def test_sections_limited_to_10(self) -> None:
        """Test sections list is limited to 10 items."""
        output = "\n".join(f"## Section {i}" for i in range(15))
        result = _analyze_output(output)
        assert len(result.sections_detected) == 10


# =============================================================================
# Tests for create_master_record
# =============================================================================


class TestCreateMasterRecord:
    """Tests for evaluation record creation."""

    def test_basic_record_creation(self, project_path: Path) -> None:
        """Test creating a basic master record."""
        start = datetime(2025, 12, 27, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 12, 27, 10, 5, 0, tzinfo=UTC)

        record = create_master_record(
            workflow_id="create-story",
            epic_num=1,
            story_num=2,
            story_title="Test Story",
            provider="claude",
            model="opus",
            start_time=start,
            end_time=end,
            output="# Story content",
            project_path=project_path,
        )

        assert record.workflow.id == "create-story"
        assert record.story.epic_num == 1
        assert record.story.story_num == 2
        assert record.story.title == "Test Story"
        assert record.evaluator.provider == "claude"
        assert record.evaluator.model == "opus"
        assert record.evaluator.role == EvaluatorRole.MASTER

    def test_duration_calculation(self, project_path: Path) -> None:
        """Test duration is calculated correctly."""
        start = datetime(2025, 12, 27, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 12, 27, 10, 2, 30, tzinfo=UTC)  # 2 min 30 sec

        record = create_master_record(
            workflow_id="dev-story",
            epic_num=1,
            story_num=1,
            story_title="Test",
            provider="claude",
            model="opus",
            start_time=start,
            end_time=end,
            output="",
            project_path=project_path,
        )

        assert record.execution.duration_ms == 150000  # 150 seconds

    def test_output_analysis_included(self, project_path: Path, sample_output: str) -> None:
        """Test output analysis is performed."""
        record = create_master_record(
            workflow_id="create-story",
            epic_num=1,
            story_num=1,
            story_title="Test",
            provider="claude",
            model="opus",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            output=sample_output,
            project_path=project_path,
        )

        assert record.output.char_count == len(sample_output)
        assert record.output.heading_count > 0

    def test_environment_info(self, project_path: Path) -> None:
        """Test environment info is populated."""
        record = create_master_record(
            workflow_id="create-story",
            epic_num=1,
            story_num=1,
            story_title="Test",
            provider="claude",
            model="opus",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            output="",
            project_path=project_path,
        )

        assert record.environment.python_version is not None
        assert record.environment.platform is not None
        assert record.environment.bmad_assist_version is not None

    def test_role_id_is_none_for_master(self, project_path: Path) -> None:
        """Test Master role has no role_id (unlike validators a/b/c/d/e)."""
        record = create_master_record(
            workflow_id="create-story",
            epic_num=1,
            story_num=1,
            story_title="Test",
            provider="claude",
            model="opus",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            output="",
            project_path=project_path,
        )

        assert record.evaluator.role_id is None


# =============================================================================
# Tests for save_master_timing
# =============================================================================


class TestSaveMasterTiming:
    """Tests for timing record persistence."""

    def test_saves_to_benchmarks_dir(self, project_path: Path) -> None:
        """Test record is saved to benchmarks directory."""
        start = datetime(2025, 12, 27, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 12, 27, 10, 5, 0, tzinfo=UTC)

        result_path = save_master_timing(
            workflow_id="create-story",
            epic_num=1,
            story_num=2,
            story_title="Test Story",
            provider="claude",
            model="opus",
            start_time=start,
            end_time=end,
            output="# Content",
            project_path=project_path,
        )

        assert result_path is not None
        assert result_path.exists()
        assert "benchmarks" in str(result_path)
        # Filename uses role "master", workflow_id stored inside record
        assert "master" in result_path.name

    def test_custom_benchmarks_base(self, tmp_path: Path, project_path: Path) -> None:
        """Test custom benchmarks base directory."""
        custom_base = tmp_path / "custom-benchmarks"

        result_path = save_master_timing(
            workflow_id="dev-story",
            epic_num=2,
            story_num=3,
            story_title="Custom",
            provider="gemini",
            model="flash",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            output="",
            project_path=project_path,
            benchmarks_base=custom_base,
        )

        assert result_path is not None
        assert str(custom_base) in str(result_path)

    def test_returns_none_on_error(self, project_path: Path) -> None:
        """Test graceful error handling."""
        with patch(
            "bmad_assist.benchmarking.master_tracking.save_evaluation_record",
            side_effect=Exception("Storage error"),
        ):
            result = save_master_timing(
                workflow_id="create-story",
                epic_num=1,
                story_num=1,
                story_title="Test",
                provider="claude",
                model="opus",
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                output="",
                project_path=project_path,
            )

        assert result is None

    def test_file_naming_convention(self, project_path: Path) -> None:
        """Test file follows eval-{epic}-{story}-{role}-{timestamp}.yaml pattern."""
        start = datetime(2025, 12, 27, 10, 0, 0, tzinfo=UTC)

        result_path = save_master_timing(
            workflow_id="create-story",
            epic_num=1,
            story_num=2,
            story_title="Test",
            provider="claude",
            model="opus",
            start_time=start,
            end_time=datetime.now(UTC),
            output="",
            project_path=project_path,
        )

        assert result_path is not None
        # Pattern: eval-{epic}-{story}-{role}-{timestamp}.yaml
        # For MASTER role, role segment is "master"
        assert result_path.name.startswith("eval-1-2-master-")
        assert result_path.suffix == ".yaml"
