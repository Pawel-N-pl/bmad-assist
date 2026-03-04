"""Tests for the code-review-synthesis workflow compiler.

Tests the CodeReviewSynthesisCompiler class which produces
synthesis prompts for Master LLM to apply source code fixes
based on anonymized code review findings.
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
def sample_anonymized_reviews() -> list[AnonymizedValidation]:
    """Create sample anonymized reviews for testing."""
    return [
        AnonymizedValidation(
            validator_id="Reviewer A",
            content="## Code Review\n\n1. Missing error handling in parse_input()",
            original_ref="uuid-1",
        ),
        AnonymizedValidation(
            validator_id="Reviewer B",
            content="## Analysis\n\nThe implementation has gaps in validation",
            original_ref="uuid-2",
        ),
        AnonymizedValidation(
            validator_id="Reviewer C",
            content="## Review\n\nGood overall, minor issues in tests",
            original_ref="uuid-3",
        ),
        AnonymizedValidation(
            validator_id="Reviewer D",
            content="## Findings\n\nNo major problems found in source code",
            original_ref="uuid-4",
        ),
    ]


@pytest.fixture
def two_reviews() -> list[AnonymizedValidation]:
    """Create minimum required reviews (2)."""
    return [
        AnonymizedValidation(
            validator_id="Reviewer A",
            content="## Issues\n\nFirst reviewer findings",
            original_ref="uuid-1",
        ),
        AnonymizedValidation(
            validator_id="Reviewer B",
            content="## Issues\n\nSecond reviewer findings",
            original_ref="uuid-2",
        ),
    ]


@pytest.fixture
def story_file_content() -> str:
    """Create sample story file content."""
    return """# Story 14.9: Test Story

Status: review

## Story

As a developer,
I want a code-review-synthesis compiler,
So that I can synthesize review findings.

## Acceptance Criteria

1. AC1: Basic functionality works

## Tasks / Subtasks

- [x] Task 1: Implement feature

## Dev Agent Record

### Completion Notes List

Implementation complete.
"""


@pytest.fixture
def project_context_content() -> str:
    """Create sample project_context.md content."""
    return """# Project Context for AI Agents

## Critical Implementation Rules

### Python Rules

- Type hints required on all functions
- Google-style docstrings for public functions only

## Testing Rules

- Tests mirror src structure
"""


@pytest.fixture
def tmp_project(tmp_path: Path, story_file_content: str, project_context_content: str) -> Path:
    """Create a temporary project structure for testing."""
    docs = tmp_path / "docs"
    docs.mkdir()

    # Create project_context.md
    (docs / "project-context.md").write_text(project_context_content)

    sprint_artifacts = docs / "sprint-artifacts"
    sprint_artifacts.mkdir()

    # Create default story file
    default_story = sprint_artifacts / "14-9-test-story.md"
    default_story.write_text(story_file_content)

    # Create workflow directory for code-review-synthesis
    workflow_dir = (
        tmp_path / "_bmad" / "bmm" / "workflows" / "4-implementation" / "code-review-synthesis"
    )
    workflow_dir.mkdir(parents=True)

    workflow_yaml = workflow_dir / "workflow.yaml"
    workflow_yaml.write_text("""name: code-review-synthesis
