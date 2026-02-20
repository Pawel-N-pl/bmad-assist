"""Tests for Prompt Browser component (Story 23.5).

These tests verify:
1. The prompt-browser.js component file structure
2. Component registration in alpine-init.js
3. Modal markup presence in 11-tail.html
4. CSS styles for collapsible sections
5. API integration for prompt fetching

Note: Frontend JavaScript behavior is tested via integration with the
/api/prompt endpoint. Full E2E tests would require Playwright setup.
"""

from pathlib import Path

import pytest

# ==========================================
# Component Structure Tests
# ==========================================


class TestPromptBrowserComponentFile:
    """Tests for prompt-browser.js file structure."""

    @pytest.fixture
    def component_path(self) -> Path:
        """Get path to prompt-browser.js source file."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )

    @pytest.fixture
    def component_content(self, component_path: Path) -> str:
        """Read component file content."""
        return component_path.read_text(encoding="utf-8")

    def test_component_file_exists(self, component_path: Path) -> None:
        """Verify prompt-browser.js exists in static-src/js/components/."""
        assert component_path.exists(), f"Component file not found: {component_path}"

    def test_exports_window_global(self, component_content: str) -> None:
        """Verify component exports window.promptBrowserComponent."""
        assert "window.promptBrowserComponent" in component_content

    def test_has_promptbrowser_state(self, component_content: str) -> None:
        """Verify component has promptBrowser state object (AC 1)."""
        assert "promptBrowser:" in component_content
        assert "show:" in component_content
        assert "parsed:" in component_content
        assert "loading:" in component_content
        assert "parseError:" in component_content

    def test_has_parse_method(self, component_content: str) -> None:
        """Verify component has parsePromptXml method (AC 1, 5)."""
        assert "parsePromptXml" in component_content
        # Should use DOMParser for XML parsing
        assert "DOMParser" in component_content
        # Should check for parsererror (AC 5)
        assert "parsererror" in component_content

    def test_has_toggle_section(self, component_content: str) -> None:
        """Verify component has toggleSection method (AC 2)."""
        assert "toggleSection" in component_content
        assert "_expandedSections" in component_content

    def test_has_open_close_methods(self, component_content: str) -> None:
        """Verify component has openPromptBrowser and closePromptBrowser."""
        assert "openPromptBrowser" in component_content
        assert "closePromptBrowser" in component_content

    def test_has_performance_markers(self, component_content: str) -> None:
        """Verify component uses performance.mark for timing (AC 4)."""
        assert "performance.mark" in component_content
        assert "performance.measure" in component_content


class TestAlpineInitRegistration:
    """Tests for component registration in alpine-init.js."""

    @pytest.fixture
    def alpine_init_path(self) -> Path:
        """Get path to alpine-init.js file."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/alpine-init.js"
        )

    @pytest.fixture
    def alpine_init_content(self, alpine_init_path: Path) -> str:
        """Read alpine-init.js content."""
        return alpine_init_path.read_text(encoding="utf-8")

    def test_alpine_init_exists(self, alpine_init_path: Path) -> None:
        """Verify alpine-init.js exists."""
        assert alpine_init_path.exists()

    def test_prompt_browser_imported(self, alpine_init_content: str) -> None:
        """Verify promptBrowser component is imported from factory."""
        assert "window.promptBrowserComponent" in alpine_init_content
        # Should call the factory function
        assert "promptBrowserComponent()" in alpine_init_content

    def test_prompt_browser_spread(self, alpine_init_content: str) -> None:
        """Verify promptBrowser is spread into dashboard return object."""
        assert "...promptBrowser" in alpine_init_content


class TestModalMarkup:
    """Tests for modal HTML markup in 11-tail.html."""

    @pytest.fixture
    def tail_html_path(self) -> Path:
        """Get path to 11-tail.html."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )

    @pytest.fixture
    def tail_html_content(self, tail_html_path: Path) -> str:
        """Read 11-tail.html content."""
        return tail_html_path.read_text(encoding="utf-8")

    def test_tail_html_exists(self, tail_html_path: Path) -> None:
        """Verify 11-tail.html exists."""
        assert tail_html_path.exists()

    def test_prompt_browser_modal_exists(self, tail_html_content: str) -> None:
        """Verify Prompt Browser modal markup is present."""
        assert "Prompt Browser Modal" in tail_html_content
        assert 'data-testid="prompt-browser-modal"' in tail_html_content

    def test_modal_has_close_button(self, tail_html_content: str) -> None:
        """Verify modal has close button (AC 2)."""
        assert 'data-testid="close-prompt-browser"' in tail_html_content

    def test_modal_has_error_state(self, tail_html_content: str) -> None:
        """Verify modal has error state with View Raw XML button (AC 5)."""
        assert "Unable to parse prompt structure" in tail_html_content
        assert 'data-testid="view-raw-xml"' in tail_html_content

    def test_modal_has_sections(self, tail_html_content: str) -> None:
        """Verify modal has section test IDs (AC 1, 3)."""
        assert 'data-testid="section-mission"' in tail_html_content
        assert 'data-testid="section-file-index"' in tail_html_content
        assert 'data-testid="section-context"' in tail_html_content
        assert 'data-testid="section-variables"' in tail_html_content
        assert 'data-testid="section-instructions"' in tail_html_content
        assert 'data-testid="section-output"' in tail_html_content

    def test_script_include(self, tail_html_content: str) -> None:
        """Verify prompt-browser.js script is included."""
        assert 'src="/js/components/prompt-browser.js"' in tail_html_content

    def test_escape_key_handler(self, tail_html_content: str) -> None:
        """Verify Escape key closes modal (AC 2)."""
        assert "keydown.escape" in tail_html_content


class TestCSSStyles:
    """Tests for CSS styles in styles.css."""

    @pytest.fixture
    def css_path(self) -> Path:
        """Get path to styles.css."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static/css/styles.css"
        )

    @pytest.fixture
    def css_content(self, css_path: Path) -> str:
        """Read styles.css content."""
        return css_path.read_text(encoding="utf-8")

    def test_css_exists(self, css_path: Path) -> None:
        """Verify styles.css exists."""
        assert css_path.exists()

    def test_prompt_section_styles(self, css_content: str) -> None:
        """Verify .prompt-section styles exist (AC 2)."""
        assert ".prompt-section" in css_content

    def test_prompt_section_header_styles(self, css_content: str) -> None:
        """Verify .prompt-section-header styles exist with hover (AC 2)."""
        assert ".prompt-section-header" in css_content
        assert ".prompt-section-header:hover" in css_content

    def test_prompt_section_content_styles(self, css_content: str) -> None:
        """Verify .prompt-section-content styles exist."""
        assert ".prompt-section-content" in css_content

    def test_chevron_animation(self, css_content: str) -> None:
        """Verify chevron rotation animation exists (AC 2)."""
        assert ".chevron" in css_content
        assert "transform" in css_content
        assert "rotate" in css_content

    def test_transition_timing(self, css_content: str) -> None:
        """Verify transition is 150ms for responsiveness (AC 2)."""
        assert "0.15s" in css_content or "150ms" in css_content


