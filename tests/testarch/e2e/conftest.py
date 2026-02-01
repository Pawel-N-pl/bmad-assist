"""Shared fixtures for TEA E2E tests.

Story 25.14: Integration Testing.
Provides fixtures for:
- Full project structure with all TEA workflows
- Config fixtures for integrated/solo/lite modes
- Mock provider and evidence collector fixtures
- Path reset fixture to prevent singleton pollution
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock

import pytest


# =============================================================================
# Path Reset Fixture (CRITICAL - prevents singleton pollution)
# =============================================================================


@pytest.fixture(autouse=True)
def reset_paths_after_test() -> Generator[None, None, None]:
    """Reset Paths singleton after each test to prevent cross-test pollution.

    This is an autouse fixture that runs for every test in the E2E suite.
    """
    yield
    from bmad_assist.core.paths import _reset_paths

    _reset_paths()


# =============================================================================
# Project Structure Fixtures
# =============================================================================


@pytest.fixture
def tea_project_with_workflows(tmp_path: Path) -> Path:
    """Create full project structure with all TEA workflows.

    Creates:
    - Workflow directories for all 8 workflows
    - Output directories
    - Docs with project-context.md and architecture.md
    - Knowledge base directory with index

    Returns:
        Path to temporary project root.
    """
    # Create workflow directories for all 8 workflows
    workflows = [
        "atdd",
        "framework",
        "ci",
        "test-design",
        "automate",
        "test-review",
        "trace",
        "nfr-assess",
    ]

    for wf in workflows:
        workflow_dir = tmp_path / f"_bmad/bmm/workflows/testarch/{wf}"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text(
            f"""name: testarch-{wf}
description: "Test workflow for {wf}"
instructions: "{{installed_path}}/instructions.xml"
"""
        )
        (workflow_dir / "instructions.xml").write_text(
            f"""<workflow>
<step n="1" goal="Execute {wf} workflow">
<action>Test action for {wf}</action>
</step>
</workflow>"""
        )

    # Create output directories
    (tmp_path / "_bmad-output/implementation-artifacts").mkdir(parents=True)
    (tmp_path / "_bmad-output/testarch").mkdir(parents=True)
    (tmp_path / "_bmad-output/standalone").mkdir(parents=True)

    # Create docs
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "project-context.md").write_text(
        """# Project Context

## Rules
- Rule 1: Follow TDD
- Rule 2: Write clean code
"""
    )
    (docs_dir / "architecture.md").write_text(
        """# Architecture

## Patterns
- Pattern 1: MVC
- Pattern 2: Repository pattern
"""
    )

    # Create knowledge base
    kb_dir = tmp_path / "_bmad/tea/testarch/knowledge"
    kb_dir.mkdir(parents=True)
    (kb_dir.parent / "tea-index.csv").write_text(
        "id,name,description,tags,fragment_file\n"
        "fixture-architecture,Fixture Architecture,Fixture patterns,fixtures,fixture-architecture.md\n"
    )
    (kb_dir / "fixture-architecture.md").write_text(
        "# Fixture Architecture\n\nBest practices for test fixtures."
    )

    # Create sprint-status.yaml
    (tmp_path / "_bmad-output/implementation-artifacts/sprint-status.yaml").write_text(
        """epics:
  - id: 1
    title: "Test Epic"
    stories:
      - key: 1-1-test-story
        status: in-progress
"""
    )

    # Create story file
    stories_dir = tmp_path / "_bmad-output/implementation-artifacts/stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "1-1-test-story.md").write_text(
        """# Story 1.1: Test Story

Status: in-progress

## Acceptance Criteria

1. AC1: First criterion
2. AC2: Second criterion

## Tasks

