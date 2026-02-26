"""Tests for PatternMatcher class."""


import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Pattern,
    PatternId,
    Severity,
    Signal,
)
from bmad_assist.deep_verify.patterns.matcher import (
    MatchContext,
    PatternMatcher,
)


class TestMatchContext:
    """Tests for MatchContext helper class."""

    def test_from_text_simple(self) -> None:
        """Test creating context from simple text."""
        context = MatchContext.from_text("line 1\nline 2\nline 3")
        assert len(context.lines) == 3
        assert context.lines[0] == "line 1"
        assert context.lines[1] == "line 2"
        assert context.lines[2] == "line 3"

    def test_from_text_single_line(self) -> None:
        """Test creating context from single line."""
        context = MatchContext.from_text("single line")
        assert len(context.lines) == 1
        assert context.lines[0] == "single line"

    def test_from_text_empty(self) -> None:
        """Test creating context from empty text."""
        context = MatchContext.from_text("")
        assert len(context.lines) == 1
        assert context.lines[0] == ""

    def test_line_offsets(self) -> None:
        """Test line offset calculation."""
        context = MatchContext.from_text("abc\ndef\nghi")
        assert context.line_offsets[0] == 0
        assert context.line_offsets[1] == 4  # "abc\n"
        assert context.line_offsets[2] == 8  # "abc\ndef\n"

    def test_get_line_number(self) -> None:
        """Test getting line number from position."""
        context = MatchContext.from_text("line 1\nline 2\nline 3")
        assert context.get_line_number(0) == 1  # Start of line 1
        assert context.get_line_number(5) == 1  # '1' in "line 1"
        assert context.get_line_number(7) == 2  # Start of line 2
        assert context.get_line_number(14) == 3  # Start of line 3

    def test_get_line_content(self) -> None:
        """Test getting line content."""
        context = MatchContext.from_text("line 1\nline 2\nline 3")
        assert context.get_line_content(1) == "line 1"
        assert context.get_line_content(2) == "line 2"
        assert context.get_line_content(3) == "line 3"
        assert context.get_line_content(0) == ""  # Invalid
        assert context.get_line_content(100) == ""  # Out of range


class TestPatternMatcherCreation:
    """Tests for PatternMatcher initialization."""

    def test_empty_matcher(self) -> None:
        """Test creating matcher with no patterns."""
        matcher = PatternMatcher([])
        assert len(matcher._patterns) == 0

    def test_matcher_with_patterns(self) -> None:
        """Test creating matcher with patterns."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[Signal(type="exact", pattern="race")],
            severity=Severity.CRITICAL,
        )
        matcher = PatternMatcher([pattern])
        assert len(matcher._patterns) == 1

    def test_matcher_custom_threshold(self) -> None:
        """Test creating matcher with custom threshold."""
        matcher = PatternMatcher([], threshold=0.8)
        assert matcher._threshold == 0.8

    def test_matcher_repr(self) -> None:
        """Test matcher repr."""
        matcher = PatternMatcher([], threshold=0.75)
        repr_str = repr(matcher)
        assert "PatternMatcher" in repr_str
        assert "threshold=0.75" in repr_str


class TestPatternMatcherExactMatching:
    """Tests for exact string matching."""

    @pytest.fixture
    def race_pattern(self) -> Pattern:
        """Create a simple race condition pattern."""
        return Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="race condition"),
                Signal(type="exact", pattern="concurrent access"),
            ],
            severity=Severity.CRITICAL,
        )

    def test_single_signal_match(self, race_pattern: Pattern) -> None:
        """Test matching with single signal."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([race_pattern], threshold=0.4)
        results = matcher.match("There is a race condition in the code")
        assert len(results) == 1
        assert results[0].confidence == 0.5  # 1 of 2 signals matched

    def test_all_signals_match(self, race_pattern: Pattern) -> None:
        """Test matching with all signals."""
        matcher = PatternMatcher([race_pattern])
        results = matcher.match(
            "race condition and concurrent access detected"
        )
        assert len(results) == 1
        assert results[0].confidence == 1.0  # All signals matched

    def test_no_match(self, race_pattern: Pattern) -> None:
        """Test when no signals match."""
        matcher = PatternMatcher([race_pattern])
        results = matcher.match("This is clean code with no issues")
        assert len(results) == 0

    def test_case_insensitive_match(self, race_pattern: Pattern) -> None:
        """Test case-insensitive matching."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([race_pattern], threshold=0.4)
        results = matcher.match("RACE CONDITION in code")
        assert len(results) == 1

    def test_partial_match_below_threshold(self, race_pattern: Pattern) -> None:
        """Test partial match below threshold is filtered."""
        matcher = PatternMatcher([race_pattern], threshold=0.6)
        results = matcher.match("race condition")  # 0.5 confidence
        assert len(results) == 0  # Below 0.6 threshold

    def test_match_with_line_number(self, race_pattern: Pattern) -> None:
        """Test that line numbers are correctly extracted."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([race_pattern], threshold=0.4)
        text = "line 1\nline 2 has race condition\nline 3"
        results = matcher.match(text)
        assert len(results) == 1
        assert len(results[0].matched_signals) == 1
        assert results[0].matched_signals[0].line_number == 2


