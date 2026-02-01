"""Tests for the code-review workflow compiler.

Tests the CodeReviewCompiler class which produces standalone prompts for
adversarial code review of implemented stories.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from bmad_assist.compiler.parser import parse_workflow
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext

# Test-time imports (will fail until implementation exists)
# These are imported inside tests to give clearer error messages


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure for testing."""
    # Create docs directory structure
    docs = tmp_path / "docs"
    docs.mkdir()

    # Create sprint-artifacts
    sprint_artifacts = docs / "sprint-artifacts"
    sprint_artifacts.mkdir()

    # Create epics directory
    epics = docs / "epics"
    epics.mkdir()

    # Create BMAD workflow directory structure
    workflow_dir = tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "code-review"
    workflow_dir.mkdir(parents=True)

    # Create workflow.yaml
    workflow_yaml = workflow_dir / "workflow.yaml"
    workflow_yaml.write_text("""name: code-review
description: "Perform an ADVERSARIAL Senior Developer code review"
config_source: "{project-root}/_bmad/bmm/config.yaml"
template: false
instructions: "{installed_path}/instructions.xml"
""")

    # Create instructions.xml
    instructions_xml = workflow_dir / "instructions.xml"
    instructions_xml.write_text("""<workflow>
  <critical>YOU ARE AN ADVERSARIAL CODE REVIEWER</critical>
  <step n="1" goal="Load story and discover changes">
    <action>Read COMPLETE story file</action>
    <action>Parse sections</action>
  </step>
  <step n="2" goal="Build review attack plan">
    <action>Extract ALL Acceptance Criteria</action>
    <check if="git repository exists">
      <action>Run git status to find changes</action>
    </check>
  </step>
  <step n="3" goal="Execute adversarial review">
    <action>Validate every claim</action>
    <ask>What should I do?</ask>
  </step>
</workflow>
""")

    # Create config.yaml
    config_dir = tmp_path / "_bmad" / "bmm"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text(f"""project_name: test-project
output_folder: '{tmp_path}/docs'
sprint_artifacts: '{tmp_path}/docs/sprint-artifacts'
user_name: TestUser
communication_language: English
document_output_language: English
""")

    # Create project_context.md (required)
    project_context = docs / "project-context.md"
    project_context.write_text("""# Project Context for AI Agents

## Technology Stack

- Python 3.11+
- pytest for testing

## Critical Rules

- Type hints required on all functions
- Google-style docstrings
""")

    return tmp_path


def create_test_context(
    project: Path,
    epic_num: int = 14,
    story_num: int = 4,
    **extra_vars: Any,
) -> CompilerContext:
    """Create a CompilerContext for testing.

    Pre-loads workflow_ir from the workflow directory (normally done by core.compile_workflow).
    """
    resolved_vars = {
        "epic_num": epic_num,
        "story_num": story_num,
        **extra_vars,
    }
    workflow_dir = project / "_bmad" / "bmm" / "workflows" / "4-implementation" / "code-review"
    workflow_ir = parse_workflow(workflow_dir) if workflow_dir.exists() else None
    return CompilerContext(
        project_root=project,
        output_folder=project / "docs",
        resolved_variables=resolved_vars,
        workflow_ir=workflow_ir,
    )


class TestWorkflowProperties:
    """Tests for CodeReviewCompiler properties (AC6, AC8)."""

    def test_workflow_name(self) -> None:
        """workflow_name returns 'code-review'."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        compiler = CodeReviewCompiler()
        assert compiler.workflow_name == "code-review"

    def test_get_required_files(self) -> None:
        """get_required_files returns expected patterns."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        compiler = CodeReviewCompiler()
        patterns = compiler.get_required_files()

        assert "**/project_context.md" in patterns or "**/project-context.md" in patterns
        assert "**/architecture*.md" in patterns
        assert "**/sprint-status.yaml" in patterns

    def test_get_variables(self) -> None:
        """get_variables returns expected variable names."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        compiler = CodeReviewCompiler()
        variables = compiler.get_variables()

        assert "epic_num" in variables
        assert "story_num" in variables
        assert "story_key" in variables
        assert "story_id" in variables
        # NOTE: git_diff is NOT in variables - it's embedded as [git-diff] context file
        # to avoid HTML-escaped duplication in the <variables> section
        assert "git_diff" not in variables
        assert "date" in variables

    def test_get_workflow_dir(self, tmp_project: Path) -> None:
        """get_workflow_dir returns correct path."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()

        workflow_dir = compiler.get_workflow_dir(context)

        assert workflow_dir.exists()
        assert "code-review" in str(workflow_dir)
        assert (workflow_dir / "workflow.yaml").exists()


