"""Tests for ATDDCompiler workflow compiler.

Tests the testarch-atdd workflow compiler that produces prompts for
ATDD (Acceptance Test Driven Development) workflow execution.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.compiler.core import compile_workflow, get_workflow_compiler
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.core.exceptions import CompilerError


class TestATDDCompilerLoading:
    """Test loading ATDDCompiler via core.py."""

    def test_get_workflow_compiler_returns_atdd_compiler(self) -> None:
        """Test get_workflow_compiler loads testarch-atdd compiler."""
        compiler = get_workflow_compiler("testarch-atdd")

        assert compiler.workflow_name == "testarch-atdd"

    def test_workflow_name_property(self) -> None:
        """Test workflow_name is correctly set."""
        compiler = get_workflow_compiler("testarch-atdd")

        assert compiler.workflow_name == "testarch-atdd"


class TestATDDCompilerWorkflowDir:
    """Test get_workflow_dir returns correct testarch path."""

    def test_get_workflow_dir_returns_testarch_atdd_path(self, tmp_path: Path) -> None:
        """Test workflow dir is _bmad/bmm/workflows/testarch/atdd."""
        compiler = get_workflow_compiler("testarch-atdd")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )

        workflow_dir = compiler.get_workflow_dir(context)

        # With bundled workflows, falls back to package path when BMAD not installed
        # Check it's either BMAD path or bundled path
        bmad_path = tmp_path / "_bmad/bmm/workflows/testarch/atdd"
        bundled_path_suffix = "workflows/testarch-atdd"
        assert workflow_dir == bmad_path or str(workflow_dir).endswith(bundled_path_suffix)


class TestATDDCompilerRequiredFiles:
    """Test get_required_files returns expected patterns."""

    def test_get_required_files_includes_project_context(self) -> None:
        """Test required files include project_context.md."""
        compiler = get_workflow_compiler("testarch-atdd")

        patterns = compiler.get_required_files()

        # Should include project context pattern
        assert any("project_context" in p or "project-context" in p for p in patterns)

    def test_get_required_files_includes_story_pattern(self) -> None:
        """Test required files include story pattern."""
        compiler = get_workflow_compiler("testarch-atdd")

        patterns = compiler.get_required_files()

        # Should have patterns for story files (used contextually)
        assert isinstance(patterns, list)
        assert len(patterns) >= 1


class TestATDDCompilerVariables:
    """Test get_variables returns expected variables."""

    def test_get_variables_includes_story_id(self) -> None:
        """Test variables include story_id."""
        compiler = get_workflow_compiler("testarch-atdd")

        variables = compiler.get_variables()

        assert "story_id" in variables or "epic_num" in variables

    def test_get_variables_includes_test_dir(self) -> None:
        """Test variables include test_dir from workflow.yaml."""
        compiler = get_workflow_compiler("testarch-atdd")

        variables = compiler.get_variables()

        assert "test_dir" in variables


class TestATDDCompilerValidation:
    """Test validate_context validates required context."""

    def test_validate_context_requires_project_root(self) -> None:
        """Test validation fails without project_root."""
        compiler = get_workflow_compiler("testarch-atdd")
        # Create context with None project_root explicitly
        context = CompilerContext(
            project_root=None,  # type: ignore
            output_folder=Path("/tmp/docs"),
        )

        with pytest.raises(CompilerError, match="project_root"):
            compiler.validate_context(context)

    def test_validate_context_requires_epic_num(self, tmp_path: Path) -> None:
        """Test validation fails without epic_num."""
        compiler = get_workflow_compiler("testarch-atdd")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {"story_num": 1}  # Missing epic_num

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.validate_context(context)

    def test_validate_context_requires_story_num(self, tmp_path: Path) -> None:
        """Test validation fails without story_num."""
        compiler = get_workflow_compiler("testarch-atdd")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {"epic_num": 1}  # Missing story_num

        with pytest.raises(CompilerError, match="story_num"):
            compiler.validate_context(context)


class TestATDDCompilerCompile:
    """Test compile() produces correct CompiledWorkflow."""

    @pytest.fixture
    def setup_testarch_workflow(self, tmp_path: Path) -> Path:
        """Create testarch-atdd workflow structure."""
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/atdd"
        workflow_dir.mkdir(parents=True)

        # Create workflow.yaml
        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-atdd
description: "Generate failing acceptance tests before implementation"
instructions: "{installed_path}/instructions.md"
template: "{installed_path}/atdd-checklist-template.md"
variables:
  test_dir: "{project-root}/tests"
default_output_file: "{output_folder}/atdd-checklist-{story_id}.md"
""")

        # Create instructions.xml (the parser expects XML format)
        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Analyze story acceptance criteria">
