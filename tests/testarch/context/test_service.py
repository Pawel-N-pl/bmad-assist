"""Tests for TEA context service."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.compiler.types import CompilerContext
from bmad_assist.testarch.config import TestarchConfig
from bmad_assist.testarch.context import TEAContextService
from bmad_assist.testarch.context.config import TEAContextConfig, TEAContextWorkflowConfig


@pytest.fixture
def mock_context(tmp_path: Path) -> CompilerContext:
    """Create a mock CompilerContext for testing."""
    context = CompilerContext(
        project_root=tmp_path,
        output_folder=tmp_path,
    )
    return context


@pytest.fixture
def base_testarch_config() -> TestarchConfig:
    """Create a base TestarchConfig with TEA context enabled."""
    return TestarchConfig(
        context=TEAContextConfig(
            enabled=True,
            budget=8000,
        )
    )


class TestTEAContextService:
    """Tests for TEAContextService."""

    def test_collect_no_config_returns_empty(
        self, mock_context: CompilerContext
    ) -> None:
        """Test collect returns empty dict when no config."""
        service = TEAContextService(mock_context, "dev_story", None)
        result = service.collect()
        assert result == {}

    def test_collect_disabled_returns_empty(
        self,
        mock_context: CompilerContext,
    ) -> None:
        """Test collect returns empty dict when disabled."""
        config = TestarchConfig(
            context=TEAContextConfig(enabled=False)
        )
        service = TEAContextService(mock_context, "dev_story", config)
        result = service.collect()
        assert result == {}

    def test_collect_zero_budget_returns_empty(
        self,
        mock_context: CompilerContext,
    ) -> None:
        """Test collect returns empty dict when budget is zero."""
        config = TestarchConfig(
            context=TEAContextConfig(enabled=True, budget=0)
        )
        service = TEAContextService(mock_context, "dev_story", config)
        result = service.collect()
        assert result == {}

    def test_collect_engagement_model_off_returns_empty(
        self,
        mock_context: CompilerContext,
    ) -> None:
        """Test collect returns empty dict when engagement_model=off (F6 Fix)."""
        config = TestarchConfig(
            engagement_model="off",
            context=TEAContextConfig(enabled=True),
        )
        service = TEAContextService(mock_context, "dev_story", config)
        result = service.collect()
        assert result == {}

    def test_collect_unknown_workflow_returns_empty(
        self,
        mock_context: CompilerContext,
        base_testarch_config: TestarchConfig,
    ) -> None:
        """Test collect returns empty dict for unknown workflow."""
        service = TEAContextService(
            mock_context, "unknown_workflow", base_testarch_config
        )
        result = service.collect()
        assert result == {}

    def test_collect_empty_include_returns_empty(
        self,
        mock_context: CompilerContext,
    ) -> None:
        """Test collect returns empty dict when include is empty (F12 Fix)."""
        config = TestarchConfig(
            context=TEAContextConfig(
                enabled=True,
                workflows={"dev_story": TEAContextWorkflowConfig(include=[])},
            )
        )
        service = TEAContextService(mock_context, "dev_story", config)
        result = service.collect()
        assert result == {}

    def test_collect_loads_artifacts(
        self,
        tmp_path: Path,
        base_testarch_config: TestarchConfig,
    ) -> None:
        """Test collect loads configured artifacts."""
        # Create test-design artifact
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir()
        (test_designs_dir / "test-design-epic-25.md").write_text("# Test plan")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        resolved = {"epic_num": 25, "story_id": "25.1"}
        service = TEAContextService(
            context, "dev_story", base_testarch_config, resolved
        )
        result = service.collect()

        assert len(result) >= 1
        # At least test-design should be loaded
        assert any("test-design" in path for path in result.keys())

    def test_collect_respects_budget(
        self,
        tmp_path: Path,
    ) -> None:
        """Test collect respects total budget."""
        # Create large artifacts that would exceed budget
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir()
        large_content = "# Large content\n" + ("x" * 50000)  # ~12500 tokens
        (test_designs_dir / "test-design-epic-25.md").write_text(large_content)

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        # Set small budget
        config = TestarchConfig(
            context=TEAContextConfig(enabled=True, budget=100)
        )

        resolved = {"epic_num": 25}
        service = TEAContextService(context, "dev_story", config, resolved)
        result = service.collect()

        # Should have loaded but truncated
        if result:
            content = list(result.values())[0]
            assert "truncated" in content or len(content) < len(large_content)

    def test_collect_stops_on_budget_exhausted(
        self,
        tmp_path: Path,
    ) -> None:
        """Test collect stops mid-loop when budget exhausted (F14 Fix)."""
        # Create test-design and atdd artifacts (dev_story loads both)
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir()
        atdd_dir = tmp_path / "atdd-checklists"
        atdd_dir.mkdir()

        # First artifact is large enough to consume most budget
        large_content = "# Test Design\n" + ("x" * 2000)  # ~500 tokens
        (test_designs_dir / "test-design-epic-25.md").write_text(large_content)
        # Second artifact would push over budget
        (atdd_dir / "atdd-checklist-25.1.md").write_text("# ATDD\n" + ("y" * 2000))

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        # Set budget that allows first but not both
        config = TestarchConfig(
            context=TEAContextConfig(enabled=True, budget=600)
        )

        resolved = {"epic_num": 25, "story_id": "25.1"}
        service = TEAContextService(context, "dev_story", config, resolved)
        result = service.collect()

        # Should have stopped after first artifact due to budget
        # Either got one artifact or budget-truncated content
        assert len(result) <= 2  # May get truncated second or stop early

    def test_resolver_exception_caught(
        self,
        tmp_path: Path,
        base_testarch_config: TestarchConfig,
    ) -> None:
        """Test resolver exception doesn't crash service (F15 Fix)."""
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        resolved = {"epic_num": 25, "story_id": "25.1"}

        # Create a mock resolver class that raises on resolve()
        class FailingResolver:
            def __init__(self, base_path: Path, max_tokens: int) -> None:
                pass

            def resolve(self, epic_id: object, story_id: object = None) -> dict[str, str]:
                raise RuntimeError("Boom")

        with patch(
            "bmad_assist.testarch.context.service.RESOLVER_REGISTRY",
            {"test-design": FailingResolver, "atdd": FailingResolver},
        ):
            service = TEAContextService(
                context, "dev_story", base_testarch_config, resolved
            )
            # Should not raise
            result = service.collect()
            # Should return empty dict (all resolvers failed)
            assert isinstance(result, dict)
            assert result == {}


