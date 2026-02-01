"""Tests for the validate-story-synthesis workflow compiler.

Tests the ValidateStorySynthesisCompiler class which produces
synthesis prompts containing only story file and anonymized validations.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bmad_assist.compiler.parser import parse_workflow
from bmad_assist.compiler.types import CompiledWorkflow, CompilerContext
from bmad_assist.core.exceptions import CompilerError
from bmad_assist.validation.anonymizer import AnonymizedValidation


@pytest.fixture
def sample_anonymized_validations() -> list[AnonymizedValidation]:
    """Create sample anonymized validations for testing."""
    return [
        AnonymizedValidation(
            validator_id="Validator A",
            content="## Issues\n\n1. Missing error handling",
            original_ref="uuid-1",
        ),
        AnonymizedValidation(
            validator_id="Validator B",
            content="## Analysis\n\nThe story has gaps",
            original_ref="uuid-2",
        ),
        AnonymizedValidation(
            validator_id="Validator C",
            content="## Review\n\nGood overall, minor issues",
            original_ref="uuid-3",
        ),
        AnonymizedValidation(
            validator_id="Validator D",
            content="## Findings\n\nNo major problems found",
            original_ref="uuid-4",
        ),
    ]


@pytest.fixture
def two_validations() -> list[AnonymizedValidation]:
    """Create minimum required validations (2)."""
    return [
        AnonymizedValidation(
            validator_id="Validator A",
            content="## Issues\n\nFirst validator findings",
            original_ref="uuid-1",
        ),
        AnonymizedValidation(
            validator_id="Validator B",
            content="## Issues\n\nSecond validator findings",
            original_ref="uuid-2",
        ),
    ]


@pytest.fixture
def story_file_content() -> str:
    """Create sample story file content."""
    return """# Story 11.1: Test Story

Status: ready-for-dev

## Story

As a developer,
I want a test story,
So that I can test synthesis.

## Acceptance Criteria

1. AC1: Basic functionality works
"""


@pytest.fixture
def tmp_project(tmp_path: Path, story_file_content: str) -> Path:
    """Create a temporary project structure for testing."""
    docs = tmp_path / "docs"
    docs.mkdir()

    sprint_artifacts = docs / "sprint-artifacts"
    sprint_artifacts.mkdir()

    # Create default story file
    default_story = sprint_artifacts / "11-1-test-story.md"
    default_story.write_text(story_file_content)

    # Create workflow directory for synthesis
    workflow_dir = (
        tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "validate-story-synthesis"
    )
    workflow_dir.mkdir(parents=True)

    workflow_yaml = workflow_dir / "workflow.yaml"
    workflow_yaml.write_text("""name: validate-story-synthesis
description: "Synthesize validator findings for story validation."
config_source: "{project-root}/_bmad/bmm/config.yaml"
template: false
instructions: "{installed_path}/instructions.xml"
""")

    instructions_xml = workflow_dir / "instructions.xml"
    instructions_xml.write_text("""<workflow>
  <critical>YOU ARE THE MASTER SYNTHESIS AGENT</critical>
  <step n="1" goal="Analyze validator findings">
    <action>Review all validator outputs</action>
    <action>Identify consensus and disagreements</action>
  </step>
  <step n="2" goal="Synthesize findings">
    <action>Prioritize issues by severity</action>
    <action>Identify false positives</action>
  </step>
  <step n="3" goal="Apply changes">
    <action>Modify story file with verified fixes</action>
  </step>