class TestContextMenuIntegration:
    """Tests for context-menu.js integration."""

    @pytest.fixture
    def context_menu_path(self) -> Path:
        """Get path to context-menu.js."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
        )

    @pytest.fixture
    def context_menu_content(self, context_menu_path: Path) -> str:
        """Read context-menu.js content."""
        return context_menu_path.read_text(encoding="utf-8")

    def test_context_menu_exists(self, context_menu_path: Path) -> None:
        """Verify context-menu.js exists."""
        assert context_menu_path.exists()

    def test_view_prompt_calls_open_prompt_browser(
        self, context_menu_content: str
    ) -> None:
        """Verify viewPrompt() calls openPromptBrowser() (Task 6)."""
        assert "openPromptBrowser" in context_menu_content
        # Should be in the viewPrompt method context
        assert "Story 23.5: Route to Prompt Browser" in context_menu_content


class TestBuildOutput:
    """Tests for build output files."""

    @pytest.fixture
    def static_dir(self) -> Path:
        """Get path to static output directory."""
        return (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static"
        )

    def test_index_html_exists(self, static_dir: Path) -> None:
        """Verify static/index.html was built."""
        index_path = static_dir / "index.html"
        assert index_path.exists(), "Build output not found. Run build_static.py first."

    def test_prompt_browser_js_copied(self, static_dir: Path) -> None:
        """Verify prompt-browser.js was copied to static/js/components/."""
        js_path = static_dir / "js/components/prompt-browser.js"
        assert js_path.exists(), "prompt-browser.js not copied to static/"

    def test_index_html_has_modal(self, static_dir: Path) -> None:
        """Verify built index.html contains prompt browser modal."""
        index_path = static_dir / "index.html"
        content = index_path.read_text(encoding="utf-8")
        assert 'data-testid="prompt-browser-modal"' in content


# ==========================================
# API Integration Tests
# ==========================================


class TestPromptAPIResponse:
    """Tests for /api/prompt endpoint XML structure.

    These tests verify the API returns properly structured XML that
    the frontend can parse.
    """

    @pytest.fixture
    def sample_compiled_xml(self) -> str:
        """Sample compiled workflow XML for testing."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<compiled-workflow>
<mission><![CDATA[Test mission description]]></mission>
<context>
<file id="abc123" path="/test/file.md"><![CDATA[# Test Content
This is test file content.]]></file>
<file id="def456" path="/test/code.py"><![CDATA[def hello():
    print("world")]]></file>
</context>
<variables>
<var name="epic_num">23</var>
<var name="story_num" file_id="abc123">5</var>
</variables>
<file-index>
<entry id="abc123" path="/test/file.md" />
<entry id="def456" path="/test/code.py" />
</file-index>
<instructions><step>Do the thing</step></instructions>
<output-template><![CDATA[Expected output format]]></output-template>
</compiled-workflow>"""

    def test_xml_has_mission(self, sample_compiled_xml: str) -> None:
        """Verify XML contains mission section."""
        assert "<mission>" in sample_compiled_xml
        assert "</mission>" in sample_compiled_xml

    def test_xml_has_context_with_files(self, sample_compiled_xml: str) -> None:
        """Verify XML contains context with file elements."""
        assert "<context>" in sample_compiled_xml
        assert '<file id="' in sample_compiled_xml
        assert 'path="' in sample_compiled_xml

    def test_xml_has_file_index(self, sample_compiled_xml: str) -> None:
        """Verify XML contains file-index section (sibling of context)."""
        assert "<file-index>" in sample_compiled_xml
        assert '<entry id="' in sample_compiled_xml

    def test_xml_has_variables(self, sample_compiled_xml: str) -> None:
        """Verify XML contains variables section."""
        assert "<variables>" in sample_compiled_xml
        assert '<var name="' in sample_compiled_xml

    def test_xml_has_instructions(self, sample_compiled_xml: str) -> None:
        """Verify XML contains instructions section."""
        assert "<instructions>" in sample_compiled_xml
        assert "</instructions>" in sample_compiled_xml

    def test_xml_has_output_template(self, sample_compiled_xml: str) -> None:
        """Verify XML contains output-template section."""
        assert "<output-template>" in sample_compiled_xml
        assert "</output-template>" in sample_compiled_xml

    def test_xml_is_well_formed(self, sample_compiled_xml: str) -> None:
        """Verify XML can be parsed (well-formed)."""
        import xml.etree.ElementTree as ET

        # Should not raise
        root = ET.fromstring(sample_compiled_xml)
        assert root.tag == "compiled-workflow"


# ==========================================
# XML Parsing Logic Tests
# ==========================================


class TestXMLParsingLogic:
    """Tests for XML parsing logic matching frontend behavior.

    These tests verify Python-side XML parsing that mirrors
    what the frontend JavaScript does.
    """

    @pytest.fixture
    def sample_xml(self) -> str:
        """Sample XML for parsing tests."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<compiled-workflow>
