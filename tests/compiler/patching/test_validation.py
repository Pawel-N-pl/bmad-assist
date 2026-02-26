"""Tests for validation engine."""


from bmad_assist.compiler.patching.types import TransformResult, Validation
from bmad_assist.compiler.patching.validation import (
    check_threshold,
    is_regex,
    parse_regex,
    validate_output,
)


class TestIsRegex:
    """Tests for regex detection."""

    def test_regex_format_detected(self) -> None:
        """Test that /pattern/ format is detected as regex."""
        assert is_regex("/test/") is True
        assert is_regex("/step\\s+n=\\d+/") is True
        assert is_regex("/^start.*end$/") is True

    def test_plain_string_not_regex(self) -> None:
        """Test that plain strings are not detected as regex."""
        assert is_regex("test") is False
        assert is_regex("<step") is False
        assert is_regex("action") is False

    def test_single_slash_not_regex(self) -> None:
        """Test that single slashes don't make a regex."""
        assert is_regex("/test") is False
        assert is_regex("test/") is False
        assert is_regex("path/to/file") is False

    def test_empty_regex_detected(self) -> None:
        """Test that empty regex pattern is still regex format."""
        assert is_regex("//") is True

    def test_escaped_slashes_in_regex(self) -> None:
        """Test regex with escaped slashes inside."""
        assert is_regex(r"/path\/to\/file/") is True


class TestParseRegex:
    """Tests for regex parsing."""

    def test_parse_simple_regex(self) -> None:
        """Test parsing a simple regex pattern."""
        pattern = parse_regex("/test/")
        assert pattern.pattern == "test"

    def test_parse_regex_with_special_chars(self) -> None:
        """Test parsing regex with special characters."""
        pattern = parse_regex(r"/step\s+n=\d+/")
        assert pattern.pattern == r"step\s+n=\d+"

    def test_regex_is_multiline(self) -> None:
        """Test that regex uses MULTILINE flag."""
        import re

        pattern = parse_regex("/^start/")
        # MULTILINE means ^ matches at line boundaries
        assert pattern.flags & re.MULTILINE

    def test_parse_empty_regex(self) -> None:
        """Test parsing empty regex pattern."""
        pattern = parse_regex("//")
        assert pattern.pattern == ""

    def test_parse_regex_with_escaped_slashes(self) -> None:
        """Test parsing regex with escaped slashes."""
        pattern = parse_regex(r"/path\/file/")
        # The escaped slash should become a literal slash in the pattern
        assert "/" in pattern.pattern or r"\/" in pattern.pattern


