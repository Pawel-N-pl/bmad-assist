"""Tests for tri-modal workflow types and detection.

Tests cover:
- StepIR dataclass creation and immutability
- WorkflowIR tri-modal fields
- Tri-modal structure detection
- Step file parsing
- Step chain building
- workflow.md frontmatter parsing
"""

from pathlib import Path

import pytest

from bmad_assist.compiler.parser import (
    parse_workflow,
    parse_workflow_md_frontmatter,
)
from bmad_assist.compiler.tri_modal import get_workflow_mode, validate_workflow_mode
from bmad_assist.compiler.types import CompilerContext, StepIR, WorkflowIR
from bmad_assist.core.exceptions import CompilerError


class TestStepIR:
    """Test StepIR dataclass."""

    def test_create_step_ir(self) -> None:
        """StepIR can be created with required fields."""
        step = StepIR(
            path=Path("/test/step-01.md"),
            name="step-01-test",
            description="Test step",
            next_step_file="./step-02.md",
            knowledge_index=None,
            raw_content="# Step 1\n\nContent here",
        )
        assert step.name == "step-01-test"
        assert step.description == "Test step"
        assert step.next_step_file == "./step-02.md"
        assert step.knowledge_index is None
        assert "Step 1" in step.raw_content

    def test_step_ir_is_frozen(self) -> None:
        """StepIR is immutable (frozen dataclass)."""
        step = StepIR(
            path=Path("/test/step.md"),
            name="test",
            description="Test",
            next_step_file=None,
            knowledge_index=None,
            raw_content="content",
        )
        with pytest.raises(AttributeError):
            step.name = "modified"  # type: ignore[misc]

    def test_step_ir_with_knowledge_index(self) -> None:
        """StepIR can have knowledge_index."""
        step = StepIR(
            path=Path("/test/step.md"),
            name="test",
            description="Test",
            next_step_file=None,
            knowledge_index="{project-root}/_bmad/tea/testarch/tea-index.csv",
            raw_content="content",
        )
        assert step.knowledge_index == "{project-root}/_bmad/tea/testarch/tea-index.csv"

    def test_step_ir_with_none_next_step(self) -> None:
        """StepIR can have None next_step_file (final step)."""
        step = StepIR(
            path=Path("/test/step-final.md"),
            name="final-step",
            description="Final step",
            next_step_file=None,
            knowledge_index=None,
            raw_content="End of chain",
        )
        assert step.next_step_file is None


class TestWorkflowIRTriModalFields:
    """Test WorkflowIR tri-modal fields."""

    def test_workflow_ir_default_macro_type(self) -> None:
        """WorkflowIR defaults to macro workflow type."""
        ir = WorkflowIR(
            name="test-workflow",
            config_path=Path("/test/workflow.yaml"),
            instructions_path=Path("/test/instructions.xml"),
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
        )
        assert ir.workflow_type == "macro"
        assert ir.has_tri_modal is False

    def test_workflow_ir_tri_modal_type(self) -> None:
        """WorkflowIR can be set to tri_modal type."""
        ir = WorkflowIR(
            name="testarch-atdd",
            config_path=Path("/test/workflow.yaml"),
            instructions_path=Path("/test/instructions.md"),
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
            workflow_type="tri_modal",
            has_tri_modal=True,
            steps_c_dir=Path("/test/steps-c"),
            steps_v_dir=Path("/test/steps-v"),
            steps_e_dir=Path("/test/steps-e"),
        )
        assert ir.workflow_type == "tri_modal"
        assert ir.has_tri_modal is True
        assert ir.steps_c_dir == Path("/test/steps-c")

    def test_workflow_ir_partial_tri_modal(self) -> None:
        """WorkflowIR can have partial tri-modal (e.g., only steps-c/)."""
        ir = WorkflowIR(
            name="testarch-simple",
            config_path=Path("/test/workflow.yaml"),
            instructions_path=Path("/test/instructions.md"),
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
            workflow_type="tri_modal",
            has_tri_modal=True,
            steps_c_dir=Path("/test/steps-c"),
            steps_v_dir=None,
            steps_e_dir=None,
        )
        assert ir.has_tri_modal is True
        assert ir.steps_c_dir is not None
        assert ir.steps_v_dir is None
        assert ir.steps_e_dir is None

    def test_workflow_ir_first_step_paths(self) -> None:
        """WorkflowIR stores first step paths for each mode."""
        ir = WorkflowIR(
            name="testarch-atdd",
            config_path=Path("/test/workflow.yaml"),
            instructions_path=Path("/test/instructions.md"),
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
            workflow_type="tri_modal",
            has_tri_modal=True,
            steps_c_dir=Path("/test/steps-c"),
            first_step_c=Path("/test/steps-c/step-01-preflight.md"),
            first_step_v=Path("/test/steps-v/step-01-validate.md"),
            first_step_e=Path("/test/steps-e/step-01-assess.md"),
        )
        assert ir.first_step_c == Path("/test/steps-c/step-01-preflight.md")
        assert ir.first_step_v == Path("/test/steps-v/step-01-validate.md")
        assert ir.first_step_e == Path("/test/steps-e/step-01-assess.md")


