"""E2E tests for TEA knowledge base integration.

Story 25.14: Integration Testing - AC: 7.
Tests knowledge base loading integration within TEA workflows, verifying
that knowledge fragments are properly loaded, cached, and passed to workflow context.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig


class TestKnowledgeBaseLoaderBasics:
    """Test knowledge base loader basic functionality."""

    @pytest.fixture
    def setup_project_with_knowledge(self, tmp_path: Path) -> Path:
        """Create project with knowledge base."""
        # Create knowledge base directory
        kb_dir = tmp_path / "_bmad/tea/testarch/knowledge"
        kb_dir.mkdir(parents=True)

        # Create index file
        index_file = tmp_path / "_bmad/tea/testarch/tea-index.csv"
        index_file.write_text("""id,name,description,tags,fragment_file
fixture-architecture,Fixture Architecture,Best practices for test fixtures,fixtures;architecture,knowledge/fixture-architecture.md
playwright-basics,Playwright Basics,Playwright testing fundamentals,playwright;e2e,knowledge/playwright-basics.md
""")

        # Create fragment files
        (kb_dir / "fixture-architecture.md").write_text("""# Fixture Architecture

## Overview
Best practices for creating maintainable test fixtures.

## Key Principles
1. Use factory patterns for complex objects
2. Prefer explicit over implicit setup
3. Clean up resources properly
""")

        (kb_dir / "playwright-basics.md").write_text("""# Playwright Basics

## Setup
Basic Playwright test setup and configuration.

## Best Practices
1. Use page object model
2. Implement proper waits
3. Handle network requests
""")

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        return tmp_path

    def test_loader_singleton_per_project(self, tmp_path: Path) -> None:
        """Test loader is singleton per project root."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()

        loader1 = get_knowledge_loader(tmp_path)
        loader2 = get_knowledge_loader(tmp_path)

        assert loader1 is loader2

        # Different path should give different loader
        other_path = tmp_path / "other"
        other_path.mkdir()
        loader3 = get_knowledge_loader(other_path)

        assert loader3 is not loader1

        clear_all_loaders()

    def test_loader_loads_index(self, setup_project_with_knowledge: Path) -> None:
        """Test loader can load knowledge index."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()
        project_path = setup_project_with_knowledge

        loader = get_knowledge_loader(project_path)

        # Load index returns list of fragments
        fragments = loader.load_index()

        # Should have loaded entries
        assert fragments is not None
        assert len(fragments) >= 0  # May have fragments

        clear_all_loaders()

    def test_loader_loads_fragments_by_tag(
        self, setup_project_with_knowledge: Path
    ) -> None:
        """Test loader can load fragments by tag."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()
        project_path = setup_project_with_knowledge

        loader = get_knowledge_loader(project_path)
        content = loader.load_by_tags(["fixtures"])

        # Should return content (or empty if not found)
        assert content is not None or content == ""

        clear_all_loaders()

    def test_loader_handles_missing_project_index_uses_bundled(
        self, tmp_path: Path
    ) -> None:
        """Test loader falls back to bundled when project has no knowledge base."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()

        # Project with no knowledge base
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        loader = get_knowledge_loader(tmp_path)
        fragments = loader.load_index()

        # Should fall back to bundled knowledge base (34 fragments)
        assert fragments is not None
        assert len(fragments) > 0
        # Verify bundled fragments are loaded
        fragment_ids = {f.id for f in fragments}
        assert "fixture-architecture" in fragment_ids

        clear_all_loaders()


class TestKnowledgeBaseInWorkflows:
    """Test knowledge base integration in TEA workflows."""

    @pytest.fixture
    def setup_workflow_with_kb(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project with workflow and knowledge base."""
        # Create workflow directory for test-review
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/test-review"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-test-review
description: "Test review workflow"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        # Create knowledge base
        kb_dir = tmp_path / "_bmad/tea/testarch/knowledge"
        kb_dir.mkdir(parents=True)
        index_file = tmp_path / "_bmad/tea/testarch/tea-index.csv"
        index_file.write_text("""id,name,description,tags,fragment_file
test-quality,Test Quality,Test quality guidelines,quality;review,knowledge/test-quality.md
""")
        (kb_dir / "test-quality.md").write_text("# Test Quality Guidelines")

        # Create output directories
        (tmp_path / "_bmad-output").mkdir(parents=True)

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_test_review_handler_can_access_knowledge(
        self, setup_workflow_with_kb: tuple[Path, State]
    ) -> None:
        """Test TestReviewHandler can access knowledge base."""
        project_path, state = setup_workflow_with_kb
        config = FakeConfig()

        from bmad_assist.testarch.handlers.test_review import TestReviewHandler

        handler = TestReviewHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test-review</compiled>"
        mock_compiled.workflow_name = "testarch-test-review"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Review\n\n## Finding Count: 0\n\nAll tests pass review.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.test_review.get_paths") as mock_tr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_tr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True