class TestPatternMatcherRegexMatching:
    """Tests for regex pattern matching."""

    @pytest.fixture
    def regex_pattern(self) -> Pattern:
        """Create a pattern with regex signals."""
        return Pattern(
            id=PatternId("CC-002"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="regex", pattern=r"\bgo\s+func\("),
                Signal(type="regex", pattern=r"\bgoroutine\b"),
            ],
            severity=Severity.ERROR,
        )

    def test_regex_match(self, regex_pattern: Pattern) -> None:
        """Test regex signal matching."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([regex_pattern], threshold=0.4)
        results = matcher.match("start a go func() to handle this")
        assert len(results) == 1

    def test_regex_word_boundary(self, regex_pattern: Pattern) -> None:
        """Test regex with word boundaries."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([regex_pattern], threshold=0.4)
        # "goroutine" at end with punctuation
        results = matcher.match("creating a goroutine.")
        assert len(results) == 1

    def test_regex_no_match(self, regex_pattern: Pattern) -> None:
        """Test regex when pattern doesn't match."""
        matcher = PatternMatcher([regex_pattern])
        results = matcher.match("This has no goroutines or go func")
        # "go func" without parentheses shouldn't match
        assert len(results) == 0

    def test_regex_captures_matched_text(self, regex_pattern: Pattern) -> None:
        """Test that regex captures the actual matched text."""
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([regex_pattern], threshold=0.4)
        results = matcher.match("use go func() for concurrency")
        assert len(results) == 1
        matched_text = results[0].matched_signals[0].matched_text
        assert "go func(" in matched_text


class TestPatternMatcherConfidence:
    """Tests for confidence calculation."""

    def test_confidence_all_signals_match(self) -> None:
        """Test 100% confidence when all signals match."""
        pattern = Pattern(
            id=PatternId("TEST-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="signal1"),
                Signal(type="exact", pattern="signal2"),
                Signal(type="exact", pattern="signal3"),
            ],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        results = matcher.match("signal1 signal2 signal3")
        assert len(results) == 1
        assert results[0].confidence == 1.0

    def test_confidence_partial_match(self) -> None:
        """Test confidence with partial matches."""
        pattern = Pattern(
            id=PatternId("TEST-002"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="signal1"),
                Signal(type="exact", pattern="signal2"),
                Signal(type="exact", pattern="signal3"),
            ],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        results = matcher.match("signal1 signal2")  # 2 of 3
        assert len(results) == 1
        assert results[0].confidence == pytest.approx(0.667, abs=0.01)

    def test_confidence_weighted_signals(self) -> None:
        """Test confidence with weighted signals."""
        pattern = Pattern(
            id=PatternId("TEST-003"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="alpha_signal", weight=2.0),
                Signal(type="exact", pattern="beta_signal", weight=1.0),
            ],
            severity=Severity.ERROR,
        )
        # Use lower threshold since pattern has 3 total weight and 1 matches = 0.333
        matcher = PatternMatcher([pattern], threshold=0.3)
        # Match only the less important signal (beta_signal is distinct)
        results = matcher.match("beta_signal")
        assert len(results) == 1
        # 1 / 3 = 0.333
        assert results[0].confidence == pytest.approx(0.333, abs=0.01)

    def test_confidence_weighted_signals_important(self) -> None:
        """Test confidence when matching important weighted signal."""
        pattern = Pattern(
            id=PatternId("TEST-004"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="important", weight=2.0),
                Signal(type="exact", pattern="less_important", weight=1.0),
            ],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        # Match only the important signal
        results = matcher.match("important")
        assert len(results) == 1
        # 2 / 3 = 0.667
        assert results[0].confidence == pytest.approx(0.667, abs=0.01)