description: "Synthesize code review findings and apply source code fixes."
config_source: "{project-root}/_bmad/bmm/config.yaml"
template: false
instructions: "{installed_path}/instructions.xml"
standalone: true
""")

    instructions_xml = workflow_dir / "instructions.xml"
    instructions_xml.write_text("""<workflow>
  <critical>YOU ARE THE MASTER CODE REVIEW SYNTHESIS AGENT</critical>
  <critical>You have WRITE PERMISSION to modify SOURCE CODE files</critical>
  <step n="1" goal="Analyze reviewer findings">
    <action>Review all reviewer outputs</action>
    <action>Identify consensus and disagreements</action>
  </step>
  <step n="2" goal="Synthesize findings">
    <action>Prioritize issues by severity</action>
    <action>Identify false positives</action>
  </step>
  <step n="3" goal="Apply source code fixes">
    <action>Modify source files with verified fixes</action>
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

    # Initialize as git repo with a commit
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main")
    (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0")

    # Create a source file
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text('def hello():\n    print("Hello, World!")\n')

    return tmp_path


def create_test_context(
    project: Path,
    epic_num: int = 14,
    story_num: int = 9,
    reviews: list[AnonymizedValidation] | None = None,
    session_id: str = "test-session-123",
    **extra_vars: Any,
) -> CompilerContext:
    """Create a CompilerContext for testing.

    Pre-loads workflow_ir from the workflow directory (normally done by core.compile_workflow).
    """
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


class TestCodeReviewSynthesisCompiler:
    """Tests for CodeReviewSynthesisCompiler."""

    def test_workflow_name_property(self) -> None:
        """Workflow name is 'code-review-synthesis'."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        compiler = CodeReviewSynthesisCompiler()
        assert compiler.workflow_name == "code-review-synthesis"

    def test_compile_basic_four_reviewers(
        self,
        tmp_project: Path,
        sample_anonymized_reviews: list[AnonymizedValidation],
    ) -> None:
        """Basic compilation with 4 reviewers produces valid output."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=sample_anonymized_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="<!-- GIT_DIFF_START -->\ndiff --git a/test.py\n<!-- GIT_DIFF_END -->",
        ):
            result = compiler.compile(context)

        assert isinstance(result, CompiledWorkflow)
        assert result.workflow_name == "code-review-synthesis"
        assert result.token_estimate > 0
        # All 4 reviewers should be in context
        assert "Reviewer A" in result.context
        assert "Reviewer B" in result.context
        assert "Reviewer C" in result.context
        assert "Reviewer D" in result.context

    def test_compile_two_reviewers_minimum(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Minimum 2 reviewers compiles successfully."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert result.workflow_name == "code-review-synthesis"
        assert "Reviewer A" in result.context
        assert "Reviewer B" in result.context


class TestSynthesisContext:
    """Tests for synthesis context building."""

    def test_context_includes_project_context(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """project_context.md IS included in synthesis context (ground truth)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # project_context content SHOULD be in output (ground truth for evaluating reviewer claims)
        assert "Project Context" in result.context or "project-context" in result.context.lower()

    def test_context_includes_git_diff(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Git diff is included in synthesis context."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        mock_diff = (
            "<!-- GIT_DIFF_START -->\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "+new line\n"
            "<!-- GIT_DIFF_END -->"
        )
        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value=mock_diff,
        ):
            result = compiler.compile(context)

        assert "GIT_DIFF_START" in result.context
        assert "GIT_DIFF_END" in result.context

    def test_context_includes_story_file(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Story file being reviewed IS included (LAST for recency-bias)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Story file should be in context
        root = ET.fromstring(result.context)
        context_elem = root.find("context")
        assert context_elem is not None
        file_elements = context_elem.findall(".//file")
        paths = [f.get("path", "") for f in file_elements]
        assert any("14-9" in p for p in paths), "Story file should be in context"

    def test_context_includes_reviews(
        self,
        tmp_project: Path,
        sample_anonymized_reviews: list[AnonymizedValidation],
    ) -> None:
        """Anonymized reviews ARE included."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=sample_anonymized_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # All review content should be present
        assert "Missing error handling" in result.context
        assert "implementation has gaps" in result.context
        assert "Good overall, minor issues" in result.context
        assert "No major problems found" in result.context

    def test_reviews_sorted_alphabetically(
        self,
        tmp_project: Path,
    ) -> None:
        """Reviews appear in order: Reviewer A, B, C, D."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Create unsorted reviews
        unsorted_reviews = [
            AnonymizedValidation(
                validator_id="Reviewer D",
                content="Fourth content",
                original_ref="uuid-4",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Second content",
                original_ref="uuid-2",
            ),
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="First content",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Reviewer C",
                content="Third content",
                original_ref="uuid-3",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=unsorted_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Find positions of each reviewer in output
        idx_a = result.context.find("Reviewer A")
        idx_b = result.context.find("Reviewer B")
        idx_c = result.context.find("Reviewer C")
        idx_d = result.context.find("Reviewer D")

        assert idx_a >= 0, "Reviewer A should be in output"
        assert idx_b >= 0, "Reviewer B should be in output"
        assert idx_c >= 0, "Reviewer C should be in output"
        assert idx_d >= 0, "Reviewer D should be in output"

        # Should be in alphabetical order
        assert idx_a < idx_b < idx_c < idx_d, "Reviewers should be sorted alphabetically"

    def test_cdata_escaping(
        self,
        tmp_project: Path,
    ) -> None:
        """Review content with ]]> is properly escaped in CDATA."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Create review with CDATA-breaking sequence
        reviews_with_cdata = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Code example: data[index]]>some text",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Normal content without special chars",
                original_ref="uuid-2",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=reviews_with_cdata,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Result should be valid XML (would throw if CDATA not escaped)
        root = ET.fromstring(result.context)
        assert root is not None

        # The escaped sequence should be in the output
        # ]]> becomes \n]]]]><![CDATA[\n (with newlines)
        assert ("\n]]]]><![CDATA[\n" in result.context or
                "]]]]><![CDATA[>" in result.context or
                "data[index]" in result.context)