- [ ] Task 1
- [ ] Task 2
"""
    )

    return tmp_path


@pytest.fixture
def tea_minimal_project(tmp_path: Path) -> Path:
    """Create minimal project structure for basic tests.

    Returns:
        Path to temporary project root.
    """
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs/project-context.md").write_text("# Project Context\nRules here.")
    (tmp_path / "_bmad-output").mkdir(parents=True)
    return tmp_path


# =============================================================================
# Config Fixtures
# =============================================================================


class FakeTestarchConfig:
    """Fake TestarchConfig for testing."""

    def __init__(
        self,
        engagement_model: str = "auto",
        atdd_mode: str = "auto",
        framework_mode: str = "auto",
        ci_mode: str = "auto",
        test_design_mode: str = "auto",
        automate_mode: str = "auto",
        nfr_assess_mode: str = "auto",
        test_review_on_code_complete: str = "auto",
        trace_on_epic_complete: str = "auto",
        evidence_enabled: bool = False,
        **kwargs: Any,
    ) -> None:
        self.engagement_model = engagement_model
        self.atdd_mode = atdd_mode
        self.framework_mode = framework_mode
        self.ci_mode = ci_mode
        self.test_design_mode = test_design_mode
        self.automate_mode = automate_mode
        self.nfr_assess_mode = nfr_assess_mode
        self.test_review_on_code_complete = test_review_on_code_complete
        self.trace_on_epic_complete = trace_on_epic_complete
        self.evidence = MagicMock()
        self.evidence.enabled = evidence_enabled
        self.preflight = None
        self.eligibility = None
        # Apply any additional kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeConfig:
    """Fake Config for E2E testing."""

    def __init__(
        self,
        provider: str = "claude-subprocess",
        model: str = "opus",
        timeout: int = 120,
        testarch: FakeTestarchConfig | None = None,
        **kwargs: Any,
    ) -> None:
        self.providers = MagicMock()
        self.providers.master = MagicMock()
        self.providers.master.provider = provider
        self.providers.master.model = model
        self.timeout = timeout
        # Identify testarch-related kwargs
        testarch_keys = {"engagement_model", "atdd_mode", "framework_mode",
                        "ci_mode", "test_design_mode", "automate_mode",
                        "nfr_assess_mode", "test_review_mode", "trace_mode",
                        "evidence_enabled"}
        testarch_kwargs = {k: v for k, v in kwargs.items() if k in testarch_keys}
        # If testarch is provided, use it; otherwise create from kwargs
        if testarch is not None:
            self.testarch = testarch
        else:
            self.testarch = FakeTestarchConfig(**testarch_kwargs)
        self.benchmarking = MagicMock()
        self.benchmarking.enabled = False
        # Apply any remaining kwargs to self (not testarch)
        for key, value in kwargs.items():
            if key not in testarch_keys:
                setattr(self, key, value)


@pytest.fixture
def tea_integrated_config() -> FakeConfig:
    """Config with full TEA integration enabled."""
    return FakeConfig(
        testarch=FakeTestarchConfig(
            engagement_model="integrated",
            atdd_mode="auto",
            framework_mode="auto",
            ci_mode="auto",
            test_design_mode="auto",
            automate_mode="auto",
            nfr_assess_mode="auto",
            test_review_on_code_complete="auto",
            trace_on_epic_complete="auto",
        ),
    )


@pytest.fixture
def tea_solo_config() -> FakeConfig:
    """Config with solo engagement model."""
    return FakeConfig(
        testarch=FakeTestarchConfig(
            engagement_model="solo",
        ),
    )


@pytest.fixture
def tea_lite_config() -> FakeConfig:
    """Config with lite engagement model (automate only)."""
    return FakeConfig(
        testarch=FakeTestarchConfig(
            engagement_model="lite",
        ),
    )


@pytest.fixture
def tea_auto_config() -> FakeConfig:
    """Config with auto engagement model (respects individual workflow modes)."""
    return FakeConfig(
        testarch=FakeTestarchConfig(
            engagement_model="auto",
            atdd_mode="auto",
            framework_mode="on",
            ci_mode="off",
            test_design_mode="auto",
            automate_mode="auto",
            nfr_assess_mode="auto",
            test_review_on_code_complete="auto",
            trace_on_epic_complete="auto",
        ),
    )


@pytest.fixture
def tea_off_config() -> FakeConfig:
    """Config with engagement_model='off' (all TEA disabled)."""
    return FakeConfig(
        testarch=FakeTestarchConfig(
            engagement_model="off",
        ),
    )


# =============================================================================
# Mock Provider Fixtures
# =============================================================================


@pytest.fixture
def mock_provider_success() -> MagicMock:
    """Mock provider returning success."""
    from bmad_assist.providers.base import ProviderResult

    mock = MagicMock()
    mock.invoke.return_value = ProviderResult(
        exit_code=0,
        stdout="## Status: PASS\n\n# Mock Output\nContent here.",
        stderr="",
        model="opus",
        command=("claude",),
        duration_ms=100,
    )
    return mock


@pytest.fixture
def mock_provider_failure() -> MagicMock:
    """Mock provider returning failure."""
    from bmad_assist.providers.base import ProviderResult

    mock = MagicMock()
    mock.invoke.return_value = ProviderResult(
        exit_code=1,
        stdout="",
        stderr="Provider execution failed",
        model="opus",
        command=("claude",),
        duration_ms=100,
    )
    return mock


def create_provider_result(
    stdout: str = "## Status: PASS\n\nWorkflow completed.",
    exit_code: int = 0,
    stderr: str = "",
) -> Any:
    """Create a mock provider result with specified output.

    Args:
        stdout: Standard output content.
        exit_code: Exit code (0 for success).
        stderr: Standard error content.

    Returns:
        ProviderResult instance.
    """
    from bmad_assist.providers.base import ProviderResult

    return ProviderResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        model="opus",
        command=("claude",),
        duration_ms=100,
    )


# =============================================================================
# Mock Evidence Collector Fixtures
# =============================================================================


@pytest.fixture
def mock_evidence_collector() -> MagicMock:
    """Mock evidence collector."""
    mock = MagicMock()
    mock.collect_all.return_value = MagicMock(
        coverage=MagicMock(coverage_percent=85.0),
        test_results=MagicMock(passed=10, failed=0),
        security=None,
        performance=None,
    )
    return mock


@pytest.fixture
def mock_evidence_empty() -> MagicMock:
    """Mock evidence collector returning empty results."""
    mock = MagicMock()
    mock.collect_all.return_value = MagicMock(
        coverage=None,
        test_results=None,
        security=None,
        performance=None,
    )
    return mock


# =============================================================================
# Compiled Workflow Mock
# =============================================================================


@pytest.fixture
def mock_compiled_workflow() -> MagicMock:
    """Mock compiled workflow result."""
    mock = MagicMock()
    mock.context = "<compiled-workflow>test</compiled-workflow>"
    mock.workflow_name = "testarch-test"
    mock.token_estimate = 5000
    return mock