class TestPatternMatcherThreshold:
    """Tests for threshold filtering."""

    @pytest.fixture
    def three_signal_pattern(self) -> Pattern:
        """Create a pattern with 3 signals."""
        return Pattern(
            id=PatternId("TEST-005"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="one"),
                Signal(type="exact", pattern="two"),
                Signal(type="exact", pattern="three"),
            ],
            severity=Severity.ERROR,
        )

    def test_threshold_60_percent(self, three_signal_pattern: Pattern) -> None:
        """Test default 60% threshold."""
        matcher = PatternMatcher([three_signal_pattern], threshold=0.6)
        # 2/3 = 66.7% > 60%, should match
        results = matcher.match("one two")
        assert len(results) == 1

    def test_threshold_70_percent(self, three_signal_pattern: Pattern) -> None:
        """Test 70% threshold filters 2/3 match."""
        matcher = PatternMatcher([three_signal_pattern], threshold=0.7)
        # 2/3 = 66.7% < 70%, should not match
        results = matcher.match("one two")
        assert len(results) == 0

    def test_threshold_100_percent(self, three_signal_pattern: Pattern) -> None:
        """Test 100% threshold requires all signals."""
        matcher = PatternMatcher([three_signal_pattern], threshold=1.0)
        # Only 2/3 match
        results = matcher.match("one two")
        assert len(results) == 0
        # All 3 match
        results = matcher.match("one two three")
        assert len(results) == 1


class TestPatternMatcherMultiplePatterns:
    """Tests for matching against multiple patterns."""

    @pytest.fixture
    def patterns(self) -> list[Pattern]:
        """Create multiple patterns."""
        return [
            Pattern(
                id=PatternId("CC-001"),
                domain=ArtifactDomain.CONCURRENCY,
                signals=[Signal(type="exact", pattern="race")],
                severity=Severity.CRITICAL,
            ),
            Pattern(
                id=PatternId("SEC-001"),
                domain=ArtifactDomain.SECURITY,
                signals=[Signal(type="exact", pattern="timing")],
                severity=Severity.ERROR,
            ),
            Pattern(
                id=PatternId("DB-001"),
                domain=ArtifactDomain.STORAGE,
                signals=[Signal(type="exact", pattern="index")],
                severity=Severity.WARNING,
            ),
        ]

    def test_match_multiple_patterns(self, patterns: list[Pattern]) -> None:
        """Test matching against multiple patterns."""
        matcher = PatternMatcher(patterns)
        results = matcher.match("race timing index")
        assert len(results) == 3

    def test_results_sorted_by_confidence(self, patterns: list[Pattern]) -> None:
        """Test results are sorted by confidence descending."""
        # Create patterns with different signal counts
        pattern1 = Pattern(
            id=PatternId("HIGH"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="one"),
                Signal(type="exact", pattern="two"),
            ],
            severity=Severity.ERROR,
        )
        pattern2 = Pattern(
            id=PatternId("LOW"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="one"),
                Signal(type="exact", pattern="two"),
                Signal(type="exact", pattern="three"),
            ],
            severity=Severity.ERROR,
        )
        # Use lower threshold since confidences are 0.5 and 0.333
        matcher = PatternMatcher([pattern1, pattern2], threshold=0.3)
        results = matcher.match("one")  # 50% for HIGH, 33% for LOW
        assert len(results) == 2
        assert results[0].pattern.id == PatternId("HIGH")  # Higher confidence first


class TestPatternMatcherMatchSingle:
    """Tests for match_single method."""

    @pytest.fixture
    def test_pattern(self) -> Pattern:
        """Create a test pattern."""
        return Pattern(
            id=PatternId("TEST-006"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="match"),
                Signal(type="exact", pattern="found"),
            ],
            severity=Severity.ERROR,
        )

    def test_match_single_match(self, test_pattern: Pattern) -> None:
        """Test match_single with match."""
        matcher = PatternMatcher([test_pattern])
        result = matcher.match_single("match found here", test_pattern)
        assert result is not None
        assert result.confidence == 1.0

    def test_match_single_no_match(self, test_pattern: Pattern) -> None:
        """Test match_single with no match (below threshold returns None)."""
        matcher = PatternMatcher([test_pattern])
        result = matcher.match_single("no relevant content", test_pattern)
        # Below threshold (0.0 < 0.6), should return None
        assert result is None

    def test_match_single_empty_text(self, test_pattern: Pattern) -> None:
        """Test match_single with empty text."""
        matcher = PatternMatcher([test_pattern])
        result = matcher.match_single("", test_pattern)
        assert result is None