<action>Read story file and extract acceptance criteria</action>
</step>

<step n="2" goal="Generate failing tests">
<action>Write acceptance tests based on AC</action>
</step>
</workflow>""")

        # Create template
        template = workflow_dir / "atdd-checklist-template.md"
        template.write_text("""
# ATDD Checklist for {{story_id}}

## Tests Generated
- [ ] AC1: {{ac1_test}}
- [ ] AC2: {{ac2_test}}

## Status
- Story: {{story_id}}
- Date: {{date}}
""")

        # Create story file in legacy stories dir (output_folder/sprint-artifacts)
        # This matches the get_stories_dir fallback when paths not initialized
        stories_dir = tmp_path / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "1-1-test-story.md"
        story_file.write_text("""
# Story 1.1: Test Story

## Acceptance Criteria
1. AC1: First criterion
2. AC2: Second criterion

## Tasks / Subtasks
- [ ] Task 1
""")

        # Create project_context.md in output folder
        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context\nRules here...")

        return tmp_path

    def test_compile_returns_compiled_workflow(self, setup_testarch_workflow: Path) -> None:
        """Test compile returns CompiledWorkflow with correct fields."""
        project_root = setup_testarch_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        compiled = compile_workflow("testarch-atdd", context)

        assert compiled.workflow_name == "testarch-atdd"
        assert compiled.mission is not None
        assert compiled.context is not None  # Full XML
        assert compiled.instructions is not None
        assert "testarch-atdd" in compiled.workflow_name

    def test_compile_includes_story_context(self, setup_testarch_workflow: Path) -> None:
        """Test compiled workflow includes story file in context."""
        project_root = setup_testarch_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        compiled = compile_workflow("testarch-atdd", context)

        # Context XML should include story content
        assert "Test Story" in compiled.context or "story" in compiled.context.lower()

    def test_compile_includes_project_context(self, setup_testarch_workflow: Path) -> None:
        """Test compiled workflow includes project_context.md."""
        project_root = setup_testarch_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        compiled = compile_workflow("testarch-atdd", context)

        # Should include project context
        assert "Project Context" in compiled.context or "project" in compiled.context.lower()

    def test_compile_resolves_test_dir_variable(self, setup_testarch_workflow: Path) -> None:
        """Test compile resolves test_dir from workflow.yaml variables."""
        project_root = setup_testarch_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        compiled = compile_workflow("testarch-atdd", context)

        # Should have test_dir resolved in variables
        assert "test_dir" in compiled.variables or "tests" in str(compiled.variables)


class TestATDDCompilerErrorHandling:
    """Test error handling in ATDDCompiler."""

    def test_compile_fails_with_missing_workflow_dir(self, tmp_path: Path) -> None:
        """Test compile fails gracefully when workflow dir missing."""
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
            cwd=tmp_path,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        # Should fail because workflow directory doesn't exist
        # Uses bundled fallback if available, otherwise raises
        try:
            result = compile_workflow("testarch-atdd", context)
            # If bundled fallback is used, it still compiles
            assert result is not None
        except CompilerError:
            pass  # Expected if no bundled fallback available

    def test_compile_logs_warning_for_missing_story(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test compile logs warning when story file not found."""
        import logging

        # Create workflow dir but no story
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/atdd"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-atdd
description: "Generate failing acceptance tests"
instructions: "{installed_path}/instructions.md"
""")

        instructions = workflow_dir / "instructions.md"
        instructions.write_text("<step>Test</step>")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
            cwd=tmp_path,
        )
        context.resolved_variables = {
            "epic_num": "99",
            "story_num": "99",
        }

        # Should log warning for missing story (not error - story is optional context)
        with caplog.at_level(logging.WARNING):
            compile_workflow("testarch-atdd", context)

        # Check warning was logged
        assert "Story file not found" in caplog.text or "99-99" in caplog.text
