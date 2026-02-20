"""Tests for TEAVariableResolver.

Tests the centralized TEA variable resolution including:
- Universal variable resolution
- Workflow-specific variable resolution
- Caching behavior
- Integration with existing tea.py resolution
"""

from pathlib import Path

from tests.testarch.core.conftest import MockCompilerContext


class TestTEAVariableResolver:
    """Tests for TEAVariableResolver class."""

    def test_resolve_all_returns_dict(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return a dictionary of resolved variables."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert isinstance(result, dict)

    def test_resolve_all_includes_project_root(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include project-root variable."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "project-root" in result
        assert result["project-root"] == str(mock_context.project_root)

    def test_resolve_all_includes_test_dir(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include test_dir variable with default value."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "test_dir" in result
        assert result["test_dir"] == "tests/"

    def test_resolve_all_includes_tea_flags(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include TEA feature flags."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "tea_use_playwright_utils" in result
        assert "tea_use_mcp_enhancements" in result
        # Defaults should be True
        assert result["tea_use_playwright_utils"] is True
        assert result["tea_use_mcp_enhancements"] is True

    def test_resolve_all_includes_config_source(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include config_source variable."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "config_source" in result
        assert result["config_source"] == "bmad-assist.yaml"

    def test_resolve_all_includes_implementation_artifacts(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include implementation_artifacts variable."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "implementation_artifacts" in result
        assert result["implementation_artifacts"] == str(mock_context.output_folder)


class TestTEAVariableResolverWorkflowSpecific:
    """Tests for workflow-specific variable resolution."""

    def test_review_scope_for_test_review(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should resolve review_scope for testarch-test-review workflow."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-test-review")

        assert "review_scope" in result
        assert result["review_scope"] == "suite"  # Default

    def test_ci_platform_for_ci_workflow(
        self, mock_context: MockCompilerContext, github_ci_project: Path
    ) -> None:
        """Should resolve ci_platform for testarch-ci workflow."""
        from bmad_assist.testarch.core import TEAVariableResolver

        # Use GitHub CI project as project root
        mock_context.project_root = github_ci_project

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-ci")

        assert "ci_platform" in result
        assert result["ci_platform"] == "github"

    def test_story_file_for_atdd(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include story_file for testarch-atdd workflow."""
        from bmad_assist.testarch.core import TEAVariableResolver

        mock_context.resolved_variables["story_file"] = "/path/to/story.md"

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "story_file" in result
        assert result["story_file"] == "/path/to/story.md"

    def test_story_file_for_trace(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should include story_file for testarch-trace workflow."""
        from bmad_assist.testarch.core import TEAVariableResolver

        mock_context.resolved_variables["story_file"] = "/path/to/story.md"

        resolver = TEAVariableResolver()
        result = resolver.resolve_all(mock_context, "testarch-trace")

        assert "story_file" in result
        assert result["story_file"] == "/path/to/story.md"


class TestTEAVariableResolverCaching:
    """Tests for caching behavior."""

    def test_cache_returns_copy(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return a copy of cached values, not the original."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()

        # First call
        result1 = resolver.resolve_all(mock_context, "testarch-atdd")

        # Modify the result
        result1["custom_key"] = "modified"

        # Second call (should return clean copy)
        result2 = resolver.resolve_all(mock_context, "testarch-atdd")

        assert "custom_key" not in result2

    def test_clear_cache(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should clear cache when clear_cache() is called."""
        from bmad_assist.testarch.core import TEAVariableResolver

        resolver = TEAVariableResolver()

        # First call to populate cache
        resolver.resolve_all(mock_context, "testarch-atdd")

        # Clear cache
        resolver.clear_cache()

        # Verify cache is empty (internal check)
        assert len(resolver._cache) == 0


class TestIsTeaWorkflow:
    """Tests for is_tea_workflow() helper."""

    def test_testarch_prefix(self) -> None:
        """Should return True for testarch-* workflows."""
        from bmad_assist.testarch.core.variables import is_tea_workflow

        assert is_tea_workflow("testarch-atdd") is True
        assert is_tea_workflow("testarch-test-review") is True
        assert is_tea_workflow("testarch-ci") is True
        assert is_tea_workflow("testarch-framework") is True

    def test_non_tea_workflows(self) -> None:
        """Should return False for non-TEA workflows."""
        from bmad_assist.testarch.core.variables import is_tea_workflow

        assert is_tea_workflow("dev-story") is False
        assert is_tea_workflow("create-story") is False
        assert is_tea_workflow("code-review") is False

    def test_empty_and_none(self) -> None:
        """Should return False for empty string or None-like."""
        from bmad_assist.testarch.core.variables import is_tea_workflow

        assert is_tea_workflow("") is False
        assert is_tea_workflow(None) is False  # type: ignore


class TestCoreVariableResolutionIntegration:
    """Tests for TEA integration in compiler/variables/core.py."""

    def test_tea_variables_resolved_for_testarch_workflow(
        self, tmp_path: Path
    ) -> None:
        """Should resolve TEA variables when workflow is testarch-*."""
        from bmad_assist.compiler.types import CompilerContext, WorkflowIR
        from bmad_assist.compiler.variables.core import resolve_variables

        # Create minimal workflow IR with testarch workflow name
        workflow_ir = WorkflowIR(
            name="testarch-atdd",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"name": "testarch-atdd"},
            raw_instructions="<workflow/>",
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # TEA variables should be present
        assert "test_dir" in resolved
        assert "config_source" in resolved
        assert "tea_use_playwright_utils" in resolved
        assert "tea_use_mcp_enhancements" in resolved

    def test_tea_variables_not_resolved_for_non_tea_workflow(
        self, tmp_path: Path
    ) -> None:
        """Should NOT resolve TEA variables for non-TEA workflows."""
        from bmad_assist.compiler.types import CompilerContext, WorkflowIR
        from bmad_assist.compiler.variables.core import resolve_variables

        # Create workflow IR with non-TEA workflow name
        workflow_ir = WorkflowIR(
            name="dev-story",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"name": "dev-story"},
            raw_instructions="<workflow/>",
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "_bmad-output",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # TEA-specific variables should NOT be present
        # (unless they were set from other sources)
        # test_dir is TEA-specific, should not be set
        # Note: config_source and communication_language are set by other steps
        assert "review_scope" not in resolved
        assert "ci_platform" not in resolved