class TestValidateOutput:
    """Tests for output validation."""

    def test_validate_empty_validation(self) -> None:
        """Test that empty validation passes."""
        validation = Validation()
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert errors == []

    def test_validate_must_contain_substring_pass(self) -> None:
        """Test substring must_contain that passes."""
        validation = Validation(must_contain=["<step", "workflow"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert errors == []

    def test_validate_must_contain_substring_fail(self) -> None:
        """Test substring must_contain that fails."""
        validation = Validation(must_contain=["<missing>"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert len(errors) == 1
        assert "<missing>" in errors[0]

    def test_validate_must_contain_regex_pass(self) -> None:
        """Test regex must_contain that passes."""
        validation = Validation(must_contain=["/step\\s*\\/>/"])
        errors = validate_output("<workflow><step /></workflow>", validation)
        assert errors == []

    def test_validate_must_contain_regex_fail(self) -> None:
        """Test regex must_contain that fails."""
        validation = Validation(must_contain=["/missing\\d+/"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert len(errors) == 1

    def test_validate_must_not_contain_substring_pass(self) -> None:
        """Test substring must_not_contain that passes."""
        validation = Validation(must_not_contain=["<ask>", "HALT"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert errors == []

    def test_validate_must_not_contain_substring_fail(self) -> None:
        """Test substring must_not_contain that fails."""
        validation = Validation(must_not_contain=["<step"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert len(errors) == 1
        assert "<step" in errors[0]

    def test_validate_must_not_contain_regex_pass(self) -> None:
        """Test regex must_not_contain that passes."""
        validation = Validation(must_not_contain=["/ask\\s*>/"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert errors == []

    def test_validate_must_not_contain_regex_fail(self) -> None:
        """Test regex must_not_contain that fails."""
        validation = Validation(must_not_contain=["/step\\s*\\/>/"])
        errors = validate_output("<workflow><step /></workflow>", validation)
        assert len(errors) == 1

    def test_validate_multiple_rules(self) -> None:
        """Test validation with multiple rules."""
        validation = Validation(
            must_contain=["<workflow>", "<step"],
            must_not_contain=["<ask", "HALT"],  # Use <ask (without >) to match <ask/> and <ask>
        )
        errors = validate_output("<workflow><step/><ask/></workflow>", validation)
        # Should fail on must_not_contain <ask
        assert len(errors) == 1
        assert "<ask" in errors[0]

    def test_validate_case_sensitive(self) -> None:
        """Test that validation is case-sensitive by default."""
        validation = Validation(must_contain=["STEP"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert len(errors) == 1  # "step" != "STEP"

    def test_validate_regex_case_insensitive_flag(self) -> None:
        """Test regex with case-insensitive flag."""
        validation = Validation(must_contain=["/(?i)STEP/"])
        errors = validate_output("<workflow><step/></workflow>", validation)
        assert errors == []  # (?i) makes it case-insensitive


class TestCheckThreshold:
    """Tests for success threshold calculation."""

    def test_all_successful(self) -> None:
        """Test threshold with all transforms successful."""
        results = [
            TransformResult(success=True, transform_index=0),
            TransformResult(success=True, transform_index=1),
            TransformResult(success=True, transform_index=2),
        ]
        assert check_threshold(results) is True

    def test_all_failed(self) -> None:
        """Test threshold with all transforms failed."""
        results = [
            TransformResult(success=False, transform_index=0, reason="Failed"),
            TransformResult(success=False, transform_index=1, reason="Failed"),
            TransformResult(success=False, transform_index=2, reason="Failed"),
        ]
        assert check_threshold(results) is False

    def test_exactly_75_percent(self) -> None:
        """Test threshold at exactly 75%."""
        results = [
            TransformResult(success=True, transform_index=0),
            TransformResult(success=True, transform_index=1),
            TransformResult(success=True, transform_index=2),
            TransformResult(success=False, transform_index=3, reason="Failed"),
        ]
        # 3/4 = 75%, should pass
        assert check_threshold(results) is True

    def test_below_75_percent(self) -> None:
        """Test threshold below 75%."""
        results = [
            TransformResult(success=True, transform_index=0),
            TransformResult(success=True, transform_index=1),
            TransformResult(success=False, transform_index=2, reason="Failed"),
            TransformResult(success=False, transform_index=3, reason="Failed"),
        ]
        # 2/4 = 50%, should fail
        assert check_threshold(results) is False

    def test_just_above_75_percent(self) -> None:
        """Test threshold just above 75%."""
        results = [
            TransformResult(success=True, transform_index=0),
            TransformResult(success=True, transform_index=1),
            TransformResult(success=True, transform_index=2),
            TransformResult(success=True, transform_index=3),
            TransformResult(success=False, transform_index=4, reason="Failed"),
        ]
        # 4/5 = 80%, should pass
        assert check_threshold(results) is True

    def test_empty_results(self) -> None:
        """Test threshold with empty results (edge case)."""
        results: list[TransformResult] = []
        # No transforms = consider it a pass (nothing to fail)
        assert check_threshold(results) is True

    def test_single_success(self) -> None:
        """Test threshold with single successful transform."""
        results = [TransformResult(success=True, transform_index=0)]
        assert check_threshold(results) is True

    def test_single_failure(self) -> None:
        """Test threshold with single failed transform."""
        results = [TransformResult(success=False, transform_index=0, reason="Failed")]
        # 0% success rate, should fail
        assert check_threshold(results) is False

    def test_floor_division_used(self) -> None:
        """Test that floor division is used for threshold calculation."""
        # 74.9% should be floored to 74% and fail
        # We need 3 success, 1 fail = 75% (exactly at threshold)
        # But 2 success, 1 fail = 66.67%, floors to 66%, fails
        results = [
            TransformResult(success=True, transform_index=0),
            TransformResult(success=True, transform_index=1),
            TransformResult(success=False, transform_index=2, reason="Failed"),
        ]
        # 2/3 = 66.67%, floor to 66%, below 75%
        assert check_threshold(results) is False
