"""Tests for testarch prompts module.

Tests AC #10: Unit tests for prompts module.
Tests AC #11: Response validation model tests.
"""

from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from bmad_assist.testarch.prompts import (
    ATDDEligibilityOutput,
    get_eligibility_prompt,
    parse_eligibility_response,
)


class TestPromptsInitExists:
    """Test AC10a: Verify __init__.py exists."""

    def test_prompts_init_exists(self) -> None:
        """Verify prompts/__init__.py exists in package."""
        from importlib import resources

        prompts_pkg = resources.files("bmad_assist.testarch.prompts")
        init_path = prompts_pkg / "__init__.py"
        assert init_path.is_file(), "prompts/__init__.py should exist"


class TestGetEligibilityPromptLoads:
    """Test AC10b: Verify prompt loading works."""

    def test_get_eligibility_prompt_loads(self) -> None:
        """Verify get_eligibility_prompt() returns non-empty string."""
        prompt = get_eligibility_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_returns_raw_template(self) -> None:
        """Verify prompt contains raw placeholder (not substituted)."""
        prompt = get_eligibility_prompt()
        assert "{story_content}" in prompt


class TestPromptHasRequiredPlaceholders:
    """Test AC10c: Verify {story_content} placeholder exists."""

    def test_prompt_has_required_placeholders(self) -> None:
        """Verify {story_content} placeholder is present."""
        prompt = get_eligibility_prompt()
        assert "{story_content}" in prompt

    def test_placeholder_is_substitutable(self) -> None:
        """Verify placeholder can be substituted."""
        prompt = get_eligibility_prompt()
        story = "# Test Story\n\nAs a user..."
        filled = prompt.format(story_content=story)
        assert story in filled
        assert "{story_content}" not in filled


class TestPromptOutputSectionHasSchema:
    """Test AC10d: Verify JSON schema is in prompt."""

    def test_prompt_output_section_has_schema(self) -> None:
        """Verify JSON schema with expected fields is in output section."""
        prompt = get_eligibility_prompt()
        # Check for schema fields
        assert "ui_score" in prompt
        assert "api_score" in prompt
        assert "testability_score" in prompt
        assert "skip_score" in prompt
        assert "reasoning" in prompt


class TestPromptHasRequiredTags:
    """Test AC10e: Verify XML structure."""

    def test_prompt_has_required_tags(self) -> None:
        """Verify workflow, mission, context, instructions, output tags exist."""
        prompt = get_eligibility_prompt()
        required_tags = ["workflow", "mission", "context", "instructions", "output"]
        for tag in required_tags:
            assert f"<{tag}" in prompt, f"Missing required tag: <{tag}>"


class TestPromptXmlIsValid:
    """Test AC10f: Verify XML is well-formed."""

    def test_prompt_xml_is_valid(self) -> None:
        """Verify prompt is valid XML."""
        prompt = get_eligibility_prompt()
        # Fill placeholder to make valid XML for parsing
        prompt_filled = prompt.format(story_content="test story content")
        try:
            ElementTree.fromstring(prompt_filled)
        except ElementTree.ParseError as e:
            pytest.fail(f"Prompt XML is not well-formed: {e}")


class TestMissingPromptRaisesFileNotFound:
    """Test AC10g: Verify error handling for missing file."""

    def test_missing_prompt_raises_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify FileNotFoundError is raised with helpful message."""
        from importlib import resources as importlib_resources

        # Mock files() to simulate missing package
        def mock_files(package: str) -> Path:
            if "testarch.prompts" in package:
                raise FileNotFoundError("Mocked missing package")
            return importlib_resources.files(package)

        monkeypatch.setattr("bmad_assist.testarch.prompts.resources.files", mock_files)

        # Need to reload module to pick up mock
        from importlib import reload

        import bmad_assist.testarch.prompts as prompts_module

        reload(prompts_module)

        with pytest.raises(FileNotFoundError) as exc_info:
            prompts_module.get_eligibility_prompt()

        assert "ATDD eligibility prompt not found" in str(exc_info.value)
        assert "broken installation" in str(exc_info.value)


class TestATDDEligibilityOutput:
    """Test AC11: Response validation model."""

    def test_valid_response_parses(self) -> None:
        """Verify valid JSON response parses correctly."""
        json_str = (
            '{"ui_score": 0.8, "api_score": 0.5, '
            '"skip_score": 0.1, "reasoning": "Story has UI components"}'
        )
        result = parse_eligibility_response(json_str)
        assert result.__class__.__name__ == "ATDDEligibilityOutput"
        assert result.ui_score == 0.8
        assert result.api_score == 0.5
        assert result.skip_score == 0.1
        assert result.reasoning == "Story has UI components"

    def test_score_at_boundaries(self) -> None:
        """Verify scores at 0.0 and 1.0 are valid."""
        json_str = (
            '{"ui_score": 0.0, "api_score": 1.0, "skip_score": 0.0, "reasoning": "Boundary test"}'
        )
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.0
        assert result.api_score == 1.0

    def test_score_above_range_raises_validation_error(self) -> None:
        """Verify score > 1.0 raises ValidationError."""
        json_str = '{"ui_score": 1.5, "api_score": 0.5, "skip_score": 0.1, "reasoning": "Invalid"}'
        with pytest.raises(ValidationError) as exc_info:
            parse_eligibility_response(json_str)
        assert "ui_score" in str(exc_info.value)

    def test_score_below_range_raises_validation_error(self) -> None:
        """Verify score < 0.0 raises ValidationError."""
        json_str = '{"ui_score": -0.1, "api_score": 0.5, "skip_score": 0.1, "reasoning": "Invalid"}'
        with pytest.raises(ValidationError) as exc_info:
            parse_eligibility_response(json_str)
        assert "ui_score" in str(exc_info.value)

    def test_missing_required_field_raises_validation_error(self) -> None:
        """Verify missing required field raises ValidationError."""
        json_str = '{"ui_score": 0.8, "api_score": 0.5, "skip_score": 0.1}'
        with pytest.raises(ValidationError) as exc_info:
            parse_eligibility_response(json_str)
        assert "reasoning" in str(exc_info.value)

    def test_invalid_json_raises_validation_error(self) -> None:
        """Verify invalid JSON raises ValidationError."""
        json_str = "not valid json"
        with pytest.raises(ValidationError):
            parse_eligibility_response(json_str)

    def test_strips_markdown_json_block(self) -> None:
        """Verify markdown code blocks are stripped before parsing."""
        json_str = """```json
{"ui_score": 0.7, "api_score": 0.3, "skip_score": 0.2, "reasoning": "Wrapped in markdown"}
```"""
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.7
        assert result.reasoning == "Wrapped in markdown"

    def test_strips_plain_markdown_block(self) -> None:
        """Verify plain markdown code blocks are stripped."""
        json_str = """```
{"ui_score": 0.6, "api_score": 0.4, "skip_score": 0.0, "reasoning": "Plain block"}
```"""
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.6

    def test_handles_whitespace(self) -> None:
        """Verify leading/trailing whitespace is handled."""
        json_str = """

