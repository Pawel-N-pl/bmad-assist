"""Tests for review scope resolution.

Tests the resolve_review_scope() function that determines
review scope based on context.
"""



from tests.testarch.core.conftest import MockCompilerContext


class TestResolveReviewScope:
    """Tests for resolve_review_scope()."""

    def test_single_when_story_file_provided(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return 'single' when story_file is in resolved_variables."""
        from bmad_assist.testarch.core import resolve_review_scope

        mock_context.resolved_variables["story_file"] = "/path/to/story.md"

        result = resolve_review_scope(mock_context)
        assert result == "single"

    def test_directory_when_test_dir_is_subdirectory(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return 'directory' when test_dir is a subdirectory of tests/."""
        from bmad_assist.testarch.core import resolve_review_scope

        # test_dir points to tests/api/ (subdirectory)
        result = resolve_review_scope(mock_context, test_dir="tests/api/")
        assert result == "directory"

    def test_directory_when_test_dir_is_nested(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return 'directory' for deeply nested test directories."""
        from bmad_assist.testarch.core import resolve_review_scope

        result = resolve_review_scope(mock_context, test_dir="tests/unit/auth/")
        assert result == "directory"

    def test_suite_when_test_dir_is_tests_root(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should return 'suite' when test_dir is just 'tests/'."""
        from bmad_assist.testarch.core import resolve_review_scope

        result = resolve_review_scope(mock_context, test_dir="tests/")
        assert result == "suite"

    def test_suite_default(self, mock_context: MockCompilerContext) -> None:
        """Should return 'suite' by default."""
        from bmad_assist.testarch.core import resolve_review_scope

        result = resolve_review_scope(mock_context)
        assert result == "suite"

    def test_suite_when_no_test_dir(self, mock_context: MockCompilerContext) -> None:
        """Should return 'suite' when test_dir is None."""
        from bmad_assist.testarch.core import resolve_review_scope

        result = resolve_review_scope(mock_context, test_dir=None)
        assert result == "suite"

    def test_uses_resolved_test_dir(self, mock_context: MockCompilerContext) -> None:
        """Should use test_dir from resolved_variables when not explicitly passed."""
        from bmad_assist.testarch.core import resolve_review_scope

        mock_context.resolved_variables["test_dir"] = "tests/integration/"

        result = resolve_review_scope(mock_context)
        assert result == "directory"

    def test_explicit_test_dir_overrides_resolved(
        self, mock_context: MockCompilerContext
    ) -> None:
        """Should use explicit test_dir over resolved_variables."""
        from bmad_assist.testarch.core import resolve_review_scope

        mock_context.resolved_variables["test_dir"] = "tests/"

        result = resolve_review_scope(mock_context, test_dir="tests/api/")
        assert result == "directory"


class TestReviewScopeEnum:
    """Tests for ReviewScope enum."""

    def test_enum_values(self) -> None:
        """Should have correct string values."""
        from bmad_assist.testarch.core import ReviewScope

        assert ReviewScope.SINGLE.value == "single"
        assert ReviewScope.DIRECTORY.value == "directory"
        assert ReviewScope.SUITE.value == "suite"

    def test_enum_count(self) -> None:
        """Should have exactly 3 review scopes."""
        from bmad_assist.testarch.core import ReviewScope

        assert len(ReviewScope) == 3