<mission><![CDATA[Execute the test]]></mission>
<context>
<file id="f1" path="/a.md"><![CDATA[Content A]]></file>
<file id="f2" path="/b.py"><![CDATA[Content B]]></file>
</context>
<variables>
<var name="epic_num">1</var>
</variables>
<file-index>
<entry id="f1" path="/a.md" />
<entry id="f2" path="/b.py" />
</file-index>
<instructions>Step 1</instructions>
<output-template><![CDATA[Output]]></output-template>
</compiled-workflow>"""

    def test_parse_mission(self, sample_xml: str) -> None:
        """Verify mission can be extracted."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(sample_xml)
        mission = root.find("mission")
        assert mission is not None
        assert mission.text == "Execute the test"

    def test_parse_context_files(self, sample_xml: str) -> None:
        """Verify context files can be extracted with id and path."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(sample_xml)
        context = root.find("context")
        assert context is not None

        files = context.findall("file")
        assert len(files) == 2

        assert files[0].get("id") == "f1"
        assert files[0].get("path") == "/a.md"
        assert files[0].text == "Content A"

    def test_parse_file_index(self, sample_xml: str) -> None:
        """Verify file-index entries can be extracted."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(sample_xml)
        file_index = root.find("file-index")
        assert file_index is not None

        entries = file_index.findall("entry")
        assert len(entries) == 2
        assert entries[0].get("id") == "f1"
        assert entries[0].get("path") == "/a.md"

    def test_parse_variables(self, sample_xml: str) -> None:
        """Verify variables can be extracted with name and value."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(sample_xml)
        variables = root.find("variables")
        assert variables is not None

        var_els = variables.findall("var")
        assert len(var_els) == 1
        assert var_els[0].get("name") == "epic_num"
        assert var_els[0].text == "1"

    def test_malformed_xml_detected(self) -> None:
        """Verify malformed XML raises exception (AC 5)."""
        import xml.etree.ElementTree as ET

        malformed = "<compiled-workflow><mission>Unclosed"

        with pytest.raises(ET.ParseError):
            ET.fromstring(malformed)


# ==========================================
# Story 23.6 - CDATA & Content Detection Tests
# ==========================================


class TestCDATADetection:
    """Tests for CDATA detection in prompt-browser.js (Story 23.6 AC1)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_cdata_detection_in_extract_context(self, component_content: str) -> None:
        """Verify _extractContext checks innerHTML for CDATA markers."""
        # Should check innerHTML before textContent
        assert "innerHTML" in component_content
        assert "hasCdata" in component_content
        # CDATA regex pattern
        assert r"<!\[CDATA\[" in component_content

    def test_cdata_detection_handles_split_pattern(self, component_content: str) -> None:
        """Verify detection handles split CDATA pattern ]]><![CDATA[."""
        # Should detect both standard and split CDATA patterns
        assert r"\]\]><!\[CDATA\[" in component_content or "]]><![CDATA[" in component_content

    def test_file_object_has_cdata_property(self, component_content: str) -> None:
        """Verify file extraction includes hasCdata property."""
        # The file object should include hasCdata
        assert "hasCdata" in component_content
        assert "contentType" in component_content

    def test_cached_content_types_in_parsing(self, component_content: str) -> None:
        """Verify content types are cached during XML parsing (performance fix)."""
        # Should cache missionContentType, instructionsContentType, outputContentType
        assert "missionContentType:" in component_content
        assert "instructionsContentType:" in component_content
        assert "outputContentType:" in component_content

    def test_consolidated_highlight_queue_method(self, component_content: str) -> None:
        """Verify _queueHighlight consolidates duplicate methods (DRY fix)."""
        # Should have shared _queueHighlight method
        assert "_queueHighlight(blockId, content, lang)" in component_content
        # Wrapper methods should delegate to shared method
        assert "_queuePromptBrowserHighlight(blockId, code, lang)" in component_content
        assert "_queueXmlHighlight(blockId, content)" in component_content


class TestCDATAIndicatorMarkup:
    """Tests for CDATA indicator markup in 11-tail.html (Story 23.6 AC1)."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Read 11-tail.html content."""
        tail_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )
        return tail_path.read_text(encoding="utf-8")

    def test_cdata_indicator_present(self, tail_html_content: str) -> None:
        """Verify CDATA indicator markup exists."""
        assert 'class="cdata-indicator' in tail_html_content
        assert "file.hasCdata" in tail_html_content

    def test_cdata_indicator_has_tooltip(self, tail_html_content: str) -> None:
        """Verify CDATA indicator has tooltip text."""
        assert 'title="Content wrapped in CDATA"' in tail_html_content

    def test_cdata_indicator_uses_package_icon(self, tail_html_content: str) -> None:
        """Verify CDATA indicator uses package icon (Story 24.4 AC4)."""
        assert 'data-lucide="package"' in tail_html_content


class TestCDATAIndicatorCSS:
    """Tests for CDATA indicator CSS styles (Story 23.6 AC1)."""

    @pytest.fixture
    def css_content(self) -> str:
        """Read styles.css content."""
        css_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static/css/styles.css"
        )
        return css_path.read_text(encoding="utf-8")

    def test_cdata_indicator_class_exists(self, css_content: str) -> None:
        """Verify .cdata-indicator class exists."""
        assert ".cdata-indicator" in css_content

    def test_cdata_indicator_opacity_50_default(self, css_content: str) -> None:
        """Verify CDATA indicator has opacity 0.5 by default."""
        assert "opacity: 0.5" in css_content

    def test_cdata_indicator_opacity_100_hover(self, css_content: str) -> None:
        """Verify CDATA indicator has opacity 1.0 on hover."""
        assert ".cdata-indicator:hover" in css_content
        assert "opacity: 1.0" in css_content or "opacity: 1;" in css_content


