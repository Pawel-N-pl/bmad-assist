"""Tests for TestarchTestReviewCompiler workflow compiler.

Tests the testarch-test-review workflow compiler that produces prompts for
test quality review workflow execution.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.compiler.core import compile_workflow, get_workflow_compiler
from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.core.exceptions import CompilerError


class TestTestReviewCompilerLoading:
    """Test loading TestarchTestReviewCompiler via core.py."""

    def test_get_workflow_compiler_returns_test_review_compiler(self) -> None:
        """Test get_workflow_compiler loads testarch-test-review compiler."""
        compiler = get_workflow_compiler("testarch-test-review")

        assert compiler.workflow_name == "testarch-test-review"

    def test_workflow_name_property(self) -> None:
        """Test workflow_name is correctly set."""
        compiler = get_workflow_compiler("testarch-test-review")

        assert compiler.workflow_name == "testarch-test-review"


class TestTestReviewCompilerWorkflowDir:
    """Test get_workflow_dir returns correct testarch path."""

    def test_get_workflow_dir_returns_testarch_test_review_path(self, tmp_path: Path) -> None:
        """Test workflow dir is _bmad/bmm/workflows/testarch/test-review."""
        compiler = get_workflow_compiler("testarch-test-review")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )

        workflow_dir = compiler.get_workflow_dir(context)

        # With bundled workflows, falls back to package path when BMAD not installed
        bmad_path = tmp_path / "_bmad/bmm/workflows/testarch/test-review"
        bundled_path_suffix = "workflows/testarch-test-review"
        assert workflow_dir == bmad_path or str(workflow_dir).endswith(bundled_path_suffix)


class TestTestReviewCompilerRequiredFiles:
    """Test get_required_files returns expected patterns."""

    def test_get_required_files_includes_project_context(self) -> None:
        """Test required files include project_context.md."""
        compiler = get_workflow_compiler("testarch-test-review")

        patterns = compiler.get_required_files()

        # Should include project context pattern
        assert any("project_context" in p or "project-context" in p for p in patterns)

    def test_get_required_files_is_list(self) -> None:
        """Test required files returns a list."""
        compiler = get_workflow_compiler("testarch-test-review")

        patterns = compiler.get_required_files()

        assert isinstance(patterns, list)
        assert len(patterns) >= 1


class TestTestReviewCompilerVariables:
    """Test get_variables returns expected variables."""

    def test_get_variables_includes_story_id(self) -> None:
        """Test variables include story_id."""
        compiler = get_workflow_compiler("testarch-test-review")

        variables = compiler.get_variables()

        assert "story_id" in variables

    def test_get_variables_includes_test_dir(self) -> None:
        """Test variables include test_dir from workflow.yaml."""
        compiler = get_workflow_compiler("testarch-test-review")

        variables = compiler.get_variables()

        assert "test_dir" in variables

    def test_get_variables_includes_epic_num(self) -> None:
        """Test variables include epic_num."""
        compiler = get_workflow_compiler("testarch-test-review")

        variables = compiler.get_variables()

        assert "epic_num" in variables

    def test_get_variables_includes_story_num(self) -> None:
        """Test variables include story_num."""
        compiler = get_workflow_compiler("testarch-test-review")

        variables = compiler.get_variables()

        assert "story_num" in variables


class TestTestReviewCompilerValidation:
    """Test validate_context validates required context."""

    def test_validate_context_requires_project_root(self) -> None:
        """Test validation fails without project_root."""
        compiler = get_workflow_compiler("testarch-test-review")
        # Create context with None project_root explicitly
        context = CompilerContext(
            project_root=None,  # type: ignore
            output_folder=Path("/tmp/docs"),
        )

        with pytest.raises(CompilerError, match="project_root"):
            compiler.validate_context(context)

    def test_validate_context_requires_output_folder(self, tmp_path: Path) -> None:
        """Test validation fails without output_folder."""
        compiler = get_workflow_compiler("testarch-test-review")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=None,  # type: ignore
        )

        with pytest.raises(CompilerError, match="output_folder"):
            compiler.validate_context(context)

    def test_validate_context_requires_epic_num(self, tmp_path: Path) -> None:
        """Test validation fails without epic_num."""
        compiler = get_workflow_compiler("testarch-test-review")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {"story_num": 1}  # Missing epic_num

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.validate_context(context)

    def test_validate_context_requires_story_num(self, tmp_path: Path) -> None:
        """Test validation fails without story_num."""
        compiler = get_workflow_compiler("testarch-test-review")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {"epic_num": 1}  # Missing story_num

        with pytest.raises(CompilerError, match="story_num"):
            compiler.validate_context(context)

    def test_validate_context_uses_bundled_fallback(self, tmp_path: Path) -> None:
        """Test validation uses bundled workflow when BMAD not installed.

        With bundled workflows, validate_context should NOT fail when
        the BMAD directory doesn't exist - it falls back to bundled.
        """
        compiler = get_workflow_compiler("testarch-test-review")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.resolved_variables = {"epic_num": 1, "story_num": 1}

        # Create a story file so validation doesn't fail for other reasons
        stories_dir = tmp_path / "_bmad-output/implementation-artifacts/stories"
        stories_dir.mkdir(parents=True)
        (stories_dir / "1-1-test.md").write_text("# Story 1.1")

        # Should NOT raise - uses bundled workflow as fallback
        compiler.validate_context(context)  # No exception expected


class TestTestReviewCompilerCompile:
    """Test compile() produces correct CompiledWorkflow."""

    @pytest.fixture
    def setup_testarch_workflow(self, tmp_path: Path) -> Path:
        """Create testarch-test-review workflow structure."""
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/test-review"
        workflow_dir.mkdir(parents=True)

        # Create workflow.yaml
        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-test-review
description: "Review test quality using comprehensive knowledge base"
instructions: "{installed_path}/instructions.md"
template: "{installed_path}/test-review-template.md"
variables:
  test_dir: "{project-root}/tests"
default_output_file: "{output_folder}/test-reviews/test-review-{story_id}.md"
""")

        # Create instructions.xml (parser expects XML format)
        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Analyze test quality">
