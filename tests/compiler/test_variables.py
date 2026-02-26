"""Tests for variable resolution engine.

Tests cover all acceptance criteria from Story 10.3:
- AC1: Variable resolution priority order
- AC2: Config source resolution ({config_source}:key)
- AC3: Path placeholder resolution ({project-root}, {installed_path})
- AC4: Story variable computation (story_id, story_key, date)
- AC5: Error handling for missing required variables
- AC6: Recursive variable resolution
- AC7: Variable pattern support
"""

import re
from pathlib import Path

import pytest

from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.compiler.variables import (
    MAX_RECURSION_DEPTH,
    _compute_story_variables,
    _extract_story_title,
    _load_external_config,
    _resolve_path_placeholders,
    _validate_config_path,
    resolve_variables,
)
from bmad_assist.core.exceptions import VariableError

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure."""
    # Create directories
    (tmp_path / "_bmad" / "bmm" / "workflows" / "test").mkdir(parents=True)
    (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

    # Create config file
    config_content = """
project_name: test-project
output_folder: '{project-root}/docs'
sprint_artifacts: '{project-root}/docs/sprint-artifacts'
user_name: TestUser
timeout: 300
"""
    (tmp_path / "_bmad" / "bmm" / "config.yaml").write_text(config_content)

    # Create workflow files
    workflow_dir = tmp_path / "_bmad" / "bmm" / "workflows" / "test"
    (workflow_dir / "workflow.yaml").write_text("""