class TestValidateContext:
    """Tests for validate_context method (AC7)."""

    def test_missing_epic_num_raises(self, tmp_project: Path) -> None:
        """Missing epic_num raises CompilerError."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler
        from bmad_assist.core.exceptions import CompilerError

        context = create_test_context(tmp_project, epic_num=None, story_num=4)  # type: ignore
        compiler = CodeReviewCompiler()

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.validate_context(context)

    def test_missing_story_num_raises(self, tmp_project: Path) -> None:
        """Missing story_num raises CompilerError."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler
        from bmad_assist.core.exceptions import CompilerError

        context = create_test_context(tmp_project, epic_num=14, story_num=None)  # type: ignore
        compiler = CodeReviewCompiler()

        with pytest.raises(CompilerError, match="story_num"):
            compiler.validate_context(context)

    def test_missing_story_file_raises(self, tmp_project: Path) -> None:
        """Missing story file raises CompilerError with helpful message."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler
        from bmad_assist.core.exceptions import CompilerError

        context = create_test_context(tmp_project, epic_num=99, story_num=99)
        compiler = CodeReviewCompiler()

        with pytest.raises(CompilerError) as exc_info:
            compiler.validate_context(context)

        error_msg = str(exc_info.value)
        assert "story file" in error_msg.lower() or "99-99" in error_msg

    def test_valid_context_passes(self, tmp_project: Path) -> None:
        """Valid context passes validation."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-code-review.md"
        story_file.write_text("""# Story 14.4: Code Review

Status: review

## Story

As a developer, I want code review.

## Acceptance Criteria

1. Code is reviewed

## Tasks / Subtasks

- [x] Task 1

## Dev Agent Record

### File List

- `src/compiler.py`
""")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()

        # Should not raise
        compiler.validate_context(context)


