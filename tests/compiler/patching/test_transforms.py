"""Tests for prompt formatting and post-processing."""

import pytest

from bmad_assist.compiler.patching.config import reset_patcher_config
from bmad_assist.compiler.patching.transforms import (
    _parse_flags,
    fix_xml_entities,
    format_transform_prompt,
    post_process_compiled,
)
from bmad_assist.compiler.patching.types import PostProcessRule


@pytest.fixture(autouse=True)
def reset_config() -> None:
    """Reset patcher config before each test."""
    reset_patcher_config()


class TestFormatTransformPrompt:
    """Tests for format_transform_prompt function."""

    def test_basic_prompt_structure(self) -> None:
        """Test that prompt has all required sections."""
        instructions = ["Remove step 1"]
        workflow = "<workflow><step n='1'/></workflow>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "<task-context>" in prompt
        assert "</task-context>" in prompt
        assert "<source-document>" in prompt
        assert "</source-document>" in prompt
        assert "<instructions>" in prompt
        assert "</instructions>" in prompt
        assert "<output-format>" in prompt
        assert "</output-format>" in prompt

    def test_workflow_content_included(self) -> None:
        """Test that workflow content is in source-document section."""
        instructions = ["Remove step 1"]
        workflow = "<workflow><step n='1'>Content</step></workflow>"

        prompt = format_transform_prompt(instructions, workflow)

        assert workflow in prompt
        # Check it's between source-document tags
        assert "<source-document>" in prompt
        assert workflow in prompt

    def test_single_instruction_formatted(self) -> None:
        """Test formatting with single instruction."""
        instructions = ["Remove all <ask> elements"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "1. Remove all <ask> elements" in prompt

    def test_multiple_instructions_numbered(self) -> None:
        """Test that multiple instructions are numbered."""
        instructions = [
            "Remove step 1",
            "Simplify instructions",
            "Renumber steps",
        ]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "1. Remove step 1" in prompt
        assert "2. Simplify instructions" in prompt
        assert "3. Renumber steps" in prompt

    def test_instructions_in_order(self) -> None:
        """Test that instructions appear in correct order."""
        instructions = ["First", "Second", "Third"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        # Check order by finding positions
        pos_1 = prompt.find("1. First")
        pos_2 = prompt.find("2. Second")
        pos_3 = prompt.find("3. Third")

        assert pos_1 < pos_2 < pos_3

    def test_system_prompt_included(self) -> None:
        """Test that system prompt from config is included."""
        instructions = ["Test instruction"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        # Default system prompt contains these phrases
        assert "TEXT TRANSFORMATION" in prompt
        assert "CRITICAL RULES" in prompt

    def test_output_format_included(self) -> None:
        """Test that output format instruction is included."""
        instructions = ["Test instruction"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "transformed-document" in prompt

    def test_empty_instructions_list(self) -> None:
        """Test with empty instructions list (edge case)."""
        instructions: list[str] = []
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        # Should still have structure but no numbered items
        assert "<instructions>" in prompt
        assert "Apply these changes IN ORDER" in prompt

    def test_instruction_with_special_characters(self) -> None:
        """Test instruction with special characters preserved."""
        instructions = ["Remove elements matching //step[@n='1']"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "//step[@n='1']" in prompt

    def test_multiline_instruction(self) -> None:
        """Test multiline instruction is preserved."""
        instructions = ["Remove step 1\nand also remove step 2"]
        workflow = "<workflow/>"

        prompt = format_transform_prompt(instructions, workflow)

        assert "Remove step 1\nand also remove step 2" in prompt


class TestParseFlags:
    """Tests for _parse_flags helper function."""

    def test_parse_single_flag(self) -> None:
        """Parse single flag."""
        assert _parse_flags("MULTILINE") != 0
        assert _parse_flags("IGNORECASE") != 0

    def test_parse_multiple_flags_space(self) -> None:
        """Parse space-separated flags."""
        import re

        result = _parse_flags("MULTILINE IGNORECASE")
        assert result & re.MULTILINE
        assert result & re.IGNORECASE

    def test_parse_multiple_flags_comma(self) -> None:
        """Parse comma-separated flags."""
        import re

        result = _parse_flags("MULTILINE,DOTALL")
        assert result & re.MULTILINE
        assert result & re.DOTALL

    def test_parse_short_flags(self) -> None:
        """Parse short flag names."""
        import re

        assert _parse_flags("M") & re.MULTILINE
        assert _parse_flags("I") & re.IGNORECASE
        assert _parse_flags("S") & re.DOTALL

    def test_parse_empty_string(self) -> None:
        """Empty string returns 0."""
        assert _parse_flags("") == 0

    def test_parse_case_insensitive(self) -> None:
        """Flag names are case-insensitive."""
        import re

        assert _parse_flags("multiline") & re.MULTILINE


class TestPostProcessCompiled:
    """Tests for post_process_compiled function."""

    def test_returns_content_when_no_rules(self) -> None:
        """Returns content unchanged when rules is None."""
        content = "Some content"
        result = post_process_compiled(content, None)
        assert result == content

    def test_returns_content_when_empty_rules(self) -> None:
        """Returns content unchanged when rules list is empty."""
        content = "Some content"
        result = post_process_compiled(content, [])
        assert result == content

    def test_applies_simple_rule(self) -> None:
        """Applies a simple regex replacement rule."""
        content = "Hello World"
        rules = [PostProcessRule(pattern="World", replacement="Universe")]
        result = post_process_compiled(content, rules)
        assert result == "Hello Universe"

    def test_applies_multiple_rules(self) -> None:
        """Applies multiple rules in order."""
        content = "foo bar baz"
        rules = [
            PostProcessRule(pattern="foo", replacement="FOO"),
            PostProcessRule(pattern="bar", replacement="BAR"),
        ]
        result = post_process_compiled(content, rules)
        assert result == "FOO BAR baz"

    def test_applies_rule_with_multiline_flag(self) -> None:
        """Applies rule with MULTILINE flag."""
        content = "start\nold_value: foo\nend"
        rules = [
            PostProcessRule(
                pattern="^old_value:.*$",
                replacement="# removed",
                flags="MULTILINE",
            )
        ]
        result = post_process_compiled(content, rules)
        assert "old_value" not in result
        assert "# removed" in result

    def test_applies_rule_with_ignorecase_flag(self) -> None:
        """Applies rule with IGNORECASE flag."""
        content = "HELLO hello HeLLo"
        rules = [
            PostProcessRule(
                pattern="hello",
                replacement="hi",
                flags="IGNORECASE",
            )
        ]
        result = post_process_compiled(content, rules)
        assert result == "hi hi hi"

    def test_applies_rule_with_dotall_flag(self) -> None:
        """Applies rule with DOTALL flag for multiline matching."""
        content = "<tag>line1\nline2</tag>"
        rules = [
            PostProcessRule(
                pattern="<tag>.*</tag>",
                replacement="<replaced/>",
                flags="DOTALL",
            )
        ]
        result = post_process_compiled(content, rules)
        assert result == "<replaced/>"

    def test_replacement_with_regex_groups(self) -> None:
        """Replacement can use regex groups."""
        content = "version: 1.2.3"
        rules = [
            PostProcessRule(
                pattern=r"version: (\d+)\.(\d+)\.(\d+)",
                replacement=r"v\1-\2-\3",
            )
        ]
        result = post_process_compiled(content, rules)
        assert result == "v1-2-3"

    def test_empty_replacement_removes_content(self) -> None:
        """Empty replacement string removes matched content."""
        content = "keep <remove>this</remove> keep"
        rules = [
            PostProcessRule(
                pattern="<remove>.*?</remove>",
                replacement="",
                flags="DOTALL",
            )
        ]
        result = post_process_compiled(content, rules)
        assert result == "keep  keep"

    def test_cleans_multiple_blank_lines(self) -> None:
        """Multiple blank lines are reduced to double after processing."""
        content = "line1\n\n\n\n\nline2"
        rules = []  # Even with no rules, blank lines are cleaned
        result = post_process_compiled(content, rules)
        assert result == "line1\n\nline2"

    def test_invalid_regex_pattern_skipped(self) -> None:
        """Invalid regex patterns are skipped with warning."""
        content = "some content"
        rules = [
            PostProcessRule(pattern="[invalid", replacement="x"),  # Invalid regex
            PostProcessRule(pattern="content", replacement="text"),  # Valid
        ]
        result = post_process_compiled(content, rules)
        assert result == "some text"  # Valid rule still applied

    def test_real_world_template_var_removal(self) -> None:
        """Test removing <var name="template"> like in real patch."""
        content = """Some content
<var name="template">/path/to/template.md</var>
More content"""
        rules = [
            PostProcessRule(
                pattern=r'^\s*<var\s+name="template"[^>]*>.*?</var>\s*$',
                replacement="",
                flags="MULTILINE DOTALL",
            )
        ]
        result = post_process_compiled(content, rules)
        assert '<var name="template">' not in result
        assert "Some content" in result
        assert "More content" in result

    def test_real_world_installed_path_replacement(self) -> None:
        """Test replacing {installed_path} references like in real patch."""
        content = "Load {installed_path}/workflow.yaml first"
        rules = [
            PostProcessRule(
                pattern=r"\{installed_path\}/workflow\.yaml",
                replacement="the <workflow-yaml> section embedded above",
                flags="IGNORECASE",
            )
        ]
        result = post_process_compiled(content, rules)
        assert "{installed_path}" not in result
        assert "<workflow-yaml>" in result


class TestFixXmlEntities:
    """Tests for fix_xml_entities function."""

    def test_valid_xml_unchanged(self) -> None:
        """Valid XML is returned unchanged."""
        content = "<workflow><step n='1'>Content</step></workflow>"
        result = fix_xml_entities(content)
        assert result == content

    def test_fixes_unescaped_less_than_before_digit(self) -> None:
        """Fixes < before digit (e.g., 'score < 3')."""
        content = "<action>Check if score < 3</action>"
        result = fix_xml_entities(content)
        assert result == "<action>Check if score &lt; 3</action>"

    def test_fixes_unescaped_less_than_before_space(self) -> None:
        """Fixes < before space."""
        content = "<action>value < other</action>"
        result = fix_xml_entities(content)
        assert result == "<action>value &lt; other</action>"

    def test_fixes_unescaped_less_than_before_equals(self) -> None:
        """Fixes <= pattern (less than or equal)."""
        content = "<action>Check if score <= 5</action>"
        result = fix_xml_entities(content)
        assert result == "<action>Check if score &lt;= 5</action>"

    def test_preserves_xml_tags(self) -> None:
        """Does not escape < that are part of XML tags."""
        content = "<workflow><action>test</action></workflow>"
        result = fix_xml_entities(content)
        assert result == content

    def test_fixes_multiple_occurrences(self) -> None:
        """Fixes multiple unescaped < characters."""
        content = "<action>if x < 3 and y < 5</action>"
        result = fix_xml_entities(content)
        assert result == "<action>if x &lt; 3 and y &lt; 5</action>"

    def test_real_world_score_comparison(self) -> None:
        """Fixes real-world score comparison patterns from workflows."""
        content = """<action>Determine Evidence Verdict:
        - **EXCELLENT** (score ≤ -3): Many clean passes
        - **PASS** (score < 3): Acceptable quality
        - **MAJOR REWORK** (3 ≤ score < 7): Significant issues
        - **REJECT** (score ≥ 7): Critical problems
      </action>"""
        result = fix_xml_entities(content)
        assert "score &lt; 3" in result
        assert "score &lt; 7" in result
        # Unicode ≤ and ≥ should be preserved
        assert "score ≤ -3" in result
        assert "score ≥ 7" in result

    def test_preserves_already_escaped_entities(self) -> None:
        """Preserves already escaped &lt; entities."""
        content = "<action>Check if score &lt; 3</action>"
        result = fix_xml_entities(content)
        assert result == content

    def test_aggressive_fixes_bare_lt_before_special_chars(self) -> None:
        """Aggressive pass fixes < before chars not handled by conservative pass."""
        content = "<action>Use <> brackets or <+2 offset</action>"
        result = fix_xml_entities(content)
        assert "&lt;>" in result
        assert "&lt;+2" in result
        # Valid XML tags should be preserved
        assert "<action>" in result
        assert "</action>" in result

    def test_aggressive_fixes_bare_ampersand(self) -> None:
        """Aggressive pass fixes bare & not followed by entity ref."""
        content = "<action>Use foo & bar together</action>"
        result = fix_xml_entities(content)
        assert "foo &amp; bar" in result
        assert "<action>" in result

    def test_preserves_valid_entity_references(self) -> None:
        """Preserves valid XML entity references like &lt; &gt; &amp;."""
        content = "<action>Compare: &lt; and &gt; and &amp; ok</action>"
        result = fix_xml_entities(content)
        assert result == content

    def test_combined_lt_and_ampersand_fix(self) -> None:
        """Fixes both < and & in same content."""
        content = "<action>if x < 3 & y > 0</action>"
        result = fix_xml_entities(content)
        assert "&lt; 3" in result
        assert "&amp;" in result