class TestContentTypeDetection:
    """Tests for content type detection logic (Story 23.6 AC2, AC3, AC5)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_detect_content_type_method_exists(self, component_content: str) -> None:
        """Verify detectContentType method exists."""
        assert "detectContentType" in component_content

    def test_detect_content_type_returns_types(self, component_content: str) -> None:
        """Verify method can return markdown, xml, or text."""
        assert "'markdown'" in component_content
        assert "'xml'" in component_content
        assert "'text'" in component_content

    def test_markdown_detection_header(self, component_content: str) -> None:
        """Verify Markdown header detection (# Header)."""
        assert "hasHeader" in component_content
        # Should check for # at start of line
        assert r"^#{1,6}\s" in component_content or "^#" in component_content

    def test_markdown_detection_unordered_list(self, component_content: str) -> None:
        """Verify Markdown unordered list detection (- item, * item)."""
        assert "hasUnorderedList" in component_content
        assert r"^[-*]\s" in component_content or "[-*]" in component_content

    def test_markdown_detection_ordered_list(self, component_content: str) -> None:
        """Verify Markdown ordered list detection (1. item)."""
        assert "hasOrderedList" in component_content
        assert r"\d+\.\s" in component_content

    def test_markdown_detection_code_block(self, component_content: str) -> None:
        """Verify Markdown code block detection (```)."""
        assert "hasCodeBlock" in component_content
        assert "```" in component_content

    def test_xml_detection_starts_with_tag(self, component_content: str) -> None:
        """Verify XML detection checks for starting tag."""
        assert "startsWithTag" in component_content
        assert r"^<[a-zA-Z]" in component_content

    def test_xml_detection_balanced_tags(self, component_content: str) -> None:
        """Verify XML detection checks for balanced tags."""
        assert "hasBalancedTags" in component_content

    def test_short_content_returns_text(self, component_content: str) -> None:
        """Verify short content (< 50 chars) returns 'text'."""
        assert "content.length < 50" in component_content or "< 50" in component_content


class TestMarkdownRendering:
    """Tests for Markdown rendering with Shiki (Story 23.6 AC2)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_render_markdown_content_method_exists(self, component_content: str) -> None:
        """Verify renderMarkdownContent method exists."""
        assert "renderMarkdownContent" in component_content

    def test_markdown_uses_escape_html(self, component_content: str) -> None:
        """Verify Markdown rendering uses escapeHtml for XSS protection."""
        assert "escapeHtml" in component_content

    def test_markdown_extracts_code_blocks(self, component_content: str) -> None:
        """Verify Markdown rendering extracts fenced code blocks."""
        assert "codeBlockRegex" in component_content or "```" in component_content

    def test_markdown_queues_shiki_highlight(self, component_content: str) -> None:
        """Verify Markdown rendering queues async Shiki highlighting."""
        assert "_queuePromptBrowserHighlight" in component_content


class TestXMLRendering:
    """Tests for XML rendering with Shiki (Story 23.6 AC3, AC4)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_render_xml_content_method_exists(self, component_content: str) -> None:
        """Verify renderXmlContent method exists."""
        assert "renderXmlContent" in component_content

    def test_xml_uses_escape_html(self, component_content: str) -> None:
        """Verify XML rendering uses escapeHtml for XSS protection."""
        # renderXmlContent should use escapeHtml
        assert "escapeHtml" in component_content

    def test_xml_queues_shiki_highlight(self, component_content: str) -> None:
        """Verify XML rendering queues async Shiki highlighting."""
        assert "_queueXmlHighlight" in component_content

    def test_xml_shiki_lang_is_xml(self, component_content: str) -> None:
        """Verify XML highlighting uses 'xml' language."""
        assert "'xml'" in component_content


class TestContentTypeBasedRendering:
    """Tests for content type based rendering in templates (Story 23.6)."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Read 11-tail.html content."""
        tail_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )
        return tail_path.read_text(encoding="utf-8")

    def test_file_section_has_markdown_template(self, tail_html_content: str) -> None:
        """Verify file section has template for markdown content."""
        assert "file.contentType === 'markdown'" in tail_html_content

    def test_file_section_has_xml_template(self, tail_html_content: str) -> None:
        """Verify file section has template for XML content."""
        assert "file.contentType === 'xml'" in tail_html_content

    def test_file_section_has_text_fallback(self, tail_html_content: str) -> None:
        """Verify file section has fallback for plain text."""
        assert "file.contentType === 'text'" in tail_html_content

    def test_mission_section_uses_cached_content_type(self, tail_html_content: str) -> None:
        """Verify mission section uses cached missionContentType (performance fix)."""
        # Mission section should use cached content type from parsing phase
        assert "promptBrowser.parsed?.missionContentType" in tail_html_content

    def test_instructions_section_uses_cached_content_type(
        self, tail_html_content: str
    ) -> None:
        """Verify instructions section uses cached instructionsContentType (performance fix)."""
        assert "promptBrowser.parsed?.instructionsContentType" in tail_html_content

    def test_output_section_uses_cached_content_type(self, tail_html_content: str) -> None:
        """Verify output section uses cached outputContentType (performance fix)."""
        assert "promptBrowser.parsed?.outputContentType" in tail_html_content


class TestAsyncHighlightCleanup:
    """Tests for async highlight cleanup on modal close (Story 23.6)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_pending_highlights_tracking(self, component_content: str) -> None:
        """Verify pending highlights are tracked."""
        assert "_pendingPromptBrowserHighlights" in component_content

    def test_cancel_pending_highlights_method_exists(self, component_content: str) -> None:
        """Verify cancel method exists."""
        assert "_cancelPendingPromptBrowserHighlights" in component_content

    def test_close_cancels_pending_highlights(self, component_content: str) -> None:
        """Verify closePromptBrowser calls cancel method."""
        # Check that closePromptBrowser calls _cancelPendingPromptBrowserHighlights
        assert "_cancelPendingPromptBrowserHighlights" in component_content
        # The call should be in closePromptBrowser context
        assert "closePromptBrowser" in component_content


class TestXSSProtection:
    """Tests for XSS protection in content rendering (Story 23.6)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_escape_html_used_in_render_markdown(self, component_content: str) -> None:
        """Verify renderMarkdownContent escapes non-code content."""
        # Should use escapeHtml from dashboardUtils
        assert "window.dashboardUtils" in component_content
        assert "escapeHtml" in component_content

    def test_escape_html_used_in_render_xml(self, component_content: str) -> None:
        """Verify renderXmlContent escapes content."""
        # renderXmlContent should also use escapeHtml
        assert "escapeHtml" in component_content

    def test_fallback_escape_html_exists(self, component_content: str) -> None:
        """Verify fallback escapeHtml method exists in component."""
        # The component has its own escapeHtml method as fallback
        assert "this.escapeHtml" in component_content or "escapeHtml(text)" in component_content


# ==========================================
# Story 23.7 - Variables Panel Tests
# ==========================================


class TestVariablesViewState:
    """Tests for variablesView state and toggleVariablesView method (Story 23.7 AC1)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_variables_view_state_exists(self, component_content: str) -> None:
        """Verify variablesView state exists with default 'rendered'."""
        assert "variablesView:" in component_content
        assert "'rendered'" in component_content

    def test_toggle_variables_view_method_exists(self, component_content: str) -> None:
        """Verify toggleVariablesView method exists."""
        assert "toggleVariablesView" in component_content

    def test_toggle_switches_between_views(self, component_content: str) -> None:
        """Verify toggle switches between 'rendered' and 'raw'."""
        assert "variablesView === 'rendered' ? 'raw' : 'rendered'" in component_content

    def test_open_prompt_browser_resets_view(self, component_content: str) -> None:
        """Verify openPromptBrowser resets variablesView to 'rendered'."""
        # Look for the reset in openPromptBrowser context
        assert "variablesView = 'rendered'" in component_content
        # Should mention Story 23.7 context
        assert "Reset variables view to rendered for consistent fresh state" in component_content


class TestProjectRootDetection:
    """Tests for _detectProjectRoot method (Story 23.7 AC2, AC3).

    Story 24.1: Implementation moved to content-browser.js, prompt-browser.js delegates.
    """

    @pytest.fixture
    def prompt_browser_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    @pytest.fixture
    def content_browser_content(self) -> str:
        """Read content-browser.js content (Story 24.1)."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/content-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_detect_project_root_method_exists(self, prompt_browser_content: str) -> None:
        """Verify _detectProjectRoot method exists in prompt-browser."""
        assert "_detectProjectRoot" in prompt_browser_content

    def test_prompt_browser_delegates_to_shared(self, prompt_browser_content: str) -> None:
        """Story 24.1: Verify prompt-browser delegates to contentBrowserUtils."""
        assert "window.contentBrowserUtils.detectProjectRoot" in prompt_browser_content

    def test_handles_empty_variables(self, content_browser_content: str) -> None:
        """Verify shared utility handles empty/null variables gracefully."""
        assert "if (!variables || variables.length === 0) return null" in content_browser_content

    def test_uses_file_suffix_pattern(self, content_browser_content: str) -> None:
        """Verify shared utility checks for *_file variable names."""
        assert "endsWith('_file')" in content_browser_content

    def test_uses_project_markers_fallback(self, content_browser_content: str) -> None:
        """Verify shared utility uses project markers as fallback."""
        # Should have markers array
        assert "'/docs/'" in content_browser_content
        assert "'/src/'" in content_browser_content
        assert "'/_bmad-output/'" in content_browser_content
        assert "'/tests/'" in content_browser_content

    def test_finds_common_prefix(self, content_browser_content: str) -> None:
        """Verify shared utility finds longest common directory prefix with boundary check."""
        # Should have logic to find common prefix with proper directory boundary checking
        assert "lastIndexOf('/')" in content_browser_content
        # FIX: Updated to check for boundary-safe pattern (path === prefix || startsWith(prefix + '/'))
        assert "startsWith(prefix + '/')" in content_browser_content