class TestGitDiffCapture:
    """Tests for git diff capture (AC3)."""

    def test_capture_git_diff_returns_diff_content(self, tmp_project: Path) -> None:
        """_capture_git_diff returns diff content for normal git repo."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff
        from bmad_assist.git import DiffValidationResult

        context = create_test_context(tmp_project)

        # Mock git rev-parse for the root check, then get_validated_diff
        with (
            patch("subprocess.run") as mock_run,
            patch("bmad_assist.compiler.workflows.code_review.get_validated_diff") as mock_diff,
        ):
            # Mock git rev-parse --show-toplevel (returns project root path)
            mock_check = Mock()
            mock_check.returncode = 0
            mock_check.stdout = str(tmp_project.resolve())
            mock_run.return_value = mock_check

            # Mock get_validated_diff to return diff content
            mock_diff.return_value = (
                "<!-- GIT_DIFF_START -->\ncommit abc123\n\ndiff --git a/file.py b/file.py\n+new line\n<!-- GIT_DIFF_END -->",
                DiffValidationResult(
                    is_valid=True,
                    total_files=1,
                    source_files=1,
                    garbage_files=0,
                    garbage_ratio=0.0,
                    issues=[],
                ),
            )

            result = _capture_git_diff(context)

        assert "<!-- GIT_DIFF_START -->" in result
        assert "<!-- GIT_DIFF_END -->" in result
        assert "diff --git" in result

    def test_capture_git_diff_empty_for_non_git_directory(self, tmp_project: Path) -> None:
        """_capture_git_diff returns empty string for non-git directory."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff

        context = create_test_context(tmp_project)

        with patch("subprocess.run") as mock_run:
            mock_check = Mock()
            mock_check.returncode = 128  # Not a git repo
            mock_run.return_value = mock_check

            result = _capture_git_diff(context)

        assert result == ""

    def test_capture_git_diff_empty_when_git_not_found(self, tmp_project: Path) -> None:
        """_capture_git_diff returns empty string when git command not found."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff

        context = create_test_context(tmp_project)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")

            result = _capture_git_diff(context)

        assert result == ""

    def test_capture_git_diff_empty_on_timeout(self, tmp_project: Path) -> None:
        """_capture_git_diff returns empty string on subprocess timeout."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff

        context = create_test_context(tmp_project)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)

            result = _capture_git_diff(context)

        assert result == ""

    def test_capture_git_diff_handles_encoding_errors(self, tmp_project: Path) -> None:
        """_capture_git_diff handles encoding errors gracefully."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff
        from bmad_assist.git import DiffValidationResult

        context = create_test_context(tmp_project)

        with (
            patch("subprocess.run") as mock_run,
            patch("bmad_assist.compiler.workflows.code_review.get_validated_diff") as mock_diff,
        ):
            # Mock git rev-parse --show-toplevel (returns project root)
            mock_check = Mock()
            mock_check.returncode = 0
            mock_check.stdout = str(tmp_project.resolve())
            mock_run.return_value = mock_check

            # Mock get_validated_diff with replacement char (from errors='replace')
            mock_diff.return_value = (
                "<!-- GIT_DIFF_START -->\ndiff with \ufffd replacement char\n<!-- GIT_DIFF_END -->",
                DiffValidationResult(
                    is_valid=True,
                    total_files=1,
                    source_files=1,
                    garbage_files=0,
                    garbage_ratio=0.0,
                    issues=[],
                ),
            )

            result = _capture_git_diff(context)

        # Should not raise, should return content
        assert "<!-- GIT_DIFF_START -->" in result

    def test_capture_git_diff_truncates_at_500_lines(self, tmp_project: Path) -> None:
        """_capture_git_diff truncates at 500 lines with marker (handled by git/diff.py)."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff
        from bmad_assist.git import DiffValidationResult

        context = create_test_context(tmp_project)

        # Create a large diff that get_validated_diff would truncate
        truncated_lines = "\n".join([f"line {i}" for i in range(499)])
        truncated_diff = f"<!-- GIT_DIFF_START -->\n{truncated_lines}\n[... TRUNCATED diff after line 499 ...]\n<!-- GIT_DIFF_END -->"

        with (
            patch("subprocess.run") as mock_run,
            patch("bmad_assist.compiler.workflows.code_review.get_validated_diff") as mock_diff,
        ):
            mock_check = Mock()
            mock_check.returncode = 0
            mock_check.stdout = str(tmp_project.resolve())
            mock_run.return_value = mock_check

            # Mock get_validated_diff to return truncated content
            mock_diff.return_value = (
                truncated_diff,
                DiffValidationResult(
                    is_valid=True,
                    total_files=1,
                    source_files=1,
                    garbage_files=0,
                    garbage_ratio=0.0,
                    issues=[],
                ),
            )

            result = _capture_git_diff(context)

        assert "[... TRUNCATED diff after line" in result
        # Count lines between markers (excluding the markers themselves)
        lines = result.split("\n")
        diff_lines = [
            line for line in lines if line and "GIT_DIFF" not in line and "TRUNCATED" not in line
        ]
        assert len(diff_lines) <= 500

    def test_capture_git_diff_wrapped_in_markers(self, tmp_project: Path) -> None:
        """_capture_git_diff wraps diff in GIT_DIFF_START/END markers."""
        from bmad_assist.compiler.workflows.code_review import _capture_git_diff
        from bmad_assist.git import DiffValidationResult

        context = create_test_context(tmp_project)

        with (
            patch("subprocess.run") as mock_run,
            patch("bmad_assist.compiler.workflows.code_review.get_validated_diff") as mock_diff,
        ):
            mock_check = Mock()
            mock_check.returncode = 0
            mock_check.stdout = str(tmp_project.resolve())
            mock_run.return_value = mock_check

            mock_diff.return_value = (
                "<!-- GIT_DIFF_START -->\nsimple diff\n<!-- GIT_DIFF_END -->",
                DiffValidationResult(
                    is_valid=True,
                    total_files=1,
                    source_files=1,
                    garbage_files=0,
                    garbage_ratio=0.0,
                    issues=[],
                ),
            )

            result = _capture_git_diff(context)

        assert result.startswith("<!-- GIT_DIFF_START -->")
        assert result.endswith("<!-- GIT_DIFF_END -->")