name: test-workflow
config_source: "{project-root}/_bmad/bmm/config.yaml"
output_folder: "{config_source}:output_folder"
sprint_artifacts: "{config_source}:sprint_artifacts"
instructions: "{installed_path}/instructions.xml"
standalone: true
""")
    (workflow_dir / "instructions.xml").write_text("<workflow><step>Test</step></workflow>")

    return tmp_path


@pytest.fixture
def workflow_ir(tmp_project: Path) -> WorkflowIR:
    """Create a WorkflowIR for testing."""
    workflow_dir = tmp_project / "_bmad" / "bmm" / "workflows" / "test"
    return WorkflowIR(
        name="test-workflow",
        config_path=workflow_dir / "workflow.yaml",
        instructions_path=workflow_dir / "instructions.xml",
        template_path=None,
        validation_path=None,
        raw_config={
            "name": "test-workflow",
            "config_source": "{project-root}/_bmad/bmm/config.yaml",
            "output_folder": "{config_source}:output_folder",
            "sprint_artifacts": "{config_source}:sprint_artifacts",
            "instructions": "{installed_path}/instructions.xml",
            "standalone": True,
        },
        raw_instructions="<workflow><step>Test</step></workflow>",
    )


@pytest.fixture
def context(tmp_project: Path, workflow_ir: WorkflowIR) -> CompilerContext:
    """Create a CompilerContext for testing."""
    ctx = CompilerContext(
        project_root=tmp_project,
        output_folder=tmp_project / "docs",
    )
    ctx.workflow_ir = workflow_ir
    return ctx


# ==============================================================================
# AC1: Variable Resolution Priority Order
# ==============================================================================


class TestResolutionPriority:
    """Tests for variable resolution priority order (AC1)."""

    def test_invocation_params_override_config(self, context: CompilerContext) -> None:
        """Invocation params take priority over config values."""
        # Config has user_name: TestUser
        invocation_params = {"user_name": "OverrideUser"}

        resolved = resolve_variables(context, invocation_params)

        assert resolved["user_name"] == "OverrideUser"

    def test_invocation_params_override_computed(self, context: CompilerContext) -> None:
        """Invocation params take priority over computed values."""
        invocation_params = {
            "epic_num": 10,
            "story_num": 3,
            "story_id": "custom.id",  # Override computed
        }

        resolved = resolve_variables(context, invocation_params)

        assert resolved["story_id"] == "custom.id"

    def test_config_values_used_when_no_invocation(self, context: CompilerContext) -> None:
        """Config values used when not overridden by invocation params."""
        resolved = resolve_variables(context, {})

        # output_folder from config via {config_source}:output_folder
        assert "docs" in resolved["output_folder"]

    def test_computed_values_generated_from_params(self, context: CompilerContext) -> None:
        """Computed values generated from resolved parameters."""
        invocation_params = {"epic_num": 10, "story_num": 3}

        resolved = resolve_variables(context, invocation_params)

        assert resolved["story_id"] == "10.3"
        assert resolved["story_key"].startswith("10-3-")


# ==============================================================================
# AC2: Config Source Resolution ({config_source}:key Pattern)
# ==============================================================================


class TestConfigSourceResolution:
    """Tests for {config_source}:key pattern resolution (AC2)."""

    def test_config_source_key_resolution(self, context: CompilerContext) -> None:
        """Variables with {config_source}:key pattern resolve from external config."""
        resolved = resolve_variables(context, {})

        # output_folder should resolve through config_source
        assert str(context.project_root / "docs") == resolved["output_folder"]

    def test_config_values_available_after_resolution(self, context: CompilerContext) -> None:
        """Config values from config.yaml are available after resolution."""
        resolved = resolve_variables(context, {})

        # Values from config.yaml are merged directly
        assert "output_folder" in resolved
        assert "user_name" in resolved
        # config_source itself is not exposed (internal detail)
        assert "config_source" not in resolved

    def test_config_source_missing_file_raises_error(self, tmp_path: Path) -> None:
        """VariableError raised when config_source file doesn't exist."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(tmp_path / "nonexistent.yaml"),
                "value": "{config_source}:key",
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        assert "nonexistent.yaml" in str(exc_info.value)
        assert exc_info.value.variable_name == "config_source"

    def test_config_values_merged_directly(self, tmp_path: Path) -> None:
        """All config values are merged directly without {config_source}:key pattern."""
        # Create config with values that will be merged
        config_path = tmp_path / "config.yaml"
        config_path.write_text("user_name: Pawel\noutput_folder: /from/config\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(config_path),
                # Legacy pattern is now skipped
                "legacy_var": "{config_source}:some_key",
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # Config values are merged directly
        assert resolved["user_name"] == "Pawel"
        assert resolved["output_folder"] == "/from/config"
        # Legacy pattern is skipped, variable not set
        assert "legacy_var" not in resolved


# ==============================================================================
# AC3: Path Placeholder Resolution ({project-root}, {installed_path})
# ==============================================================================


class TestPathPlaceholderResolution:
    """Tests for path placeholder resolution (AC3)."""

    def test_project_root_placeholder_resolution(self, context: CompilerContext) -> None:
        """{project-root} is replaced with context.project_root."""
        resolved = resolve_variables(context, {})

        # output_folder contains resolved project root path
        assert str(context.project_root) in resolved["output_folder"]
        assert "{project-root}" not in resolved["output_folder"]

    def test_installed_path_placeholder_resolution(
        self, context: CompilerContext, workflow_ir: WorkflowIR
    ) -> None:
        """{installed_path} is replaced with workflow directory."""
        resolved = resolve_variables(context, {})

        # instructions contains {installed_path}
        workflow_dir = workflow_ir.config_path.parent
        assert str(workflow_dir) in resolved["instructions"]
        assert "{installed_path}" not in resolved["instructions"]

    def test_sprint_artifacts_resolved_from_config(self, context: CompilerContext) -> None:
        """{sprint_artifacts} is resolved from config, then substituted."""
        resolved = resolve_variables(context, {})

        expected = str(context.project_root / "docs" / "sprint-artifacts")
        assert resolved["sprint_artifacts"] == expected

    def test_multiple_placeholders_in_value(self, tmp_path: Path) -> None:
        """Multiple placeholders in same value are all resolved."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("base: '{project-root}/base'\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(config_path),
                "path": "{project-root}/a/{installed_path}/b",
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert "{project-root}" not in resolved["path"]
        assert "{installed_path}" not in resolved["path"]
        assert str(tmp_path) in resolved["path"]


# ==============================================================================
# AC4: Story Variable Computation
# ==============================================================================


class TestStoryVariableComputation:
    """Tests for story variable computation (AC4)."""

    def test_story_id_computed(self, context: CompilerContext) -> None:
        """story_id is computed from epic_num and story_num."""
        invocation_params = {"epic_num": 10, "story_num": 3}

        resolved = resolve_variables(context, invocation_params)

        assert resolved["story_id"] == "10.3"

    def test_story_key_computed(self, context: CompilerContext) -> None:
        """story_key is computed with story_title."""
        invocation_params = {
            "epic_num": 10,
            "story_num": 3,
            "story_title": "variable-resolution-engine",
        }

        resolved = resolve_variables(context, invocation_params)

        assert resolved["story_key"] == "10-3-variable-resolution-engine"

    def test_date_computed_in_iso_format(self, context: CompilerContext) -> None:
        """Date is computed in ISO format (YYYY-MM-DD)."""
        invocation_params = {"epic_num": 10, "story_num": 3}

        resolved = resolve_variables(context, invocation_params)

        assert re.match(r"\d{4}-\d{2}-\d{2}", resolved["date"])

    def test_story_title_extracted_from_sprint_status(self, tmp_path: Path) -> None:
        """story_title extracted from sprint-status.yaml when not provided."""
        # Create sprint-status.yaml
        sprint_status = tmp_path / "sprint-status.yaml"
        sprint_status.write_text("""
development_status:
  10-3-variable-resolution-engine: in-progress
""")

        # Create minimal workflow
        (tmp_path / "workflow.yaml").write_text("name: test\n")
        (tmp_path / "instructions.xml").write_text("<x/>")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"name": "test"},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        invocation_params = {"epic_num": 10, "story_num": 3}
        resolved = resolve_variables(context, invocation_params, sprint_status_path=sprint_status)

        assert resolved["story_title"] == "variable-resolution-engine"
        assert resolved["story_key"] == "10-3-variable-resolution-engine"

    def test_story_title_fallback_when_not_found(self, context: CompilerContext) -> None:
        """story_title defaults to 'story-{story_num}' when not found."""
        invocation_params = {"epic_num": 10, "story_num": 3}
        # No sprint_status_path provided

        resolved = resolve_variables(context, invocation_params)

        assert resolved["story_title"] == "story-3"
        assert resolved["story_key"] == "10-3-story-3"

    def test_deterministic_date_with_override(self, context: CompilerContext) -> None:
        """Date can be overridden for deterministic builds (NFR11)."""
        invocation_params = {
            "epic_num": 10,
            "story_num": 3,
            "date": "2025-01-15",
        }

        resolved = resolve_variables(context, invocation_params)

        assert resolved["date"] == "2025-01-15"


# ==============================================================================
# AC5: Error Handling for Missing Required Variables
# ==============================================================================


class TestMissingVariableErrors:
    """Tests for missing variable error handling (AC5)."""

    def test_legacy_config_source_pattern_skipped(self, tmp_path: Path) -> None:
        """Legacy {config_source}:key pattern is skipped without error."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "value": "{config_source}:some_key",
                # config_source NOT defined - but legacy pattern is just skipped
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        # No error raised - legacy pattern is skipped
        resolved = resolve_variables(context, {})
        assert "value" not in resolved

    def test_missing_config_file_raises_error(self, tmp_path: Path) -> None:
        """VariableError raised when config_source file doesn't exist."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(tmp_path / "nonexistent.yaml"),
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        assert exc_info.value.sources_checked  # Non-empty
        assert exc_info.value.suggestion  # Non-empty


# ==============================================================================
# AC6: Recursive Variable Resolution
# ==============================================================================


class TestRecursiveResolution:
    """Tests for recursive variable resolution (AC6)."""

    def test_recursive_variable_resolution(self, tmp_path: Path) -> None:
        """Variables that reference other variables are resolved recursively."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("base: /base\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(config_path),
                # Config values are merged directly, so 'base' is available
                "level2": "{base}/subdir",
                "level3": "{level2}/file.md",
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # 'base' comes from config.yaml (merged directly)
        assert resolved["base"] == "/base"
        assert resolved["level2"] == "/base/subdir"
        assert resolved["level3"] == "/base/subdir/file.md"

    def test_circular_reference_detected(self, tmp_path: Path) -> None:
        """VariableError raised for circular variable references."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "a": "{b}",
                "b": "{c}",
                "c": "{a}",  # Circular: a -> b -> c -> a
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        error_msg = str(exc_info.value).lower()
        assert "circular" in error_msg

    def test_max_recursion_depth_exceeded(self, tmp_path: Path) -> None:
        """VariableError raised when recursion depth exceeds limit."""
        # Create a chain of 15 variables (exceeds MAX_RECURSION_DEPTH=10)
        raw_config: dict[str, str] = {}
        for i in range(15):
            if i == 0:
                raw_config[f"var{i}"] = "base"
            else:
                raw_config[f"var{i}"] = f"{{var{i - 1}}}/level{i}"

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config=raw_config,
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        assert str(MAX_RECURSION_DEPTH) in str(exc_info.value)


# ==============================================================================
# AC7: Variable Pattern Support
# ==============================================================================


class TestVariablePatternSupport:
    """Tests for variable pattern support (AC7)."""

    def test_single_brace_variables_resolved(self, context: CompilerContext) -> None:
        """{variable} patterns are resolved."""
        invocation_params = {"epic_num": 10, "story_num": 3}

        resolved = resolve_variables(context, invocation_params)

        # output_folder is resolved (no placeholders remain)
        assert "{project-root}" not in resolved["output_folder"]
        assert str(context.project_root) in resolved["output_folder"]

    def test_double_brace_variables_resolved(self, tmp_path: Path) -> None:
        """{{variable}} patterns are also resolved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"template": "Story {{epic_num}}.{{story_num}}"},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {"epic_num": 10, "story_num": 3})

        assert resolved["template"] == "Story 10.3"

    def test_unrecognized_patterns_preserved(self, tmp_path: Path) -> None:
        """Unknown patterns like {unknown_var} are left as-is (no error)."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"unknown": "Value with {unknown_pattern} here"},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # Unknown pattern preserved
        assert "{unknown_pattern}" in resolved["unknown"]

    def test_mixed_patterns_in_same_value(self, tmp_path: Path) -> None:
        """Mixed known and unknown patterns in same value."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "mixed": "{project-root}/{{epic_num}}/{future_var}",
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {"epic_num": 10})

        assert str(tmp_path) in resolved["mixed"]
        assert "10" in resolved["mixed"]
        assert "{future_var}" in resolved["mixed"]


