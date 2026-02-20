"""Tests for Epic Metrics Browser (Story 24.7).

Tests verify:
1. Modal HTML structure (metrics-modal, metrics-timeline, metrics-accordion, metrics-tooltip)
2. Component file exports window.epicMetricsComponent
3. Alpine.js integration via alpine-init.js
4. Context menu disabled state for non-done epics
5. CSS styles for metrics-specific classes
"""

from pathlib import Path

import pytest


class TestEpicMetricsComponentFile:
    """Tests for epic-metrics.js component file."""

    @pytest.fixture
    def component_content(self) -> str:
        """Load the epic-metrics.js component file content."""
        component_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "js" / "components" / "epic-metrics.js"
        return component_path.read_text()

    def test_component_file_exists(self):
        """Verify the epic-metrics.js component file exists."""
        component_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "js" / "components" / "epic-metrics.js"
        assert component_path.exists(), f"Component file not found at {component_path}"

    def test_exports_window_global(self, component_content: str):
        """Verify component exports window.epicMetricsComponent."""
        assert "window.epicMetricsComponent" in component_content
        # Check it's a function assignment
        assert "window.epicMetricsComponent = function()" in component_content

    def test_has_metrics_modal_state(self, component_content: str):
        """Verify component defines metricsModal state object."""
        assert "metricsModal:" in component_content
        assert "show:" in component_content
        assert "epicId:" in component_content
        assert "data:" in component_content
        assert "loading:" in component_content

    def test_has_open_epic_metrics_method(self, component_content: str):
        """Verify component has openEpicMetrics method."""
        assert "openEpicMetrics(" in component_content

    def test_has_close_epic_metrics_method(self, component_content: str):
        """Verify component has closeEpicMetrics method."""
        assert "closeEpicMetrics()" in component_content

    def test_has_format_duration_method(self, component_content: str):
        """Verify component has formatDuration method."""
        assert "formatDuration(" in component_content

    def test_has_segment_width_method(self, component_content: str):
        """Verify component has getSegmentWidth method with zero-guard."""
        assert "getSegmentWidth(" in component_content
        # Verify zero-guard logic
        assert "totalDurationMs === 0" in component_content or "!totalDurationMs" in component_content

    def test_has_segment_color_method(self, component_content: str):
        """Verify component has getSegmentColor method."""
        assert "getSegmentColor(" in component_content

    def test_has_toggle_metrics_story_method(self, component_content: str):
        """Verify component has toggleMetricsStory method."""
        assert "toggleMetricsStory(" in component_content

    def test_has_is_metrics_story_expanded_method(self, component_content: str):
        """Verify component has isMetricsStoryExpanded method."""
        assert "isMetricsStoryExpanded(" in component_content

    def test_has_tooltip_methods(self, component_content: str):
        """Verify component has tooltip methods."""
        assert "showSegmentTooltip(" in component_content
        assert "hideSegmentTooltip()" in component_content

    def test_has_color_palette(self, component_content: str):
        """Verify component defines segment color palette."""
        assert "SEGMENT_COLORS" in component_content
        # Should have at least 8 colors
        assert "bg-blue-500" in component_content
        assert "bg-green-500" in component_content


class TestAlpineInitIntegration:
    """Tests for alpine-init.js integration of epic-metrics component."""

    @pytest.fixture
    def alpine_init_content(self) -> str:
        """Load the alpine-init.js file content."""
        alpine_init_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "js" / "alpine-init.js"
        return alpine_init_path.read_text()

    def test_imports_epic_metrics_component(self, alpine_init_content: str):
        """Verify alpine-init.js imports epicMetricsComponent with null-safety."""
        assert "epicMetricsComponent" in alpine_init_content
        # Check null-safety pattern
        assert "window.epicMetricsComponent ? window.epicMetricsComponent() : {}" in alpine_init_content

    def test_spreads_epic_metrics_in_dashboard(self, alpine_init_content: str):
        """Verify alpine-init.js spreads epicMetrics in dashboard return."""
        assert "...epicMetrics," in alpine_init_content

    def test_documents_epic_metrics_in_header(self, alpine_init_content: str):
        """Verify alpine-init.js header documents epic-metrics.js component."""
        assert "epic-metrics.js" in alpine_init_content
        assert "Story 24.7" in alpine_init_content


