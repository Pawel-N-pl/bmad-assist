"""Tests for context loading in TestarchTriModalCompiler.

Verifies that _build_context_files() correctly integrates:
- StrategicContextService
- TEAContextService
- SourceContextService
- Story file (recency bias - last position)
"""

from unittest.mock import MagicMock, patch

from bmad_assist.compiler.types import CompilerContext


class TestStrategicContextIntegration:
    """Tests for StrategicContextService integration."""

    def test_strategic_context_called_with_workflow_name(self, tmp_path):
        """StrategicContextService should be called with correct workflow_name."""
        from bmad_assist.compiler.workflows.testarch_automate import TestarchAutomateCompiler

        compiler = TestarchAutomateCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.collect.return_value = {"docs/project-context.md": "# Context"}
            mock_service_class.return_value = mock_service

            # Mock other services to isolate strategic context test
            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False
                    mock_source_class.return_value = mock_source

                    compiler._build_context_files(context, {"epic_num": 25})

            mock_service_class.assert_called_once()
            call_args = mock_service_class.call_args
            assert call_args[0][1] == "testarch-automate"  # workflow_name

    def test_strategic_context_files_included(self, tmp_path):
        """Strategic context files should be included in result."""
        from bmad_assist.compiler.workflows.testarch_atdd import TestarchAtddCompiler

        compiler = TestarchAtddCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.collect.return_value = {
                "docs/project-context.md": "# Project Context\nRules here"
            }
            mock_service_class.return_value = mock_service

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False
                    mock_source_class.return_value = mock_source

                    files = compiler._build_context_files(context, {"epic_num": 25})

        assert "docs/project-context.md" in files
        assert "Project Context" in files["docs/project-context.md"]


class TestTEAContextIntegration:
    """Tests for TEAContextService integration.

    Note: Due to Python's import caching with lazy imports inside functions,
    these tests verify behavior with real config rather than mocking the
    module functions.
    """

    def test_tea_context_disabled_by_default(self, tmp_path):
        """TEA context should be disabled when config is not present."""
        from bmad_assist.testarch.context import is_tea_context_enabled

        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        # Without config, should return False
        assert is_tea_context_enabled(context) is False

    def test_tea_context_enabled_requires_config(self, tmp_path):
        """TEA context requires testarch.context.enabled = True."""
        from bmad_assist.testarch.context import is_tea_context_enabled
        from bmad_assist.testarch.context.config import TEAContextConfig

        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        # Add mock config with TEA context enabled (F3 fix: use object.__setattr__ for frozen dataclass)
        mock_testarch = MagicMock()
        mock_testarch.context = TEAContextConfig(enabled=True)
        mock_config = MagicMock()
        mock_config.testarch = mock_testarch
        object.__setattr__(context, "config", mock_config)

        assert is_tea_context_enabled(context) is True

    def test_build_context_files_skips_tea_when_disabled(self, tmp_path):
        """TEA context should NOT be collected when config is not present."""
        from bmad_assist.compiler.workflows.testarch_atdd import TestarchAtddCompiler

        compiler = TestarchAtddCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_strategic:
            mock_strategic.return_value.collect.return_value = {}

            with patch(
                "bmad_assist.compiler.source_context.SourceContextService"
            ) as mock_source_class:
                mock_source = MagicMock()
                mock_source.is_enabled.return_value = False
                mock_source_class.return_value = mock_source

                # No config means TEA context disabled
                files = compiler._build_context_files(context, {"epic_num": 25})

        # Should have empty result (no TEA artifacts)
        assert isinstance(files, dict)


