"""Tests for the dev-story workflow compiler.

Tests the DevStoryCompiler class which produces standalone prompts for
story implementation by developers.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from bmad_assist.compiler.parser import parse_workflow
from bmad_assist.compiler.source_context import extract_file_paths_from_story
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.compiler.workflows.dev_story import DevStoryCompiler
from bmad_assist.core.exceptions import CompilerError


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
    workflow_dir = tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "dev-story"
    workflow_dir.mkdir(parents=True)

    # Create workflow.yaml
    workflow_yaml = workflow_dir / "workflow.yaml"
    workflow_yaml.write_text("""name: dev-story
description: "Execute a story by implementing tasks/subtasks, writing tests, validating"
config_source: "{project-root}/_bmad/bmm/config.yaml"
template: false
instructions: "{installed_path}/instructions.xml"
""")

    # Create instructions.xml
    instructions_xml = workflow_dir / "instructions.xml"
    instructions_xml.write_text("""<workflow>
  <step n="1" goal="Load story">
    <action>Read story file</action>
    <action>Parse acceptance criteria</action>
  </step>
  <step n="2" goal="Implement">
    <action>Follow TDD cycle</action>
    <check if="tests pass">
      <action>Mark task complete</action>
    </check>
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
    project_context = docs / "project_context.md"
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
    story_num: int = 1,
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
    workflow_dir = project / "_bmad" / "bmm" / "workflows" / "4-implementation" / "dev-story"
    workflow_ir = parse_workflow(workflow_dir) if workflow_dir.exists() else None
    return CompilerContext(
        project_root=project,
        output_folder=project / "docs",
        resolved_variables=resolved_vars,
        workflow_ir=workflow_ir,
    )


class TestWorkflowProperties:
    """Tests for DevStoryCompiler properties (AC6)."""

    def test_workflow_name(self) -> None:
        """workflow_name returns 'dev-story'."""
        compiler = DevStoryCompiler()
        assert compiler.workflow_name == "dev-story"

    def test_get_required_files(self) -> None:
        """get_required_files returns expected patterns."""
        compiler = DevStoryCompiler()
        patterns = compiler.get_required_files()

        assert "**/project_context.md" in patterns or "**/project-context.md" in patterns
        assert "**/architecture*.md" in patterns
        assert "**/prd*.md" in patterns
        assert "**/sprint-status.yaml" in patterns

    def test_get_variables(self) -> None:
        """get_variables returns expected variable names."""
        compiler = DevStoryCompiler()
        variables = compiler.get_variables()

        assert "epic_num" in variables
        assert "story_num" in variables
        assert "story_key" in variables
        assert "story_id" in variables
        assert "story_file" in variables
        assert "date" in variables

    def test_get_workflow_dir(self, tmp_project: Path) -> None:
        """get_workflow_dir returns correct path."""
        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()

        workflow_dir = compiler.get_workflow_dir(context)

        assert workflow_dir.exists()
        assert "dev-story" in str(workflow_dir)
        assert (workflow_dir / "workflow.yaml").exists()


class TestValidateContext:
    """Tests for validate_context method (AC6)."""

    def test_missing_project_root_raises(self, tmp_project: Path) -> None:
        """Missing project_root raises CompilerError."""
        context = CompilerContext(
            project_root=None,  # type: ignore
            output_folder=tmp_project / "docs",
            resolved_variables={"epic_num": 14, "story_num": 1},
        )
        compiler = DevStoryCompiler()

        with pytest.raises(CompilerError, match="project_root"):
            compiler.validate_context(context)

    def test_missing_output_folder_raises(self, tmp_project: Path) -> None:
        """Missing output_folder raises CompilerError."""
        context = CompilerContext(
            project_root=tmp_project,
            output_folder=None,  # type: ignore
            resolved_variables={"epic_num": 14, "story_num": 1},
        )
        compiler = DevStoryCompiler()

        with pytest.raises(CompilerError, match="output_folder"):
            compiler.validate_context(context)

    def test_missing_epic_num_raises(self, tmp_project: Path) -> None:
        """Missing epic_num raises CompilerError."""
        context = create_test_context(tmp_project, epic_num=None, story_num=1)  # type: ignore
        compiler = DevStoryCompiler()

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.validate_context(context)

    def test_missing_story_num_raises(self, tmp_project: Path) -> None:
        """Missing story_num raises CompilerError."""
        context = create_test_context(tmp_project, epic_num=14, story_num=None)  # type: ignore
        compiler = DevStoryCompiler()

        with pytest.raises(CompilerError, match="story_num"):
            compiler.validate_context(context)

    def test_missing_story_file_raises(self, tmp_project: Path) -> None:
        """Missing story file raises CompilerError with helpful message."""
        context = create_test_context(tmp_project, epic_num=99, story_num=99)
        compiler = DevStoryCompiler()

        with pytest.raises(CompilerError) as exc_info:
            compiler.validate_context(context)

        # Check the error message contains pattern info and suggestion
        error_msg = str(exc_info.value)
        assert "story file" in error_msg.lower() or "99-99" in error_msg
        assert "create-story" in error_msg.lower() or "pattern" in error_msg.lower()

    def test_valid_context_passes(self, tmp_project: Path) -> None:
        """Valid context passes validation."""
        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test-story.md"
        story_file.write_text("""# Story 14.1: Test Story

Status: ready-for-dev

## Story

As a developer, I want to test.

## Acceptance Criteria

1. Test works

## Tasks / Subtasks

- [ ] Task 1
""")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()

        # Should not raise
        compiler.validate_context(context)


