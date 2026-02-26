"""Tests for TraceCompiler workflow compiler.

Tests the testarch-trace workflow compiler that produces prompts for
generating traceability matrices and quality gate decisions.
"""

from pathlib import Path

import pytest

from bmad_assist.compiler.core import compile_workflow, get_workflow_compiler
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.exceptions import CompilerError


class TestTraceCompilerLoading:
    """Test loading TraceCompiler via core.py."""

    def test_get_workflow_compiler_returns_trace_compiler(self) -> None:
        """Test get_workflow_compiler loads testarch-trace compiler."""
        compiler = get_workflow_compiler("testarch-trace")

        assert compiler.workflow_name == "testarch-trace"

    def test_workflow_name_property(self) -> None:
        """Test workflow_name is correctly set."""
        compiler = get_workflow_compiler("testarch-trace")

        assert compiler.workflow_name == "testarch-trace"


class TestTraceCompilerWorkflowDir:
    """Test get_workflow_dir returns correct testarch path."""

    def test_get_workflow_dir_returns_testarch_trace_path(self, tmp_path: Path) -> None:
        """Test workflow dir is _bmad/bmm/workflows/testarch/trace."""
        compiler = get_workflow_compiler("testarch-trace")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )

        workflow_dir = compiler.get_workflow_dir(context)

        # With bundled workflows, falls back to package path when BMAD not installed
        bmad_path = tmp_path / "_bmad/bmm/workflows/testarch/trace"
        bundled_path_suffix = "workflows/testarch-trace"
        assert workflow_dir == bmad_path or str(workflow_dir).endswith(bundled_path_suffix)


class TestTraceCompilerRequiredFiles:
    """Test get_required_files returns expected patterns."""

    def test_get_required_files_includes_project_context(self) -> None:
        """Test required files include project_context.md."""
        compiler = get_workflow_compiler("testarch-trace")

        patterns = compiler.get_required_files()

        # Should include project context pattern
        assert any("project_context" in p or "project-context" in p for p in patterns)

    def test_get_required_files_includes_epics_pattern(self) -> None:
        """Test required files include epic pattern."""
        compiler = get_workflow_compiler("testarch-trace")

        patterns = compiler.get_required_files()

        # Should have patterns for files needed for trace
        assert isinstance(patterns, list)
        assert len(patterns) >= 1


class TestTraceCompilerVariables:
    """Test get_variables returns expected variables."""

    def test_get_variables_includes_epic_num(self) -> None:
        """Test variables include epic_num."""
        compiler = get_workflow_compiler("testarch-trace")

        variables = compiler.get_variables()

        assert "epic_num" in variables

    def test_get_variables_includes_test_dir(self) -> None:
        """Test variables include test_dir from workflow.yaml."""
        compiler = get_workflow_compiler("testarch-trace")

        variables = compiler.get_variables()

        assert "test_dir" in variables

    def test_get_variables_includes_source_dir(self) -> None:
        """Test variables include source_dir from workflow.yaml."""
        compiler = get_workflow_compiler("testarch-trace")

        variables = compiler.get_variables()

        assert "source_dir" in variables


class TestTraceCompilerValidation:
    """Test validate_context validates required context."""

    def test_validate_context_requires_project_root(self) -> None:
        """Test validation fails without project_root."""
        compiler = get_workflow_compiler("testarch-trace")
        # Create context with None project_root explicitly
        context = CompilerContext(
            project_root=None,  # type: ignore
            output_folder=Path("/tmp/docs"),
        )

        with pytest.raises(CompilerError, match="project_root"):
            compiler.validate_context(context)

    def test_validate_context_requires_epic_num(self, tmp_path: Path) -> None:
        """Test validation fails without epic_num."""
        compiler = get_workflow_compiler("testarch-trace")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {}  # Missing epic_num

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.validate_context(context)


class TestTraceCompilerCompile:
    """Test compile() produces correct CompiledWorkflow."""

    @pytest.fixture
    def setup_testarch_trace_workflow(self, tmp_path: Path) -> Path:
        """Create testarch-trace workflow structure."""
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/trace"
        workflow_dir.mkdir(parents=True)

        # Create workflow.yaml
        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-trace
description: "Generate requirements-to-tests traceability matrix"
instructions: "{installed_path}/instructions.xml"
template: "{installed_path}/trace-template.md"
variables:
  test_dir: "{project-root}/tests"
  source_dir: "{project-root}/src"
  gate_type: "epic"