# ==============================================================================
# Additional Tests from Master Synthesis
# ==============================================================================


class TestSecurityValidation:
    """Tests for security validation (path traversal, etc.)."""

    def test_config_source_path_traversal_blocked(self, tmp_path: Path) -> None:
        """VariableError raised when config_source tries to escape project_root."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "config_source": str(tmp_path / ".." / ".." / "etc" / "passwd"),
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        error_msg = str(exc_info.value).lower()
        assert "outside" in error_msg or "project root" in error_msg


class TestNonStringValuePreservation:
    """Tests for non-string value preservation."""

    def test_boolean_values_preserved(self, tmp_path: Path) -> None:
        """Boolean values in raw_config are preserved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"enabled": True, "debug_mode": False},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["enabled"] is True
        assert resolved["debug_mode"] is False

    def test_integer_values_preserved(self, tmp_path: Path) -> None:
        """Integer values in raw_config are preserved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"timeout": 300},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["timeout"] == 300
        assert isinstance(resolved["timeout"], int)

    def test_list_values_preserved(self, tmp_path: Path) -> None:
        """List values in raw_config are preserved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"steps": ["a", "b", "c"]},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["steps"] == ["a", "b", "c"]

    def test_dict_values_preserved(self, tmp_path: Path) -> None:
        """Dict values in raw_config are preserved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"metadata": {"key": "value", "num": 42}},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["metadata"] == {"key": "value", "num": 42}


class TestContextUpdates:
    """Tests for context updates."""

    def test_resolved_variables_stored_in_context(self, context: CompilerContext) -> None:
        """Resolved variables are stored in context.resolved_variables."""
        invocation_params = {"epic_num": 10, "story_num": 3}

        resolved = resolve_variables(context, invocation_params)

        assert context.resolved_variables == resolved
        assert "story_id" in context.resolved_variables

    def test_workflow_ir_required(self, tmp_path: Path) -> None:
        """VariableError raised when workflow_ir not set."""
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        # workflow_ir NOT set

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        assert "workflow_ir" in str(exc_info.value)


# ==============================================================================
# Unit Tests for Helper Functions
# ==============================================================================


class TestHelperFunctions:
    """Unit tests for internal helper functions."""

    def test_compute_story_variables_basic(self) -> None:
        """_compute_story_variables generates correct values."""
        result = _compute_story_variables(
            epic_num=10,
            story_num=3,
            sprint_status_path=None,
            story_title_override="test-title",
            date_override="2025-01-15",
        )

        assert result["story_id"] == "10.3"
        assert result["story_title"] == "test-title"
        assert result["story_key"] == "10-3-test-title"
        assert result["date"] == "2025-01-15"

    def test_extract_story_title_found(self, tmp_path: Path) -> None:
        """_extract_story_title finds title in sprint-status."""
        sprint_status = tmp_path / "sprint-status.yaml"
        sprint_status.write_text("""
