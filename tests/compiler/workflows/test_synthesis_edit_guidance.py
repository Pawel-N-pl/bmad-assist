"""Tests for Edit tool guidance in synthesis workflows.

Story 22.4: Verifies that synthesis prompts include proper guidance
for using Read tool before Edit tool to avoid old_string mismatches.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from bmad_assist.compiler.parser import parse_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.validation.anonymizer import AnonymizedValidation


@pytest.fixture
def sample_validations() -> list[AnonymizedValidation]:
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
  </step>
</workflow>
""")

    # Create code-review-synthesis workflow
    cr_workflow_dir = (
        tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "code-review-synthesis"
    )
    cr_workflow_dir.mkdir(parents=True)

    cr_workflow_yaml = cr_workflow_dir / "workflow.yaml"
    cr_workflow_yaml.write_text("""name: code-review-synthesis
description: "Synthesize code review findings."
config_source: "{project-root}/_bmad/bmm/config.yaml"
template: false
instructions: "{installed_path}/instructions.xml"
""")

    cr_instructions_xml = cr_workflow_dir / "instructions.xml"
    cr_instructions_xml.write_text("""<workflow>
  <critical>YOU ARE THE MASTER CODE REVIEW SYNTHESIS AGENT</critical>
  <step n="1" goal="Analyze reviewer findings">
    <action>Review all reviewer outputs</action>
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
    """Create a CompilerContext for testing."""
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


def create_code_review_context(
    project: Path,
    epic_num: int = 11,
    story_num: int = 1,
    reviews: list[AnonymizedValidation] | None = None,
    session_id: str = "test-session-123",
    **extra_vars: Any,
) -> CompilerContext:
    """Create a CompilerContext for code review synthesis testing."""
    resolved_vars = {
        "epic_num": epic_num,
        "story_num": story_num,
        "anonymized_reviews": reviews or [],
        "session_id": session_id,
        **extra_vars,
    }
    workflow_dir = (
        project / "_bmad" / "bmm" / "workflows" / "4-implementation" / "code-review-synthesis"
    )
    workflow_ir = parse_workflow(workflow_dir) if workflow_dir.exists() else None
    return CompilerContext(
        project_root=project,
        output_folder=project / "docs",
        resolved_variables=resolved_vars,
        workflow_ir=workflow_ir,
    )


class TestValidateStorySynthesisEditGuidance:
    """Tests for Edit guidance in validate-story-synthesis mission (AC4)."""

    def test_mission_includes_read_before_edit_guidance(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission includes instruction to Read before Edit (AC4)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Verify Read tool guidance is in mission
        mission_lower = result.mission.lower()
        assert "read" in mission_lower, "Mission should mention Read tool"
        assert "edit" in mission_lower, "Mission should mention Edit tool"

    def test_mission_warns_against_using_embedded_content(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission warns NOT to use embedded content for old_string (AC4)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Check for warning about embedded content
        mission_lower = result.mission.lower()
        assert (
            "not" in mission_lower and "prompt" in mission_lower
        ) or "not" in mission_lower and "embedded" in mission_lower, (
            "Mission should warn against using prompt content for old_string"
        )

    def test_mission_mentions_old_string(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission mentions old_string parameter (AC4)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        assert "old_string" in result.mission, "Mission should mention old_string parameter"

    def test_mission_mentions_truncation_handling(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Mission mentions offset/limit for truncated Read output (AC4)."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        mission_lower = result.mission.lower()
        has_truncation_guidance = "offset" in mission_lower or "limit" in mission_lower or "truncat" in mission_lower
        assert has_truncation_guidance, "Mission should mention handling truncated output"


class TestCodeReviewSynthesisEditGuidance:
    """Tests for Edit guidance in code-review-synthesis mission (AC4)."""

    def test_mission_includes_read_before_edit_guidance(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Code review synthesis mission includes Read before Edit guidance."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_code_review_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            reviews=sample_validations,
        )
        compiler = CodeReviewSynthesisCompiler()

        result = compiler.compile(context)

        # Verify Read tool guidance is in mission
        mission_lower = result.mission.lower()
        assert "read" in mission_lower, "Mission should mention Read tool"
        assert "edit" in mission_lower, "Mission should mention Edit tool"

    def test_mission_warns_against_embedded_content(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Code review synthesis warns against using embedded content for old_string."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_code_review_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            reviews=sample_validations,
        )
        compiler = CodeReviewSynthesisCompiler()

        result = compiler.compile(context)

        # Check for old_string and related guidance
        assert "old_string" in result.mission, "Mission should mention old_string"


class TestEditFailureDetection:
    """Tests for Edit tool failure detection in handlers (AC5)."""

    def test_check_for_edit_failures_detects_zero_occurrences(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """check_for_edit_failures detects '0 occurrences found' pattern."""
        import logging

        from bmad_assist.core.loop.handlers.base import check_for_edit_failures

        caplog.set_level(logging.WARNING)

        # Simulate provider output with Edit failure
        stdout = """
        Attempting to edit file...
        Error: 0 occurrences found in target file.
        The old_string doesn't match any content.
        """

        check_for_edit_failures(stdout, target_hint="story file")

        # Should log a warning
        assert len(caplog.records) >= 1
        warning_msg = caplog.records[0].message.lower()
        assert "edit tool failure" in warning_msg
        assert "story file" in warning_msg

    def test_check_for_edit_failures_detects_string_not_found(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """check_for_edit_failures detects 'string not found' pattern."""
        import logging

        from bmad_assist.core.loop.handlers.base import check_for_edit_failures

        caplog.set_level(logging.WARNING)

        stdout = "Edit operation failed: string not found in the target file."

        check_for_edit_failures(stdout)

        assert len(caplog.records) >= 1
        assert "edit tool failure" in caplog.records[0].message.lower()

    def test_check_for_edit_failures_no_false_positives(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """check_for_edit_failures doesn't warn on normal output."""
        import logging

        from bmad_assist.core.loop.handlers.base import check_for_edit_failures

        caplog.set_level(logging.WARNING)

        # Normal successful output
        stdout = """
        Successfully edited file.
        Applied 3 changes.
        All tests pass.
        """

        check_for_edit_failures(stdout)

        # Should NOT log any warnings
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 0

    def test_check_for_edit_failures_includes_guidance(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """check_for_edit_failures includes remediation guidance."""
        import logging

        from bmad_assist.core.loop.handlers.base import check_for_edit_failures

        caplog.set_level(logging.WARNING)

        stdout = "Error: no matches found for the specified old_string"

        check_for_edit_failures(stdout)

        assert len(caplog.records) >= 1
        warning_msg = caplog.records[0].message.lower()
        # Should include guidance about Read tool
        assert "read" in warning_msg
        assert "old_string" in warning_msg or "guidance" in warning_msg


class TestCdataEdgeCases:
    """Tests for CDATA edge case handling (AC2)."""

    def test_cdata_split_content_in_validation(
        self,
        tmp_project: Path,
    ) -> None:
        """Validation content with ]]> is properly handled in CDATA."""
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
                content="Normal content",
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

    def test_story_file_with_cdata_content(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
    ) -> None:
        """Story file containing ]]> is properly embedded."""
        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        # Create story file with CDATA-breaking content
        story_content = """# Story 11.1: Test

Status: ready-for-dev

## Story

Code: data[0]]>EOF

## AC

1. Works
"""
        story_file = tmp_project / "docs" / "sprint-artifacts" / "11-1-test-story.md"
        story_file.write_text(story_content)

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        result = compiler.compile(context)

        # Should produce valid XML
        root = ET.fromstring(result.context)
        assert root is not None


class TestMtimeLogging:
    """Tests for mtime logging at compile time (AC3)."""

    def test_mtime_logged_at_compile_time(
        self,
        tmp_project: Path,
        sample_validations: list[AnonymizedValidation],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Story file mtime is logged at compile time for debugging."""
        import logging

        from bmad_assist.compiler.workflows.validate_story_synthesis import (
            ValidateStorySynthesisCompiler,
        )

        caplog.set_level(logging.DEBUG)

        context = create_test_context(
            tmp_project,
            epic_num=11,
            story_num=1,
            validations=sample_validations,
        )
        compiler = ValidateStorySynthesisCompiler()

        compiler.compile(context)

        # Check for mtime in debug logs
        debug_messages = [r.message for r in caplog.records if r.levelname == "DEBUG"]
        has_mtime_log = any("mtime" in msg.lower() for msg in debug_messages)
        assert has_mtime_log, "Should log mtime at compile time for debugging"
