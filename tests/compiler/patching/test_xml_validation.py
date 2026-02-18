"""Tests for XML well-formedness validation in patch compilation pipeline.

Tests _validate_instructions_xml() and the graceful fallback in
_try_load_from_cache() when cached templates contain invalid XML.
"""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.compiler.patching.compiler import (
    _try_load_from_cache,
    _validate_instructions_xml,
)


class TestValidateInstructionsXml:
    """Tests for _validate_instructions_xml()."""

    def test_valid_xml_returns_none(self) -> None:
        """Valid XML in instructions section should return None (no error)."""
        content = textwrap.dedent("""\
            <instructions-xml>
            <workflow>
              <step n="1" title="Test">
                <action>Do something</action>
              </step>
            </workflow>
            </instructions-xml>
        """)
        assert _validate_instructions_xml(content) is None

    def test_mismatched_tag_returns_error(self) -> None:
        """Mismatched XML tags should return an error string."""
        content = textwrap.dedent("""\
            <instructions-xml>
            <workflow>
              <step n="1" title="Test">
                <action>Do something</step>
              </action>
            </workflow>
            </instructions-xml>
        """)
        result = _validate_instructions_xml(content)
        assert result is not None
        assert "mismatched" in result.lower() or "malformed" in result.lower()

    def test_unclosed_tag_returns_error(self) -> None:
        """Unclosed XML tags should return an error string."""
        content = textwrap.dedent("""\
            <instructions-xml>
            <workflow>
              <step n="1" title="Test">
                <action>Do something
              </step>
            </workflow>
            </instructions-xml>
        """)
        result = _validate_instructions_xml(content)
        assert result is not None

    def test_no_instructions_section_returns_none(self) -> None:
        """Content without <instructions-xml> should return None."""
        content = "<workflow-yaml>name: test</workflow-yaml>"
        assert _validate_instructions_xml(content) is None

    def test_empty_instructions_returns_none(self) -> None:
        """Empty instructions section should return None."""
        content = "<instructions-xml>\n  \n</instructions-xml>"
        assert _validate_instructions_xml(content) is None

    def test_markdown_instructions_returns_none(self) -> None:
        """Markdown content in instructions section should skip validation."""
        content = textwrap.dedent("""\
            <instructions-xml>
            # Step 1: Do something

            - Check this
            - Check that
            </instructions-xml>
        """)
        assert _validate_instructions_xml(content) is None

    def test_xml_with_entities_valid(self) -> None:
        """XML with proper entities (&lt;, &amp;) should pass validation."""
        content = textwrap.dedent("""\
            <instructions-xml>
            <workflow>
              <action>Score &lt; 3 means APPROVED</action>
              <action>Use &amp; for AND</action>
            </workflow>
            </instructions-xml>
        """)
        assert _validate_instructions_xml(content) is None

    def test_complex_valid_xml(self) -> None:
        """Complex nested XML (like real workflows) should pass validation."""
        content = textwrap.dedent("""\
            <instructions-xml>
            <workflow>
              <step n="1" title="Review">
                <substep n="1a" title="Check">
                  <action>Verify each claim</action>
                  <critical>MUST check all items</critical>
                </substep>
                <substep n="1b" title="Score">
                  <action>Calculate: score &lt; 3 = APPROVED</action>
                </substep>
              </step>
            </workflow>
            </instructions-xml>
        """)
        assert _validate_instructions_xml(content) is None


class TestTryLoadFromCacheXmlValidation:
    """Tests for XML validation in _try_load_from_cache()."""

    def _make_cache_file(self, tmp_path: Path, instructions_xml: str) -> Path:
        """Create a mock cache file with given instructions XML."""
        cache_content = textwrap.dedent(f"""\
            <!-- Compiled from: test workflow -->
            <workflow-yaml>
            name: test-workflow
            </workflow-yaml>
            <instructions-xml>
            {instructions_xml}
            </instructions-xml>
        """)
        cache_path = tmp_path / "test.tpl.xml"
        cache_path.write_text(cache_content)
        return cache_path

    @patch("bmad_assist.compiler.patching.compiler._find_workflow_files")
    def test_valid_cache_loads_successfully(
        self, mock_find: object, tmp_path: Path
    ) -> None:
        """Cache with valid XML should load successfully."""
        instructions = '<workflow><step n="1"><action>Test</action></step></workflow>'
        cache_path = self._make_cache_file(tmp_path, instructions)

        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        mock_find.return_value = (workflow_yaml, cache_path)  # type: ignore[union-attr]

        result = _try_load_from_cache(cache_path, "test", tmp_path, None)
        assert result is not None
        workflow_ir, patch_path = result
        assert patch_path is None
        assert "Test" in workflow_ir.raw_instructions

    @patch("bmad_assist.compiler.patching.compiler._find_workflow_files")
    def test_invalid_xml_cache_returns_none_and_deletes(
        self, mock_find: object, tmp_path: Path
    ) -> None:
        """Cache with invalid XML should return None and delete cache files."""
        instructions = "<workflow><step>Broken</workflow></step>"
        cache_path = self._make_cache_file(tmp_path, instructions)

        # Create meta file too
        meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.yaml")
        meta_path.write_text("compiled_at: test")

        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text("name: test")
        mock_find.return_value = (workflow_yaml, cache_path)  # type: ignore[union-attr]

        result = _try_load_from_cache(cache_path, "test", tmp_path, None)
        assert result is None
        # Cache should be deleted
        assert not cache_path.exists()
        assert not meta_path.exists()

    def test_unreadable_cache_returns_none(self, tmp_path: Path) -> None:
        """Cache that can't be read should return None."""
        cache_path = tmp_path / "nonexistent.tpl.xml"
        result = _try_load_from_cache(cache_path, "test", tmp_path, None)
        assert result is None

    def test_cache_missing_sections_returns_none(self, tmp_path: Path) -> None:
        """Cache without required sections should return None."""
        cache_path = tmp_path / "test.tpl.xml"
        cache_path.write_text("just some text, no XML sections")
        result = _try_load_from_cache(cache_path, "test", tmp_path, None)
        assert result is None