development_status:
  10-3-my-title: in-progress
""")

        result = _extract_story_title(sprint_status, 10, 3)

        assert result == "my-title"

    def test_extract_story_title_not_found(self, tmp_path: Path) -> None:
        """_extract_story_title returns None when not found."""
        sprint_status = tmp_path / "sprint-status.yaml"
        sprint_status.write_text("""
development_status:
  10-1-other: done
""")

        result = _extract_story_title(sprint_status, 10, 3)

        assert result is None

    def test_extract_story_title_file_not_exists(self, tmp_path: Path) -> None:
        """_extract_story_title returns None for missing file."""
        result = _extract_story_title(tmp_path / "missing.yaml", 10, 3)

        assert result is None

    def test_load_external_config_valid(self, tmp_path: Path) -> None:
        """_load_external_config loads valid YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("key: value\nnum: 42\n")

        result = _load_external_config(config_path)

        assert result == {"key": "value", "num": 42}

    def test_load_external_config_empty(self, tmp_path: Path) -> None:
        """_load_external_config returns empty dict for empty file."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        result = _load_external_config(config_path)

        assert result == {}

    def test_load_external_config_invalid_yaml(self, tmp_path: Path) -> None:
        """_load_external_config raises VariableError for invalid YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("invalid: yaml: syntax: here:")

        with pytest.raises(VariableError):
            _load_external_config(config_path)

    def test_resolve_path_placeholders_both(self, tmp_path: Path) -> None:
        """_resolve_path_placeholders resolves both placeholders."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflows" / "test" / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = _resolve_path_placeholders(
            "{project-root}/a/{installed_path}/b",
            context,
            workflow_ir,
        )

        assert str(tmp_path) in result
        assert "{project-root}" not in result
        assert "{installed_path}" not in result

    def test_validate_config_path_valid(self, tmp_path: Path) -> None:
        """_validate_config_path passes for valid path."""
        config_path = tmp_path / "config.yaml"
        config_path.touch()

        # Should not raise
        _validate_config_path(config_path, tmp_path)

    def test_validate_config_path_traversal(self, tmp_path: Path) -> None:
        """_validate_config_path raises for path traversal."""
        config_path = tmp_path / ".." / ".." / "etc" / "passwd"

        with pytest.raises(VariableError):
            _validate_config_path(config_path, tmp_path)

    def test_validate_config_path_sibling_directory(self, tmp_path: Path) -> None:
        """_validate_config_path blocks sibling directories with similar prefix.

        Regression test for CVE-like bug where /project/root2 would pass
        validation when project_root is /project/root using startswith().
        The fix uses is_relative_to() which correctly blocks this.
        """
        # Create a sibling directory that shares prefix with project root
        project_root = tmp_path / "project"
        project_root.mkdir()

        sibling_dir = tmp_path / "project2"
        sibling_dir.mkdir()

        sibling_config = sibling_dir / "config.yaml"
        sibling_config.touch()

        # This should be blocked - sibling_config is NOT under project_root
        with pytest.raises(VariableError) as exc_info:
            _validate_config_path(sibling_config, project_root)

        error_msg = str(exc_info.value).lower()
        assert "security" in error_msg or "outside" in error_msg


# ==============================================================================
# Edge Case Tests
# ==============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_workflow_config(self, tmp_path: Path) -> None:
        """Empty workflow config returns invocation params + computed."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},  # Empty
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {"epic_num": 1, "story_num": 1})

        assert resolved["epic_num"] == 1
        assert resolved["story_id"] == "1.1"

    def test_unicode_in_variable_values(self, tmp_path: Path) -> None:
        """Unicode in variable values is preserved."""
        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"greeting": "Cześć! 你好! 👋"},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["greeting"] == "Cześć! 你好! 👋"

    def test_none_value_in_invocation_params(self, context: CompilerContext) -> None:
        """None values in invocation params are handled."""
        invocation_params = {"epic_num": 10, "story_num": 3, "optional": None}

        resolved = resolve_variables(context, invocation_params)

        assert resolved["optional"] is None