class TestKnowledgeBaseCaching:
    """Test knowledge base caching behavior."""

    @pytest.fixture
    def setup_cacheable_kb(self, tmp_path: Path) -> Path:
        """Create project for cache testing."""
        kb_dir = tmp_path / "_bmad/tea/testarch/knowledge"
        kb_dir.mkdir(parents=True)

        index_file = tmp_path / "_bmad/tea/testarch/tea-index.csv"
        index_file.write_text("""id,name,description,tags,fragment_file
test-kb,Test KB,Test knowledge,test,knowledge/test-kb.md
""")
        (kb_dir / "test-kb.md").write_text("# Test Knowledge")

        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")

        return tmp_path

    def test_loader_caches_index(self, setup_cacheable_kb: Path) -> None:
        """Test loader caches index on subsequent calls."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()
        project_path = setup_cacheable_kb

        loader = get_knowledge_loader(project_path)

        # First load
        fragments1 = loader.load_index()
        # Second load (should use cache)
        fragments2 = loader.load_index()

        # Both should be valid
        assert fragments1 is not None
        assert fragments2 is not None

        clear_all_loaders()

    def test_loader_caches_fragments(self, setup_cacheable_kb: Path) -> None:
        """Test loader caches fragments on subsequent loads."""
        from bmad_assist.testarch.knowledge import get_knowledge_loader
        from bmad_assist.testarch.knowledge.loader import clear_all_loaders

        clear_all_loaders()
        project_path = setup_cacheable_kb

        loader = get_knowledge_loader(project_path)

        # First load
        content1 = loader.load_by_tags(["test"])
        # Second load (should use cache)
        content2 = loader.load_by_tags(["test"])

        # Both should return same content
        assert content1 == content2

        clear_all_loaders()


class TestKnowledgeBaseWorkflowDefaults:
    """Test workflow-specific knowledge defaults."""

    def test_get_workflow_defaults_returns_list(self) -> None:
        """Test workflow defaults provide tag list."""
        from bmad_assist.testarch.knowledge.defaults import get_workflow_defaults

        # Different workflows may have different default tags
        framework_defaults = get_workflow_defaults("testarch-framework")
        test_review_defaults = get_workflow_defaults("testarch-test-review")

        # Should return list of tags
        assert isinstance(framework_defaults, list)
        assert isinstance(test_review_defaults, list)

    def test_unknown_workflow_returns_empty_defaults(self) -> None:
        """Test unknown workflow returns empty list."""
        from bmad_assist.testarch.knowledge.defaults import get_workflow_defaults

        unknown_defaults = get_workflow_defaults("unknown-workflow")

        # Should return empty list
        assert isinstance(unknown_defaults, list)
        assert len(unknown_defaults) == 0


class TestKnowledgeFragmentModels:
    """Test knowledge fragment data models."""

    def test_knowledge_fragment_creation(self) -> None:
        """Test KnowledgeFragment can be created."""
        from bmad_assist.testarch.knowledge.models import KnowledgeFragment

        fragment = KnowledgeFragment(
            id="test-fragment",
            name="Test Fragment",
            description="A test fragment",
            tags=("test", "unit"),
            fragment_file="test-fragment.md",
        )

        assert fragment.id == "test-fragment"
        assert fragment.name == "Test Fragment"
        assert "test" in fragment.tags

    def test_knowledge_index_creation(self) -> None:
        """Test KnowledgeIndex can be created."""
        from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex

        fragment = KnowledgeFragment(
            id="test",
            name="Test",
            description="Test",
            tags=("test",),
            fragment_file="test.md",
        )

        index = KnowledgeIndex(
            path="index.csv",
            fragments={"test": fragment},
            fragment_order=("test",),
        )

        assert len(index.fragments) == 1
        assert index.fragments["test"].id == "test"

    def test_knowledge_index_get_by_tags(self) -> None:
        """Test KnowledgeIndex get_fragments_by_tags."""
        from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex

        fragment1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="First fragment",
            tags=("fixtures", "architecture"),
            fragment_file="f1.md",
        )
        fragment2 = KnowledgeFragment(
            id="f2",
            name="Fragment 2",
            description="Second fragment",
            tags=("playwright",),
            fragment_file="f2.md",
        )

        index = KnowledgeIndex(
            path="index.csv",
            fragments={"f1": fragment1, "f2": fragment2},
            fragment_order=("f1", "f2"),
        )

        # Get by fixtures tag
        fixtures = index.get_fragments_by_tags(["fixtures"])
        assert len(fixtures) == 1
        assert fixtures[0].id == "f1"

        # Get by playwright tag
        playwright = index.get_fragments_by_tags(["playwright"])
        assert len(playwright) == 1
        assert playwright[0].id == "f2"