</workflow>
""")

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

    return tmp_path


def create_test_context(
    project: Path,
    epic_num: int = 11,
    story_num: int = 1,
    validations: list[AnonymizedValidation] | None = None,
    session_id: str = "test-session-123",
    **extra_vars: Any,
) -> CompilerContext:
    """Create a CompilerContext for testing.

    Pre-loads workflow_ir from the workflow directory (normally done by core.compile_workflow).
    """
    resolved_vars = {
        "epic_num": epic_num,
        "story_num": story_num,
        "anonymized_validations": validations or [],
        "session_id": session_id,
        **extra_vars,
    }
    workflow_dir = (
        project / "_bmad" / "bmm" / "workflows" / "4-implementation" / "validate-story-synthesis"
    )
    workflow_ir = parse_workflow(workflow_dir) if workflow_dir.exists() else None
    return CompilerContext(
        project_root=project,
        output_folder=project / "docs",
        resolved_variables=resolved_vars,
        workflow_ir=workflow_ir,
    )


class TestValidateStorySynthesisCompiler:
    """Tests for ValidateStorySynthesisCompiler."""

    def test_workflow_name_property(self) -> None:
        """Workflow name is 'validate-story-synthesis'."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        compiler = ValidateStorySynthesisCompiler()
        assert compiler.workflow_name == "validate-story-synthesis"

    def test_compile_basic_four_validators(
        self,
        tmp_project: Path,
        sample_anonymized_validations: list[AnonymizedValidation],
    ) -> None:
        """Basic compilation with 4 validators produces valid output."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_anonymized_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "validate-story-synthesis"
        assert result.token_estimate > 0
        # All 4 validators should be in context
        assert "Validator A" in result.context
        assert "Validator B" in result.context
        assert "Validator C" in result.context
        assert "Validator D" in result.context

    def test_compile_two_validators_minimum(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Minimum 2 validators compiles successfully."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"
        assert "Validator A" in result.context
        assert "Validator B" in result.context


class TestSynthesisContext:
    """Tests for synthesis context building."""

    def test_context_includes_project_context(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """project_context.md IS included in synthesis context (ground truth)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create project_context.md - SHOULD be included as ground truth
        pc_content = "# Project Context\n\nProject rules and patterns..."
        (tmp_project / "docs" / "project_context.md").write_text(pc_content)

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # project_context content SHOULD be in output (ground truth for evaluating validator claims)
        assert "Project Context" in result.context or "project_context" in result.context.lower()

    def test_context_excludes_prd_files(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """PRD files are NOT included in synthesis context."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create PRD file - should NOT be included
        (tmp_project / "docs" / "prd.md").write_text("# PRD\n\n## Requirements...")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Check that prd.md file is NOT in context
        # Use filename check instead of substring to avoid pytest temp dir name issues
        root = ET.fromstring(result.context)
        context_elem = root.find("context")
        if context_elem is not None:
            file_elements = context_elem.findall(".//file")
            paths = [f.get("path", "") for f in file_elements]
            filenames = [Path(p).name for p in paths if p]
            assert "prd.md" not in filenames, (
                f"prd.md should not be in context, found files: {filenames}"
            )

    def test_context_excludes_architecture_files_by_default(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """architecture.md is NOT included in synthesis context by default.

        Synthesis workflows need minimal context since they aggregate validator outputs.
        Architecture was removed per Strategic Context Optimization (tech-spec).
        """
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create architecture file - should NOT be included by default
        (tmp_project / "docs" / "architecture.md").write_text("# Architecture\n\n## Patterns...")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Check that architecture.md file is NOT in context (optimized behavior)
        root = ET.fromstring(result.context)
        context_elem = root.find("context")
        if context_elem is not None:
            file_elements = context_elem.findall(".//file")
            paths = [f.get("path", "") for f in file_elements]
            filenames = [Path(p).name for p in paths if p]
            assert "architecture.md" not in filenames, (
                f"architecture.md should NOT be in context by default, found: {filenames}"
            )

    def test_context_excludes_epic_doc_files(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Epic files are NOT included in synthesis context."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create epic file - should NOT be included
        epics_dir = tmp_project / "docs" / "epics"
        epics_dir.mkdir(exist_ok=True)
        (epics_dir / "epic-11-validation.md").write_text("# Epic 11\n\n## Stories...")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Check that epic-11-validation.md file is NOT in context
        root = ET.fromstring(result.context)
        context_elem = root.find("context")
        if context_elem is not None:
            file_elements = context_elem.findall(".//file")
            paths = [f.get("path", "") for f in file_elements]
            filenames = [Path(p).name for p in paths if p]
            epic_files = [f for f in filenames if f.startswith("epic-")]
            assert not epic_files, f"Epic files should not be in context, found: {epic_files}"

    def test_context_includes_story_file(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Story file being validated IS included."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Story file should be in context
        root = ET.fromstring(result.context)
        context_elem = root.find("context")
        assert context_elem is not None
        file_elements = context_elem.findall(".//file")
        paths = [f.get("path", "") for f in file_elements]
        assert any("11-1" in p for p in paths), "Story file should be in context"

    def test_context_includes_validations(
        self,
        tmp_project: Path,
        sample_anonymized_validations: list[AnonymizedValidation],
    ) -> None:
        """Anonymized validations ARE included."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_anonymized_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # All validation content should be present
        assert "Missing error handling" in result.context
        assert "The story has gaps" in result.context
        assert "Good overall, minor issues" in result.context
        assert "No major problems found" in result.context

    def test_validations_sorted_alphabetically(
        self,
        tmp_project: Path,
    ) -> None:
        """Validations appear in order: Validator A, B, C, D."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create unsorted validations
        unsorted_validations = [
            AnonymizedValidation(
                validator_id="Validator D",
                content="Fourth content",
                original_ref="uuid-4",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Second content",
                original_ref="uuid-2",
            ),
            AnonymizedValidation(
                validator_id="Validator A",
                content="First content",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Validator C",
                content="Third content",
                original_ref="uuid-3",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=unsorted_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Find positions of each validator in output
        idx_a = result.context.find("Validator A")
        idx_b = result.context.find("Validator B")
        idx_c = result.context.find("Validator C")
        idx_d = result.context.find("Validator D")

        assert idx_a >= 0, "Validator A should be in output"
        assert idx_b >= 0, "Validator B should be in output"
        assert idx_c >= 0, "Validator C should be in output"
        assert idx_d >= 0, "Validator D should be in output"

        # Should be in alphabetical order
        assert idx_a < idx_b < idx_c < idx_d, "Validators should be sorted alphabetically"

    def test_cdata_escaping(
        self,
        tmp_project: Path,
    ) -> None:
        """Validation content with ]]> is properly escaped in CDATA."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create validation with CDATA-breaking sequence
        validations_with_cdata = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Code example: data[index]]>some text",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Normal content without special chars",
                original_ref="uuid-2",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=validations_with_cdata,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Result should be valid XML (would throw if CDATA not escaped)
        root = ET.fromstring(result.context)
        assert root is not None

        # The escaped sequence should be in the output
        # ]]> becomes ]]]]><![CDATA[>
        assert "]]]]><![CDATA[>" in result.context or "data[index]" in result.context