class TestPathShortening:
    """Tests for shortenPath method (Story 23.7 AC2, AC3).

    Story 24.1: Implementation moved to content-browser.js, prompt-browser.js delegates.
    """

    @pytest.fixture
    def prompt_browser_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    @pytest.fixture
    def content_browser_content(self) -> str:
        """Read content-browser.js content (Story 24.1)."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/content-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_shorten_path_method_exists(self, prompt_browser_content: str) -> None:
        """Verify shortenPath method exists in prompt-browser."""
        assert "shortenPath(fullPath, projectRoot)" in prompt_browser_content

    def test_prompt_browser_delegates_to_shared(self, prompt_browser_content: str) -> None:
        """Story 24.1: Verify prompt-browser delegates to contentBrowserUtils."""
        assert "window.contentBrowserUtils.shortenPath" in prompt_browser_content

    def test_handles_empty_path(self, content_browser_content: str) -> None:
        """Verify shared utility returns empty string for empty path."""
        assert "if (!fullPath) return ''" in content_browser_content

    def test_removes_project_root_prefix(self, content_browser_content: str) -> None:
        """Verify shared utility removes project root from path with boundary check."""
        # FIX: Updated to check for boundary-safe pattern (path === root || startsWith(root + '/'))
        assert "fullPath.startsWith(projectRoot + '/')" in content_browser_content
        assert "fullPath.slice(projectRoot.length)" in content_browser_content

    def test_uses_markers_as_fallback(self, content_browser_content: str) -> None:
        """Verify shared utility uses project markers when no root provided."""
        # Should have fallback marker detection
        assert "fullPath.indexOf(marker)" in content_browser_content


class TestVariableCategorization:
    """Tests for _categorizeVariables method (Story 23.7 AC2)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_categorize_variables_method_exists(self, component_content: str) -> None:
        """Verify _categorizeVariables method exists."""
        assert "_categorizeVariables" in component_content

    def test_has_story_context_category(self, component_content: str) -> None:
        """Verify Story Context category exists."""
        assert "'Story Context'" in component_content
        # Check for story-related variable names
        assert "'epic_num'" in component_content
        assert "'story_num'" in component_content
        assert "'story_key'" in component_content

    def test_has_input_files_category(self, component_content: str) -> None:
        """Verify Input Files category exists."""
        assert "'Input Files'" in component_content

    def test_has_output_paths_category(self, component_content: str) -> None:
        """Verify Output Paths category exists."""
        assert "'Output Paths'" in component_content

    def test_has_project_settings_category(self, component_content: str) -> None:
        """Verify Project Settings category exists."""
        assert "'Project Settings'" in component_content
        # Check for settings-related variable names
        assert "'project_name'" in component_content
        assert "'user_name'" in component_content

    def test_has_other_category(self, component_content: str) -> None:
        """Verify Other category exists for uncategorized variables."""
        assert "'Other'" in component_content

    def test_categorizes_file_suffix_to_input_files(self, component_content: str) -> None:
        """Verify *_file variables go to Input Files category."""
        assert "endsWith('_file')" in component_content
        assert "categories['Input Files']" in component_content

    def test_categorizes_artifacts_suffix_to_output_paths(self, component_content: str) -> None:
        """Verify *_artifacts variables go to Output Paths category."""
        assert "endsWith('_artifacts')" in component_content
        assert "categories['Output Paths']" in component_content


class TestCategoryOrderAndAccess:
    """Tests for getVariableCategoryOrder and getVariablesForCategory (Story 23.7)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_get_variable_category_order_exists(self, component_content: str) -> None:
        """Verify getVariableCategoryOrder method exists."""
        assert "getVariableCategoryOrder" in component_content

    def test_category_order_is_correct(self, component_content: str) -> None:
        """Verify categories are in correct order."""
        # Should have ordered array
        assert "['Story Context', 'Input Files', 'Output Paths', 'Project Settings', 'Other']" in component_content

    def test_filters_empty_categories(self, component_content: str) -> None:
        """Verify empty categories are filtered out."""
        assert "filter(cat =>" in component_content
        assert "categorized[cat].length > 0" in component_content

    def test_get_variables_for_category_exists(self, component_content: str) -> None:
        """Verify getVariablesForCategory method exists."""
        assert "getVariablesForCategory(categoryName)" in component_content


class TestRawXmlRetrieval:
    """Tests for getVariablesRawXml method (Story 23.7 AC4)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_get_variables_raw_xml_exists(self, component_content: str) -> None:
        """Verify getVariablesRawXml method exists."""
        assert "getVariablesRawXml" in component_content

    def test_prefers_stored_raw_xml(self, component_content: str) -> None:
        """Verify method prefers stored rawVariablesXml."""
        assert "rawVariablesXml" in component_content
        assert "parsed?.rawVariablesXml" in component_content

    def test_has_fallback_reconstruction(self, component_content: str) -> None:
        """Verify method can reconstruct XML from parsed data."""
        assert "<variables>" in component_content
        assert "</variables>" in component_content

    def test_escapes_xml_special_chars(self, component_content: str) -> None:
        """Verify XML special characters are escaped in fallback."""
        assert "'&amp;'" in component_content or '"&amp;"' in component_content
        assert "'&lt;'" in component_content or '"&lt;"' in component_content
        assert "'&gt;'" in component_content or '"&gt;"' in component_content