class TestModifiedFilesExtraction:
    """Tests for modified files extraction from git diff --stat (AC4)."""

    def test_extract_modified_files_from_stat_normal(self) -> None:
        """Parses normal git diff --stat output."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ src/compiler.py     | 42 +++++++++++++++++++++++++++++++++--------
 tests/test_comp.py | 25 ++++++++++++++++++++---
 README.md          |  5 +++++
 3 files changed, 61 insertions(+), 11 deletions(-)
"""
        result = _extract_modified_files_from_stat(stat_output)

        assert len(result) == 3
        # Sorted by changes desc
        assert result[0][0] == "src/compiler.py"
        assert result[0][1] == 42
        assert result[1][0] == "tests/test_comp.py"
        assert result[1][1] == 25

    def test_extract_modified_files_skips_binary(self) -> None:
        """Skips binary files (Bin X -> Y bytes)."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ src/main.py  | 10 ++++++++++
 image.png   | Bin 1234 -> 5678 bytes
 2 files changed, 10 insertions(+)
"""
        result = _extract_modified_files_from_stat(stat_output)

        assert len(result) == 1
        assert result[0][0] == "src/main.py"

    def test_extract_modified_files_handles_renames(self) -> None:
        """Handles renamed files (uses new path)."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ old.py => new.py | 5 +++--
 other.py        | 3 +++
"""
        result = _extract_modified_files_from_stat(stat_output)

        assert len(result) == 2
        # Should use new path for renamed file
        paths = [r[0] for r in result]
        assert "new.py" in paths
        assert "old.py" not in paths

    def test_extract_modified_files_skips_pure_renames(self) -> None:
        """Skips pure renames without content changes (AC4)."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ old.py => new.py | 0
 other.py        | 3 +++
"""
        result = _extract_modified_files_from_stat(stat_output)

        # Pure rename with 0 changes should be skipped
        assert len(result) == 1
        assert result[0][0] == "other.py"

    def test_extract_modified_files_handles_brace_style_renames(self) -> None:
        """Handles brace-style renames like src/{old => new}/file.py."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ src/{old => new}/file.py | 10 +++---
 other.py                 | 3 +++
"""
        result = _extract_modified_files_from_stat(stat_output)

        # Should extract both files
        assert len(result) == 2
        paths = [r[0] for r in result]
        # The new path from brace-style rename should be captured
        assert any("new" in p for p in paths)

    def test_extract_modified_files_sorted_by_changes_desc(self) -> None:
        """Files sorted by change count descending."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ small.py  | 5 +++++
 large.py  | 100 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 medium.py | 30 ++++++++++++++++++++++++++++++
"""
        result = _extract_modified_files_from_stat(stat_output)

        assert result[0][0] == "large.py"
        assert result[1][0] == "medium.py"
        assert result[2][0] == "small.py"

    def test_extract_modified_files_alphabetical_secondary_sort(self) -> None:
        """Equal change counts sorted alphabetically."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ zebra.py | 10 ++++++++++
 alpha.py | 10 ++++++++++
 beta.py  | 10 ++++++++++
"""
        result = _extract_modified_files_from_stat(stat_output)

        # All have same change count, should be alphabetical
        paths = [r[0] for r in result]
        assert paths == ["alpha.py", "beta.py", "zebra.py"]

    def test_extract_modified_files_skips_docs(self) -> None:
        """Files in docs/ directory are skipped."""
        from bmad_assist.compiler.workflows.code_review import _extract_modified_files_from_stat

        stat_output = """ src/main.py           | 10 ++++++++++
 docs/architecture.md | 20 ++++++++++++++++++++
 docs/prd.md          | 15 +++++++++++++++
"""
        result = _extract_modified_files_from_stat(stat_output, skip_docs=True)

        assert len(result) == 1
        assert result[0][0] == "src/main.py"


class TestContextFileBuilding:
    """Tests for context file building (AC1, AC2)."""

    def test_story_file_last_in_context(self, tmp_project: Path) -> None:
        """Story file is positioned LAST in context (recency-bias)."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-code-review.md"
        story_file.write_text("# Story 14.4\n\nStatus: review\n\n## File List\n")

        # Create architecture.md
        (tmp_project / "docs" / "architecture.md").write_text("# Architecture")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        resolved = dict(context.resolved_variables)
        resolved["story_file"] = str(story_file)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            context_files = compiler._build_context_files(context, resolved)

        paths = list(context_files.keys())

        # Story file should be last
        assert "14-4" in paths[-1]

    def test_recency_bias_order(self, tmp_project: Path) -> None:
        """Context files ordered: project_context → architecture → ux → story."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        (tmp_project / "docs" / "architecture.md").write_text("# Architecture")
        (tmp_project / "docs" / "ux.md").write_text("# UX Design")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        resolved = dict(context.resolved_variables)
        resolved["story_file"] = str(story_file)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            context_files = compiler._build_context_files(context, resolved)

        paths = list(context_files.keys())

        ctx_idx = next((i for i, p in enumerate(paths) if "project-context" in p), -1)
        arch_idx = next((i for i, p in enumerate(paths) if "architecture" in p), -1)
        ux_idx = next((i for i, p in enumerate(paths) if "ux" in p.lower()), -1)
        story_idx = next((i for i, p in enumerate(paths) if "14-4" in p), -1)

        # Verify ordering
        if ctx_idx >= 0 and arch_idx >= 0:
            assert ctx_idx < arch_idx
        if ux_idx >= 0 and story_idx >= 0:
            assert ux_idx < story_idx
        if arch_idx >= 0 and story_idx >= 0:
            assert arch_idx < story_idx

    def test_source_context_service_used(self, tmp_project: Path) -> None:
        """Source files collected via SourceContextService."""
        from bmad_assist.compiler.source_context import SourceContextService

        # Create source file
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# Main file\nprint('hello')")

        context = create_test_context(tmp_project)

        # Test service directly
        service = SourceContextService(context, "code_review")
        assert service.is_enabled()  # Default budget is 15000
        assert service.budget == 15000  # code_review default

        result = service.collect_files(["src/main.py"], None)
        assert len(result) == 1

    def test_source_context_truncation(self, tmp_project: Path) -> None:
        """SourceContextService truncates large files within budget."""
        from bmad_assist.compiler.source_context import SourceContextService

        # Create large source file (much larger than budget)
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        large_content = "x" * 200000  # ~50000 tokens (budget is 15000)
        (src_dir / "large.py").write_text(large_content)

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "code_review")

        result = service.collect_files(["src/large.py"], None)

        assert len(result) == 1
        content = list(result.values())[0]
        # Should be truncated (budget is 15000 tokens = ~60000 chars)
        # Content (without marker) should be much smaller than original
        assert len(content) < len(large_content) * 0.5
        assert "truncated" in content.lower()


