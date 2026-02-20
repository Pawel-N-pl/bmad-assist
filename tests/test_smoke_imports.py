"""Smoke tests for module imports.

This module verifies that all public modules can be imported without errors.
Catches broken imports, circular dependencies, and missing dependencies early.

Added as action item from Epic 11 retrospective after Story 11.6 revealed
preexisting broken imports that caused 52 test failures.
"""

import importlib

import pytest

# All public packages that should be importable
PACKAGES = [
    "bmad_assist",
    "bmad_assist.core",
    "bmad_assist.core.loop",
    "bmad_assist.core.loop.handlers",
    "bmad_assist.providers",
    "bmad_assist.bmad",
    "bmad_assist.bmad.sharding",
    "bmad_assist.compiler",
    "bmad_assist.compiler.patching",
    "bmad_assist.compiler.workflows",
    "bmad_assist.validation",
    "bmad_assist.benchmarking",
    "bmad_assist.code_review",
    "bmad_assist.reporting",
]

# Key modules that should be importable (not just packages)
MODULES = [
    # Core
    "bmad_assist.cli",
    "bmad_assist.core.config",
    "bmad_assist.core.state",
    "bmad_assist.core.exceptions",
    "bmad_assist.core.loop.runner",
    "bmad_assist.core.loop.handlers.base",
    "bmad_assist.core.loop.handlers.create_story",
    "bmad_assist.core.loop.handlers.validate_story",
    "bmad_assist.core.loop.handlers.validate_story_synthesis",
    "bmad_assist.core.loop.handlers.dev_story",
    "bmad_assist.core.loop.handlers.code_review",
    "bmad_assist.core.loop.handlers.code_review_synthesis",
    # Providers
    "bmad_assist.providers.base",
    "bmad_assist.providers.registry",
    "bmad_assist.providers.claude",
    "bmad_assist.providers.claude_sdk",
    "bmad_assist.providers.codex",
    "bmad_assist.providers.gemini",
    # BMAD
    "bmad_assist.bmad.parser",
    "bmad_assist.bmad.correction",
    "bmad_assist.bmad.discrepancy",
    "bmad_assist.bmad.state_reader",
    # Compiler
    "bmad_assist.compiler.core",
    "bmad_assist.compiler.variables",
    "bmad_assist.compiler.output",
    "bmad_assist.compiler.workflows.create_story",
    "bmad_assist.compiler.workflows.validate_story",
    "bmad_assist.compiler.workflows.validate_story_synthesis",
    "bmad_assist.compiler.workflows.dev_story",
    "bmad_assist.compiler.workflows.code_review",
    "bmad_assist.compiler.workflows.code_review_synthesis",
    # Validation
    "bmad_assist.validation.anonymizer",
    "bmad_assist.validation.orchestrator",
    "bmad_assist.validation.reports",
    # Benchmarking
    "bmad_assist.benchmarking.schema",
    "bmad_assist.benchmarking.collector",
    "bmad_assist.benchmarking.extraction",
    "bmad_assist.benchmarking.storage",
    "bmad_assist.benchmarking.ground_truth",
    "bmad_assist.benchmarking.reports",
    # Code Review
    "bmad_assist.code_review.orchestrator",
]


class TestSmokeImports:
    """Smoke tests to verify all modules can be imported."""

    # NOTE: We do NOT delete modules from sys.modules before importing.
    # Deleting and reimporting causes Pydantic model class identity issues:
    # when models are redefined, other modules still hold references to old
    # class definitions, causing validation errors like "Input should be a
    # valid dictionary or instance of X" even when passing an X instance.

    @pytest.mark.parametrize("package", PACKAGES)
    def test_package_imports(self, package: str) -> None:
        """Verify each package can be imported without errors."""
        try:
            module = importlib.import_module(package)
            assert module is not None
        except ImportError as e:
            pytest.fail(f"Failed to import package {package}: {e}")

    @pytest.mark.parametrize("module", MODULES)
    def test_module_imports(self, module: str) -> None:
        """Verify each module can be imported without errors."""
        try:
            mod = importlib.import_module(module)
            assert mod is not None
        except ImportError as e:
            pytest.fail(f"Failed to import module {module}: {e}")

    def test_cli_entry_point(self) -> None:
        """Verify CLI entry point is accessible."""
        from bmad_assist.cli import app

        assert app is not None

    def test_public_api_exports(self) -> None:
        """Verify main package exports expected symbols."""
        import bmad_assist

        # Should have __version__
        assert hasattr(bmad_assist, "__version__")

    def test_no_circular_imports(self) -> None:
        """Verify no circular import issues by importing all at once."""
        # Import all in sequence - circular imports would fail here
        from bmad_assist import core  # noqa: F401
        from bmad_assist.benchmarking import schema  # noqa: F401
        from bmad_assist.code_review import orchestrator as cr_orch  # noqa: F401
        from bmad_assist.compiler import core as compiler_core  # noqa: F401
        from bmad_assist.core import config, state  # noqa: F401
        from bmad_assist.providers import registry  # noqa: F401
        from bmad_assist.validation import orchestrator  # noqa: F401

        # If we get here, no circular imports
        assert True