{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.5, "reasoning": "With whitespace"}

"""
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.5

    def test_model_direct_creation(self) -> None:
        """Verify model can be created directly."""
        model = ATDDEligibilityOutput(
            ui_score=0.8,
            api_score=0.6,
            testability_score=0.5,
            skip_score=0.0,
            reasoning="Direct creation test",
        )
        assert model.ui_score == 0.8
        assert model.api_score == 0.6
        assert model.testability_score == 0.5
        assert model.skip_score == 0.0
        assert model.reasoning == "Direct creation test"

    def test_testability_score_defaults_to_zero(self) -> None:
        """Verify testability_score defaults to 0.0 when not provided."""
        model = ATDDEligibilityOutput(
            ui_score=0.5,
            api_score=0.5,
            skip_score=0.0,
            reasoning="No testability provided",
        )
        assert model.testability_score == 0.0

    def test_testability_score_above_range_raises_validation_error(self) -> None:
        """Verify testability_score > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ATDDEligibilityOutput(
                ui_score=0.5,
                api_score=0.5,
                testability_score=1.5,
                skip_score=0.0,
                reasoning="Invalid testability",
            )
        assert "testability_score" in str(exc_info.value)

    def test_testability_score_below_range_raises_validation_error(self) -> None:
        """Verify testability_score < 0.0 raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ATDDEligibilityOutput(
                ui_score=0.5,
                api_score=0.5,
                testability_score=-0.1,
                skip_score=0.0,
                reasoning="Invalid testability",
            )
        assert "testability_score" in str(exc_info.value)

    def test_testability_score_at_boundaries(self) -> None:
        """Verify testability_score at 0.0 and 1.0 are valid."""
        model_zero = ATDDEligibilityOutput(
            ui_score=0.5, api_score=0.5, testability_score=0.0,
            skip_score=0.0, reasoning="Min testability",
        )
        assert model_zero.testability_score == 0.0

        model_one = ATDDEligibilityOutput(
            ui_score=0.5, api_score=0.5, testability_score=1.0,
            skip_score=0.0, reasoning="Max testability",
        )
        assert model_one.testability_score == 1.0


class TestMarkdownParsingEdgeCases:
    """Test edge cases for markdown parsing robustness."""

    def test_strips_uppercase_json_block(self) -> None:
        """Verify uppercase JSON language tag is stripped."""
        json_str = """```JSON
{"ui_score": 0.6, "api_score": 0.4, "skip_score": 0.0, "reasoning": "Uppercase"}
```"""
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.6
        assert result.reasoning == "Uppercase"

    def test_handles_preamble_text(self) -> None:
        """Verify preamble text before code block is handled."""
        json_str = """Here is the analysis:

```json
{"ui_score": 0.7, "api_score": 0.3, "skip_score": 0.1, "reasoning": "With preamble"}
```"""
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.7
        assert result.reasoning == "With preamble"

    def test_empty_input_raises_validation_error(self) -> None:
        """Verify empty string raises ValidationError."""
        with pytest.raises(ValidationError):
            parse_eligibility_response("")

    def test_text_only_raises_validation_error(self) -> None:
        """Verify text-only output (no JSON) raises ValidationError."""
        with pytest.raises(ValidationError):
            parse_eligibility_response("This is just text, no JSON here.")

    def test_empty_reasoning_raises_validation_error(self) -> None:
        """Verify empty reasoning string raises ValidationError."""
        json_str = '{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.0, "reasoning": ""}'
        with pytest.raises(ValidationError):
            parse_eligibility_response(json_str)

    def test_extra_fields_ignored(self) -> None:
        """Verify extra fields in LLM response are ignored."""
        json_str = (
            '{"ui_score": 0.8, "api_score": 0.5, "skip_score": 0.1, '
            '"reasoning": "test", "extra_field": "ignored"}'
        )
        result = parse_eligibility_response(json_str)
        assert result.ui_score == 0.8
        assert not hasattr(result, "extra_field")