<action>Read test files and evaluate quality</action>
</step>

<step n="2" goal="Generate quality report">
<action>Write test quality report with score</action>
</step>
</workflow>""")

        # Create template
        template = workflow_dir / "test-review-template.md"
        template.write_text("""
# Test Review for {{story_id}}

## Quality Score
**Quality Score**: {{quality_score}}/100

## Findings
- {{finding1}}

## Status
- Story: {{story_id}}
- Date: {{date}}
""")

        # Create story file in sprint-artifacts dir (fallback location for tests)
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

        # Create project_context.md
        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context\nRules here...")

        # Create tests directory with sample test files
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_sample.py"
        test_file.write_text('"""Sample test file."""\n\ndef test_sample():\n    assert True\n')

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

        compiled = compile_workflow("testarch-test-review", context)

        assert compiled.workflow_name == "testarch-test-review"
        assert compiled.mission is not None
        assert compiled.context is not None  # Full XML
        assert compiled.instructions is not None

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

        compiled = compile_workflow("testarch-test-review", context)

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

        compiled = compile_workflow("testarch-test-review", context)

        # Should have test_dir resolved in variables
        assert "test_dir" in compiled.variables
        assert "tests" in compiled.variables["test_dir"]

    def test_compile_resolves_story_id_variable(self, setup_testarch_workflow: Path) -> None:
        """Test compile resolves story_id from epic_num and story_num."""
        project_root = setup_testarch_workflow
        context = CompilerContext(
            project_root=project_root,
            output_folder=project_root / "_bmad-output",
            cwd=project_root,
        )
        context.resolved_variables = {
            "epic_num": "testarch",
            "story_num": "9",
        }

        compiled = compile_workflow("testarch-test-review", context)

        # story_id uses dash format: epic_num-story_num
        assert "story_id" in compiled.variables
        assert compiled.variables["story_id"] == "testarch-9"


class TestTestReviewCompilerTestFileDiscovery:
    """Test test file discovery in TestarchTestReviewCompiler."""

    @pytest.fixture
    def setup_with_test_files(self, tmp_path: Path) -> Path:
        """Create workflow structure with test files."""
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/test-review"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-test-review
description: "Review test quality"
instructions: "{installed_path}/instructions.md"
variables:
  test_dir: "{project-root}/tests"
""")

        instructions = workflow_dir / "instructions.md"
        instructions.write_text("<step>Review tests</step>")

        # Create story file
        stories_dir = tmp_path / "_bmad-output/implementation-artifacts/stories"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "testarch-9-test-story.md"
        story_file.write_text("# Story testarch.9: Test Story")

        # Create tests directory with story-specific and generic test files
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # Story-specific test files
        (tests_dir / "test_testarch-9_handler.py").write_text("def test_handler(): pass")
        (tests_dir / "test_testarch_9_compiler.py").write_text("def test_compiler(): pass")

        # Generic test files
        (tests_dir / "test_utils.py").write_text("def test_utils(): pass")
        (tests_dir / "test_config.py").write_text("def test_config(): pass")

        return tmp_path

    def test_discovers_story_specific_test_files(self, setup_with_test_files: Path) -> None:
        """Test compiler discovers test files matching story pattern."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=setup_with_test_files,
            output_folder=setup_with_test_files / "_bmad-output",
        )

        test_files = compiler._discover_test_files(context, "testarch", "9")

        # Should find story-specific files
        filenames = [f.name for f in test_files]
        assert any("testarch-9" in name or "testarch_9" in name for name in filenames)

    def test_fallback_to_recent_test_files(self, tmp_path: Path) -> None:
        """Test compiler falls back to recent test files when no story match."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        # Create tests without story-specific names
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_a.py").write_text("def test_a(): pass")
        (tests_dir / "test_b.py").write_text("def test_b(): pass")
        (tests_dir / "test_c.py").write_text("def test_c(): pass")

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )

        test_files = compiler._discover_test_files(context, "nonexistent", "99")

        # Should fallback to generic test files
        assert len(test_files) > 0
        filenames = [f.name for f in test_files]
        assert "test_a.py" in filenames or "test_b.py" in filenames

    def test_returns_empty_list_when_no_tests_dir(self, tmp_path: Path) -> None:
        """Test compiler returns empty list when tests directory doesn't exist."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )

        test_files = compiler._discover_test_files(context, "1", "1")

        assert test_files == []

    def test_limits_test_files_to_max(self, tmp_path: Path) -> None:
        """Test compiler limits test files to MAX_TEST_FILES."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            _MAX_TEST_FILES,
            TestarchTestReviewCompiler,
        )

        # Create more test files than the limit
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        for i in range(30):
            (tests_dir / f"test_{i:03d}.py").write_text(f"def test_{i}(): pass")

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )

        test_files = compiler._discover_test_files(context, "nonexistent", "99")

        assert len(test_files) <= _MAX_TEST_FILES