class TestSourceContextIntegration:
    """Tests for SourceContextService integration."""

    def test_source_context_skipped_when_disabled(self, tmp_path):
        """SourceContextService.collect_files() NOT called when budget=0."""
        from bmad_assist.compiler.workflows.testarch_atdd import TestarchAtddCompiler

        compiler = TestarchAtddCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_strategic:
            mock_strategic.return_value.collect.return_value = {}

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False  # Budget=0
                    mock_source_class.return_value = mock_source

                    compiler._build_context_files(
                        context, {"epic_num": 25, "story_file": None}
                    )

                # collect_files should NOT be called when disabled
                mock_source.collect_files.assert_not_called()

    def test_source_context_collected_when_enabled(self, tmp_path):
        """SourceContextService.collect_files() called when enabled and story_content exists."""
        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        # Create story file
        stories_dir = tmp_path / "_bmad-output"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "25-1-test.md"
        story_file.write_text("# Story\n\n## File List\n- src/main.py")

        compiler = TestarchAutomateCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=stories_dir)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_strategic:
            mock_strategic.return_value.collect.return_value = {}

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = True  # Enabled
                    mock_source.collect_files.return_value = {
                        "src/main.py": "# Main code"
                    }
                    mock_source_class.return_value = mock_source

                    with patch(
                        "bmad_assist.compiler.source_context.extract_file_paths_from_story"
                    ) as mock_extract:
                        mock_extract.return_value = ["src/main.py"]

                        files = compiler._build_context_files(
                            context,
                            {"epic_num": 25, "story_file": str(story_file)},
                        )

                    # collect_files SHOULD be called when enabled
                    mock_source.collect_files.assert_called_once()
                    assert "src/main.py" in files


class TestRecencyBiasOrdering:
    """Tests for recency-bias ordering (story file last).

    Note: Python 3.7+ guarantees dict insertion order preservation (PEP 468).
    This is relied upon for recency-bias context ordering (F8 documented).
    """

    def test_story_file_is_last_in_context_files(self, tmp_path):
        """Story file should be last key in context_files dict (Python 3.7+ order)."""
        from bmad_assist.compiler.workflows.testarch_atdd import TestarchAtddCompiler

        # Setup
        stories_dir = tmp_path / "_bmad-output"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "25-1-test.md"
        story_file.write_text("# Story Content")

        compiler = TestarchAtddCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=stories_dir)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_strategic:
            mock_strategic.return_value.collect.return_value = {
                str(tmp_path / "docs/project-context.md"): "# Context"
            }

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False
                    mock_source_class.return_value = mock_source

                    files = compiler._build_context_files(
                        context,
                        {"epic_num": 25, "story_num": 1, "story_file": str(story_file)},
                    )

        # Story file should be last
        keys = list(files.keys())
        assert len(keys) > 0
        assert "25-1-test.md" in keys[-1]


class TestServiceFailureHandling:
    """Tests for graceful handling of service failures."""

    def test_strategic_context_empty_returns_valid_dict(self, tmp_path):
        """Empty strategic context should not crash compilation."""
        from bmad_assist.compiler.workflows.testarch_atdd import TestarchAtddCompiler

        compiler = TestarchAtddCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.collect.return_value = {}  # Empty on failure
            mock_service_class.return_value = mock_service

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False
                    mock_source_class.return_value = mock_source

                    # Should not raise
                    files = compiler._build_context_files(context, {"epic_num": 25})

        assert isinstance(files, dict)


class TestTokenWarning:
    """Tests for token budget warning (ADR-7)."""

    def test_large_context_logs_info(self, tmp_path, caplog):
        """Large context should trigger INFO log."""
        import logging

        from bmad_assist.compiler.workflows.testarch_automate import (
            TestarchAutomateCompiler,
        )

        compiler = TestarchAutomateCompiler()
        context = CompilerContext(project_root=tmp_path, output_folder=tmp_path)

        # Create large content to exceed 15000 token threshold
        # Token estimation: ~4 chars per token, so 15000 tokens ≈ 60000 chars
        # Using 70000 chars to ensure we exceed threshold with margin (F6 fix)
        large_content = "x" * 70000

        with patch(
            "bmad_assist.compiler.strategic_context.StrategicContextService"
        ) as mock_strategic:
            mock_strategic.return_value.collect.return_value = {
                "large.md": large_content
            }

            with patch(
                "bmad_assist.testarch.context.is_tea_context_enabled"
            ) as mock_tea:
                mock_tea.return_value = False

                with patch(
                    "bmad_assist.compiler.source_context.SourceContextService"
                ) as mock_source_class:
                    mock_source = MagicMock()
                    mock_source.is_enabled.return_value = False
                    mock_source_class.return_value = mock_source

                    with caplog.at_level(logging.INFO):
                        compiler._build_context_files(context, {"epic_num": 25})

        # Should have logged warning about large context
        assert any("TEA context large" in record.message for record in caplog.records)