class TestParseWorkflowMdFrontmatter:
    """Test workflow.md frontmatter parsing (AC1)."""

    def test_parse_frontmatter_basic(self, tmp_path: Path) -> None:
        """Parse basic YAML frontmatter from workflow.md."""
        workflow_md = tmp_path / "workflow.md"
        workflow_md.write_text(
            """---
name: testarch-atdd
description: 'Generate failing tests'
web_bundle: true
---

# Workflow Title

Body content here
"""
        )
        config = parse_workflow_md_frontmatter(workflow_md)
        assert config["name"] == "testarch-atdd"
        assert config["description"] == "Generate failing tests"
        assert config["web_bundle"] is True

    def test_parse_frontmatter_no_yaml(self, tmp_path: Path) -> None:
        """Return empty dict when no frontmatter in workflow.md."""
        workflow_md = tmp_path / "workflow.md"
        workflow_md.write_text("# Just Markdown\n\nNo frontmatter here.\n")
        config = parse_workflow_md_frontmatter(workflow_md)
        assert config == {}

    def test_parse_frontmatter_empty_file(self, tmp_path: Path) -> None:
        """Return empty dict for empty workflow.md."""
        workflow_md = tmp_path / "workflow.md"
        workflow_md.write_text("")
        config = parse_workflow_md_frontmatter(workflow_md)
        assert config == {}

    def test_parse_frontmatter_only_markers(self, tmp_path: Path) -> None:
        """Return empty dict when only --- markers present."""
        workflow_md = tmp_path / "workflow.md"
        workflow_md.write_text("---\n---\n\n# Body\n")
        config = parse_workflow_md_frontmatter(workflow_md)
        assert config == {}

    def test_parse_frontmatter_file_not_found(self, tmp_path: Path) -> None:
        """Return empty dict when file does not exist."""
        workflow_md = tmp_path / "nonexistent.md"
        config = parse_workflow_md_frontmatter(workflow_md)
        assert config == {}