class TestMetricsModalHTML:
    """Tests for Epic Metrics Modal HTML structure in 11-tail.html."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Load the 11-tail.html file content."""
        tail_html_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "11-tail.html"
        return tail_html_path.read_text()

    def test_modal_exists(self, tail_html_content: str):
        """Verify metrics modal container exists with data-testid."""
        assert 'data-testid="metrics-modal"' in tail_html_content

    def test_modal_has_timeline_section(self, tail_html_content: str):
        """Verify metrics modal has timeline section with data-testid."""
        assert 'data-testid="metrics-timeline"' in tail_html_content

    def test_modal_has_accordion_section(self, tail_html_content: str):
        """Verify metrics modal has accordion section with data-testid."""
        assert 'data-testid="metrics-accordion"' in tail_html_content

    def test_modal_has_tooltip(self, tail_html_content: str):
        """Verify metrics modal has tooltip element with data-testid."""
        assert 'data-testid="metrics-tooltip"' in tail_html_content

    def test_modal_has_close_button(self, tail_html_content: str):
        """Verify metrics modal has close button with data-testid."""
        assert 'data-testid="close-metrics-btn"' in tail_html_content

    def test_modal_binds_to_metrics_modal_state(self, tail_html_content: str):
        """Verify modal visibility is bound to metricsModal.show."""
        assert 'x-show="metricsModal.show"' in tail_html_content

    def test_modal_has_loading_state(self, tail_html_content: str):
        """Verify modal has loading state indicator."""
        assert 'metricsModal.loading' in tail_html_content
        assert 'Loading metrics' in tail_html_content

    def test_modal_has_total_duration(self, tail_html_content: str):
        """Verify modal displays total duration."""
        assert 'formatDuration(metricsModal.data?.total_duration_ms' in tail_html_content

    def test_modal_has_keyboard_support(self, tail_html_content: str):
        """Verify accordion buttons have keyboard handlers."""
        assert '@keydown.enter="toggleMetricsStory' in tail_html_content
        assert '@keydown.space.prevent="toggleMetricsStory' in tail_html_content

    def test_modal_close_on_escape(self, tail_html_content: str):
        """Verify modal closes on Escape key."""
        assert "closeEpicMetrics()" in tail_html_content
        assert "@keydown.escape.window" in tail_html_content


class TestMetricsCSS:
    """Tests for Epic Metrics Browser CSS styles."""

    @pytest.fixture
    def css_content(self) -> str:
        """Load the styles.css file content."""
        css_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static" / "css" / "styles.css"
        return css_path.read_text()

    def test_has_metrics_timeline_style(self, css_content: str):
        """Verify CSS has .metrics-timeline style."""
        assert ".metrics-timeline" in css_content

    def test_has_metrics_segment_style(self, css_content: str):
        """Verify CSS has .metrics-segment style."""
        assert ".metrics-segment" in css_content
        # Check hover effect
        assert ".metrics-segment:hover" in css_content

    def test_has_metrics_tooltip_style(self, css_content: str):
        """Verify CSS has .metrics-tooltip style."""
        assert ".metrics-tooltip" in css_content

    def test_has_metrics_accordion_style(self, css_content: str):
        """Verify CSS has .metrics-accordion style."""
        assert ".metrics-accordion" in css_content

    def test_has_tabular_nums_style(self, css_content: str):
        """Verify CSS has tabular-nums utility class."""
        assert ".tabular-nums" in css_content
        assert "font-variant-numeric: tabular-nums" in css_content