class TestExtractVariablesEnhanced:
    """Tests for enhanced _extractVariables method (Story 23.7)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_extract_variables_stores_raw_xml(self, component_content: str) -> None:
        """Verify _extractVariables stores original XML."""
        # Should capture outerHTML
        assert "varsEl.outerHTML" in component_content
        assert "rawXml" in component_content

    def test_extract_variables_returns_enhanced_object(self, component_content: str) -> None:
        """Verify _extractVariables returns object with all fields."""
        # Should return object with variables, rawXml, projectRoot, categorized
        assert "return { variables, rawXml, projectRoot, categorized }" in component_content

    def test_calls_detect_project_root(self, component_content: str) -> None:
        """Verify _extractVariables calls _detectProjectRoot."""
        assert "this._detectProjectRoot(variables)" in component_content

    def test_calls_categorize_variables(self, component_content: str) -> None:
        """Verify _extractVariables calls _categorizeVariables."""
        assert "this._categorizeVariables(variables, projectRoot)" in component_content


class TestParsePromptXmlEnhanced:
    """Tests for enhanced parsePromptXml with variables data (Story 23.7)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_parsed_includes_raw_variables_xml(self, component_content: str) -> None:
        """Verify parsed result includes rawVariablesXml."""
        assert "rawVariablesXml:" in component_content

    def test_parsed_includes_project_root(self, component_content: str) -> None:
        """Verify parsed result includes projectRoot."""
        assert "projectRoot:" in component_content

    def test_parsed_includes_categorized_variables(self, component_content: str) -> None:
        """Verify parsed result includes categorizedVariables."""
        assert "categorizedVariables:" in component_content


class TestVariablesPanelMarkup:
    """Tests for Variables Panel markup in 11-tail.html (Story 23.7)."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Read 11-tail.html content."""
        tail_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )
        return tail_path.read_text(encoding="utf-8")

    def test_view_toggle_buttons_exist(self, tail_html_content: str) -> None:
        """Verify view toggle buttons are present (AC1)."""
        assert 'data-testid="variables-view-toggle"' in tail_html_content
        assert 'data-testid="variables-view-rendered"' in tail_html_content
        assert 'data-testid="variables-view-raw"' in tail_html_content

    def test_rendered_view_container_exists(self, tail_html_content: str) -> None:
        """Verify rendered view container is present (AC2)."""
        assert 'data-testid="variables-rendered"' in tail_html_content
        assert 'class="variables-rendered-view"' in tail_html_content

    def test_raw_view_container_exists(self, tail_html_content: str) -> None:
        """Verify raw view container is present (AC4)."""
        assert 'data-testid="variables-raw"' in tail_html_content

    def test_uses_category_order_method(self, tail_html_content: str) -> None:
        """Verify template uses getVariableCategoryOrder()."""
        assert "getVariableCategoryOrder()" in tail_html_content

    def test_uses_variables_for_category_method(self, tail_html_content: str) -> None:
        """Verify template uses getVariablesForCategory()."""
        assert "getVariablesForCategory(categoryName)" in tail_html_content

    def test_displays_category_headers(self, tail_html_content: str) -> None:
        """Verify category headers are displayed."""
        assert 'class="variables-category-header"' in tail_html_content

    def test_uses_multi_column_grid(self, tail_html_content: str) -> None:
        """Verify multi-column grid class is used."""
        assert 'class="variables-grid"' in tail_html_content

    def test_path_tooltip_for_shortened_paths(self, tail_html_content: str) -> None:
        """Verify shortened paths have tooltip with full path (AC3)."""
        assert "isPathShortened(v)" in tail_html_content
        assert ":title=" in tail_html_content
        assert "v.fullValue" in tail_html_content

    def test_uses_raw_xml_method(self, tail_html_content: str) -> None:
        """Verify raw view uses getVariablesRawXml()."""
        assert "getVariablesRawXml()" in tail_html_content

    def test_raw_view_uses_render_xml_content(self, tail_html_content: str) -> None:
        """Verify raw view uses renderXmlContent for Shiki highlighting."""
        assert "renderXmlContent(getVariablesRawXml()" in tail_html_content


class TestVariablesPanelCSS:
    """Tests for Variables Panel CSS styles (Story 23.7)."""

    @pytest.fixture
    def css_content(self) -> str:
        """Read styles.css content."""
        css_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static/css/styles.css"
        )
        return css_path.read_text(encoding="utf-8")

    def test_variables_view_toggle_styles(self, css_content: str) -> None:
        """Verify .variables-view-toggle styles exist."""
        assert ".variables-view-toggle" in css_content
        assert ".variables-view-toggle button" in css_content
        assert ".variables-view-toggle button.active" in css_content

    def test_variables_rendered_view_styles(self, css_content: str) -> None:
        """Verify .variables-rendered-view styles exist."""
        assert ".variables-rendered-view" in css_content

    def test_variables_category_styles(self, css_content: str) -> None:
        """Verify .variables-category styles exist."""
        assert ".variables-category" in css_content
        assert ".variables-category-header" in css_content

    def test_variables_grid_styles(self, css_content: str) -> None:
        """Verify .variables-grid responsive styles exist."""
        assert ".variables-grid" in css_content
        assert "grid-template-columns" in css_content

    def test_variables_grid_responsive(self, css_content: str) -> None:
        """Verify grid is responsive with media queries."""
        assert "@media (min-width: 640px)" in css_content
        assert "@media (min-width: 1024px)" in css_content

    def test_variable_item_styles(self, css_content: str) -> None:
        """Verify .variable-item styles exist."""
        assert ".variable-item" in css_content
        assert ".variable-name" in css_content
        assert ".variable-value" in css_content

    def test_variable_value_truncation(self, css_content: str) -> None:
        """Verify variable values have truncation styles."""
        assert "text-overflow: ellipsis" in css_content
        assert "max-width: 200px" in css_content

    def test_cursor_help_for_shortened_paths(self, css_content: str) -> None:
        """Verify cursor-help class for shortened paths."""
        assert ".variable-value.cursor-help" in css_content
        assert "cursor: help" in css_content


class TestIsPathShortenedMethod:
    """Tests for isPathShortened method (Story 23.7 AC3)."""

    @pytest.fixture
    def component_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_is_path_shortened_exists(self, component_content: str) -> None:
        """Verify isPathShortened method exists."""
        assert "isPathShortened(variable)" in component_content

    def test_checks_display_vs_full_value(self, component_content: str) -> None:
        """Verify method compares displayValue and fullValue."""
        assert "displayValue !== variable.fullValue" in component_content

    def test_checks_path_starts_with_slash(self, component_content: str) -> None:
        """Verify method checks if fullValue is an absolute path."""
        assert "fullValue.startsWith('/')" in component_content


# ==========================================
# Story 24.2 - View Prompt Phase ID Fix Tests
# ==========================================