class TestVariableResolution:
    """Tests for variable resolution (AC4)."""

    def test_variable_resolution_from_invocation(self, tmp_project: Path) -> None:
        """Variables resolved from invocation params."""
        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-2-my-story.md"
        story_file.write_text("""# Story 14.2

Status: ready-for-dev
""")

        context = create_test_context(tmp_project, epic_num=14, story_num=2)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert result.variables.get("epic_num") == 14
        assert result.variables.get("story_num") == 2
        assert result.variables.get("story_id") == "14.2"

    def test_variable_resolution_from_sprint_status(self, tmp_project: Path) -> None:
        """Variables resolved from sprint-status.yaml."""
        # Create sprint-status.yaml
        sprint_status = tmp_project / "docs" / "sprint-artifacts" / "sprint-status.yaml"
        sprint_status.write_text("""development_status:
  14-1-dev-story-compiler: ready-for-dev
""")

        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-dev-story-compiler.md"
        story_file.write_text("# Story 14.1\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project, epic_num=14, story_num=1)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert result.variables.get("story_key") == "14-1-dev-story-compiler"
        assert result.variables.get("story_title") == "dev-story-compiler"

    def test_story_file_variable_resolved(self, tmp_project: Path) -> None:
        """story_file variable is resolved to actual path."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert "story_file" in result.variables
        assert "14-1-test.md" in str(result.variables["story_file"])


class TestContextFileBuilding:
    """Tests for context file building (AC1, AC2)."""

    def test_story_file_last_in_context(self, tmp_project: Path) -> None:
        """Story file is positioned LAST in context (recency-bias)."""
        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story 14.1\n\nStatus: ready-for-dev")

        # Create architecture.md
        (tmp_project / "docs" / "architecture.md").write_text("# Architecture")

        # Create prd.md
        (tmp_project / "docs" / "prd.md").write_text("# PRD")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        # Resolve story_file for _build_context_files
        resolved = dict(context.resolved_variables)
        resolved["story_file"] = str(story_file)

        context_files = compiler._build_context_files(context, resolved)
        paths = list(context_files.keys())

        # Story file should be last
        assert "14-1-test.md" in paths[-1]

    def test_context_recency_bias_order(self, tmp_project: Path) -> None:
        """Context files ordered: general → specific → story.

        Note: By default, dev_story only includes project-context (no PRD/architecture).
        This test verifies story file is always last.
        """
        # Create files
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story 14.1\n\nStatus: ready-for-dev")

        # Create project-context (this IS included by default)
        (tmp_project / "docs" / "project-context.md").write_text("# Project Context")
        (tmp_project / "docs" / "epics" / "epic-14.md").write_text("# Epic 14")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        context_files = compiler._build_context_files(context, context.resolved_variables)
        paths = list(context_files.keys())

        # Find indices
        ctx_idx = next((i for i, p in enumerate(paths) if "project-context" in p or "project_context" in p), -1)
        story_idx = next((i for i, p in enumerate(paths) if "14-1" in p), -1)

        # Verify ordering: project_context should be early, story should be last
        if ctx_idx >= 0 and story_idx >= 0:
            assert ctx_idx < story_idx, "project_context should come before story"
            assert story_idx == len(paths) - 1, "story should be last"

    def test_prd_excluded_by_default(self, tmp_project: Path) -> None:
        """PRD is NOT included for dev_story by default (Strategic Context Optimization).

        Benchmarks showed 0% PRD citation rate for dev_story - story file is source of truth.
        PRD can be included via config if needed.
        """
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        prd_content = "# PRD\n\n## Epic 1\nRequirements\n\n## Epic 14\nMore requirements"
        (tmp_project / "docs" / "prd.md").write_text(prd_content)

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        # Resolve story_file for _build_context_files
        resolved = dict(context.resolved_variables)
        resolved["story_file"] = str(story_file)

        context_files = compiler._build_context_files(context, resolved)

        # PRD should NOT be included by default for dev_story
        prd_files = [(k, v) for k, v in context_files.items() if k.endswith("prd.md")]
        assert len(prd_files) == 0, f"PRD should not be in context. Keys: {list(context_files.keys())}"

    def test_ux_optional(self, tmp_project: Path) -> None:
        """UX file is optional - no error if missing."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        # Should not raise
        context_files = compiler._build_context_files(context, context.resolved_variables)
        assert len(context_files) > 0

    def test_ux_excluded_by_default(self, tmp_project: Path) -> None:
        """UX file is NOT included for dev_story by default (Strategic Context Optimization).

        Similar to PRD, UX has 0% citation rate in benchmarks for dev_story.
        """
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        (tmp_project / "docs" / "ux.md").write_text("# UX Design\n\nUI patterns")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        # Resolve story_file for _build_context_files
        resolved = dict(context.resolved_variables)
        resolved["story_file"] = str(story_file)

        context_files = compiler._build_context_files(context, resolved)

        # UX should NOT be included by default for dev_story
        ux_content = next((v for k, v in context_files.items() if k.endswith("ux.md")), None)
        assert ux_content is None, "UX should not be in context for dev_story by default"


class TestFileListExtraction:
    """Tests for File List source file extraction (AC3)."""

    def test_extract_file_paths_basic(self) -> None:
        """Extracts file paths from File List section."""
        story_content = """# Story 14.1

## File List

- `src/bmad_assist/compiler/dev_story.py` - New compiler
- `tests/compiler/test_dev_story.py` - Unit tests
"""
        paths = extract_file_paths_from_story(story_content)

        assert len(paths) == 2
        assert "src/bmad_assist/compiler/dev_story.py" in paths
        assert "tests/compiler/test_dev_story.py" in paths

    def test_extract_file_paths_empty_list(self) -> None:
        """Empty File List returns empty list."""
        story_content = """# Story 14.1

## File List

(No files yet)

## Change Log
"""
        paths = extract_file_paths_from_story(story_content)
        assert paths == []

    def test_extract_file_paths_no_section(self) -> None:
        """Missing File List section returns empty list."""
        story_content = """# Story 14.1

## Story

Implementation details.
"""
        paths = extract_file_paths_from_story(story_content)
        assert paths == []

    def test_source_files_collected_via_service(self, tmp_project: Path) -> None:
        """Source files are collected via SourceContextService."""
        from bmad_assist.compiler.source_context import SourceContextService

        # Create source file
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# Main file")

        context = create_test_context(tmp_project)

        # Use service directly
        service = SourceContextService(context, "dev_story")
        # Budget comes from bmad-assist.yaml config (15000) or defaults (20000)
        assert service.budget > 0  # Budget should be set

        result = service.collect_files(["src/main.py"], None)
        assert len(result) == 1

    def test_skip_nonexistent_files(self, tmp_project: Path) -> None:
        """Non-existent files are skipped gracefully."""
        from bmad_assist.compiler.source_context import SourceContextService

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["src/nonexistent.py"], None)

        # Should return empty, not raise
        assert len(result) == 0

    def test_skip_binary_files(self, tmp_project: Path) -> None:
        """Binary files are skipped."""
        from bmad_assist.compiler.source_context import SourceContextService

        # Create binary file
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        (src_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        context = create_test_context(tmp_project)
        service = SourceContextService(context, "dev_story")

        result = service.collect_files(["src/image.png"], None)
        assert len(result) == 0


class TestCompileOutput:
    """Tests for compile() method output (AC5, AC7)."""

    def test_compiled_workflow_structure(self, tmp_project: Path) -> None:
        """CompiledWorkflow has all required fields."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "dev-story"
        assert isinstance(result.mission, str)
        assert isinstance(result.context, str)
        assert isinstance(result.variables, dict)
        assert isinstance(result.instructions, str)
        assert result.output_template == ""  # action-workflow, no template
        assert isinstance(result.token_estimate, int)
        assert result.token_estimate > 0

    def test_empty_template_for_action_workflow(self, tmp_project: Path) -> None:
        """dev-story is action-workflow, output_template is empty."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert result.output_template == ""

    def test_mission_includes_story_info(self, tmp_project: Path) -> None:
        """Mission includes story ID and title."""
        # Create sprint-status for title
        sprint_status = tmp_project / "docs" / "sprint-artifacts" / "sprint-status.yaml"
        sprint_status.write_text("""development_status:
  14-1-dev-story-compiler: ready-for-dev
""")

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-dev-story-compiler.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert "14.1" in result.mission
        assert "dev-story-compiler" in result.mission

    def test_xml_output_parseable(self, tmp_project: Path) -> None:
        """Generated XML is parseable."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        root = ET.fromstring(result.context)
        assert root.tag == "compiled-workflow"

    def test_instructions_filtered(self, tmp_project: Path) -> None:
        """Instructions are filtered (no ask/output tags)."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert "<ask" not in result.instructions
        assert "<output>" not in result.instructions


class TestCoreIntegration:
    """Tests for integration with core.py (AC7)."""

    def test_compile_workflow_integration(self, tmp_project: Path) -> None:
        """compile_workflow('dev-story', context) works."""
        from bmad_assist.compiler.core import compile_workflow

        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context = CompilerContext(
            project_root=tmp_project,
            output_folder=tmp_project / "docs",
            resolved_variables={"epic_num": 14, "story_num": 1},
        )

        result = compile_workflow("dev-story", context)

        assert result.workflow_name == "dev-story"
        assert result.token_estimate > 0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_unicode_content(self, tmp_project: Path) -> None:
        """Unicode content is handled correctly."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story 14.1: Tëst Störy\n\nPolish: ąęć\n\nStatus: ready-for-dev")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        assert "ąęć" in result.context or "Tëst" in result.context

    def test_deterministic_compilation(self, tmp_project: Path) -> None:
        """Same input produces identical output (NFR11)."""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story\n\nStatus: ready-for-dev")

        context1 = create_test_context(tmp_project, date="2025-01-01")
        compiler1 = DevStoryCompiler()
        compiler1.validate_context(context1)
        result1 = compiler1.compile(context1)

        context2 = create_test_context(tmp_project, date="2025-01-01")
        compiler2 = DevStoryCompiler()
        compiler2.validate_context(context2)
        result2 = compiler2.compile(context2)

        assert result1.mission == result2.mission
        assert result1.instructions == result2.instructions


class TestSourceContextConfigDefaults:
    """Tests for SourceContext config defaults."""

    def test_dev_story_default_budget(self) -> None:
        """dev_story default budget is 20000."""
        from bmad_assist.core.config import SourceContextBudgetsConfig

        budgets = SourceContextBudgetsConfig()
        assert budgets.get_budget("dev_story") == 20000


class TestFinalXMLOrdering:
    """Tests that verify the final XML output has correct file ordering."""

    def test_story_file_last_in_compiled_xml(self, tmp_project: Path) -> None:
        """Story file appears LAST in compiled XML context (not just dict order)."""
        # Create story file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("# Story 14.1\n\nStatus: ready-for-dev")

        # Create other context files
        (tmp_project / "docs" / "architecture.md").write_text("# Architecture")
        (tmp_project / "docs" / "prd.md").write_text("# PRD")
        (tmp_project / "docs" / "epics" / "epic-14.md").write_text("# Epic 14")

        # Create source file and list it in story
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("# Source code")

        # Update story with File List
        story_file.write_text("""# Story 14.1

Status: ready-for-dev

## File List

- `src/module.py` - Source module

## Tasks
- [ ] Task 1
""")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        # Parse the compiled XML to verify file order
        root = ET.fromstring(result.context)
        files = root.findall(".//file")

        # Get file paths in order they appear in XML
        file_paths = [f.get("path", "") for f in files]

        # Story file must be LAST
        story_file_paths = [p for p in file_paths if "14-1-test.md" in p]
        assert len(story_file_paths) == 1, f"Expected 1 story file, found: {story_file_paths}"

        # Verify story file is the last file in context
        assert "14-1-test.md" in file_paths[-1], (
            f"Story file should be LAST in XML context but last file is: {file_paths[-1]}\n"
            f"Full order: {[p.split('/')[-1] for p in file_paths]}"
        )

    def test_source_files_before_story_in_xml(self, tmp_project: Path) -> None:
        """Source files from File List appear BEFORE story in compiled XML."""
        # Create source file
        src_dir = tmp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("# Source code\nclass Foo: pass")

        # Create story with File List referencing source file
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-1-test.md"
        story_file.write_text("""# Story 14.1

Status: ready-for-dev

## File List

- `src/module.py` - Source module

## Tasks
- [ ] Task 1
""")

        context = create_test_context(tmp_project)
        compiler = DevStoryCompiler()
        compiler.validate_context(context)

        result = compiler.compile(context)

        # Parse XML
        root = ET.fromstring(result.context)
        files = root.findall(".//file")
        file_paths = [f.get("path", "") for f in files]

        # Find indices
        source_idx = next((i for i, p in enumerate(file_paths) if "module.py" in p), -1)
        story_idx = next((i for i, p in enumerate(file_paths) if "14-1-test.md" in p), -1)

        # Source must come before story
        assert source_idx >= 0, "Source file not found in context"
        assert story_idx >= 0, "Story file not found in context"
        assert source_idx < story_idx, (
            f"Source file (idx={source_idx}) must appear BEFORE story file (idx={story_idx})\n"
            f"Full order: {[p.split('/')[-1] for p in file_paths]}"
        )