# ==============================================================================
# Sprint Status Resolution Tests
# ==============================================================================


class TestSprintStatusResolution:
    """Tests for sprint_status variable resolution."""

    def test_sprint_status_in_docs(self, tmp_path: Path) -> None:
        """sprint_status resolves to docs/sprint-status.yaml when it exists."""
        # Create project structure
        (tmp_path / "docs").mkdir()
        sprint_status = tmp_path / "docs" / "sprint-status.yaml"
        sprint_status.write_text("status: active\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["sprint_status"] == str(sprint_status)

    def test_sprint_status_in_sprint_artifacts(self, tmp_path: Path) -> None:
        """sprint_status resolves to docs/sprint-artifacts/sprint-status.yaml."""
        # Create project structure
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)
        sprint_status = tmp_path / "docs" / "sprint-artifacts" / "sprint-status.yaml"
        sprint_status.write_text("status: active\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["sprint_status"] == str(sprint_status)

    def test_sprint_status_none_when_missing(self, tmp_path: Path) -> None:
        """sprint_status is 'none' when file doesn't exist in either location."""
        # Create empty docs structure - no sprint-status.yaml
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        assert resolved["sprint_status"] == "none"

    def test_sprint_status_priority_when_both_exist(self, tmp_path: Path) -> None:
        """sprint_status uses priority order when file exists in multiple locations."""
        # Create project structure with both files
        (tmp_path / "docs" / "sprint-artifacts").mkdir(parents=True)
        docs_file = tmp_path / "docs" / "sprint-status.yaml"
        artifacts_file = tmp_path / "docs" / "sprint-artifacts" / "sprint-status.yaml"
        docs_file.write_text("status: docs\n")
        artifacts_file.write_text("status: artifacts\n")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        # Should use first found by priority (docs/sprint-status.yaml)
        resolved = resolve_variables(context, {})
        assert resolved["sprint_status"] == str(docs_file)


# ==============================================================================
# Token Estimation Tests
# ==============================================================================


class TestTokenEstimation:
    """Tests for token estimation in attributed variables."""

    def test_estimate_tokens_basic(self, tmp_path: Path) -> None:
        """_estimate_tokens calculates chars / 4."""
        from bmad_assist.compiler.variables import _estimate_tokens

        # 400 characters = 100 tokens
        test_file = tmp_path / "test.md"
        test_file.write_text("x" * 400)

        result = _estimate_tokens(test_file)

        assert result == 100

    def test_estimate_tokens_missing_file(self, tmp_path: Path) -> None:
        """_estimate_tokens returns None for missing file."""
        from bmad_assist.compiler.variables import _estimate_tokens

        result = _estimate_tokens(tmp_path / "missing.md")

        assert result is None

    def test_input_file_patterns_includes_token_approx(self, tmp_path: Path) -> None:
        """input_file_patterns resolution adds token_approx attribute."""
        # Create project structure with a file
        (tmp_path / "docs").mkdir()
        arch_file = tmp_path / "docs" / "architecture.md"
        arch_file.write_text("# Architecture\n" + "content " * 100)  # ~800 chars

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "input_file_patterns": {
                    "architecture": {
                        "description": "Architecture docs",
                        "load_strategy": "FULL_LOAD",
                        "whole": str(tmp_path / "docs" / "*architecture*.md"),
                    }
                }
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # Should have architecture_file with token_approx
        arch_var = resolved.get("architecture_file")
        assert arch_var is not None
        assert "_token_approx" in arch_var
        # ~800 chars / 4 = ~200 tokens
        assert int(arch_var["_token_approx"]) > 100


# ==============================================================================
# Sharded Epics Resolution Tests
# ==============================================================================


class TestShardedEpicsResolution:
    """Tests for sharded epics_file resolution with epic_num context."""

    def test_sharded_epics_resolves_to_specific_epic_file(self, tmp_path: Path) -> None:
        """When epics is sharded and epic_num is set, resolve to epic-{num}-*.md."""
        # Create sharded epics structure
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "index.md").write_text("# Epic Index")
        (epics_dir / "epic-5-auth.md").write_text("# Epic 5")
        (epics_dir / "epic-6-loop.md").write_text("# Epic 6: Main Loop")
        (epics_dir / "epic-7-reporting.md").write_text("# Epic 7")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "input_file_patterns": {
                    "epics": {
                        "description": "Epic files",
                        "load_strategy": "FULL_LOAD",
                        "sharded": str(epics_dir / "*.md"),
                        "whole": str(tmp_path / "docs" / "epics.md"),
                    }
                }
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        # With epic_num=6, should resolve to epic-6-loop.md
        resolved = resolve_variables(context, {"epic_num": 6, "story_num": 3})

        epics_var = resolved.get("epics_file")
        assert epics_var is not None
        assert "_value" in epics_var
        assert "epic-6-loop.md" in epics_var["_value"]
        assert epics_var.get("_sharded") == "true"

    def test_sharded_epics_falls_back_to_index_without_epic_num(self, tmp_path: Path) -> None:
        """Without epic_num, sharded epics falls back to index.md."""
        # Create sharded epics structure
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "index.md").write_text("# Epic Index")
        (epics_dir / "epic-6-loop.md").write_text("# Epic 6")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "input_file_patterns": {
                    "epics": {
                        "description": "Epic files",
                        "load_strategy": "FULL_LOAD",
                        "sharded": str(epics_dir / "*.md"),
                    }
                }
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        # Without epic_num, should fall back to index.md
        resolved = resolve_variables(context, {})

        epics_var = resolved.get("epics_file")
        assert epics_var is not None
        assert "index.md" in epics_var["_value"]

    def test_sharded_epics_falls_back_to_index_when_epic_not_found(self, tmp_path: Path) -> None:
        """When epic_num doesn't match any file, fall back to index.md."""
        # Create sharded epics structure without epic-99
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "index.md").write_text("# Epic Index")
        (epics_dir / "epic-6-loop.md").write_text("# Epic 6")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={
                "input_file_patterns": {
                    "epics": {
                        "description": "Epic files",
                        "load_strategy": "FULL_LOAD",
                        "sharded": str(epics_dir / "*.md"),
                    }
                }
            },
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        # epic_num=99 doesn't exist, should fall back to index.md
        resolved = resolve_variables(context, {"epic_num": 99})

        epics_var = resolved.get("epics_file")
        assert epics_var is not None
        assert "index.md" in epics_var["_value"]