class TestViewPromptPhaseIdFix:
    """Tests for Story 24.2 - Fix View Prompt Phase ID Bug.

    Verifies that context-menu.js uses phase.id (snake_case) instead of
    phase.name (display name) when calling the API.
    """

    @pytest.fixture
    def context_menu_content(self) -> str:
        """Read context-menu.js content."""
        context_menu_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
        )
        return context_menu_path.read_text(encoding="utf-8")

    def test_view_prompt_uses_phase_id_not_name(self, context_menu_content: str) -> None:
        """AC1: Verify view-prompt case uses item?.id instead of item?.name."""
        # Should NOT use item?.name for phase ID
        assert "item?.name || 'dev-story'" not in context_menu_content
        # Should use item?.id with snake_case default
        assert "item?.id || 'dev_story'" in context_menu_content

    def test_view_prompt_simplified_phase_only(self, context_menu_content: str) -> None:
        """AC4: Verify view-prompt handler uses item?.id directly (Story 24.10 simplification).

        Story 24.10 removed story-level View Prompt, so handler no longer needs
        type === 'phase' check. Handler now uses item?.id || 'dev_story' directly.
        """
        # Find the view-prompt case
        case_start = context_menu_content.find("case 'view-prompt':")
        assert case_start != -1, "view-prompt case not found"
        next_case = context_menu_content.find("case '", case_start + 20)
        section = context_menu_content[case_start:next_case]

        # Story 24.10: Should NOT have type === 'phase' check anymore
        assert "if (type === 'phase')" not in section
        # Story 24.10: Should NOT have Story-level comment anymore
        assert "Story-level" not in section
        # Should use item?.id || 'dev_story' directly
        assert "const phaseId = item?.id || 'dev_story'" in section

    def test_view_prompt_has_defensive_warning(self, context_menu_content: str) -> None:
        """AC1.3: Verify defensive check logs warning when phase ID is undefined."""
        assert "console.warn" in context_menu_content
        assert "Phase ID undefined" in context_menu_content

    def test_story_24_2_comment_present(self, context_menu_content: str) -> None:
        """Verify Story 24.2 comment is present for traceability."""
        assert "Story 24.2" in context_menu_content
        assert "snake_case" in context_menu_content

    def test_re_run_phase_aborts_on_missing_id(self, context_menu_content: str) -> None:
        """Verify re-run-phase aborts with toast when phase ID is missing."""
        # Should NOT silently fall back to name
        assert "item?.id || item?.name" not in context_menu_content
        # Should abort and show toast when ID missing
        assert "Cannot re-run: phase ID missing" in context_menu_content


class TestViewPromptAvailability:
    """Tests for Story 24.2 AC2 - View Prompt available before completion."""

    @pytest.fixture
    def context_menu_content(self) -> str:
        """Read context-menu.js content."""
        context_menu_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
        )
        return context_menu_path.read_text(encoding="utf-8")

    def test_view_prompt_not_restricted_to_completed(
        self, context_menu_content: str
    ) -> None:
        """AC2: Verify View Prompt is added unconditionally in getPhaseActions."""
        # Find the getPhaseActions function
        func_start = context_menu_content.find("getPhaseActions(phase)")
        assert func_start != -1, "getPhaseActions function not found"

        # Find the first actions.push (should be View Prompt)
        first_push = context_menu_content.find("actions.push", func_start)
        assert first_push != -1, "No actions.push found"

        # Verify the first push is View Prompt
        first_action = context_menu_content[first_push:first_push + 200]
        assert "view-prompt" in first_action
        assert "testId: 'action-view-prompt'" in first_action

        # Verify there's no 'completed' status check before View Prompt is added
        section_before_view_prompt = context_menu_content[func_start:first_push]
        assert "phaseStatus === 'completed'" not in section_before_view_prompt


class TestGetPhaseActionsUsesPhaseId:
    """Tests for Story 24.2 synthesis fix - getPhaseActions uses phase.id not phase.name."""

    @pytest.fixture
    def context_menu_content(self) -> str:
        """Read context-menu.js content."""
        context_menu_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
        )
        return context_menu_path.read_text(encoding="utf-8")

    def test_get_phase_actions_uses_phase_id(self, context_menu_content: str) -> None:
        """Verify getPhaseActions uses phase.id (snake_case) not phase.name (display name)."""
        # Should NOT use phase?.name for matching
        assert "phaseName === 'create-story'" not in context_menu_content
        assert "phaseName === 'dev-story'" not in context_menu_content
        # Should use phase?.id for matching with snake_case
        assert "phaseId === 'create_story'" in context_menu_content
        assert "phaseId === 'dev_story'" in context_menu_content

    def test_get_phase_actions_extracts_phase_id(self, context_menu_content: str) -> None:
        """Verify getPhaseActions extracts phase?.id not phase?.name."""
        # Should extract phaseId from phase.id
        assert "const phaseId = phase?.id" in context_menu_content
        # Should NOT extract phaseName from phase.name
        assert "const phaseName = phase?.name" not in context_menu_content

    def test_get_phase_actions_uses_snake_case_phases(self, context_menu_content: str) -> None:
        """Verify phase matching in getPhaseActions uses snake_case convention."""
        # All phase checks should use snake_case (underscores)
        assert "validate_story" in context_menu_content
        assert "validate_story_synthesis" in context_menu_content
        assert "code_review" in context_menu_content
        assert "code_review_synthesis" in context_menu_content
        # Phase comparisons should NOT use hyphenated format (note: other uses like 'dev-story' workflow name are OK)
        # Check specifically for phase comparisons (phaseId === or phaseName ===)
        assert "phaseId === 'create-story'" not in context_menu_content
        assert "phaseId === 'dev-story'" not in context_menu_content
        assert "phaseId === 'code-review'" not in context_menu_content
        assert "phaseName === 'create-story'" not in context_menu_content
        assert "phaseName === 'dev-story'" not in context_menu_content


class TestPromptTerminologyFrontend:
    """Tests for Story 24.2 AC3 - Prompt terminology in frontend."""

    @pytest.fixture
    def context_menu_content(self) -> str:
        """Read context-menu.js content."""
        context_menu_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/context-menu.js"
        )
        return context_menu_path.read_text(encoding="utf-8")

    def test_modal_title_uses_prompt_not_template(
        self, context_menu_content: str
    ) -> None:
        """AC3.1: Verify modal title uses 'Prompt:' not 'Template:'."""
        # Should have "Prompt: ${phase}" not "Template: ${phase}"
        assert "Prompt: ${phase}" in context_menu_content or "`Prompt: ${phase}`" in context_menu_content
        assert "Template: ${phase}" not in context_menu_content

    def test_404_error_uses_prompt_terminology(
        self, context_menu_content: str
    ) -> None:
        """AC3.2: Verify 404 fallback uses 'Prompt not found'."""
        assert "Prompt not found for phase:" in context_menu_content
        assert "Template not found for phase:" not in context_menu_content

    def test_network_error_uses_prompt_terminology(
        self, context_menu_content: str
    ) -> None:
        """AC3.3: Verify network error uses 'Failed to fetch prompt'."""
        assert "Failed to fetch prompt" in context_menu_content
        # Should NOT have 'Failed to fetch template'
        # Note: The string appears in the showToast call
        lines = context_menu_content.split("\n")
        for line in lines:
            if "showToast" in line and "fetch" in line.lower():
                assert "template" not in line.lower() or "prompt" in line.lower()