class TestContextMenuViewMetrics:
    """Tests for context menu View Metrics action."""

    @pytest.fixture
    def context_menu_content(self) -> str:
        """Load the context-menu.js file content."""
        context_menu_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "js" / "components" / "context-menu.js"
        return context_menu_path.read_text()

    def test_view_metrics_action_in_epic_context(self, context_menu_content: str):
        """Verify View metrics action exists in epic context menu."""
        assert "view-metrics" in context_menu_content
        assert "View metrics" in context_menu_content

    def test_view_metrics_disabled_for_non_done_epics(self, context_menu_content: str):
        """Verify View metrics is disabled when epic status is not 'done'."""
        # The context menu checks hasMetrics = item?.status === 'done'
        assert "item?.status === 'done'" in context_menu_content
        # And sets disabled flag based on this
        assert "disabled: !hasMetrics" in context_menu_content


class TestTreeViewMetricsIntegration:
    """Tests for tree-view.js viewEpicMetrics integration."""

    @pytest.fixture
    def tree_view_content(self) -> str:
        """Load the tree-view.js file content."""
        tree_view_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "js" / "components" / "tree-view.js"
        return tree_view_path.read_text()

    def test_view_epic_metrics_method_exists(self, tree_view_content: str):
        """Verify viewEpicMetrics method exists."""
        assert "viewEpicMetrics(" in tree_view_content

    def test_view_epic_metrics_calls_open_epic_metrics(self, tree_view_content: str):
        """Verify viewEpicMetrics calls openEpicMetrics on success."""
        assert "openEpicMetrics(" in tree_view_content

    def test_view_epic_metrics_shows_toast_on_404(self, tree_view_content: str):
        """Verify viewEpicMetrics shows toast when metrics not available."""
        assert 'Metrics not available for this epic' in tree_view_content

    def test_format_epic_metrics_removed(self, tree_view_content: str):
        """Verify formatEpicMetrics method was removed."""
        # The old text-based formatter should no longer exist
        assert "formatEpicMetrics(" not in tree_view_content


class TestScriptLoadOrder:
    """Tests for script load order in 11-tail.html."""

    @pytest.fixture
    def tail_html_content(self) -> str:
        """Load the 11-tail.html file content."""
        tail_html_path = Path(__file__).parent.parent.parent / "src" / "bmad_assist" / "dashboard" / "static-src" / "11-tail.html"
        return tail_html_path.read_text()

    def test_epic_metrics_script_tag_exists(self, tail_html_content: str):
        """Verify epic-metrics.js script tag exists."""
        assert 'src="/js/components/epic-metrics.js"' in tail_html_content

    def test_epic_metrics_loads_after_content_browser(self, tail_html_content: str):
        """Verify epic-metrics.js loads after content-browser.js."""
        # Search for script tags specifically (not comments mentioning these files)
        content_browser_pos = tail_html_content.find('src="/js/components/content-browser.js"')
        epic_metrics_pos = tail_html_content.find('src="/js/components/epic-metrics.js"')
        alpine_init_pos = tail_html_content.find('src="/js/alpine-init.js"')

        assert content_browser_pos < epic_metrics_pos < alpine_init_pos, \
            "Script load order should be: content-browser.js -> epic-metrics.js -> alpine-init.js"


@pytest.mark.skip(reason="Frontend spec - requires E2E/Playwright testing")
class TestEpicMetricsBrowserFrontendSpec:
    """Frontend specification tests for Epic Metrics Browser.

    These tests document expected frontend behavior. They are SKIPPED because:
    - Python unit tests cannot verify JavaScript behavior
    - Actual verification requires E2E testing with Playwright/Selenium

    See epic-metrics.js and 11-tail.html for implementation.
    """

    def test_modal_opens_with_metrics_panel(self):
        """Specification: Modal opens showing metrics panel with total, timeline, and accordion."""
        pass

    def test_timeline_segments_proportional_to_duration(self):
        """Specification: Segment widths are proportional to story execution time."""
        pass

    def test_timeline_hover_shows_tooltip(self):
        """Specification: Hovering over segment shows tooltip with story info."""
        pass

    def test_accordion_expands_with_workflow_details(self):
        """Specification: Expanding accordion item shows per-workflow breakdown."""
        pass

    def test_tabular_nums_for_alignment(self):
        """Specification: All numeric values use tabular-nums for alignment."""
        pass

    def test_disabled_action_for_non_done_epics(self):
        """Specification: View Metrics is grayed out for epics not in 'done' status."""
        pass