class TestParseWorkflowWithWorkflowMd:
    """Test parse_workflow with workflow.md support (AC1)."""

    def test_workflow_md_only(self, tmp_path: Path) -> None:
        """Parse workflow when only workflow.md exists (no workflow.yaml)."""
        # Create workflow.md with frontmatter
        (tmp_path / "workflow.md").write_text(
            """---
name: tri-modal-workflow
description: 'TEA workflow'
web_bundle: true
---

# Workflow Content
"""
        )
        # Create minimal instructions.md
        (tmp_path / "instructions.md").write_text("# Instructions\n\nDo something.")

        ir = parse_workflow(tmp_path)
        assert ir.name == "tri-modal-workflow"
        assert ir.raw_config["description"] == "TEA workflow"
        assert ir.raw_config["web_bundle"] is True

    def test_workflow_yaml_takes_precedence(self, tmp_path: Path) -> None:
        """workflow.yaml values override workflow.md for same keys."""
        # Create workflow.md with frontmatter
        (tmp_path / "workflow.md").write_text(
            """---
name: from-md
description: 'MD description'
web_bundle: true
---

# Workflow
"""
        )
        # Create workflow.yaml with different values
        (tmp_path / "workflow.yaml").write_text(
            """name: from-yaml
description: "YAML description"
"""
        )
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)
        # workflow.yaml takes precedence
        assert ir.name == "from-yaml"
        assert ir.raw_config["description"] == "YAML description"
        # web_bundle only in workflow.md, so it should be included
        assert ir.raw_config.get("web_bundle") is True

    def test_merge_workflow_md_and_yaml(self, tmp_path: Path) -> None:
        """Merge non-overlapping fields from workflow.md and workflow.yaml."""
        (tmp_path / "workflow.md").write_text(
            """---
name: test-workflow
web_bundle: true
md_only_field: "from md"
---
"""
        )
        (tmp_path / "workflow.yaml").write_text(
            """name: test-workflow
yaml_only_field: "from yaml"
"""
        )
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)
        assert ir.raw_config["md_only_field"] == "from md"
        assert ir.raw_config["yaml_only_field"] == "from yaml"
        assert ir.raw_config["web_bundle"] is True

    def test_workflow_md_no_frontmatter_uses_yaml(self, tmp_path: Path) -> None:
        """When workflow.md has no frontmatter, use workflow.yaml."""
        (tmp_path / "workflow.md").write_text("# Just markdown\n\nNo frontmatter.")
        (tmp_path / "workflow.yaml").write_text("name: yaml-workflow\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)
        assert ir.name == "yaml-workflow"

    def test_no_workflow_files_raises_error(self, tmp_path: Path) -> None:
        """ParserError when neither workflow.md nor workflow.yaml exists."""
        from bmad_assist.core.exceptions import ParserError

        (tmp_path / "instructions.md").write_text("# Instructions")

        with pytest.raises(ParserError) as exc_info:
            parse_workflow(tmp_path)
        assert "workflow.yaml" in str(exc_info.value) or "workflow.md" in str(exc_info.value)


class TestTriModalDetection:
    """Test tri-modal structure detection (AC2)."""

    def test_detect_tri_modal_all_modes(self, tmp_path: Path) -> None:
        """Detect tri-modal when all three step directories exist."""
        # Create workflow files
        (tmp_path / "workflow.md").write_text("---\nname: tri-modal-test\n---\n# Test")
        (tmp_path / "instructions.md").write_text("# Instructions")

        # Create step directories
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-v").mkdir()
        (tmp_path / "steps-e").mkdir()

        # Create step files
        (tmp_path / "steps-c" / "step-01-first.md").write_text(
            "---\nname: step-01-first\n---\n# First step"
        )
        (tmp_path / "steps-v" / "step-01-validate.md").write_text(
            "---\nname: step-01-validate\n---\n# Validate"
        )
        (tmp_path / "steps-e" / "step-01-edit.md").write_text(
            "---\nname: step-01-edit\n---\n# Edit"
        )

        ir = parse_workflow(tmp_path)
        assert ir.has_tri_modal is True
        assert ir.workflow_type == "tri_modal"
        assert ir.steps_c_dir == tmp_path / "steps-c"
        assert ir.steps_v_dir == tmp_path / "steps-v"
        assert ir.steps_e_dir == tmp_path / "steps-e"

    def test_detect_tri_modal_create_only(self, tmp_path: Path) -> None:
        """Detect tri-modal when only steps-c/ exists."""
        (tmp_path / "workflow.yaml").write_text("name: create-only\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01-first.md").write_text(
            "---\nname: step-01-first\n---\n# Step"
        )

        ir = parse_workflow(tmp_path)
        assert ir.has_tri_modal is True
        assert ir.workflow_type == "tri_modal"
        assert ir.steps_c_dir == tmp_path / "steps-c"
        assert ir.steps_v_dir is None
        assert ir.steps_e_dir is None

    def test_no_tri_modal_macro_workflow(self, tmp_path: Path) -> None:
        """Detect macro workflow when no step directories exist."""
        (tmp_path / "workflow.yaml").write_text("name: macro-workflow\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)
        assert ir.has_tri_modal is False
        assert ir.workflow_type == "macro"
        assert ir.steps_c_dir is None

    def test_empty_step_directory_ignored(self, tmp_path: Path) -> None:
        """Empty step directories are treated as non-existent."""
        (tmp_path / "workflow.yaml").write_text("name: empty-steps\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        # Create empty step directory
        (tmp_path / "steps-c").mkdir()
        # No .md files inside

        ir = parse_workflow(tmp_path)
        # Empty directory should not count as tri-modal
        assert ir.has_tri_modal is False
        assert ir.workflow_type == "macro"

    def test_first_step_natural_sort(self, tmp_path: Path) -> None:
        """First step file determined by natural sort order."""
        (tmp_path / "workflow.yaml").write_text("name: natural-sort\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        (tmp_path / "steps-c").mkdir()
        # Create step files in non-alphabetical order
        (tmp_path / "steps-c" / "step-10-tenth.md").write_text("# Tenth")
        (tmp_path / "steps-c" / "step-02-second.md").write_text("# Second")
        (tmp_path / "steps-c" / "step-01-first.md").write_text("# First")

        ir = parse_workflow(tmp_path)
        assert ir.first_step_c == tmp_path / "steps-c" / "step-01-first.md"

    def test_first_step_with_substeps(self, tmp_path: Path) -> None:
        """Substeps (04a, 04b) come after main step."""
        (tmp_path / "workflow.yaml").write_text("name: substeps\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-04a-subprocess-api.md").write_text("# Sub A")
        (tmp_path / "steps-c" / "step-04b-subprocess-e2e.md").write_text("# Sub B")
        (tmp_path / "steps-c" / "step-04-generate.md").write_text("# Main")
        (tmp_path / "steps-c" / "step-01-first.md").write_text("# First")

        ir = parse_workflow(tmp_path)
        # step-01 should be first
        assert ir.first_step_c == tmp_path / "steps-c" / "step-01-first.md"

    def test_tri_modal_no_instructions_file_in_dir(self, tmp_path: Path) -> None:
        """Tri-modal workflows don't require instructions.xml/md when step dirs exist."""
        (tmp_path / "workflow.md").write_text("---\nname: no-instructions\n---\n")

        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01-first.md").write_text("# Step content")

        ir = parse_workflow(tmp_path)
        # Should work without instructions file for tri-modal
        assert ir.has_tri_modal is True
        # instructions_path should point to first step or workflow.md
        # (implementation detail, but it should not raise)
        assert ir.name == "no-instructions"


class TestModeSelection:
    """Test mode selection for tri-modal workflows (AC4)."""

    def test_get_mode_default_create(self, tmp_path: Path) -> None:
        """Default mode is 'c' (create) for tri-modal workflows."""
        (tmp_path / "workflow.yaml").write_text("name: test-tri-modal\n")
        (tmp_path / "instructions.md").write_text("# Instructions")
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01.md").write_text("# Step 1")

        ir = parse_workflow(tmp_path)
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            workflow_ir=ir,
        )

        mode = get_workflow_mode(context)
        assert mode == "c"

    def test_get_mode_from_context_variable(self, tmp_path: Path) -> None:
        """Mode can be overridden via resolved_variables['workflow_mode']."""
        (tmp_path / "workflow.yaml").write_text("name: test-tri-modal\n")
        (tmp_path / "instructions.md").write_text("# Instructions")
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01.md").write_text("# Step 1")
        (tmp_path / "steps-v").mkdir()
        (tmp_path / "steps-v" / "step-01.md").write_text("# Validate")

        ir = parse_workflow(tmp_path)
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            workflow_ir=ir,
            resolved_variables={"workflow_mode": "v"},
        )

        mode = get_workflow_mode(context)
        assert mode == "v"

    def test_get_mode_returns_none_for_macro(self, tmp_path: Path) -> None:
        """Mode is None for macro workflows (no tri-modal)."""
        (tmp_path / "workflow.yaml").write_text("name: macro-workflow\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            workflow_ir=ir,
        )

        mode = get_workflow_mode(context)
        assert mode is None

    def test_validate_mode_valid_modes(self, tmp_path: Path) -> None:
        """Valid modes pass validation."""
        (tmp_path / "workflow.yaml").write_text("name: test\n")
        (tmp_path / "instructions.md").write_text("# Instructions")
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01.md").write_text("# Step")
        (tmp_path / "steps-v").mkdir()
        (tmp_path / "steps-v" / "step-01.md").write_text("# Validate")
        (tmp_path / "steps-e").mkdir()
        (tmp_path / "steps-e" / "step-01.md").write_text("# Edit")

        ir = parse_workflow(tmp_path)

        # All three modes should be valid
        validate_workflow_mode(ir, "c")  # No exception
        validate_workflow_mode(ir, "v")  # No exception
        validate_workflow_mode(ir, "e")  # No exception

    def test_validate_mode_invalid_raises_error(self, tmp_path: Path) -> None:
        """Invalid mode raises CompilerError with available modes."""
        (tmp_path / "workflow.yaml").write_text("name: test\n")
        (tmp_path / "instructions.md").write_text("# Instructions")
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01.md").write_text("# Step")
        # steps-v and steps-e do NOT exist

        ir = parse_workflow(tmp_path)

        with pytest.raises(CompilerError) as exc_info:
            validate_workflow_mode(ir, "v")

        error_msg = str(exc_info.value)
        assert "v" in error_msg  # Invalid mode mentioned
        assert "c" in error_msg  # Available mode mentioned

    def test_validate_mode_unknown_mode(self, tmp_path: Path) -> None:
        """Unknown mode (not c, v, e) raises CompilerError."""
        (tmp_path / "workflow.yaml").write_text("name: test\n")
        (tmp_path / "instructions.md").write_text("# Instructions")
        (tmp_path / "steps-c").mkdir()
        (tmp_path / "steps-c" / "step-01.md").write_text("# Step")

        ir = parse_workflow(tmp_path)

        with pytest.raises(CompilerError) as exc_info:
            validate_workflow_mode(ir, "x")

        assert "x" in str(exc_info.value)

    def test_validate_mode_on_macro_workflow(self, tmp_path: Path) -> None:
        """Mode validation on macro workflow raises error."""
        (tmp_path / "workflow.yaml").write_text("name: macro\n")
        (tmp_path / "instructions.md").write_text("# Instructions")

        ir = parse_workflow(tmp_path)

        with pytest.raises(CompilerError) as exc_info:
            validate_workflow_mode(ir, "c")

        assert "macro" in str(exc_info.value).lower() or "not available" in str(
            exc_info.value
        ).lower()


class TestWorkflowDiscoveryUpdate:
    """Test workflow discovery updates (AC7)."""

    def test_is_valid_workflow_dir_yaml_only(self, tmp_path: Path) -> None:
        """workflow.yaml only makes valid workflow dir."""
        from bmad_assist.compiler.workflow_discovery import _is_valid_workflow_dir

        workflow_dir = tmp_path / "my-workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text("name: test\n")

        assert _is_valid_workflow_dir(workflow_dir) is True

    def test_is_valid_workflow_dir_md_only(self, tmp_path: Path) -> None:
        """workflow.md only makes valid workflow dir."""
        from bmad_assist.compiler.workflow_discovery import _is_valid_workflow_dir

        workflow_dir = tmp_path / "my-workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.md").write_text("---\nname: test\n---\n")

        assert _is_valid_workflow_dir(workflow_dir) is True

    def test_is_valid_workflow_dir_both_files(self, tmp_path: Path) -> None:
        """Both workflow.yaml and workflow.md makes valid workflow dir."""
        from bmad_assist.compiler.workflow_discovery import _is_valid_workflow_dir

        workflow_dir = tmp_path / "my-workflow"
        workflow_dir.mkdir()
        (workflow_dir / "workflow.yaml").write_text("name: test\n")
        (workflow_dir / "workflow.md").write_text("---\nname: test\n---\n")

        assert _is_valid_workflow_dir(workflow_dir) is True

    def test_is_valid_workflow_dir_neither_file(self, tmp_path: Path) -> None:
        """Neither workflow.yaml nor workflow.md makes invalid workflow dir."""
        from bmad_assist.compiler.workflow_discovery import _is_valid_workflow_dir

        workflow_dir = tmp_path / "my-workflow"
        workflow_dir.mkdir()
        # No workflow files

        assert _is_valid_workflow_dir(workflow_dir) is False

    def test_standard_workflows_includes_new_tea(self) -> None:
        """STANDARD_WORKFLOWS includes new TEA workflows."""
        from bmad_assist.compiler.workflow_discovery import STANDARD_WORKFLOWS

        expected_tea_workflows = {
            "testarch-atdd",
            "testarch-trace",
            "testarch-test-review",
            "testarch-automate",
            "testarch-ci",
            "testarch-framework",
            "testarch-nfr-assess",
            "testarch-test-design",
        }

        for workflow in expected_tea_workflows:
            assert workflow in STANDARD_WORKFLOWS, f"{workflow} not in STANDARD_WORKFLOWS"

    def test_workflow_to_bmad_dir_has_new_mappings(self) -> None:
        """WORKFLOW_TO_BMAD_DIR has mappings for new TEA workflows."""
        from bmad_assist.compiler.workflow_discovery import WORKFLOW_TO_BMAD_DIR

        expected_mappings = {
            "testarch-atdd": "atdd",
            "testarch-trace": "trace",
            "testarch-test-review": "test-review",
            "testarch-automate": "automate",
            "testarch-ci": "ci",
            "testarch-framework": "framework",
            "testarch-nfr-assess": "nfr-assess",
            "testarch-test-design": "test-design",
        }

        for workflow, bmad_dir in expected_mappings.items():
            assert WORKFLOW_TO_BMAD_DIR.get(workflow) == bmad_dir, (
                f"{workflow} -> {bmad_dir} mapping missing"
            )