class TestTestReviewCompilerStoryFileDiscovery:
    """Test story file discovery in TestarchTestReviewCompiler."""

    def test_finds_story_file_by_pattern(self, tmp_path: Path) -> None:
        """Test _find_story_file locates story by epic-story pattern."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        # Create stories directory in fallback location (sprint-artifacts)
        # This matches get_stories_dir fallback when paths not initialized
        stories_dir = tmp_path / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "testarch-9-test-review-handler.md"
        story_file.write_text("# Story testarch.9")

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )

        result = compiler._find_story_file(context, "testarch", "9")

        assert result is not None
        assert result.name == "testarch-9-test-review-handler.md"

    def test_returns_none_when_story_not_found(self, tmp_path: Path) -> None:
        """Test _find_story_file returns None when story doesn't exist."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        # Create empty stories directory (fallback location)
        stories_dir = tmp_path / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )

        result = compiler._find_story_file(context, "nonexistent", "99")

        assert result is None


class TestTestReviewCompilerBuildMission:
    """Test mission building in TestarchTestReviewCompiler."""

    def test_build_mission_includes_story_id(self) -> None:
        """Test _build_mission includes story_id in mission."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        compiler = TestarchTestReviewCompiler()

        # Create mock workflow_ir
        workflow_ir = MagicMock(spec=WorkflowIR)
        workflow_ir.raw_config = {"description": "Review test quality"}

        resolved = {"story_id": "testarch.9"}

        mission = compiler._build_mission(workflow_ir, resolved)

        assert "testarch.9" in mission
        assert "Review" in mission or "review" in mission


class TestTestReviewCompilerErrorHandling:
    """Test error handling in TestarchTestReviewCompiler."""

    def test_compile_uses_bundled_fallback_when_workflow_dir_missing(
        self, tmp_path: Path
    ) -> None:
        """Test compile uses bundled fallback when workflow dir missing.

        With bundled workflows, compile_workflow should NOT fail when
        the BMAD directory doesn't exist - it falls back to bundled.
        """
        # Create story file so validation doesn't fail for other reasons
        stories_dir = tmp_path / "_bmad-output/implementation-artifacts/stories"
        stories_dir.mkdir(parents=True)
        (stories_dir / "1-1-test.md").write_text("# Story 1.1")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output/implementation-artifacts",
            cwd=tmp_path,
        )
        context.resolved_variables = {
            "epic_num": "1",
            "story_num": "1",
        }

        # Should NOT raise - uses bundled workflow as fallback
        result = compile_workflow("testarch-test-review", context)
        assert result.workflow_name == "testarch-test-review"

    def test_compile_raises_when_workflow_ir_not_set(self, tmp_path: Path) -> None:
        """Test compile raises when workflow_ir is not set in context."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )
        context.resolved_variables = {"epic_num": "1", "story_num": "1"}
        context.workflow_ir = None  # Not set

        with pytest.raises(CompilerError, match="workflow_ir"):
            compiler.compile(context)