class TestSynthesisValidation:
    """Tests for input validation (AC #8)."""

    def test_fails_with_zero_reviews(
        self,
        tmp_project: Path,
    ) -> None:
        """Fails with CompilerError when no reviews provided."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=[],  # Empty list
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)no.*review|review.*required"):
            compiler.compile(context)

    def test_fails_with_one_review(
        self,
        tmp_project: Path,
    ) -> None:
        """Fails with CompilerError when only 1 review provided (AC #8)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        single_review = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Single review",
                original_ref="uuid-1",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=single_review,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError) as exc_info:
            compiler.compile(context)

        # AC #8: Exact error format
        error_msg = str(exc_info.value)
        assert "at least" in error_msg.lower() or "minimum" in error_msg.lower()
        assert "2" in error_msg
        assert "1" in error_msg
        assert "synthesis" in error_msg.lower() or "single review" in error_msg.lower()

    def test_fails_without_epic_num(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when epic_num not provided."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=None,  # type: ignore
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError, match="epic_num"):
            compiler.compile(context)

    def test_fails_without_story_num(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when story_num not provided."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=None,  # type: ignore
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError, match="story_num"):
            compiler.compile(context)

    def test_fails_story_not_found(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Fails with CompilerError when story file doesn't exist."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=99,  # Non-existent story
            story_num=99,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)story.*not found"):
            compiler.compile(context)

    def test_error_includes_suggestion(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Error messages include actionable suggestions."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=None,  # type: ignore
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError) as exc_info:
            compiler.compile(context)

        error_msg = str(exc_info.value).lower()
        assert "suggestion" in error_msg or "provide" in error_msg or "required" in error_msg


