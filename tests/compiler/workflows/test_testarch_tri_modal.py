"""Tests for TEA tri-modal testarch workflow compilers.

Tests the base tri-modal compiler and all new testarch workflow compilers.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.compiler.types import CompilerContext, WorkflowIR


@pytest.fixture
def tri_modal_workflow_ir() -> WorkflowIR:
    """Create a mock tri-modal WorkflowIR."""
    return WorkflowIR(
        name="testarch-automate",
        config_path=Path("/mock/workflow.yaml"),
        instructions_path=Path("/mock/instructions.md"),
        template_path=None,
        validation_path=None,
        raw_config={
            "name": "testarch-automate",
            "description": "Test automation workflow",
        },
        raw_instructions="",
        workflow_type="tri_modal",
        has_tri_modal=True,
        steps_c_dir=Path("/mock/steps-c"),
        steps_v_dir=Path("/mock/steps-v"),
        steps_e_dir=Path("/mock/steps-e"),
        first_step_c=Path("/mock/steps-c/step-01.md"),
        first_step_v=Path("/mock/steps-v/step-01.md"),
        first_step_e=Path("/mock/steps-e/step-01.md"),
    )


@pytest.fixture
def basic_context(tmp_path: Path) -> CompilerContext:
    """Create a basic compiler context."""
    output_folder = tmp_path / "_bmad-output"
    output_folder.mkdir()
    return CompilerContext(
        project_root=tmp_path,
        output_folder=output_folder,
        resolved_variables={"epic_num": 25},
    )


class TestGetWorkflowCompiler:
    """Tests for loading tri-modal compilers via get_workflow_compiler."""

    def test_load_testarch_automate(self) -> None:
        """Should load testarch-automate compiler."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-automate")
        assert compiler.workflow_name == "testarch-automate"

    def test_load_testarch_ci(self) -> None:
        """Should load testarch-ci compiler."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-ci")
        assert compiler.workflow_name == "testarch-ci"

    def test_load_testarch_framework(self) -> None:
        """Should load testarch-framework compiler."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-framework")
        assert compiler.workflow_name == "testarch-framework"

    def test_load_testarch_nfr_assess(self) -> None:
        """Should load testarch-nfr-assess compiler."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-nfr-assess")
        assert compiler.workflow_name == "testarch-nfr-assess"

    def test_load_testarch_test_design(self) -> None:
        """Should load testarch-test-design compiler."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-test-design")
        assert compiler.workflow_name == "testarch-test-design"


class TestTestarchTriModalCompiler:
    """Tests for the base TestarchTriModalCompiler class."""

    def test_get_required_files(self) -> None:
        """Should return project context patterns."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        compiler = TestarchAutomateCompiler()
        patterns = compiler.get_required_files()

        assert "**/project_context.md" in patterns
        assert "**/project-context.md" in patterns

    def test_get_variables(self) -> None:
        """Should return expected variables."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        compiler = TestarchAutomateCompiler()
        variables = compiler.get_variables()

        assert "epic_num" in variables
        assert "story_num" in variables
        assert "workflow_mode" in variables
        assert "date" in variables

    def test_validate_context_requires_epic_num(
        self, basic_context: CompilerContext
    ) -> None:
        """Should require epic_num in context."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )
        from bmad_assist.core.exceptions import CompilerError

        compiler = TestarchAutomateCompiler()
        basic_context.resolved_variables = {}  # No epic_num

        with pytest.raises(CompilerError, match="epic_num is required"):
            compiler.validate_context(basic_context)

    def test_validate_context_requires_project_root(
        self, basic_context: CompilerContext
    ) -> None:
        """Should require project_root in context."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )
        from bmad_assist.core.exceptions import CompilerError

        compiler = TestarchAutomateCompiler()
        basic_context.project_root = None  # type: ignore

        with pytest.raises(CompilerError, match="project_root is required"):
            compiler.validate_context(basic_context)


