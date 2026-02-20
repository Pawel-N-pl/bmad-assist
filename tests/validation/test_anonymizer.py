"""Tests for validation anonymizer module.

This module tests the anonymizer functionality for Multi-LLM validation synthesis.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest


class TestModuleStructure:
    """Tests for module structure and imports (AC: #1)."""

    def test_module_exists(self) -> None:
        """Module can be imported."""
        from bmad_assist.validation import anonymizer

        assert anonymizer is not None

    def test_public_api_exports(self) -> None:
        """Public API is exported from __init__.py."""
        from bmad_assist.validation import (
            AnonymizationMapping,
            AnonymizedValidation,
            ValidationOutput,
            anonymize_validations,
            get_mapping,
            save_mapping,
        )

        assert ValidationOutput is not None
        assert AnonymizedValidation is not None
        assert AnonymizationMapping is not None
        assert anonymize_validations is not None
        assert save_mapping is not None
        assert get_mapping is not None


class TestValidationOutput:
    """Tests for ValidationOutput dataclass (AC: #2)."""

    def test_frozen_immutable(self) -> None:
        """ValidationOutput cannot be modified after creation."""
        from bmad_assist.validation import ValidationOutput

        output = ValidationOutput(
            provider="claude",
            model="claude-sonnet-4",
            content="Test content",
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
        )

        with pytest.raises(AttributeError):
            output.provider = "gemini"  # type: ignore[misc]

    def test_all_fields_required(self) -> None:
        """All fields must be provided."""
        from bmad_assist.validation import ValidationOutput

        # Should work with all fields
        output = ValidationOutput(
            provider="claude",
            model="claude-sonnet-4",
            content="Test content",
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
        )
        assert output.provider == "claude"
        assert output.model == "claude-sonnet-4"
        assert output.content == "Test content"
        assert output.duration_ms == 1000
        assert output.token_count == 100


class TestAnonymizedValidation:
    """Tests for AnonymizedValidation dataclass (AC: #3)."""

    def test_frozen_immutable(self) -> None:
        """AnonymizedValidation cannot be modified after creation."""
        from bmad_assist.validation import AnonymizedValidation

        anon = AnonymizedValidation(
            validator_id="Validator A",
            content="Test content",
            original_ref="550e8400-e29b-41d4-a716-446655440000",
        )

        with pytest.raises(AttributeError):
            anon.validator_id = "Validator B"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        """All fields are present."""
        from bmad_assist.validation import AnonymizedValidation

        anon = AnonymizedValidation(
            validator_id="Validator A",
            content="Anonymized content",
            original_ref="550e8400-e29b-41d4-a716-446655440000",
        )
        assert anon.validator_id == "Validator A"
        assert anon.content == "Anonymized content"
        assert anon.original_ref == "550e8400-e29b-41d4-a716-446655440000"


class TestAnonymizationMapping:
    """Tests for AnonymizationMapping dataclass."""

    def test_frozen_immutable(self) -> None:
        """AnonymizationMapping cannot be modified after creation."""
        from bmad_assist.validation import AnonymizationMapping

        mapping = AnonymizationMapping(
            session_id="test-session",
            timestamp=datetime.now(UTC),
            mapping={},
        )

        with pytest.raises(AttributeError):
            mapping.session_id = "new-session"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        """All fields are present."""
        from bmad_assist.validation import AnonymizationMapping

        now = datetime.now(UTC)
        mapping = AnonymizationMapping(
            session_id="test-session",
            timestamp=now,
            mapping={"Validator A": {"provider": "claude"}},
        )
        assert mapping.session_id == "test-session"
        assert mapping.timestamp == now
        assert mapping.mapping == {"Validator A": {"provider": "claude"}}


class TestAnonymizeValidations:
    """Tests for anonymize_validations() function (AC: #1, #7)."""

    def _make_output(
        self, provider: str, model: str = "test-model", content: str = "Test content"
    ) -> "ValidationOutput":
        """Helper to create ValidationOutput instances."""
        from bmad_assist.validation import ValidationOutput

        return ValidationOutput(
            provider=provider,
            model=model,
            content=content,
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
        )

    def test_four_validators_standard_case(self) -> None:
        """Four validators get Validator A, B, C, D (AC: #1)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [
            self._make_output("claude", "claude-sonnet-4"),
            self._make_output("gemini", "gemini-2.5-pro"),
            self._make_output("gpt", "gpt-5"),
            self._make_output("master", "claude-opus-4"),
        ]

        anonymized, mapping = anonymize_validations(outputs)

        # Check we got 4 anonymized outputs
        assert len(anonymized) == 4

        # Check validator IDs are A, B, C, D (in any order due to shuffle)
        validator_ids = {a.validator_id for a in anonymized}
        assert validator_ids == {"Validator A", "Validator B", "Validator C", "Validator D"}

        # Check mapping has all 4 validators
        assert len(mapping.mapping) == 4
        assert set(mapping.mapping.keys()) == validator_ids

        # Check each mapping has required fields
        for validator_id, data in mapping.mapping.items():
            assert "provider" in data
            assert "model" in data
            assert "original_ref" in data
            assert "timestamp" in data
            assert "duration_ms" in data
            assert "token_count" in data

    def test_two_validators_only_ab(self) -> None:
        """Two validators only get Validator A, B (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [
            self._make_output("claude"),
            self._make_output("gemini"),
        ]

        anonymized, mapping = anonymize_validations(outputs)

        assert len(anonymized) == 2
        validator_ids = {a.validator_id for a in anonymized}
        assert validator_ids == {"Validator A", "Validator B"}
        assert len(mapping.mapping) == 2

    def test_single_validator(self) -> None:
        """Single validator gets Validator A (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [self._make_output("claude")]

        anonymized, mapping = anonymize_validations(outputs)

        assert len(anonymized) == 1
        assert anonymized[0].validator_id == "Validator A"
        assert len(mapping.mapping) == 1

    def test_five_validators(self) -> None:
        """Five validators extend to E (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [
            self._make_output("claude"),
            self._make_output("gemini"),
            self._make_output("gpt"),
            self._make_output("master"),
            self._make_output("claude"),  # duplicate provider is valid
        ]

        anonymized, mapping = anonymize_validations(outputs)

        assert len(anonymized) == 5
        validator_ids = {a.validator_id for a in anonymized}
        assert validator_ids == {
            "Validator A",
            "Validator B",
            "Validator C",
            "Validator D",
            "Validator E",
        }

    def test_27_validators_raises(self) -> None:
        """27 validators exceeds A-Z limit and raises ValueError (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [self._make_output(f"provider-{i}") for i in range(27)]

        with pytest.raises(ValueError, match="26"):
            anonymize_validations(outputs)

    def test_empty_list_returns_empty(self) -> None:
        """Empty input returns empty output, no error (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        anonymized, mapping = anonymize_validations([])

        assert anonymized == []
        assert mapping.mapping == {}
        assert mapping.session_id  # should have valid session_id
        assert mapping.timestamp  # should have valid timestamp

    def test_randomizes_assignment_order(self) -> None:
        """Multiple calls produce different orderings (AC: #1).

        Run 10 times, verify at least 2 different orderings to confirm
        random.shuffle() is being used. This prevents model bias.
        """
        from bmad_assist.validation import anonymize_validations

        outputs = [
            self._make_output("claude"),
            self._make_output("gemini"),
            self._make_output("gpt"),
            self._make_output("master"),
        ]

        # Collect provider-to-validator mappings from multiple runs
        orderings = set()
        for _ in range(10):
            _, mapping = anonymize_validations(outputs)
            # Create a tuple of (provider, validator_id) sorted by validator_id
            ordering = tuple(
                sorted(
                    ((data["provider"], vid) for vid, data in mapping.mapping.items()),
                    key=lambda x: x[1],  # sort by validator_id
                )
            )
            orderings.add(ordering)

        # With random shuffle, we should see at least 2 different orderings in 10 runs
        # (probability of all 10 being identical is 1/(4!)^9 ≈ 0)
        assert len(orderings) >= 2, "Expected at least 2 different orderings in 10 runs"

    def test_duplicate_provider_unique_ids(self) -> None:
        """Same provider twice gets two different validator IDs (AC: #7)."""
        from bmad_assist.validation import anonymize_validations

        outputs = [
            self._make_output("claude", "claude-sonnet-4", "First output"),
            self._make_output("claude", "claude-opus-4", "Second output"),
        ]

        anonymized, mapping = anonymize_validations(outputs)

        assert len(anonymized) == 2
        # Different validator IDs
        assert anonymized[0].validator_id != anonymized[1].validator_id
        # Different original_refs (UUIDs)
        assert anonymized[0].original_ref != anonymized[1].original_ref

    def test_original_ref_is_uuid(self) -> None:
        """Each anonymized validation has a valid UUID as original_ref."""
        import uuid

        from bmad_assist.validation import anonymize_validations

        outputs = [self._make_output("claude")]
        anonymized, mapping = anonymize_validations(outputs)

        # Verify original_ref is a valid UUID
        ref = anonymized[0].original_ref
        uuid.UUID(ref)  # Raises ValueError if invalid

        # Verify same ref is in mapping
        validator_id = anonymized[0].validator_id
        assert mapping.mapping[validator_id]["original_ref"] == ref

    def test_session_id_is_uuid(self) -> None:
        """Mapping session_id is a valid UUID."""
        import uuid

        from bmad_assist.validation import anonymize_validations

        outputs = [self._make_output("claude")]
        _, mapping = anonymize_validations(outputs)

        # Verify session_id is a valid UUID
        uuid.UUID(mapping.session_id)  # Raises ValueError if invalid

    def test_mapping_contains_all_metadata(self) -> None:
        """Mapping contains all required metadata fields."""
        from bmad_assist.validation import anonymize_validations

        now = datetime(2025, 12, 16, 10, 0, 0, tzinfo=UTC)
        from bmad_assist.validation import ValidationOutput

        output = ValidationOutput(
            provider="claude",
            model="claude-sonnet-4",
            content="Test",
            timestamp=now,
            duration_ms=12345,
            token_count=2847,
        )

        anonymized, mapping = anonymize_validations([output])

        validator_id = anonymized[0].validator_id
        data = mapping.mapping[validator_id]

        assert data["provider"] == "claude"
        assert data["model"] == "claude-sonnet-4"
        assert data["timestamp"] == now.isoformat()
        assert data["duration_ms"] == 12345
        assert data["token_count"] == 2847
        assert "original_ref" in data


class TestNeutralizePatterns:
    """Tests for provider pattern neutralization (AC: #4)."""

    def _anonymize_content(self, content: str, provider: str, model: str = "test-model") -> str:
        """Helper to anonymize content for a given provider."""
        from bmad_assist.validation import ValidationOutput, anonymize_validations

        output = ValidationOutput(
            provider=provider,
            model=model,
            content=content,
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
        )
        anonymized, _ = anonymize_validations([output])
        return anonymized[0].content

    # --- Self-referential patterns ---

    def test_neutralize_as_claude(self) -> None:
        """'As Claude' becomes 'As a validator'."""
        result = self._anonymize_content("As Claude, I think this is good.", "claude")
        assert "As a validator" in result
        assert "Claude" not in result

    def test_neutralize_im_claude(self) -> None:
        """'I'm Claude' becomes 'I'm a validator'."""
        result = self._anonymize_content("I'm Claude and I found an issue.", "claude")
        assert "I'm a validator" in result
        assert "Claude" not in result

    def test_neutralize_i_am_claude(self) -> None:
        """'I am Claude' becomes 'I am a validator'."""
        result = self._anonymize_content("I am Claude, analyzing this code.", "claude")
        assert "I am a validator" in result
        assert "Claude" not in result

    def test_neutralize_as_gpt(self) -> None:
        """'As GPT' becomes 'As a validator'."""
        result = self._anonymize_content("As GPT, I recommend refactoring.", "gpt")
        assert "As a validator" in result
        assert "GPT" not in result

    def test_neutralize_im_gpt(self) -> None:
        """'I'm GPT' becomes 'I'm a validator'."""
        result = self._anonymize_content("I'm GPT and here are my findings.", "gpt")
        assert "I'm a validator" in result
        assert "GPT" not in result

    def test_neutralize_as_gemini(self) -> None:
        """'As Gemini' becomes 'As a validator'."""
        result = self._anonymize_content("As Gemini, I suggest improvements.", "gemini")
        assert "As a validator" in result
        assert "Gemini" not in result

    # --- Verb form patterns ---

    def test_neutralize_claude_believes(self) -> None:
        """'Claude believes' becomes 'The validator believes'."""
        result = self._anonymize_content("Claude believes this is correct.", "claude")
        assert "The validator believes" in result
        assert "Claude" not in result

    def test_neutralize_claude_suggests(self) -> None:
        """'Claude suggests' becomes 'The validator suggests'."""
        result = self._anonymize_content("Claude suggests refactoring.", "claude")
        assert "The validator suggests" in result
        assert "Claude" not in result

    def test_neutralize_gpt_finds(self) -> None:
        """'GPT finds' becomes 'The validator finds'."""
        result = self._anonymize_content("GPT finds a bug here.", "gpt")
        assert "The validator finds" in result
        assert "GPT" not in result

    def test_neutralize_gemini_recommends(self) -> None:
        """'Gemini recommends' becomes 'The validator recommends'."""
        result = self._anonymize_content("Gemini recommends using async.", "gemini")
        assert "The validator recommends" in result
        assert "Gemini" not in result

    def test_neutralize_gpt_identifies(self) -> None:
        """'GPT identifies' becomes 'The validator identifies'."""
        result = self._anonymize_content("GPT identifies three issues.", "gpt")
        assert "The validator identifies" in result
        assert "GPT" not in result

    def test_neutralize_claude_notes(self) -> None:
        """'Claude notes' becomes 'The validator notes'."""
        result = self._anonymize_content("Claude notes that the test is missing.", "claude")
        assert "The validator notes" in result
        assert "Claude" not in result

    def test_neutralize_claude_argues(self) -> None:
        """'Claude argues' becomes 'The validator argues' (expanded verb)."""
        result = self._anonymize_content("Claude argues that this is wrong.", "claude")
        assert "The validator argues" in result
        assert "Claude" not in result

    def test_neutralize_gpt_proposes(self) -> None:
        """'GPT proposes' becomes 'The validator proposes' (expanded verb)."""
        result = self._anonymize_content("GPT proposes a better solution.", "gpt")
        assert "The validator proposes" in result
        assert "GPT" not in result

    def test_neutralize_gemini_highlights(self) -> None:
        """'Gemini highlights' becomes 'The validator highlights' (expanded verb)."""
        result = self._anonymize_content("Gemini highlights this concern.", "gemini")
        assert "The validator highlights" in result
        assert "Gemini" not in result

    # --- Possessive patterns ---

    def test_neutralize_claudes_analysis(self) -> None:
        """'Claude's analysis' becomes 'The validator's analysis'."""
        result = self._anonymize_content("Claude's analysis shows a flaw.", "claude")
        assert "The validator's analysis" in result
        assert "Claude" not in result

    def test_neutralize_gpts_findings(self) -> None:
        """'GPT's findings' becomes 'The validator's findings'."""
        result = self._anonymize_content("GPT's findings are as follows.", "gpt")
        assert "The validator's findings" in result
        assert "GPT" not in result

    def test_neutralize_geminis_assessment(self) -> None:
        """'Gemini's assessment' becomes 'The validator's assessment'."""
        result = self._anonymize_content("Gemini's assessment is positive.", "gemini")
        assert "The validator's assessment" in result
        assert "Gemini" not in result

    def test_neutralize_claudes_recommendation(self) -> None:
        """'Claude's recommendation' becomes 'The validator's recommendation' (expanded)."""
        result = self._anonymize_content("Claude's recommendation is solid.", "claude")
        assert "The validator's recommendation" in result
        assert "Claude" not in result

    def test_neutralize_gpts_conclusion(self) -> None:
        """'GPT's conclusion' becomes 'The validator's conclusion' (expanded)."""
        result = self._anonymize_content("GPT's conclusion indicates a bug.", "gpt")
        assert "The validator's conclusion" in result
        assert "GPT" not in result

    def test_neutralize_geminis_insight(self) -> None:
        """'Gemini's insight' becomes 'The validator's insight' (expanded)."""
        result = self._anonymize_content("Gemini's insight is valuable.", "gemini")
        assert "The validator's insight" in result
        assert "Gemini" not in result

    # --- Attribution patterns ---

    def test_neutralize_according_to_claude(self) -> None:
        """'According to Claude' becomes 'According to the validator'."""
        result = self._anonymize_content("According to Claude, this is fine.", "claude")
        assert "According to the validator" in result
        assert "Claude" not in result

    def test_neutralize_in_gpts_view(self) -> None:
        """'In GPT's view' becomes 'In the validator's view'."""
        result = self._anonymize_content("In GPT's view, we should refactor.", "gpt")
        # Case may vary due to IGNORECASE replacement
        assert "the validator's view" in result.lower()
        assert "GPT" not in result

    def test_neutralize_per_geminis_analysis(self) -> None:
        """'Per Gemini's analysis' becomes 'Per the validator's analysis'."""
        result = self._anonymize_content("Per Gemini's analysis, there's a bug.", "gemini")
        # Case may vary due to IGNORECASE replacement
        assert "the validator's analysis" in result.lower()
        assert "Gemini" not in result

    # --- Generic AI patterns ---

    def test_neutralize_as_an_ai(self) -> None:
        """'As an AI' becomes 'As a validator'."""
        result = self._anonymize_content("As an AI, I cannot execute code.", "claude")
        assert "As a validator" in result
        assert "AI" not in result or "AI" in "validator"  # AI may be in other context

    def test_neutralize_as_a_language_model(self) -> None:
        """'As a language model' becomes 'As a validator'."""
        result = self._anonymize_content("As a language model, I analyze text.", "gpt")
        assert "As a validator" in result
        assert "language model" not in result

    def test_neutralize_as_an_ai_developed_by(self) -> None:
        """'As an AI developed by Anthropic' becomes 'As a validator'."""
        result = self._anonymize_content("As an AI developed by Anthropic, I follow...", "claude")
        assert "As a validator" in result
        assert "Anthropic" not in result

    # --- Model name patterns ---

    def test_neutralize_claude_sonnet_4(self) -> None:
        """'Claude Sonnet 4' becomes 'the validation model'."""
        result = self._anonymize_content("Running Claude Sonnet 4 for analysis.", "claude")
        assert "the validation model" in result
        assert "Claude Sonnet" not in result

    def test_neutralize_gpt_5(self) -> None:
        """'GPT-5' becomes 'the validation model'."""
        result = self._anonymize_content("Using GPT-5 for code review.", "gpt")
        assert "the validation model" in result
        assert "GPT-5" not in result

    def test_neutralize_gemini_pro(self) -> None:
        """'Gemini 2.5 Pro' becomes 'the validation model'."""
        result = self._anonymize_content("Gemini 2.5 Pro detected a flaw.", "gemini")
        assert "the validation model" in result
        assert "Gemini 2.5 Pro" not in result

    # --- Only neutralize matching provider ---

    def test_neutralize_only_matching_provider(self) -> None:
        """If Claude mentions GPT, GPT should NOT be neutralized."""
        result = self._anonymize_content("Unlike GPT, I think this approach is better.", "claude")
        # Claude references should be neutralized, GPT should NOT
        assert "GPT" in result  # GPT preserved (third-party reference)

    def test_neutralize_only_matching_provider_gemini_mentions_claude(self) -> None:
        """If Gemini mentions Claude, Claude should NOT be neutralized."""
        result = self._anonymize_content("Claude's approach differs from mine.", "gemini")
        # Claude should be preserved (third-party reference)
        assert "Claude" in result

    def test_neutralize_model_names_only_for_matching_provider(self) -> None:
        """Model names for OTHER providers are preserved (cross-validator refs)."""
        # Claude mentions GPT-5 - should be preserved
        result = self._anonymize_content("Unlike GPT-5, I found different issues.", "claude")
        assert "GPT-5" in result  # Preserved

        # GPT mentions Claude Sonnet 4 - should be preserved
        result2 = self._anonymize_content("Claude Sonnet 4 might approach this differently.", "gpt")
        assert "Claude Sonnet 4" in result2  # Preserved

        # Claude's own model name IS neutralized
        result3 = self._anonymize_content("Using Claude Sonnet 4 for analysis.", "claude")
        assert "the validation model" in result3
        assert "Claude Sonnet 4" not in result3

        # GPT's own model name IS neutralized
        result4 = self._anonymize_content("Running GPT-5 to review code.", "gpt")
        assert "the validation model" in result4
        assert "GPT-5" not in result4

    # --- Code block preservation ---

    def test_preserves_fenced_code_blocks(self) -> None:
        """Content inside ``` is not modified."""
        content = """As Claude, I found this issue:

```python
# Claude's helper function
def claude_helper():
    return "Claude says hello"
```

Claude believes this is correct."""

        result = self._anonymize_content(content, "claude")

        # Code block should be preserved
        assert "# Claude's helper function" in result
        assert 'return "Claude says hello"' in result
        # Prose should be neutralized
        assert "As a validator" in result
        assert "The validator believes" in result

    def test_preserves_inline_code(self) -> None:
        """Content inside ` is not modified."""
        content = "Use `claude_client.send()` for requests. Claude suggests this."

        result = self._anonymize_content(content, "claude")

        # Inline code should be preserved
        assert "`claude_client.send()`" in result
        # Prose should be neutralized
        assert "The validator suggests" in result

    def test_preserves_multiple_code_blocks(self) -> None:
        """Multiple code blocks are all preserved."""
        content = """Claude notes:

```js
// Claude's code
const claude = "hello";
```

More text. Claude believes it works.

```python
claude_var = True
```

Final Claude's analysis."""

        result = self._anonymize_content(content, "claude")

        # All code blocks preserved
        assert "// Claude's code" in result
        assert 'const claude = "hello"' in result
        assert "claude_var = True" in result
        # Prose neutralized
        assert "The validator notes" in result
        assert "The validator believes" in result
        assert "The validator's analysis" in result

    # --- Markdown structure preservation ---

    def test_preserves_markdown_headers(self) -> None:
        """Markdown headers are preserved."""
        content = """# Analysis by Claude

## Issues Found

Claude believes these are critical."""

        result = self._anonymize_content(content, "claude")

        # Headers structure preserved (but content neutralized)
        assert "# Analysis by" in result
        assert "## Issues Found" in result
        # The word "Claude" in headers should also be neutralized in prose
        assert "The validator believes" in result

    def test_preserves_markdown_lists(self) -> None:
        """Markdown lists are preserved."""
        content = """Claude's findings:

- Item 1
- Item 2
- Item 3

Claude recommends fixes."""

        result = self._anonymize_content(content, "claude")

        # List structure preserved
        assert "- Item 1" in result
        assert "- Item 2" in result
        assert "- Item 3" in result
        # Prose neutralized
        assert "The validator's findings" in result
        assert "The validator recommends" in result

    # --- Case insensitivity ---

    def test_case_insensitive_matching(self) -> None:
        """Patterns match regardless of case."""
        result = self._anonymize_content("AS CLAUDE, I think this is good.", "claude")
        assert "AS a validator" in result or "As a validator" in result
        assert "CLAUDE" not in result

        result2 = self._anonymize_content("as claude, I think this is good.", "claude")
        assert "as a validator" in result2 or "As a validator" in result2
        assert "claude" not in result2.lower().replace("validator", "")

    # --- Edge cases ---

    def test_no_patterns_unchanged(self) -> None:
        """Content without patterns is returned unchanged."""
        content = "This is a regular analysis with no provider references."
        result = self._anonymize_content(content, "claude")
        assert result == content

    def test_empty_content(self) -> None:
        """Empty content returns empty."""
        result = self._anonymize_content("", "claude")
        assert result == ""

    def test_content_with_only_code(self) -> None:
        """Content that is only code block is preserved."""
        content = """```python
claude = "hello"
```"""
        result = self._anonymize_content(content, "claude")
        assert result == content


class TestMappingPersistence:
    """Tests for mapping save/load (AC: #5, #6)."""

    def test_save_creates_cache_directory(self, tmp_path: Path) -> None:
        """Cache directory is created if not exists."""
        from bmad_assist.validation import AnonymizationMapping, save_mapping

        mapping = AnonymizationMapping(
            session_id="test-session-123",
            timestamp=datetime.now(UTC),
            mapping={},
        )

        # Cache dir shouldn't exist yet
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        assert not cache_dir.exists()

        save_mapping(mapping, tmp_path)

        # Now cache dir should exist
        assert cache_dir.exists()

    def test_save_returns_path(self, tmp_path: Path) -> None:
        """Returns path to saved file."""
        from bmad_assist.validation import AnonymizationMapping, save_mapping

        mapping = AnonymizationMapping(
            session_id="test-session-456",
            timestamp=datetime.now(UTC),
            mapping={"Validator A": {"provider": "claude"}},
        )

        result_path = save_mapping(mapping, tmp_path)

        assert result_path.exists()
        assert result_path.name == "validation-mapping-test-session-456.json"
        assert result_path.parent == tmp_path / ".bmad-assist" / "cache"

    def test_save_atomic_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses temp file + os.replace pattern."""
        import os

        from bmad_assist.validation import AnonymizationMapping, save_mapping

        # Track os.replace calls
        replace_calls: list[tuple[Path, Path]] = []
        original_replace = os.replace

        def tracked_replace(src: str, dst: str) -> None:
            replace_calls.append((Path(src), Path(dst)))
            original_replace(src, dst)

        monkeypatch.setattr(os, "replace", tracked_replace)

        mapping = AnonymizationMapping(
            session_id="test-atomic",
            timestamp=datetime.now(UTC),
            mapping={},
        )

        save_mapping(mapping, tmp_path)

        # os.replace should have been called exactly once
        assert len(replace_calls) == 1
        src, dst = replace_calls[0]
        assert src.suffix == ".tmp"
        assert dst.name == "validation-mapping-test-atomic.json"

    def test_save_correct_json_format(self, tmp_path: Path) -> None:
        """Saved file has correct JSON format."""
        import json

        from bmad_assist.validation import AnonymizationMapping, save_mapping

        now = datetime(2025, 12, 16, 1, 21, 0, tzinfo=UTC)
        mapping = AnonymizationMapping(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            timestamp=now,
            mapping={
                "Validator A": {
                    "provider": "claude",
                    "model": "claude-sonnet-4",
                    "original_ref": "550e8400-e29b-41d4-a716-446655440001",
                    "timestamp": "2025-12-16T01:20:45+00:00",
                    "duration_ms": 12400,
                    "token_count": 2847,
                },
            },
        )

        result_path = save_mapping(mapping, tmp_path)

        with open(result_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["session_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["timestamp"] == now.isoformat()
        assert "mapping" in data
        assert "Validator A" in data["mapping"]
        assert data["mapping"]["Validator A"]["provider"] == "claude"

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        """Saving with same session_id overwrites existing file."""
        from bmad_assist.validation import AnonymizationMapping, save_mapping

        mapping1 = AnonymizationMapping(
            session_id="same-session",
            timestamp=datetime.now(UTC),
            mapping={"Validator A": {"provider": "claude"}},
        )
        mapping2 = AnonymizationMapping(
            session_id="same-session",
            timestamp=datetime.now(UTC),
            mapping={"Validator B": {"provider": "gemini"}},
        )

        path1 = save_mapping(mapping1, tmp_path)
        path2 = save_mapping(mapping2, tmp_path)

        assert path1 == path2

        import json

        with open(path2, encoding="utf-8") as f:
            data = json.load(f)
        assert "Validator B" in data["mapping"]
        assert "Validator A" not in data["mapping"]


class TestGetMapping:
    """Tests for get_mapping() function (AC: #6)."""

    def test_get_mapping_returns_mapping(self, tmp_path: Path) -> None:
        """Successfully retrieves saved mapping."""
        from bmad_assist.validation import (
            AnonymizationMapping,
            get_mapping,
            save_mapping,
        )

        now = datetime(2025, 12, 16, 1, 21, 0, tzinfo=UTC)
        original = AnonymizationMapping(
            session_id="test-retrieval",
            timestamp=now,
            mapping={
                "Validator A": {
                    "provider": "claude",
                    "model": "claude-sonnet-4",
                    "original_ref": "ref-uuid",
                    "timestamp": "2025-12-16T01:20:45+00:00",
                    "duration_ms": 12400,
                    "token_count": 2847,
                },
            },
        )

        save_mapping(original, tmp_path)
        retrieved = get_mapping("test-retrieval", tmp_path)

        assert retrieved is not None
        assert retrieved.session_id == "test-retrieval"
        assert retrieved.timestamp == now
        assert "Validator A" in retrieved.mapping
        assert retrieved.mapping["Validator A"]["provider"] == "claude"

    def test_get_mapping_not_found_returns_none(self, tmp_path: Path) -> None:
        """Returns None for non-existent session."""
        from bmad_assist.validation import get_mapping

        result = get_mapping("nonexistent-session", tmp_path)
        assert result is None

    def test_get_mapping_missing_cache_dir_returns_none(self, tmp_path: Path) -> None:
        """Returns None if cache directory doesn't exist."""
        from bmad_assist.validation import get_mapping

        # Don't create cache dir
        result = get_mapping("any-session", tmp_path)
        assert result is None

    def test_get_mapping_validates_schema_missing_session_id(self, tmp_path: Path) -> None:
        """Invalid schema (missing session_id) returns None with warning."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write invalid mapping (missing session_id)
        file_path = cache_dir / "validation-mapping-invalid1.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": "2025-12-16T01:21:00Z", "mapping": {}}, f)

        result = get_mapping("invalid1", tmp_path)
        assert result is None

    def test_get_mapping_validates_schema_missing_timestamp(self, tmp_path: Path) -> None:
        """Invalid schema (missing timestamp) returns None with warning."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write invalid mapping (missing timestamp)
        file_path = cache_dir / "validation-mapping-invalid2.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"session_id": "invalid2", "mapping": {}}, f)

        result = get_mapping("invalid2", tmp_path)
        assert result is None

    def test_get_mapping_validates_schema_missing_mapping(self, tmp_path: Path) -> None:
        """Invalid schema (missing mapping) returns None with warning."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write invalid mapping (missing mapping key)
        file_path = cache_dir / "validation-mapping-invalid3.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"session_id": "invalid3", "timestamp": "2025-12-16T01:21:00Z"}, f)

        result = get_mapping("invalid3", tmp_path)
        assert result is None

    def test_get_mapping_validates_schema_wrong_type(self, tmp_path: Path) -> None:
        """Invalid schema (session_id wrong type) returns None with warning."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write invalid mapping (session_id is int, not string)
        file_path = cache_dir / "validation-mapping-12345.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"session_id": 12345, "timestamp": "2025-12-16T01:21:00Z", "mapping": {}}, f)

        result = get_mapping("12345", tmp_path)
        assert result is None

    def test_get_mapping_handles_malformed_json(self, tmp_path: Path) -> None:
        """Malformed JSON returns None."""
        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write malformed JSON
        file_path = cache_dir / "validation-mapping-malformed.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write('{"session_id": "malformed"')  # Unclosed brace

        result = get_mapping("malformed", tmp_path)
        assert result is None

    def test_get_mapping_handles_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns None."""
        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write empty file
        file_path = cache_dir / "validation-mapping-empty.json"
        file_path.touch()

        result = get_mapping("empty", tmp_path)
        assert result is None

    def test_get_mapping_handles_invalid_timestamp_format(self, tmp_path: Path) -> None:
        """Invalid timestamp format returns None."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write with invalid timestamp
        file_path = cache_dir / "validation-mapping-badtime.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"session_id": "badtime", "timestamp": "not-a-date", "mapping": {}}, f)

        result = get_mapping("badtime", tmp_path)
        assert result is None

    def test_get_mapping_handles_z_suffix_timestamp(self, tmp_path: Path) -> None:
        """Timestamps with Z suffix (ISO 8601) are accepted."""
        import json

        from bmad_assist.validation import get_mapping

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Write with Z suffix timestamp (common in external tools)
        file_path = cache_dir / "validation-mapping-zsuffix.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": "zsuffix",
                    "timestamp": "2025-12-16T01:21:00Z",  # Z suffix
                    "mapping": {},
                },
                f,
            )

        result = get_mapping("zsuffix", tmp_path)
        assert result is not None
        assert result.session_id == "zsuffix"
        assert result.timestamp.tzinfo is not None  # Should be timezone-aware