# ==============================================================================
# Project Context Resolution Tests
# ==============================================================================


class TestProjectContextResolution:
    """Tests for project_context variable resolution."""

    def test_project_context_hyphen_file(self, tmp_path: Path) -> None:
        """project_context resolves to project-context.md when it exists."""
        # Create project structure
        (tmp_path / "docs").mkdir()
        ctx_file = tmp_path / "docs" / "project-context.md"
        ctx_file.write_text("# Project Context\n" + "content " * 50)

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # Should have attributed variable
        ctx_var = resolved.get("project_context")
        assert isinstance(ctx_var, dict)
        assert ctx_var["_value"] == str(ctx_file)
        assert "_token_approx" in ctx_var

    def test_project_context_underscore_file(self, tmp_path: Path) -> None:
        """project_context resolves to project_context.md when only it exists."""
        # Create project structure
        (tmp_path / "docs").mkdir()
        ctx_file = tmp_path / "docs" / "project_context.md"
        ctx_file.write_text("# Project Context\n" + "content " * 50)

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        ctx_var = resolved.get("project_context")
        assert isinstance(ctx_var, dict)
        assert ctx_var["_value"] == str(ctx_file)

    def test_project_context_both_same_size_prefers_hyphen(self, tmp_path: Path) -> None:
        """project_context uses project-context.md when both exist with same size."""
        # Create project structure with both files (same content = same size)
        (tmp_path / "docs").mkdir()
        content = "# Project Context\nSame content"
        (tmp_path / "docs" / "project_context.md").write_text(content)
        hyphen_file = tmp_path / "docs" / "project-context.md"
        hyphen_file.write_text(content)

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        ctx_var = resolved.get("project_context")
        assert isinstance(ctx_var, dict)
        # Should prefer project-context.md
        assert ctx_var["_value"] == str(hyphen_file)

    def test_project_context_both_different_size_error(self, tmp_path: Path) -> None:
        """project_context raises error when both files exist with different sizes."""
        # Create project structure with both files (different content = different size)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "project_context.md").write_text("Short content")
        (tmp_path / "docs" / "project-context.md").write_text("Much longer content that differs")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        with pytest.raises(VariableError) as exc_info:
            resolve_variables(context, {})

        error_msg = str(exc_info.value).lower()
        assert "ambiguous" in error_msg
        assert "project" in error_msg

    def test_project_context_none_when_missing(self, tmp_path: Path) -> None:
        """project_context has default path when no file exists."""
        # Create empty docs structure
        (tmp_path / "docs").mkdir()

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        # Should return attributed var with default path instead of "none"
        assert isinstance(resolved["project_context"], dict)
        assert "_value" in resolved["project_context"]
        assert "project-context.md" in resolved["project_context"]["_value"]

    def test_project_context_symlink_prefers_hyphen(self, tmp_path: Path) -> None:
        """project_context uses project-context.md when underscore is symlink."""
        import os

        # Create project structure with symlink
        (tmp_path / "docs").mkdir()
        hyphen_file = tmp_path / "docs" / "project-context.md"
        hyphen_file.write_text("# Project Context\nActual content")
        underscore_file = tmp_path / "docs" / "project_context.md"

        # Create symlink (skip on Windows if not supported)
        try:
            os.symlink(hyphen_file, underscore_file)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        workflow_ir = WorkflowIR(
            name="test",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={"output_folder": str(tmp_path / "docs")},
            raw_instructions="<x/>",
        )
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path / "docs",
        )
        context.workflow_ir = workflow_ir

        resolved = resolve_variables(context, {})

        ctx_var = resolved.get("project_context")
        assert isinstance(ctx_var, dict)
        # Should prefer project-context.md
        assert ctx_var["_value"] == str(hyphen_file)