class TestPromptTerminologyBackend:
    """Tests for Story 24.2 AC3 - Prompt terminology in backend."""

    @pytest.fixture
    def backend_content(self) -> str:
        """Read routes/content.py content."""
        backend_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/routes/content.py"
        )
        return backend_path.read_text(encoding="utf-8")

    def test_docstring_uses_prompt_terminology(self, backend_content: str) -> None:
        """AC3.4.2: Verify docstring uses 'Get compiled prompt'."""
        assert "Get compiled prompt" in backend_content
        assert "Get compiled template" not in backend_content

    def test_404_error_uses_prompt_terminology(self, backend_content: str) -> None:
        """AC3.4.1: Verify 404 error uses 'Prompt not found'."""
        assert "Prompt not found for phase:" in backend_content
        assert "Template not found for phase:" not in backend_content

    def test_story_24_2_comment_present(self, backend_content: str) -> None:
        """Verify Story 24.2 comment is present for traceability."""
        assert "Story 24.2" in backend_content


# ==========================================
# Story 24.4 - Prompt Browser Defaults & Polish
# ==========================================


class TestMissionSectionCollapsible:
    """Tests for Mission section collapsible behavior (Story 24.4 AC3)."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Read 11-tail.html content."""
        tail_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )
        return tail_path.read_text(encoding="utf-8")

    @pytest.fixture
    def prompt_browser_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_mission_section_has_chevron_icon(self, tail_html_content: str) -> None:
        """AC3: Verify Mission section has chevron icon for collapsing."""
        # Mission section should have chevron with dynamic data-lucide binding
        assert 'data-testid="section-mission"' in tail_html_content
        # Should have chevron icon before target icon
        assert "getChevronIcon('mission')" in tail_html_content

    def test_mission_section_is_collapsible(self, tail_html_content: str) -> None:
        """AC3: Verify Mission section has toggle click handler."""
        assert "@click=\"toggleSection('mission')\"" in tail_html_content
        assert ":aria-expanded=\"isExpanded('mission')\"" in tail_html_content

    def test_mission_section_has_keyboard_handlers(self, tail_html_content: str) -> None:
        """AC3: Verify Mission section has keyboard handlers for accessibility."""
        assert "@keydown.enter=\"toggleSection('mission')\"" in tail_html_content
        assert "@keydown.space.prevent=\"toggleSection('mission')\"" in tail_html_content

    def test_mission_content_has_x_show(self, tail_html_content: str) -> None:
        """AC3: Verify Mission content uses x-show with isExpanded."""
        assert 'x-show="isExpanded(\'mission\')"' in tail_html_content


class TestDefaultExpansionState:
    """Tests for default expansion in openPromptBrowser (Story 24.4 AC1)."""

    @pytest.fixture
    def prompt_browser_content(self) -> str:
        """Read prompt-browser.js content."""
        component_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/js/components/prompt-browser.js"
        )
        return component_path.read_text(encoding="utf-8")

    def test_expanded_sections_starts_empty(self, prompt_browser_content: str) -> None:
        """AC1: Verify _expandedSections starts as empty Set."""
        assert "_expandedSections: new Set()" in prompt_browser_content

    def test_variables_view_defaults_to_rendered(self, prompt_browser_content: str) -> None:
        """AC1: Verify variablesView defaults to 'rendered'."""
        assert "variablesView: 'rendered'" in prompt_browser_content

    def test_open_prompt_browser_sets_mission_expanded(
        self, prompt_browser_content: str
    ) -> None:
        """AC1: Verify Mission starts expanded when modal opens."""
        assert "_expandedSections.add('mission')" in prompt_browser_content

    def test_open_prompt_browser_sets_instructions_expanded(
        self, prompt_browser_content: str
    ) -> None:
        """AC1: Verify Instructions starts expanded when modal opens."""
        assert "_expandedSections.add('instructions')" in prompt_browser_content

    def test_story_24_4_comment_present(self, prompt_browser_content: str) -> None:
        """Verify Story 24.4 comment is present for traceability."""
        assert "Story 24.4" in prompt_browser_content


class TestMonospaceFont:
    """Tests for monospace font in prompt sections (Story 24.4 AC2)."""

    @pytest.fixture
    def css_content(self) -> str:
        """Read styles.css content."""
        css_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static/css/styles.css"
        )
        return css_path.read_text(encoding="utf-8")

    def test_prompt_section_content_has_monospace_font(self, css_content: str) -> None:
        """AC2: Verify .prompt-section-content has monospace font-family."""
        # Find the .prompt-section-content rule
        assert ".prompt-section-content" in css_content
        # Should have JetBrains Mono in font stack
        assert "'JetBrains Mono'" in css_content
        # Verify it's in the prompt-section-content block (check proximity)
        section_start = css_content.find(".prompt-section-content {")
        if section_start == -1:
            section_start = css_content.find(".prompt-section-content{")
        assert section_start != -1, ".prompt-section-content rule not found"
        # Check font-family is within reasonable distance of the rule start
        section_content = css_content[section_start:section_start + 500]
        assert "font-family:" in section_content
        assert "monospace" in section_content


class TestScriptLoadingOrder:
    """Tests for script loading order (Story 24.4 AC1 - dependency order)."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Read 11-tail.html content."""
        tail_path = (
            Path(__file__).parent.parent.parent
            / "src/bmad_assist/dashboard/static-src/11-tail.html"
        )
        return tail_path.read_text(encoding="utf-8")

    def test_content_browser_loads_before_prompt_browser(
        self, tail_html_content: str
    ) -> None:
        """AC1: Verify content-browser.js loads BEFORE prompt-browser.js."""
        # Search for script tags specifically, not comments
        content_browser_script = 'src="/js/components/content-browser.js"'
        prompt_browser_script = 'src="/js/components/prompt-browser.js"'

        content_browser_pos = tail_html_content.find(content_browser_script)
        prompt_browser_pos = tail_html_content.find(prompt_browser_script)

        assert content_browser_pos != -1, "content-browser.js script tag not found"
        assert prompt_browser_pos != -1, "prompt-browser.js script tag not found"
        assert (
            content_browser_pos < prompt_browser_pos
        ), "content-browser.js must load before prompt-browser.js"

    def test_utils_loads_first(self, tail_html_content: str) -> None:
        """Verify utils.js loads before component scripts."""
        utils_pos = tail_html_content.find('src="/js/utils.js"')
        content_browser_pos = tail_html_content.find("content-browser.js")

        assert utils_pos != -1, "utils.js not found"
        assert utils_pos < content_browser_pos, "utils.js must load before components"