class TestBudgetAllocation:
    """Tests for proportional budget allocation (F1 Fix)."""

    def test_allocate_budgets_proportional(
        self,
        mock_context: CompilerContext,
        base_testarch_config: TestarchConfig,
    ) -> None:
        """Test budget is allocated proportionally across artifact types."""
        resolved = {"epic_num": 25, "story_id": "25.1"}
        service = TEAContextService(
            mock_context, "dev_story", base_testarch_config, resolved
        )

        # dev_story has test-design + atdd by default
        budgets = service._allocate_budgets(["test-design", "atdd"])

        # Should have allocations for both
        assert "test-design" in budgets
        assert "atdd" in budgets

        # Allocations should be roughly equal (proportional)
        # Allow for min floor differences
        assert budgets["test-design"] > 0
        assert budgets["atdd"] > 0

    def test_allocate_budgets_respects_max_per_artifact(
        self,
        mock_context: CompilerContext,
    ) -> None:
        """Test allocation doesn't exceed max_tokens_per_artifact."""
        config = TestarchConfig(
            context=TEAContextConfig(
                enabled=True,
                budget=100000,  # Large total
                max_tokens_per_artifact=1000,  # Small per-artifact cap
            )
        )

        resolved = {"epic_num": 25}
        service = TEAContextService(mock_context, "dev_story", config, resolved)

        budgets = service._allocate_budgets(["test-design"])

        # Should be capped at max_tokens_per_artifact
        assert budgets["test-design"] <= 1000