class TestPatternMatcherMatchedSignals:
    """Tests for matched signal details."""

    def test_matched_signals_structure(self) -> None:
        """Test that matched signals have correct structure."""
        pattern = Pattern(
            id=PatternId("TEST-007"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="race"),
                Signal(type="regex", pattern=r"\bgo\s+func\("),
            ],
            severity=Severity.CRITICAL,
        )
        matcher = PatternMatcher([pattern])
        text = """line 1
        line 2 has race condition
        line 3 uses go func() here
        """
        results = matcher.match(text)
        assert len(results) == 1
        result = results[0]
        assert len(result.matched_signals) == 2

        # Check signal types
        signal_types = [ms.signal.type for ms in result.matched_signals]
        assert "exact" in signal_types
        assert "regex" in signal_types

    def test_matched_signal_line_numbers(self) -> None:
        """Test line number extraction for matched signals."""
        pattern = Pattern(
            id=PatternId("TEST-008"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="first"),
                Signal(type="exact", pattern="second"),
            ],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        text = "line 1 has first\nline 2 has second"
        results = matcher.match(text)
        assert len(results) == 1

        line_numbers = [ms.line_number for ms in results[0].matched_signals]
        assert 1 in line_numbers
        assert 2 in line_numbers

    def test_unmatched_signals(self) -> None:
        """Test that unmatched signals are tracked."""
        pattern = Pattern(
            id=PatternId("TEST-009"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="match"),
                Signal(type="exact", pattern="no_match"),
            ],
            severity=Severity.ERROR,
        )
        # Use lower threshold since pattern has 2 signals and 1 matches = 0.5
        matcher = PatternMatcher([pattern], threshold=0.4)
        results = matcher.match("match")
        assert len(results) == 1
        assert len(results[0].matched_signals) == 1
        assert len(results[0].unmatched_signals) == 1


class TestPatternMatcherEdgeCases:
    """Tests for edge cases."""

    def test_empty_text(self) -> None:
        """Test matching against empty text."""
        pattern = Pattern(
            id=PatternId("TEST-010"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[Signal(type="exact", pattern="test")],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        results = matcher.match("")
        assert len(results) == 0

    def test_empty_patterns(self) -> None:
        """Test matching with no patterns."""
        matcher = PatternMatcher([])
        results = matcher.match("some text with content")
        assert len(results) == 0

    def test_pattern_with_no_signals(self) -> None:
        """Test pattern with no signals."""
        pattern = Pattern(
            id=PatternId("TEST-011"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        results = matcher.match("some text")
        assert len(results) == 0  # 0/0 signals = 0 confidence

    def test_unicode_text(self) -> None:
        """Test matching in unicode text."""
        pattern = Pattern(
            id=PatternId("TEST-012"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[Signal(type="exact", pattern="naïve")],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        results = matcher.match("naïve approach")
        assert len(results) == 1

    def test_multiline_match(self) -> None:
        """Test matching across multiple lines."""
        pattern = Pattern(
            id=PatternId("TEST-013"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[Signal(type="exact", pattern="line")],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern])
        text = "line 1\nline 2\nline 3"
        results = matcher.match(text)
        assert len(results) == 1
        # Should match on first occurrence
        assert results[0].matched_signals[0].line_number == 1


class TestPatternMatcherWithRealPatterns:
    """Tests using actual pattern definitions."""

    def test_cc_004_check_then_act(self) -> None:
        """Test CC-004 pattern (check-then-act)."""
        pattern = Pattern(
            id=PatternId("CC-004"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="check then act"),
                Signal(type="exact", pattern="check-then-act"),
                Signal(type="regex", pattern=r"\bif\s+.*len\s*\(.*\).*append"),
                Signal(type="regex", pattern=r"\bif\s+.*nil\s*\{[^}]*create"),
            ],
            severity=Severity.CRITICAL,
        )
        matcher = PatternMatcher([pattern], threshold=0.25)

        code = """
        if len(items) > 0 {
            items = append(items, newItem)
        }
        """
        results = matcher.match(code)
        assert len(results) == 1

    def test_sec_004_auth_bypass(self) -> None:
        """Test SEC-004 pattern (auth bypass)."""
        pattern = Pattern(
            id=PatternId("SEC-004"),
            domain=ArtifactDomain.SECURITY,
            signals=[
                Signal(type="exact", pattern="auth bypass"),
                Signal(type="exact", pattern="authentication bypass"),
                Signal(type="exact", pattern="skip auth"),
                Signal(type="exact", pattern="bypass check"),
            ],
            severity=Severity.CRITICAL,
        )
        # Use lower threshold since pattern has 4 signals and 1 matches = 0.25
        matcher = PatternMatcher([pattern], threshold=0.2)

        code = "TODO: remove auth bypass before production"
        results = matcher.match(code)
        assert len(results) == 1
        assert results[0].confidence == 0.25  # 1 of 4 signals

    def test_db_003_toctou(self) -> None:
        """Test DB-003 pattern (TOCTOU in storage)."""
        pattern = Pattern(
            id=PatternId("DB-003"),
            domain=ArtifactDomain.STORAGE,
            signals=[
                Signal(type="exact", pattern="check then write"),
                Signal(type="exact", pattern="exists then insert"),
                Signal(type="exact", pattern="find then create"),
                Signal(type="regex", pattern=r"\bif\s+.*[Ee]xists\s*\("),
            ],
            severity=Severity.ERROR,
        )
        matcher = PatternMatcher([pattern], threshold=0.25)

        code = "if recordExists(id) { insertRecord(id, data) }"
        results = matcher.match(code)
        assert len(results) >= 1  # May match multiple signals
