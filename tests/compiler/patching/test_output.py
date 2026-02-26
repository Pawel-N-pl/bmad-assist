"""Tests for output generator."""



from bmad_assist.compiler.patching.output import (
    TemplateMetadata,
    generate_template,
)


class TestTemplateMetadata:
    """Tests for TemplateMetadata dataclass."""

    def test_create_metadata(self) -> None:
        """Test creating template metadata."""
        meta = TemplateMetadata(
            workflow="create-story",
            patch_name="optimize-story",
            patch_version="1.0.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T12:00:00Z",
            source_hash="abc123",
        )

        assert meta.workflow == "create-story"
        assert meta.patch_name == "optimize-story"
        assert meta.patch_version == "1.0.0"
        assert meta.bmad_version == "0.1.0"


class TestGenerateTemplate:
    """Tests for template generation."""

    def test_generate_xml_template(self) -> None:
        """Test generating XML template with header."""
        content = "<workflow><step n='1'>Content</step></workflow>"
        meta = TemplateMetadata(
            workflow="create-story",
            patch_name="optimize-story",
            patch_version="1.0.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T12:00:00Z",
            source_hash="abc123def456",
        )

        result = generate_template(content, meta)

        # Should have XML comment header
        assert result.startswith("<!--")
        assert "-->" in result
        # Should contain metadata
        assert "create-story" in result
        assert "optimize-story" in result
        assert "1.0.0" in result
        assert "0.1.0" in result
        # Should contain the content
        assert "<step n='1'>Content</step>" in result

    def test_generate_template_preserves_content(self) -> None:
        """Test that content is preserved exactly."""
        content = """<workflow>
  <step n="1">
    <action>First action</action>
  </step>
  <step n="2">
    <check>Some check</check>
  </step>
</workflow>"""
        meta = TemplateMetadata(
            workflow="test",
            patch_name="test-patch",
            patch_version="1.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T00:00:00Z",
            source_hash="hash",
        )

        result = generate_template(content, meta)

        # Content should be in the result (after header)
        assert content in result

    def test_generate_template_header_format(self) -> None:
        """Test that header follows expected format."""
        content = "<workflow/>"
        meta = TemplateMetadata(
            workflow="create-story",
            patch_name="opt",
            patch_version="2.0",
            bmad_version="0.1.0",
            compiled_at="2025-06-15T10:30:00Z",
            source_hash="abcdef",
        )

        result = generate_template(content, meta)

        # Check header structure
        lines = result.split("\n")
        assert lines[0] == "<!--"

        # Find header content
        header_lines = []
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "-->":
                break
            header_lines.append(line)

        header = "\n".join(header_lines)

        # Verify expected fields
        assert "Compiled from:" in header
        assert "create-story" in header
        assert "Patch:" in header
        assert "opt" in header
        assert "v2.0" in header
        assert "BMAD:" in header
        assert "0.1.0" in header
        assert "Compiled at:" in header
        assert "Source hash:" in header

    def test_generate_template_with_special_characters(self) -> None:
        """Test that special characters in content are handled."""
        content = "<workflow><!-- existing comment --><step>Content with <special> & chars</step></workflow>"
        meta = TemplateMetadata(
            workflow="test",
            patch_name="test",
            patch_version="1.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T00:00:00Z",
            source_hash="hash",
        )

        result = generate_template(content, meta)

        # Content should be preserved
        assert "<!-- existing comment -->" in result
        assert "&" in result

    def test_generate_md_template(self) -> None:
        """Test generating markdown template (different format)."""
        content = "# Workflow\n\n## Step 1\n\nDo something"
        meta = TemplateMetadata(
            workflow="test-md",
            patch_name="opt",
            patch_version="1.0",
            bmad_version="0.1.0",
            compiled_at="2025-01-01T00:00:00Z",
            source_hash="hash",
            is_markdown=True,
        )

        result = generate_template(content, meta)

        # Markdown uses HTML comment for header too (universal)
        assert "<!--" in result
        assert content in result
