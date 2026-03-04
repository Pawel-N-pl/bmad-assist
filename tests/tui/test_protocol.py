"""Tests for Renderer protocol conformance."""

from __future__ import annotations

from bmad_assist.tui import InteractiveRenderer, PlainRenderer, Renderer


class TestProtocolConformance:
    """Verify both renderers satisfy the Renderer protocol."""

    def test_plain_renderer_is_renderer(self) -> None:
        """PlainRenderer satisfies the Renderer protocol (structural subtyping)."""
        renderer = PlainRenderer()
        assert isinstance(renderer, Renderer)

    def test_interactive_renderer_is_renderer(self) -> None:
        """InteractiveRenderer satisfies the Renderer protocol."""
        renderer = InteractiveRenderer()
        assert isinstance(renderer, Renderer)

    def test_renderer_protocol_is_runtime_checkable(self) -> None:
        """Renderer protocol is decorated with @runtime_checkable."""
        # This would fail if @runtime_checkable was missing
        assert isinstance(PlainRenderer(), Renderer)

    def test_non_renderer_fails_isinstance(self) -> None:
        """Objects missing protocol methods don't pass isinstance check."""

        class NotARenderer:
            pass

        assert not isinstance(NotARenderer(), Renderer)

    def test_partial_renderer_fails_isinstance(self) -> None:
        """Objects with only some methods don't pass isinstance check."""

        class PartialRenderer:
            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

        # runtime_checkable only checks method existence, not signature completeness
        # but PartialRenderer is missing render_log, render_phase_started, etc.
        assert not isinstance(PartialRenderer(), Renderer)
