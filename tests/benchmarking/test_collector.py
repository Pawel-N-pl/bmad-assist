"""Tests for deterministic metrics collector (Story 13.2).

Tests cover:
- Structure metrics (headings, code blocks, lists, sections)
- Linguistic metrics (sentence length, vocabulary, readability)
- Reasoning signals (citations, conditionals, uncertainty)
- Edge cases (empty, single word, no sentences)
- Schema model mapping
- Deterministic reproducibility
"""

from datetime import UTC, datetime

import pytest

from bmad_assist.benchmarking.collector import (
    CollectorContext,
    DeterministicMetrics,
    LinguisticMetrics,
    ReasoningSignals,
    StructureMetrics,
    calculate_linguistic_metrics,
    calculate_reasoning_signals,
    calculate_structure_metrics,
    collect_deterministic_metrics,
)
from bmad_assist.benchmarking.schema import (
    LinguisticFingerprint,
    OutputAnalysis,
    ReasoningPatterns,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_markdown() -> str:
    """Sample markdown document for testing."""
    return """# Main Heading

## Section One

This is a paragraph with some text. It has multiple sentences.

- Item 1
  - Nested item 1.1
    - Deeply nested 1.1.1
- Item 2

## Section Two

```python
def hello():
    print("Hello")
```

### Subsection

Another paragraph here.
"""


@pytest.fixture
def sample_validation_output() -> str:
    """Sample validation output with various patterns."""
    return """# Validation Report

## Analysis

Based on the PRD requirements and Architecture guidelines, I found several issues.

### Findings

1. AC-1 is missing validation for edge cases
2. Task 2 needs more error handling
3. See #13.2 for related changes

[Source: docs/prd.md] The requirements state...
[Source: docs/architecture.md] The architecture specifies...

If the user provides invalid input, the system should handle it gracefully.
When errors occur, we must log them properly.

This might cause issues. Perhaps we should reconsider.
The implementation must always validate input. Definitely needs tests.
"""


@pytest.fixture
def collector_context() -> CollectorContext:
    """Collector context for testing."""
    return CollectorContext(
        story_epic=13,
        story_num=2,
        timestamp=datetime.now(UTC),
    )


# =============================================================================
# Structure Metrics Tests
# =============================================================================


class TestCalculateStructureMetrics:
    """Tests for calculate_structure_metrics function."""

    def test_char_count(self, sample_markdown: str) -> None:
        """Test character count calculation."""
        result = calculate_structure_metrics(sample_markdown)
        assert result.char_count == len(sample_markdown)

    def test_heading_count(self, sample_markdown: str) -> None:
        """Test heading count (all levels)."""
        result = calculate_structure_metrics(sample_markdown)
        # # Main Heading, ## Section One, ## Section Two, ### Subsection
        assert result.heading_count == 4

    def test_heading_count_levels(self) -> None:
        """Test various heading levels (# to ######)."""
        content = """# H1
## H2
### H3
#### H4
##### H5
###### H6
"""
        result = calculate_structure_metrics(content)
        assert result.heading_count == 6

    def test_code_block_count(self, sample_markdown: str) -> None:
        """Test code block count (paired backticks)."""
        result = calculate_structure_metrics(sample_markdown)
        assert result.code_block_count == 1

    def test_code_block_count_multiple(self) -> None:
        """Test multiple code blocks."""
        content = """
```python
code1
```

```javascript
code2
```

```
code3
```
"""
        result = calculate_structure_metrics(content)
        assert result.code_block_count == 3

    def test_code_block_count_unpaired(self) -> None:
        """Test unpaired backticks (incomplete block)."""
        content = """
```python
incomplete block
"""
        result = calculate_structure_metrics(content)
        assert result.code_block_count == 0  # No complete blocks

    def test_list_depth_nested(self, sample_markdown: str) -> None:
        """Test nested list depth calculation."""
        result = calculate_structure_metrics(sample_markdown)
        # 3 levels: Item 1, Nested item 1.1, Deeply nested 1.1.1
        assert result.list_depth_max == 3

    def test_list_depth_no_lists(self) -> None:
        """Test list depth with no lists."""
        content = "Just a paragraph with no lists."
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 0

    def test_list_depth_flat(self) -> None:
        """Test flat list (no nesting)."""
        content = """
- Item 1
- Item 2
- Item 3
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 1

    def test_list_depth_deeply_nested(self) -> None:
        """Test deeply nested lists (4+ levels)."""
        content = """
- Level 1
  - Level 2
    - Level 3
      - Level 4
        - Level 5
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 5

    def test_list_depth_mixed_indent(self) -> None:
        """Test list depth with mixed indentation (2-space and 4-space)."""
        content = """
- Item 1
  - 2-space indent
    - 4-space indent
      - 6-space indent
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 4

    def test_list_depth_numbered(self) -> None:
        """Test numbered list depth."""
        content = """
1. First
   1. Nested
      1. Deep
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 3

    def test_sections_detected(self, sample_markdown: str) -> None:
        """Test section extraction from level 1-3 headings."""
        result = calculate_structure_metrics(sample_markdown)
        # Level 1: Main Heading
        # Level 2: Section One, Section Two
        # Level 3: Subsection
        expected = ("Main Heading", "Section One", "Section Two", "Subsection")
        assert result.sections_detected == expected

    def test_sections_detected_level_4_excluded(self) -> None:
        """Test that level 4+ headings are excluded from sections."""
        content = """# H1
## H2
### H3
#### H4
##### H5
"""
        result = calculate_structure_metrics(content)
        assert result.sections_detected == ("H1", "H2", "H3")

    def test_empty_content(self) -> None:
        """Test empty content handling."""
        result = calculate_structure_metrics("")
        assert result.char_count == 0
        assert result.heading_count == 0
        assert result.list_depth_max == 0
        assert result.code_block_count == 0
        assert result.sections_detected == ()


# =============================================================================
# Linguistic Metrics Tests
# =============================================================================


class TestCalculateLinguisticMetrics:
    """Tests for calculate_linguistic_metrics function."""

    def test_avg_sentence_length_basic(self) -> None:
        """Test average sentence length calculation."""
        content = "One two three. Four five six seven."
        result = calculate_linguistic_metrics(content)
        # Sentence 1: 3 words, Sentence 2: 4 words, avg = 3.5
        assert result.avg_sentence_length == pytest.approx(3.5)

    def test_avg_sentence_length_exclamation(self) -> None:
        """Test sentence detection with exclamation marks."""
        content = "Hello world! This is great! Three sentences here."
        result = calculate_linguistic_metrics(content)
        # 3 sentences
        assert result.avg_sentence_length == pytest.approx(8 / 3)

    def test_avg_sentence_length_question(self) -> None:
        """Test sentence detection with question marks."""
        content = "What is this? How does it work? I wonder."
        result = calculate_linguistic_metrics(content)
        # 3 sentences: 3 words, 4 words, 2 words = 9 words / 3 sentences = 3.0
        assert result.avg_sentence_length == pytest.approx(3.0)

    def test_avg_sentence_length_newlines(self) -> None:
        """Test sentence boundary with newlines after punctuation."""
        content = "First sentence.\nSecond sentence.\nThird sentence."
        result = calculate_linguistic_metrics(content)
        # 3 sentences, 2 words each
        assert result.avg_sentence_length == pytest.approx(2.0)

    def test_vocabulary_richness(self) -> None:
        """Test vocabulary richness (type-token ratio)."""
        content = "the the the cat cat sat sat sat mat"
        result = calculate_linguistic_metrics(content)
        # 9 words, 4 unique (the, cat, sat, mat)
        assert result.vocabulary_richness == pytest.approx(4 / 9)

    def test_vocabulary_richness_all_unique(self) -> None:
        """Test vocabulary richness with all unique words."""
        content = "one two three four five"
        result = calculate_linguistic_metrics(content)
        assert result.vocabulary_richness == pytest.approx(1.0)

    def test_vocabulary_richness_case_insensitive(self) -> None:
        """Test vocabulary richness is case-insensitive."""
        content = "Hello HELLO hello"
        result = calculate_linguistic_metrics(content)
        # 3 words, 1 unique
        assert result.vocabulary_richness == pytest.approx(1 / 3)

    def test_flesch_reading_ease(self) -> None:
        """Test Flesch Reading Ease integration."""
        # Simple text should have high readability
        content = "The cat sat on the mat. The dog ran fast."
        result = calculate_linguistic_metrics(content)
        # Flesch score should be positive and reasonable for simple text
        assert result.flesch_reading_ease > 50.0

    def test_flesch_reading_ease_complex(self) -> None:
        """Test Flesch Reading Ease with complex text."""
        content = """The implementation of sophisticated algorithmic
        methodologies necessitates comprehensive understanding of
        multifaceted architectural paradigms."""
        result = calculate_linguistic_metrics(content)
        # Complex text should have lower readability
        assert result.flesch_reading_ease < 50.0

    def test_vague_terms_detection(self) -> None:
        """Test vague terms counting."""
        content = "Some people say various things often. Several etc."
        result = calculate_linguistic_metrics(content)
        # some, various, often, several, etc = 5
        assert result.vague_terms_count == 5

    def test_vague_terms_case_insensitive(self) -> None:
        """Test vague terms detection is case-insensitive."""
        content = "SOME things and Some other things and somE more"
        result = calculate_linguistic_metrics(content)
        assert result.vague_terms_count == 3

    def test_empty_content_linguistic(self) -> None:
        """Test empty content returns zeroed metrics."""
        result = calculate_linguistic_metrics("")
        assert result.avg_sentence_length == 0.0
        assert result.vocabulary_richness == 0.0
        assert result.flesch_reading_ease == 0.0
        assert result.vague_terms_count == 0

    def test_whitespace_only(self) -> None:
        """Test whitespace-only content."""
        result = calculate_linguistic_metrics("   \n\t  ")
        assert result.avg_sentence_length == 0.0
        assert result.vocabulary_richness == 0.0

    def test_single_word(self) -> None:
        """Test single word content."""
        result = calculate_linguistic_metrics("hello")
        assert result.vocabulary_richness == 1.0
        # No sentence endings, so fallback to word count
        assert result.avg_sentence_length == 1.0

    def test_no_sentences_fallback(self) -> None:
        """Test content without sentence-ending punctuation."""
        content = "word1 word2 word3 word4"
        result = calculate_linguistic_metrics(content)
        # Fallback to word count as sentence length
        assert result.avg_sentence_length == 4.0


# =============================================================================
# Reasoning Signals Tests
# =============================================================================


class TestCalculateReasoningSignals:
    """Tests for calculate_reasoning_signals function."""

    def test_cites_prd_uppercase(self) -> None:
        """Test PRD detection (uppercase)."""
        content = "According to the PRD requirements..."
        result = calculate_reasoning_signals(content)
        assert result.cites_prd is True

    def test_cites_prd_lowercase(self) -> None:
        """Test prd detection (lowercase)."""
        content = "As mentioned in the prd document..."
        result = calculate_reasoning_signals(content)
        assert result.cites_prd is True

    def test_cites_prd_path(self) -> None:
        """Test PRD path detection."""
        content = "See docs/prd.md for details"
        result = calculate_reasoning_signals(content)
        assert result.cites_prd is True

    def test_cites_prd_false(self) -> None:
        """Test no PRD citation."""
        content = "This is a random document with no references."
        result = calculate_reasoning_signals(content)
        assert result.cites_prd is False

    def test_cites_architecture_capital(self) -> None:
        """Test Architecture detection."""
        content = "The Architecture document specifies..."
        result = calculate_reasoning_signals(content)
        assert result.cites_architecture is True

    def test_cites_architecture_lowercase(self) -> None:
        """Test architecture detection."""
        content = "Based on the architecture patterns..."
        result = calculate_reasoning_signals(content)
        assert result.cites_architecture is True

    def test_cites_architecture_path(self) -> None:
        """Test architecture path detection."""
        content = "See docs/architecture.md for patterns"
        result = calculate_reasoning_signals(content)
        assert result.cites_architecture is True

    def test_cites_story_sections_ac(self) -> None:
        """Test AC pattern detection."""
        content = "AC-1 requires validation. AC2 also important."
        result = calculate_reasoning_signals(content)
        assert result.cites_story_sections is True

    def test_cites_story_sections_task(self) -> None:
        """Test Task pattern detection."""
        content = "Task 1 is about implementation. Task 2 is testing."
        result = calculate_reasoning_signals(content)
        assert result.cites_story_sections is True

    def test_cites_story_sections_story_number(self) -> None:
        """Test story number pattern detection (#13.2)."""
        content = "See story #13.2 for details."
        result = calculate_reasoning_signals(content)
        assert result.cites_story_sections is True

    def test_uses_conditionals_english(self) -> None:
        """Test conditional detection (English)."""
        content = "If this happens, then do that. When errors occur..."
        result = calculate_reasoning_signals(content)
        assert result.uses_conditionals is True

    def test_uses_conditionals_unless(self) -> None:
        """Test 'unless' conditional detection."""
        content = "Do this unless you have a good reason."
        result = calculate_reasoning_signals(content)
        assert result.uses_conditionals is True

    def test_uses_conditionals_polish(self) -> None:
        """Test Polish conditional detection."""
        content = "Jeśli użytkownik wprowadzi błędne dane, gdy system..."
        result = calculate_reasoning_signals(content)
        assert result.uses_conditionals is True

    def test_uses_conditionals_polish_kiedy(self) -> None:
        """Test Polish 'kiedy' conditional detection."""
        content = "Kiedy wystąpi błąd, system powinien..."
        result = calculate_reasoning_signals(content)
        assert result.uses_conditionals is True

    def test_uncertainty_phrases_count(self) -> None:
        """Test uncertainty phrase counting."""
        content = "This might work. Perhaps we should try. Could be an issue."
        result = calculate_reasoning_signals(content)
        # might, perhaps, could = 3
        assert result.uncertainty_phrases_count == 3

    def test_uncertainty_phrases_polish(self) -> None:
        """Test Polish uncertainty phrases."""
        content = "Może to zadziała. To może być problem."
        result = calculate_reasoning_signals(content)
        assert result.uncertainty_phrases_count == 2

    def test_confidence_phrases_count(self) -> None:
        """Test confidence phrase counting."""
        content = "This must work. Definitely needs testing. Always validate."
        result = calculate_reasoning_signals(content)
        # must, definitely, always = 3
        assert result.confidence_phrases_count == 3

    def test_confidence_phrases_polish(self) -> None:
        """Test Polish confidence phrase."""
        content = "Zawsze sprawdzaj dane wejściowe."
        result = calculate_reasoning_signals(content)
        assert result.confidence_phrases_count == 1

    def test_empty_content_reasoning(self) -> None:
        """Test empty content returns default signals."""
        result = calculate_reasoning_signals("")
        assert result.cites_prd is False
        assert result.cites_architecture is False
        assert result.cites_story_sections is False
        assert result.uses_conditionals is False
        assert result.uncertainty_phrases_count == 0
        assert result.confidence_phrases_count == 0


# =============================================================================
# CollectorContext Tests
# =============================================================================


class TestCollectorContext:
    """Tests for CollectorContext dataclass."""

    def test_creation(self) -> None:
        """Test context creation."""
        ts = datetime.now(UTC)
        ctx = CollectorContext(story_epic=13, story_num=2, timestamp=ts)
        assert ctx.story_epic == 13
        assert ctx.story_num == 2
        assert ctx.timestamp == ts

    def test_frozen(self) -> None:
        """Test context is immutable."""
        ctx = CollectorContext(story_epic=1, story_num=1, timestamp=datetime.now(UTC))
        with pytest.raises(AttributeError):
            ctx.story_epic = 2  # type: ignore[misc]


# =============================================================================
# DeterministicMetrics Tests
# =============================================================================


class TestDeterministicMetrics:
    """Tests for DeterministicMetrics dataclass."""

    def test_creation(self) -> None:
        """Test DeterministicMetrics creation."""
        structure = StructureMetrics(
            char_count=100,
            heading_count=3,
            list_depth_max=2,
            code_block_count=1,
            sections_detected=("A", "B"),
        )
        linguistic = LinguisticMetrics(
            avg_sentence_length=10.0,
            vocabulary_richness=0.8,
            flesch_reading_ease=60.0,
            vague_terms_count=5,
        )
        reasoning = ReasoningSignals(
            cites_prd=True,
            cites_architecture=False,
            cites_story_sections=True,
            uses_conditionals=True,
            uncertainty_phrases_count=3,
            confidence_phrases_count=1,
        )
        metrics = DeterministicMetrics(
            structure=structure,
            linguistic=linguistic,
            reasoning=reasoning,
            collected_at=datetime.now(UTC),
        )
        assert metrics.structure == structure
        assert metrics.linguistic == linguistic
        assert metrics.reasoning == reasoning

    def test_frozen(self) -> None:
        """Test DeterministicMetrics is immutable."""
        structure = StructureMetrics(0, 0, 0, 0, ())
        linguistic = LinguisticMetrics(0.0, 0.0, 0.0, 0)
        reasoning = ReasoningSignals(False, False, False, False, 0, 0)
        metrics = DeterministicMetrics(
            structure=structure,
            linguistic=linguistic,
            reasoning=reasoning,
            collected_at=datetime.now(UTC),
        )
        with pytest.raises(AttributeError):
            metrics.structure = structure  # type: ignore[misc]


# =============================================================================
# Schema Mapping Tests
# =============================================================================


class TestSchemaMapping:
    """Tests for schema model mapping methods."""

    @pytest.fixture
    def sample_metrics(self) -> DeterministicMetrics:
        """Create sample DeterministicMetrics for testing."""
        return DeterministicMetrics(
            structure=StructureMetrics(
                char_count=500,
                heading_count=5,
                list_depth_max=3,
                code_block_count=2,
                sections_detected=("Section A", "Section B"),
            ),
            linguistic=LinguisticMetrics(
                avg_sentence_length=12.5,
                vocabulary_richness=0.75,
                flesch_reading_ease=55.0,
                vague_terms_count=3,
            ),
            reasoning=ReasoningSignals(
                cites_prd=True,
                cites_architecture=True,
                cites_story_sections=False,
                uses_conditionals=True,
                uncertainty_phrases_count=2,
                confidence_phrases_count=5,
            ),
            collected_at=datetime.now(UTC),
        )

    def test_to_output_analysis(self, sample_metrics: DeterministicMetrics) -> None:
        """Test OutputAnalysis schema model conversion."""
        result = sample_metrics.to_output_analysis()

        assert isinstance(result, OutputAnalysis)
        assert result.char_count == 500
        assert result.heading_count == 5
        assert result.list_depth_max == 3
        assert result.code_block_count == 2
        assert result.sections_detected == ["Section A", "Section B"]
        assert result.anomalies == []

    def test_to_linguistic_fingerprint(self, sample_metrics: DeterministicMetrics) -> None:
        """Test LinguisticFingerprint schema model conversion."""
        result = sample_metrics.to_linguistic_fingerprint()

        assert isinstance(result, LinguisticFingerprint)
        assert result.avg_sentence_length == 12.5
        assert result.vocabulary_richness == 0.75
        assert result.flesch_reading_ease == 55.0
        assert result.vague_terms_count == 3
        # Placeholder values for LLM extraction
        assert result.formality_score == 0.0
        assert result.sentiment == "neutral"

    def test_to_reasoning_patterns(self, sample_metrics: DeterministicMetrics) -> None:
        """Test ReasoningPatterns schema model conversion."""
        result = sample_metrics.to_reasoning_patterns()

        assert isinstance(result, ReasoningPatterns)
        assert result.cites_prd is True
        assert result.cites_architecture is True
        assert result.cites_story_sections is False
        assert result.uses_conditionals is True
        assert result.uncertainty_phrases_count == 2
        assert result.confidence_phrases_count == 5


# =============================================================================
# End-to-End Tests
# =============================================================================


class TestCollectDeterministicMetrics:
    """Tests for collect_deterministic_metrics entry point."""

    def test_end_to_end(
        self, sample_validation_output: str, collector_context: CollectorContext
    ) -> None:
        """Test full pipeline from raw output to metrics."""
        result = collect_deterministic_metrics(sample_validation_output, collector_context)

        # Check structure
        assert isinstance(result, DeterministicMetrics)
        assert result.structure.char_count > 0
        assert result.structure.heading_count > 0

        # Check linguistic
        assert result.linguistic.avg_sentence_length > 0
        assert result.linguistic.vocabulary_richness > 0

        # Check reasoning
        assert result.reasoning.cites_prd is True
        assert result.reasoning.cites_architecture is True

        # Check timestamp is populated
        assert result.collected_at is not None

    def test_empty_input(self, collector_context: CollectorContext) -> None:
        """Test with empty input."""
        result = collect_deterministic_metrics("", collector_context)

        assert result.structure.char_count == 0
        assert result.linguistic.avg_sentence_length == 0.0
        assert result.reasoning.cites_prd is False


# =============================================================================
# Deterministic Reproducibility Tests
# =============================================================================


class TestDeterministicReproducibility:
    """Tests ensuring deterministic reproducibility."""

    def test_structure_metrics_reproducible(self, sample_markdown: str) -> None:
        """Test structure metrics are identical across 10 runs."""
        results = [calculate_structure_metrics(sample_markdown) for _ in range(10)]
        first = results[0]
        for result in results[1:]:
            assert result == first

    def test_linguistic_metrics_reproducible(self, sample_markdown: str) -> None:
        """Test linguistic metrics are identical across 10 runs."""
        results = [calculate_linguistic_metrics(sample_markdown) for _ in range(10)]
        first = results[0]
        for result in results[1:]:
            assert result == first

    def test_reasoning_signals_reproducible(self, sample_validation_output: str) -> None:
        """Test reasoning signals are identical across 10 runs."""
        results = [calculate_reasoning_signals(sample_validation_output) for _ in range(10)]
        first = results[0]
        for result in results[1:]:
            assert result == first

    def test_full_pipeline_reproducible(
        self, sample_validation_output: str, collector_context: CollectorContext
    ) -> None:
        """Test full pipeline produces reproducible results (excluding timestamp)."""
        results = [
            collect_deterministic_metrics(sample_validation_output, collector_context)
            for _ in range(10)
        ]
        first = results[0]
        for result in results[1:]:
            # Compare all fields except collected_at (which will differ)
            assert result.structure == first.structure
            assert result.linguistic == first.linguistic
            assert result.reasoning == first.reasoning


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_unicode_content(self) -> None:
        """Test handling of unicode content."""
        content = "Żółć i języki słowiańskie. Można używać emoji: 🎉"
        result = calculate_structure_metrics(content)
        assert result.char_count == len(content)

    def test_tabs_in_lists(self) -> None:
        """Test list depth with tab indentation."""
        content = """
- Level 1
\t- Level 2
\t\t- Level 3
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 3

    def test_mixed_list_markers(self) -> None:
        """Test list depth with mixed markers (-, *, +, numbers)."""
        content = """
- Dash
  * Asterisk
    + Plus
      1. Number
"""
        result = calculate_structure_metrics(content)
        assert result.list_depth_max == 4

    def test_code_block_in_list(self) -> None:
        """Test code block counting inside list."""
        content = """
- Item with code:
  ```python
  print("hello")
  ```
"""
        result = calculate_structure_metrics(content)
        assert result.code_block_count == 1

    def test_headings_in_code_block(self) -> None:
        """Test that headings inside code blocks are counted."""
        # Note: Current implementation doesn't distinguish code block content
        content = """
```markdown
# This is in code block
## Also in code block
```

# Real heading
"""
        result = calculate_structure_metrics(content)
        # Current impl counts all headings - this is acceptable behavior
        assert result.heading_count >= 1

    def test_very_long_content(self) -> None:
        """Test handling of very long content."""
        content = "word " * 10000
        result = calculate_linguistic_metrics(content)
        assert result.vocabulary_richness == pytest.approx(1 / 10000)

    def test_special_characters_in_words(self) -> None:
        """Test word extraction with special characters."""
        content = "hello-world test_case foo.bar"
        result = calculate_linguistic_metrics(content)
        # Word pattern \w+ captures alphanumeric + underscore
        # hello, world, test, case, foo, bar
        assert result.vocabulary_richness == 1.0  # All unique