class TestSynthesisValidation:
    """Tests for input validation."""

    def test_fails_with_zero_validations(
        self,
        tmp_project: Path,
    ) -> None:
        """Fails with CompilerError when no validations provided."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=[],  # Empty list
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)no.*validation|validation.*required"):
            compiler.compile(context)

    def test_fails_with_one_validation(
        self,
        tmp_project: Path,
    ) -> None:
        """Fails with CompilerError when only 1 validation provided."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        single_validation = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Single validation",
                original_ref="uuid-1",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=single_validation,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)minimum|at least 2|fewer than 2"):
            compiler.compile(context)

    def test_fails_without_epic_num(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when epic_num not provided."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=None,  # type: ignore
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.compile(context)

    def test_fails_without_story_num(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when story_num not provided."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=None,  # type: ignore
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="story_num"):
            compiler.compile(context)

    def test_fails_story_not_found(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when story file doesn't exist."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=99,  # Non-existent story
            story_num=99,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)story.*not found"):
            compiler.compile(context)

    def test_error_includes_suggestion(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Error messages include actionable suggestions."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=None,  # type: ignore
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError) as exc_info:
            compiler.compile(context)

        error_msg = str(exc_info.value).lower()
        assert "suggestion" in error_msg or "provide" in error_msg or "required" in error_msg


class TestSynthesisMission:
    """Tests for mission generation."""

    def test_mission_includes_story_id(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission includes epic_num.story_num."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert "11.1" in result.mission

    def test_mission_includes_validator_count(
        self,
        tmp_project: Path,
        sample_anonymized_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission mentions number of validators."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_anonymized_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # 4 validators
        assert "4" in result.mission

    def test_mission_grants_write_permission(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission grants permission to modify story file."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        mission_lower = result.mission.lower()
        has_write_permission = (
            "write" in mission_lower or "modify" in mission_lower or "permission" in mission_lower
        )
        assert has_write_permission


class TestSynthesisPatch:
    """Tests for patch integration."""

    def test_compiles_without_patch(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Compilation succeeds when no patch file exists."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Ensure no patch exists
        fake_home = tmp_project / "fake_home_no_patch"
        fake_home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"

    def test_applies_patch_post_process(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Applies patch post_process rules when patch exists."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create patch with post_process
        patch_dir = tmp_project / "_bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "validate-story-synthesis.patch.yaml"
        patch_file.write_text("""patch:
  name: synthesis-patch
  version: "1.0.0"
compatibility:
  bmad_version: "6.0.0"
  workflow: validate-story-synthesis
transforms:
  - "Test transform"
post_process:
  - pattern: "SYNTHESIS_MARKER"
    replacement: "REPLACED"
""")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Compilation should succeed even without the marker
        assert result.workflow_name == "validate-story-synthesis"

    def test_validates_against_patch_rules(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Validates output against patch validation rules."""
        import logging

        caplog.set_level(logging.WARNING)

        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create patch with validation
        patch_dir = tmp_project / "_bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "validate-story-synthesis.patch.yaml"
        patch_file.write_text("""patch:
  name: synthesis-patch
  version: "1.0.0"
compatibility:
  bmad_version: "6.0.0"
  workflow: validate-story-synthesis
transforms:
  - "Test transform"
validation:
  must_contain:
    - "<step"
    - "NONEXISTENT_STRING"
""")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        # Should not raise - validation failures are warnings
        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"


class TestSynthesisVariables:
    """Tests for variable resolution."""

    def test_story_id_computed(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """story_id is computed as '{epic_num}.{story_num}'."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.variables["story_id"] == "11.1"

    def test_validator_count_computed(
        self,
        tmp_project: Path,
        sample_anonymized_validations: list[AnonymizedValidation],
    ) -> None:
        """validator_count is computed from anonymized_validations length."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_anonymized_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.variables["validator_count"] == 4

    def test_date_system_generated(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Date is system-generated."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert "date" in result.variables
        assert result.variables["date"] is not None


class TestOutputTemplate:
    """Tests for output_template (AC7)."""

    def test_output_template_empty(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """output_template is empty for action-workflow."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.output_template == ""


class TestDynamicLoading:
    """Tests for dynamic loading via get_workflow_compiler (AC1)."""

    def test_dynamic_loading(self) -> None:
        """ValidateStorySynthesisCompiler is loaded dynamically via naming convention."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("validate-story-synthesis")

        assert compiler.workflow_name == "validate-story-synthesis"

    def test_compile_workflow_function(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """compile_workflow() works with validate-story-synthesis."""
        from bmad_assist.compiler import compile_workflow

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )

        # Mock discover_patch to avoid finding global/CWD patches (requires config)
        with patch("bmad_assist.compiler.patching.compiler.discover_patch", return_value=None):
            result = compile_workflow("validate-story-synthesis", context)

        assert result.workflow_name == "validate-story-synthesis"


class TestXMLOutput:
    """Tests for XML output structure."""

    def test_xml_parseable(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Generated XML is parseable by ElementTree."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        root = ET.fromstring(result.context)
        assert root.tag == "compiled-workflow"

    def test_xml_has_required_sections(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """XML output has all required sections."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        root = ET.fromstring(result.context)

        assert root.find("mission") is not None
        assert root.find("context") is not None
        assert root.find("variables") is not None
        assert root.find("instructions") is not None

    def test_validations_in_xml_structure(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Validations are embedded in XML with correct structure."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Check validations are embedded as separate file entries with virtual paths
        # Paths include project root prefix: /path/to/project/[Validator A]
        assert "[Validator A]" in result.context
        assert "[Validator B]" in result.context
        # Check validation content is in CDATA (embedded in context section)
        assert "First validator findings" in result.context
        assert "Second validator findings" in result.context


class TestProtocolCompliance:
    """Tests for WorkflowCompiler protocol compliance."""

    def test_get_required_files_minimal(self) -> None:
        """get_required_files returns minimal patterns (no PRD/arch)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        compiler = ValidateStorySynthesisCompiler()
        patterns = compiler.get_required_files()

        # Should only have story patterns, not PRD/architecture
        assert "**/sprint-artifacts/*.md" in patterns
        # PRD and architecture should NOT be in patterns
        assert "**/prd*.md" not in patterns
        assert "**/architecture*.md" not in patterns
        assert "**/project_context.md" not in patterns

    def test_get_variables(self) -> None:
        """get_variables returns synthesis-specific variables."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        compiler = ValidateStorySynthesisCompiler()
        variables = compiler.get_variables()

        # Required variables
        assert "epic_num" in variables
        assert "story_num" in variables
        assert "session_id" in variables
        assert "anonymized_validations" in variables

        # Computed variables
        assert "story_id" in variables
        assert "story_key" in variables
        assert "story_file" in variables
        assert "validator_count" in variables
        assert "date" in variables


class TestEdgeCases:
    """Tests for edge cases."""

    def test_compiles_without_project_context(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Compilation succeeds when project_context.md doesn't exist (optional file)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Ensure project_context.md doesn't exist
        project_context_path = tmp_project / "docs" / "project_context.md"
        if project_context_path.exists():
            project_context_path.unlink()

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Should still compile successfully
        assert result.workflow_name == "validate-story-synthesis"

    def test_compile_max_validators(
        self,
        tmp_project: Path,
    ) -> None:
        """Compilation with 26 validators (max)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create 26 validators (A-Z)
        many_validations = [
            AnonymizedValidation(
                validator_id=f"Validator {chr(65 + i)}",
                content=f"Validation content from validator {chr(65 + i)}",
                original_ref=f"uuid-{i}",
            )
            for i in range(26)
        ]

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=many_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"
        assert result.variables["validator_count"] == 26

    def test_empty_story_file_raises(
        self,
        tmp_project: Path,
        two_validations: list[AnonymizedValidation],
    ) -> None:
        """Empty story file raises CompilerError."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Delete existing and create empty story
        story_file = tmp_project / "docs" / "sprint-artifacts" / "11-1-test-story.md"
        story_file.write_text("")

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)empty"):
            compiler.compile(context)

    def test_unicode_in_validations(
        self,
        tmp_project: Path,
    ) -> None:
        """Unicode content in validations is handled correctly."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        unicode_validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="## Issues\n\nÜñíçödé characters: 你好世界 🎉",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="## Issues\n\nNormal ASCII content",
                original_ref="uuid-2",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=unicode_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"
        # Unicode should be preserved
        assert "Üñíçödé" in result.context or "unicode" in result.context.lower()


class TestIntegrationWithRealWorkflowFiles:
    """Tests for integration with actual workflow files created in Story 11.6."""

    def test_compile_with_real_workflow_files(
        self,
        tmp_path: Path,
        two_validations: list[AnonymizedValidation],
        story_file_content: str,
    ) -> None:
        """Verify compilation works with actual workflow files from repository.

        This test uses the real workflow files created in Story 11.6:
        - _bmad/bmm/workflows/4-implementation/validate-story-synthesis/workflow.yaml
        - _bmad/bmm/workflows/4-implementation/validate-story-synthesis/instructions.xml
        """
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Read real workflow files from repository
        repo_root = Path(__file__).parent.parent.parent.parent
        real_workflow_dir = (
            repo_root
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
        )

        if not real_workflow_dir.exists():
            pytest.skip("Real workflow files not yet created (Story 11.6 in progress)")

        real_workflow_yaml = (real_workflow_dir / "workflow.yaml").read_text()
        real_instructions_xml = (real_workflow_dir / "instructions.xml").read_text()

        # Create test project with real workflow files
        bmad_dir = (
            tmp_path
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
        )
        bmad_dir.mkdir(parents=True)
        (bmad_dir / "workflow.yaml").write_text(real_workflow_yaml)
        (bmad_dir / "instructions.xml").write_text(real_instructions_xml)

        # Create config
        config_dir = tmp_path / "_bmad" / "bmm"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text(f"""project_name: test-project
output_folder: '{tmp_path}/docs'
sprint_artifacts: '{tmp_path}/docs/sprint-artifacts'
user_name: TestUser
communication_language: English
document_output_language: English
""")

        # Create story file
        sprint_dir = tmp_path / "docs" / "sprint-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "11-1-test-story.md").write_text(story_file_content)

        # Compile
        context = create_test_context(
            tmp_path,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert result.workflow_name == "validate-story-synthesis"
        # Verify mission contains synthesis elements
        assert "synthesis" in result.mission.lower() or "synthesiz" in result.mission.lower()
        assert len(result.instructions) > 0

    def test_real_workflow_yaml_structure(self) -> None:
        """Verify real workflow.yaml has required structure per AC2."""
        repo_root = Path(__file__).parent.parent.parent.parent
        workflow_yaml_path = (
            repo_root
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
            / "workflow.yaml"
        )

        if not workflow_yaml_path.exists():
            pytest.skip("Real workflow files not yet created (Story 11.6 in progress)")

        import yaml

        content = yaml.safe_load(workflow_yaml_path.read_text())

        # AC2 requirements
        assert content.get("name") == "validate-story-synthesis"
        assert content.get("template") is False  # Action-workflow
        assert content.get("standalone") is True
        assert "config_source" in content
        # Variables section with synthesis-specific vars
        variables = content.get("variables", {})
        assert "epic_num" in variables
        assert "story_num" in variables
        assert "session_id" in variables
        assert "validator_count" in variables

    def test_real_instructions_xml_structure(self) -> None:
        """Verify real instructions.xml has required structure per AC3, AC8, AC9."""
        import xml.etree.ElementTree as XMLTree

        repo_root = Path(__file__).parent.parent.parent.parent
        instructions_path = (
            repo_root
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
            / "instructions.xml"
        )

        if not instructions_path.exists():
            pytest.skip("Real workflow files not yet created (Story 11.6 in progress)")

        content = instructions_path.read_text()

        # AC3: Must contain verification/prioritization/synthesis steps
        root = XMLTree.fromstring(content)
        assert root.tag == "workflow"

        # AC3: File modification permission
        assert "WRITE PERMISSION" in content

        # AC3: No interactive elements
        assert "<ask>" not in content
        assert "HALT" not in content
        assert "Your choice:" not in content.lower()

        # AC3: No file loading instructions (context embedded)
        assert "load from {installed_path}" not in content.lower()

        # AC8: Output format defined
        assert "## Synthesis Summary" in content or "Synthesis Summary" in content
        assert "## Changes Applied" in content or "Changes Applied" in content

        # AC9: Change application guidance
        assert "atomic" in content.lower() or "modify" in content.lower()

    def test_real_patch_file_structure(self) -> None:
        """Verify patch file has required structure per AC4-AC7."""
        import yaml

        # Check project-local patch (for tests)
        repo_root = Path(__file__).parent.parent.parent.parent
        patch_path = repo_root / "_bmad-assist" / "patches" / "validate-story-synthesis.patch.yaml"

        if not patch_path.exists():
            pytest.skip("Patch file not yet created (Story 11.6 in progress)")

        patch = yaml.safe_load(patch_path.read_text())

        # AC4: Patch metadata
        assert "patch" in patch
        assert "name" in patch["patch"]
        assert "version" in patch["patch"]

        # AC4: Compatibility
        assert "compatibility" in patch
        assert patch["compatibility"]["workflow"] == "validate-story-synthesis"

        # AC5: Transforms
        assert "transforms" in patch
        assert isinstance(patch["transforms"], list)

        # AC6: Post-process rules
        assert "post_process" in patch
        assert isinstance(patch["post_process"], list)

        # AC7: Validation rules
        assert "validation" in patch
        validation = patch["validation"]
        assert "must_contain" in validation
        assert "must_not_contain" in validation
        # Specific required values
        assert "synthesis" in validation["must_contain"]
        assert "verify" in validation["must_contain"]
        assert "apply" in validation["must_contain"]
        assert "WRITE PERMISSION" in validation["must_contain"]
        assert "{installed_path}" in validation["must_not_contain"]
        assert "HALT" in validation["must_not_contain"]

    def test_patch_applied_when_exists(
        self,
        tmp_path: Path,
        two_validations: list[AnonymizedValidation],
        story_file_content: str,
    ) -> None:
        """Verify patch post_process rules are applied during compilation."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Read real files
        repo_root = Path(__file__).parent.parent.parent.parent
        real_workflow_dir = (
            repo_root
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
        )
        real_patch_path = (
            repo_root / "_bmad-assist" / "patches" / "validate-story-synthesis.patch.yaml"
        )

        if not real_workflow_dir.exists() or not real_patch_path.exists():
            pytest.skip("Real workflow/patch files not yet created (Story 11.6)")

        # Setup test project
        bmad_dir = (
            tmp_path
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
        )
        bmad_dir.mkdir(parents=True)
        (bmad_dir / "workflow.yaml").write_text((real_workflow_dir / "workflow.yaml").read_text())
        (bmad_dir / "instructions.xml").write_text(
            (real_workflow_dir / "instructions.xml").read_text()
        )

        config_dir = tmp_path / "_bmad" / "bmm"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text(f"""project_name: test-project
output_folder: '{tmp_path}/docs'
sprint_artifacts: '{tmp_path}/docs/sprint-artifacts'
user_name: TestUser
communication_language: English
document_output_language: English
""")

        sprint_dir = tmp_path / "docs" / "sprint-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "11-1-test-story.md").write_text(story_file_content)

        # Copy real patch to test project
        patch_dir = tmp_path / "_bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        (patch_dir / "validate-story-synthesis.patch.yaml").write_text(real_patch_path.read_text())

        # Compile
        context = create_test_context(
            tmp_path,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Verify patch validation rules pass (no {installed_path}, no HALT)
        assert "{installed_path}" not in result.context
        assert "HALT" not in result.context

    def test_workflow_file_not_found_error(
        self,
        tmp_path: Path,
        two_validations: list[AnonymizedValidation],
        story_file_content: str,
    ) -> None:
        """Verify fail-fast error when workflow files don't exist."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )
        from bmad_assist.core.exceptions import ParserError

        # Create minimal project WITHOUT workflow files
        config_dir = tmp_path / "_bmad" / "bmm"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yaml").write_text(f"""project_name: test-project
output_folder: '{tmp_path}/docs'
sprint_artifacts: '{tmp_path}/docs/sprint-artifacts'
user_name: TestUser
communication_language: English
document_output_language: English
""")

        sprint_dir = tmp_path / "docs" / "sprint-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "11-1-test-story.md").write_text(story_file_content)

        # Compile without workflow files
        # Note: create_test_context() returns workflow_ir=None when workflow dir doesn't exist
        context = create_test_context(
            tmp_path,
            epic_num=11,
            story_num=1,
            validations=two_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        # With new architecture, workflow_ir is None when workflow dir doesn't exist
        # The compile() method raises CompilerError about workflow_ir not being set
        with pytest.raises(
            CompilerError, match="(?i)workflow_ir not set|workflow.*not found|directory.*not found"
        ):
            compiler.compile(context)

    def test_output_format_preserved_in_instructions(self) -> None:
        """Verify synthesis output format is present in instructions per AC8."""
        repo_root = Path(__file__).parent.parent.parent.parent
        instructions_path = (
            repo_root
            / "_bmad"
            / "bmm"
            / "workflows"
            / "4-implementation"
            / "validate-story-synthesis"
            / "instructions.xml"
        )

        if not instructions_path.exists():
            pytest.skip("Real workflow files not yet created (Story 11.6 in progress)")

        content = instructions_path.read_text()

        # AC8: Output format sections (actual severity levels used in workflow)
        format_sections = [
            "Synthesis Summary",
            "Issues Verified",
            "Critical",  # Blocks implementation
            "High",  # Significant gaps
            "Medium",  # Quality improvements
            "Low",  # Nice-to-have suggestions
            "Issues Dismissed",
            "Changes Applied",
        ]
        for section in format_sections:
            assert section in content, f"Missing output format section: {section}"