class TestTriModalCompilerWithRealWorkflow:
    """Integration tests with real workflow files."""

    def test_get_workflow_dir_finds_automate(self, tmp_path: Path) -> None:
        """Should find testarch-automate workflow directory."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.md").write_text("---\nname: test\n---\n")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "output",
        )

        compiler = TestarchAutomateCompiler()
        result = compiler.get_workflow_dir(context)

        assert result == workflow_dir

    def test_compile_basic_workflow(self, tmp_path: Path) -> None:
        """Should compile a basic tri-modal workflow."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )
        from bmad_assist.compiler.types import WorkflowIR

        # Create workflow directory with step files
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.md").write_text(
            "---\nname: testarch-automate\ndescription: Test\nweb_bundle: true\n---\n"
        )

        steps_c = workflow_dir / "steps-c"
        steps_c.mkdir()
        (steps_c / "step-01.md").write_text(
            "---\nname: step-01\ndescription: First step\n---\n"
            "## Step 1\n\nExecute with epic {epic_num}.\n"
        )

        # Create output folder
        output_folder = tmp_path / "_bmad-output/implementation-artifacts"
        output_folder.mkdir(parents=True)

        # Create workflow IR
        workflow_ir = WorkflowIR(
            name="testarch-automate",
            config_path=workflow_dir / "workflow.yaml",
            instructions_path=workflow_dir / "instructions.md",
            template_path=None,
            validation_path=None,
            raw_config={
                "name": "testarch-automate",
                "description": "Test automation workflow",
            },
            raw_instructions="",
            workflow_type="tri_modal",
            has_tri_modal=True,
            steps_c_dir=steps_c,
            steps_v_dir=None,
            steps_e_dir=None,
            first_step_c=steps_c / "step-01.md",
            first_step_v=None,
            first_step_e=None,
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=output_folder,
            resolved_variables={"epic_num": 25},
            workflow_ir=workflow_ir,
        )

        compiler = TestarchAutomateCompiler()
        result = compiler.compile(context)

        assert result.workflow_name == "testarch-automate"
        assert "Execute with epic 25" in result.instructions
        assert "<!-- STEP: step-01 -->" in result.instructions

    def test_compile_with_mode_validate(self, tmp_path: Path) -> None:
        """Should compile in validate mode."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )
        from bmad_assist.compiler.types import WorkflowIR

        # Create workflow directory with validate steps
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.md").write_text(
            "---\nname: testarch-automate\ndescription: Test\nweb_bundle: true\n---\n"
        )

        # Create both steps-c and steps-v
        steps_c = workflow_dir / "steps-c"
        steps_c.mkdir()
        (steps_c / "step-01.md").write_text(
            "---\nname: create-step\n---\nCreate mode content\n"
        )

        steps_v = workflow_dir / "steps-v"
        steps_v.mkdir()
        (steps_v / "step-01.md").write_text(
            "---\nname: validate-step\n---\nValidate mode content\n"
        )

        output_folder = tmp_path / "_bmad-output/implementation-artifacts"
        output_folder.mkdir(parents=True)

        workflow_ir = WorkflowIR(
            name="testarch-automate",
            config_path=workflow_dir / "workflow.yaml",
            instructions_path=workflow_dir / "instructions.md",
            template_path=None,
            validation_path=None,
            raw_config={"name": "testarch-automate", "description": "Test"},
            raw_instructions="",
            workflow_type="tri_modal",
            has_tri_modal=True,
            steps_c_dir=steps_c,
            steps_v_dir=steps_v,
            steps_e_dir=None,
            first_step_c=steps_c / "step-01.md",
            first_step_v=steps_v / "step-01.md",
            first_step_e=None,
        )

        # Set mode to validate
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=output_folder,
            resolved_variables={"epic_num": 25, "workflow_mode": "v"},
            workflow_ir=workflow_ir,
        )

        compiler = TestarchAutomateCompiler()
        result = compiler.compile(context)

        assert "Validate mode content" in result.instructions
        assert "<!-- STEP: validate-step -->" in result.instructions
        assert "Create mode content" not in result.instructions


class TestAllNewCompilersWorkflowName:
    """Verify workflow_name property for all new compilers."""

    def test_automate_workflow_name(self) -> None:
        """testarch-automate should have correct name."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        assert TestarchAutomateCompiler().workflow_name == "testarch-automate"

    def test_ci_workflow_name(self) -> None:
        """testarch-ci should have correct name."""
        from bmad_assist.compiler.workflows.testarch_ci import TestarchCiCompiler

        assert TestarchCiCompiler().workflow_name == "testarch-ci"

    def test_framework_workflow_name(self) -> None:
        """testarch-framework should have correct name."""
        from bmad_assist.compiler.workflows.testarch_framework import (
            TestarchFrameworkCompiler,
        )

        assert TestarchFrameworkCompiler().workflow_name == "testarch-framework"

    def test_nfr_assess_workflow_name(self) -> None:
        """testarch-nfr-assess should have correct name."""
        from bmad_assist.compiler.workflows.testarch_nfr_assess import (
            TestarchNfrAssessCompiler,
        )

        assert TestarchNfrAssessCompiler().workflow_name == "testarch-nfr-assess"

    def test_test_design_workflow_name(self) -> None:
        """testarch-test-design should have correct name."""
        from bmad_assist.compiler.workflows.testarch_test_design import (
            TestarchTestDesignCompiler,
        )

        assert TestarchTestDesignCompiler().workflow_name == "testarch-test-design"