class TestTestReviewCompilerContextBuilding:
    """Test context building with recency-bias ordering."""

    @pytest.fixture
    def setup_full_context(self, tmp_path: Path) -> Path:
        """Create full context with project, story, and test files."""
        # Create workflow
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/test-review"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-test-review
description: "Review tests"
instructions: "{installed_path}/instructions.md"
variables:
  test_dir: "{project-root}/tests"
""")
        (workflow_dir / "instructions.xml").write_text("<step>Review</step>")

        # Create project context
        output_dir = tmp_path / "_bmad-output"
        output_dir.mkdir()
        (output_dir / "project-context.md").write_text("# Project Rules")

        # Create story
        stories_dir = output_dir / "implementation-artifacts/stories"
        stories_dir.mkdir(parents=True)
        (stories_dir / "1-1-test.md").write_text("# Story 1.1")

        # Create tests
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_feature.py").write_text("def test_feature(): pass")

        return tmp_path

    def test_build_context_files_includes_all_sources(self, setup_full_context: Path) -> None:
        """Test _build_context_files includes project, story, and test files."""
        from bmad_assist.compiler.workflows.testarch_test_review import (
            TestarchTestReviewCompiler,
        )

        compiler = TestarchTestReviewCompiler()
        context = CompilerContext(
            project_root=setup_full_context,
            output_folder=setup_full_context / "_bmad-output",
        )

        resolved = {
            "epic_num": "1",
            "story_num": "1",
            "story_file": str(
                setup_full_context / "_bmad-output/implementation-artifacts/stories/1-1-test.md"
            ),
        }

        context_files = compiler._build_context_files(context, resolved)

        # Should include project context
        assert any("project" in k.lower() for k in context_files.keys())

        # Should include story file
        assert any("story" in k.lower() or "1-1" in k for k in context_files.keys())

        # Should include test files
        assert any("test" in k.lower() for k in context_files.keys())