class TestSynthesisMission:
    """Tests for mission generation (AC #9)."""

    def test_mission_includes_story_id(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Mission includes epic_num.story_num."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert "14.9" in result.mission

    def test_mission_includes_reviewer_count(
        self,
        tmp_project: Path,
        sample_anonymized_reviews: list[AnonymizedValidation],
    ) -> None:
        """Mission mentions number of reviewers."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=sample_anonymized_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # 4 reviewers
        assert "4" in result.mission

    def test_mission_emphasizes_source_code(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Mission emphasizes SOURCE CODE modifications (AC #9)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        mission_lower = result.mission.lower()
        has_source_code_emphasis = (
            "source code" in mission_lower
            or "source file" in mission_lower
            or "code fix" in mission_lower
        )
        assert has_source_code_emphasis, f"Mission should emphasize source code: {result.mission}"


class TestVariables:
    """Tests for variable resolution (AC #7, #10)."""

    def test_story_id_computed(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """story_id is computed as '{epic_num}.{story_num}'."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert result.variables["story_id"] == "14.9"

    def test_reviewer_count_computed(
        self,
        tmp_project: Path,
        sample_anonymized_reviews: list[AnonymizedValidation],
    ) -> None:
        """reviewer_count is computed from anonymized_reviews length."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=sample_anonymized_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert result.variables["reviewer_count"] == 4

    def test_date_system_generated(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Date is system-generated."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert "date" in result.variables
        assert result.variables["date"] is not None


class TestDeterministicStorySelection:
    """Tests for deterministic story file selection (AC #10)."""

    def test_multiple_matches_uses_first_alphabetically(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """When multiple story files match, use first alphabetically."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Create additional story file that would sort after
        sprint_dir = tmp_project / "docs" / "sprint-artifacts"
        (sprint_dir / "14-9-zzz-story.md").write_text("# Story 14.9: ZZZ\n\nSecond match")

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Should use 14-9-test-story.md (alphabetically first) not 14-9-zzz-story.md
        assert "14-9-test-story" in result.variables.get("story_key", "")

    def test_uses_first_match_on_multiple_files(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Uses first match (alphabetically) when multiple story files exist.

        Note: Story 12.6 Dev Note specifies that the multiple-matches warning
        from the original local method is informational only and not critical
        for correctness. The shared resolve_story_file() does not log this
        warning, and this behavioral difference is accepted.
        """
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Create additional story file that comes AFTER alphabetically
        sprint_dir = tmp_project / "docs" / "sprint-artifacts"
        (sprint_dir / "14-9-zzz-story.md").write_text("# Story 14.9: ZZZ\n\nLast match")

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Should use alphabetically first file
        story_key = result.variables.get("story_key", "")
        assert "14-9-test-story" in story_key, f"Should use first match, got: {story_key}"


class TestPathSecurity:
    """Tests for path security validation (AC #11)."""

    def test_rejects_path_traversal(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Paths with traversal are rejected."""
        from bmad_assist.compiler.shared_utils import safe_read_file

        project_root = tmp_project

        # Try to read outside project with path traversal
        malicious_path = tmp_project / ".." / "etc" / "passwd"
        result = safe_read_file(malicious_path, project_root)

        # Should return empty string (rejected)
        assert result == ""

    def test_rejects_absolute_paths_outside_project(
        self,
        tmp_project: Path,
    ) -> None:
        """Absolute paths outside project root are rejected."""
        from bmad_assist.compiler.shared_utils import safe_read_file

        project_root = tmp_project

        # Try to read absolute path outside project
        outside_path = Path("/etc/passwd")
        result = safe_read_file(outside_path, project_root)

        # Should return empty string (rejected)
        assert result == ""


class TestGitDiff:
    """Tests for git diff capture (AC #5)."""

    def test_git_diff_embedded_with_markers(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Git diff is wrapped in markers."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        mock_diff = (
            "<!-- GIT_DIFF_START -->\ndiff --git a/test.py\n+new line\n<!-- GIT_DIFF_END -->"
        )
        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value=mock_diff,
        ):
            result = compiler.compile(context)

        assert "<!-- GIT_DIFF_START -->" in result.context
        assert "<!-- GIT_DIFF_END -->" in result.context

    def test_graceful_degradation_non_git_repo(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Compilation succeeds when not a git repo."""
        # Remove .git directory
        import shutil

        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        git_dir = tmp_project / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        # Should not raise - graceful degradation
        result = compiler.compile(context)
        assert result.workflow_name == "code-review-synthesis"


class TestModifiedSourceFiles:
    """Tests for modified source files embedding (AC #6)."""

    def test_skips_docs_files(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """docs/ files are skipped from modified source files."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            _extract_modified_files_from_stat,
        )

        stat_output = """
 src/main.py | 42 +++++++
 docs/readme.md | 10 +++
 tests/test.py | 25 ++++
"""
        result = _extract_modified_files_from_stat(stat_output, skip_docs=True)

        paths = [p for p, _ in result]
        assert "src/main.py" in paths
        assert "tests/test.py" in paths
        assert "docs/readme.md" not in paths


class TestXMLOutput:
    """Tests for XML output structure."""

    def test_xml_parseable(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Generated XML is parseable by ElementTree."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        root = ET.fromstring(result.context)
        assert root.tag == "compiled-workflow"

    def test_xml_has_required_sections(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """XML output has all required sections."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        root = ET.fromstring(result.context)

        assert root.find("mission") is not None
        assert root.find("context") is not None
        assert root.find("variables") is not None
        assert root.find("instructions") is not None

    def test_reviews_in_xml_structure(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Reviews are embedded as separate files with CDATA (AC #4)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Check reviews are embedded as separate file entries with virtual paths
        # Paths include project root prefix: /path/to/project/[Reviewer A]
        assert "[Reviewer A]" in result.context
        assert "[Reviewer B]" in result.context
        # Check review content is in CDATA (embedded in context section)
        assert "First reviewer findings" in result.context
        assert "Second reviewer findings" in result.context


class TestProtocolCompliance:
    """Tests for WorkflowCompiler protocol compliance (AC #1)."""

    def test_get_required_files(self) -> None:
        """get_required_files returns story patterns."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        compiler = CodeReviewSynthesisCompiler()
        patterns = compiler.get_required_files()

        # Should have story patterns
        assert "**/sprint-artifacts/*.md" in patterns

    def test_get_variables(self) -> None:
        """get_variables returns synthesis-specific variables."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        compiler = CodeReviewSynthesisCompiler()
        variables = compiler.get_variables()

        # Required variables
        assert "epic_num" in variables
        assert "story_num" in variables
        assert "session_id" in variables
        assert "anonymized_reviews" in variables

        # Computed variables
        assert "story_id" in variables
        assert "story_key" in variables
        assert "reviewer_count" in variables
        assert "date" in variables


class TestPatchIntegration:
    """Tests for patch post_process rules (AC #12)."""

    def test_compiles_without_patch(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Compilation succeeds when no patch file exists."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Ensure no patch exists
        fake_home = tmp_project / "fake_home_no_patch"
        fake_home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert result.workflow_name == "code-review-synthesis"

    def test_applies_patch_post_process(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Applies patch post_process rules when patch exists."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Create patch with post_process
        patch_dir = tmp_project / "_bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "code-review-synthesis.patch.yaml"
        patch_file.write_text("""patch:
  name: synthesis-patch
  version: "1.0.0"
compatibility:
  bmad_version: "6.0.0"
  workflow: code-review-synthesis
transforms:
  - "Test transform"
post_process:
  - pattern: "SYNTHESIS_MARKER"
    replacement: "REPLACED"
""")

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Compilation should succeed even without the marker
        assert result.workflow_name == "code-review-synthesis"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_compiles_without_project_context(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Compilation succeeds when project_context.md doesn't exist (optional file)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Ensure project_context.md doesn't exist
        project_context_path = tmp_project / "docs" / "project-context.md"
        if project_context_path.exists():
            project_context_path.unlink()

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        # Should still compile successfully
        assert result.workflow_name == "code-review-synthesis"

    def test_empty_story_file_raises(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Empty story file raises CompilerError."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        # Delete existing and create empty story
        story_file = tmp_project / "docs" / "sprint-artifacts" / "14-9-test-story.md"
        story_file.write_text("")

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with pytest.raises(CompilerError, match="(?i)empty"):
            compiler.compile(context)

    def test_unicode_in_reviews(
        self,
        tmp_project: Path,
    ) -> None:
        """Unicode content in reviews is handled correctly."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        unicode_reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="## Issues\n\nÜñíçödé characters: 你好世界 🎉",
                original_ref="uuid-1",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="## Issues\n\nNormal ASCII content",
                original_ref="uuid-2",
            ),
        ]

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=unicode_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value="",
        ):
            result = compiler.compile(context)

        assert result.workflow_name == "code-review-synthesis"
        # Unicode should be preserved
        assert "Üñíçödé" in result.context or "unicode" in result.context.lower()


class TestDynamicLoading:
    """Tests for dynamic loading via get_workflow_compiler (AC #1)."""

    def test_dynamic_loading(self) -> None:
        """CodeReviewSynthesisCompiler is loaded dynamically via naming convention."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("code-review-synthesis")

        assert compiler.workflow_name == "code-review-synthesis"

    def test_compile_workflow_function(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """compile_workflow() works with code-review-synthesis."""
        from bmad_assist.compiler import compile_workflow

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )

        # Mock discover_patch and git diff
        with (
            patch("bmad_assist.compiler.patching.compiler.discover_patch", return_value=None),
            patch(
                "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
                return_value="",
            ),
        ):
            result = compile_workflow("code-review-synthesis", context)

        assert result.workflow_name == "code-review-synthesis"


class TestSkipSourceFiles:
    """Tests for skip_source_files flag (Step 0 source file trimming)."""

    def test_skip_source_files_excludes_source_files(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """With skip_source_files=True, no source file content in context but git diff IS preserved."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        mock_diff = (
            "<!-- GIT_DIFF_START -->\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "+new line\n"
            "<!-- GIT_DIFF_END -->"
        )

        # Mock source context to return known content when called
        mock_source_files = {
            str(tmp_project / "src" / "main.py"): 'def hello():\n    print("Hello, World!")\n',
        }

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
            skip_source_files=True,
        )
        compiler = CodeReviewSynthesisCompiler()

        with (
            patch(
                "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
                return_value=mock_diff,
            ),
            patch(
                "bmad_assist.compiler.source_context.SourceContextService.collect_files",
                return_value=mock_source_files,
            ) as mock_collect,
        ):
            result = compiler.compile(context)

        # Source context service should NOT have been called
        mock_collect.assert_not_called()

        # Git diff should still be present
        assert "[git-diff]" in result.context
        assert "GIT_DIFF_START" in result.context

    def test_skip_source_files_false_includes_source_files(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """With skip_source_files=False, source files are included as normal."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        mock_source_files = {
            str(tmp_project / "src" / "main.py"): 'def hello():\n    print("Hello, World!")\n',
        }

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
            skip_source_files=False,
        )
        compiler = CodeReviewSynthesisCompiler()

        with (
            patch(
                "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
                return_value="",
            ),
            patch(
                "bmad_assist.compiler.source_context.SourceContextService.collect_files",
                return_value=mock_source_files,
            ) as mock_collect,
        ):
            result = compiler.compile(context)

        # Source context service SHOULD have been called
        mock_collect.assert_called_once()

        # Source file content should be in the compiled output
        assert "main.py" in result.context

    def test_skip_source_files_not_in_vars_includes_source_files(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """Without skip_source_files key at all, source files included (backward compat)."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        mock_source_files = {
            str(tmp_project / "src" / "main.py"): 'def hello():\n    print("Hello, World!")\n',
        }

        # Do NOT pass skip_source_files at all
        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
        )
        compiler = CodeReviewSynthesisCompiler()

        with (
            patch(
                "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
                return_value="",
            ),
            patch(
                "bmad_assist.compiler.source_context.SourceContextService.collect_files",
                return_value=mock_source_files,
            ) as mock_collect,
        ):
            result = compiler.compile(context)

        # Source context service SHOULD have been called (default behavior)
        mock_collect.assert_called_once()

        # Source file content should be in the compiled output
        assert "main.py" in result.context

    def test_skip_source_files_preserves_git_diff(
        self,
        tmp_project: Path,
        two_reviews: list[AnonymizedValidation],
    ) -> None:
        """With skip_source_files=True, git diff content IS present in compiled context."""
        from bmad_assist.compiler.workflows.code_review_synthesis import (
            CodeReviewSynthesisCompiler,
        )

        mock_diff = (
            "<!-- GIT_DIFF_START -->\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def hello():\n"
            '-    print("Hello")\n'
            '+    print("Hello, World!")\n'
            "<!-- GIT_DIFF_END -->"
        )

        context = create_test_context(
            tmp_project,
            epic_num=14,
            story_num=9,
            reviews=two_reviews,
            skip_source_files=True,
        )
        compiler = CodeReviewSynthesisCompiler()

        with patch(
            "bmad_assist.compiler.workflows.code_review_synthesis._capture_git_diff",
            return_value=mock_diff,
        ):
            result = compiler.compile(context)

        # Git diff markers and content should be present
        assert "GIT_DIFF_START" in result.context
        assert "GIT_DIFF_END" in result.context
        assert "diff --git a/src/main.py" in result.context
        assert "++" in result.context or "Hello, World!" in result.context