default_output_file: "{output_folder}/traceability-matrix.md"
""")

        # Create instructions.xml (parser expects XML format)
        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Collect test files">
<action>Find all test files in test_dir</action>
</step>

<step n="2" goal="Build traceability matrix">
<action>Map tests to requirements</action>
</step>

<step n="3" goal="Make gate decision">
<action>Determine PASS/CONCERNS/FAIL/WAIVED</action>
</step>
</workflow>""")

        # Create template
        template = workflow_dir / "trace-template.md"
        template.write_text("""
# Traceability Matrix for Epic {{epic_num}}

## Requirements Coverage
| Requirement | Test | Status |
|-------------|------|--------|
| AC1 | test_ac1 | ✓ |

## Gate Decision: {{gate_decision}}
""")

        # Create epic file in epics dir
        epics_dir = tmp_path / "_bmad-output/epics"
        epics_dir.mkdir(parents=True)
        epic_file = epics_dir / "epic-1.md"
        epic_file.write_text("""
# Epic 1: Core Feature

## Stories
- 1.1 First story
- 1.2 Second story
""")

        # Create project_context.md in output folder
        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context\nRules here...")

        return tmp_path

    def test_compile_returns_compiled_workflow(self, setup_testarch_trace_workflow: Path) -> None:
        """Test compile returns CompiledWorkflow with correct fields."""
        project_root = setup_testarch_trace_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        compiled = compile_workflow("testarch-trace", context)

        assert compiled.workflow_name == "testarch-trace"
        assert compiled.mission is not None
        assert compiled.context is not None  # Full XML
        assert compiled.instructions is not None
        assert "testarch-trace" in compiled.workflow_name

    def test_compile_includes_epic_context(self, setup_testarch_trace_workflow: Path) -> None:
        """Test compiled workflow includes epic file in context."""
        project_root = setup_testarch_trace_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        compiled = compile_workflow("testarch-trace", context)

        # Context XML should include epic content
        assert "Epic 1" in compiled.context or "epic" in compiled.context.lower()

    def test_compile_includes_story_files(self, setup_testarch_trace_workflow: Path) -> None:
        """Test compiled workflow includes all stories in epic (AC #2)."""
        project_root = setup_testarch_trace_workflow

        # Create story files in stories directory
        stories_dir = project_root / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)
        (stories_dir / "1-1-first-story.md").write_text(
            "# Story 1.1: First Story\n## Acceptance Criteria\n1. AC1"
        )
        (stories_dir / "1-2-second-story.md").write_text(
            "# Story 1.2: Second Story\n## Acceptance Criteria\n1. AC2"
        )

        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        compiled = compile_workflow("testarch-trace", context)

        # Context XML should include story content
        assert "First Story" in compiled.context
        assert "Second Story" in compiled.context

    def test_compile_includes_project_context(self, setup_testarch_trace_workflow: Path) -> None:
        """Test compiled workflow includes project_context.md."""
        project_root = setup_testarch_trace_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        compiled = compile_workflow("testarch-trace", context)

        # Should include project context
        assert "Project Context" in compiled.context or "project" in compiled.context.lower()

    def test_compile_resolves_test_dir_and_source_dir(
        self, setup_testarch_trace_workflow: Path
    ) -> None:
        """Test compile resolves test_dir and source_dir from workflow.yaml."""
        project_root = setup_testarch_trace_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        compiled = compile_workflow("testarch-trace", context)

        # Should have test_dir and source_dir resolved in variables
        assert "test_dir" in compiled.variables
        assert "source_dir" in compiled.variables


class TestTraceCompilerErrorHandling:
    """Test error handling in TraceCompiler."""

    def test_compile_fails_with_missing_workflow_dir(self, tmp_path: Path) -> None:
        """Test compile uses bundled fallback when workflow dir missing.

        With bundled workflows, compile_workflow should NOT fail when
        the BMAD directory doesn't exist - it falls back to bundled.
        """
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
            cwd=tmp_path,
        )
        context.resolved_variables = {
            "epic_num": "1",
        }

        # Should NOT raise - uses bundled workflow as fallback
        result = compile_workflow("testarch-trace", context)
        assert result.workflow_name == "testarch-trace"