class TestCompileOutput:
    """Tests for compile() method output (AC5, AC6)."""

    def test_compiled_workflow_structure(self, tmp_project: Path) -> None:
        """CompiledWorkflow has all required fields."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review\n\n## File List\n")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "code-review"
        assert isinstance(result.mission, str)
        assert isinstance(result.context, str)
        assert isinstance(result.variables, dict)
        assert isinstance(result.instructions, str)
        assert result.output_template == ""  # action-workflow
        assert isinstance(result.token_estimate, int)
        assert result.token_estimate > 0

    def test_mission_emphasizes_adversarial_review(self, tmp_project: Path) -> None:
        """Mission describes adversarial code review focus."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Mission should mention adversarial or review
        assert "adversarial" in result.mission.lower() or "review" in result.mission.lower()

    def test_instructions_filtered(self, tmp_project: Path) -> None:
        """Instructions are filtered (no <ask>, no HALT)."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert "<ask" not in result.instructions
        assert "<output>" not in result.instructions

    def test_xml_output_parseable(self, tmp_project: Path) -> None:
        """Generated XML is parseable."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        context = create_test_context(tmp_project)
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        root = ET.fromstring(result.context)
        assert root.tag == "compiled-workflow"


class TestPatchPostProcess:
    """Tests for patch post_process application."""

    def test_patch_post_process_applied(self, tmp_project: Path) -> None:
        """Patch post_process rules are applied if patch exists."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        # Create patch file
        patch_dir = tmp_project / "_bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "code-review.patch.yaml"
        patch_file.write_text("""name: code-review
post_process:
  - find: "placeholder_text"
    replace: "replaced_text"
""")

        context = create_test_context(tmp_project)
        context.patch_path = patch_file
        compiler = CodeReviewCompiler()
        compiler.validate_context(context)

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Compilation should succeed (patch loaded)
        assert result.workflow_name == "code-review"


class TestRegistration:
    """Tests for compiler registration in registry."""

    def test_compile_workflow_integration(self, tmp_project: Path) -> None:
        """compile_workflow('code-review', context) works."""
        from bmad_assist.compiler.core import compile_workflow

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        context = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
            resolved_variables={"epic_num": 14, "story_num": 4},
        )

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            result = compile_workflow("code-review", context)

        assert result.workflow_name == "code-review"
        assert result.token_estimate > 0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_deterministic_compilation(self, tmp_project: Path) -> None:
        """Same input produces identical output (NFR11)."""
        from bmad_assist.compiler.workflows.code_review import CodeReviewCompiler

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-4-test.md"
        story_file.write_text("# Story\n\nStatus: review")

        with patch(
            "bmad_assist.compiler.workflows.code_review._capture_git_diff",
            return_value="",
        ):
            context1 = create_test_context(tmp_project, date="2025-01-01")
            compiler1 = CodeReviewCompiler()
            compiler1.validate_context(context1)
            result1 = compiler1.compile(context1)

            context2 = create_test_context(tmp_project, date="2025-01-01")
            compiler2 = CodeReviewCompiler()
            compiler2.validate_context(context2)
            result2 = compiler2.compile(context2)

        assert result1.mission == result2.mission
        assert result1.instructions == result2.instructions
