"""Test fixtures for TEA Knowledge Base tests."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_index_content() -> str:
    """Sample tea-index.csv content."""
    return """id,name,description,tags,fragment_file
fixture-architecture,Fixture Architecture,"Composable fixture patterns","fixtures,architecture,playwright",knowledge/fixture-architecture.md
network-first,Network-First Safeguards,"Intercept-before-navigate workflow","network,stability,playwright-utils",knowledge/network-first.md
data-factories,Data Factories,"Factory patterns for test data","data,factories,api",knowledge/data-factories.md
overview,Overview,"Playwright utils overview","playwright-utils,overview",knowledge/overview.md
"""


@pytest.fixture
def sample_fragment_content() -> str:
    """Sample fragment markdown content."""
    return """# Fixture Architecture Playbook

## Principle

Build test helpers as pure functions first.

## Rationale

Traditional POM creates tight coupling.
"""


@pytest.fixture
def mock_knowledge_dir(tmp_path: Path, sample_index_content: str, sample_fragment_content: str) -> Path:
    """Create mock knowledge directory structure."""
    # Create directory structure
    tea_dir = tmp_path / "_bmad" / "tea" / "testarch"
    tea_dir.mkdir(parents=True)
    knowledge_dir = tea_dir / "knowledge"
    knowledge_dir.mkdir()

    # Write index file
    index_path = tea_dir / "tea-index.csv"
    index_path.write_text(sample_index_content)

    # Write fragment files
    (knowledge_dir / "fixture-architecture.md").write_text(sample_fragment_content)
    (knowledge_dir / "network-first.md").write_text("# Network-First\n\nContent here.")
    (knowledge_dir / "data-factories.md").write_text("# Data Factories\n\nContent here.")
    (knowledge_dir / "overview.md").write_text("# Overview\n\nPlaywright utils overview.")

    return tmp_path


@pytest.fixture
def empty_knowledge_dir(tmp_path: Path) -> Path:
    """Create directory without knowledge index."""
    (tmp_path / "_bmad" / "tea" / "testarch").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def malformed_index_content() -> str:
    """Malformed CSV content (missing required columns)."""
    return """id,name,description
fixture-architecture,Fixture Architecture,Description
"""


@pytest.fixture
def quoted_fields_index_content() -> str:
    """CSV content with quoted fields containing commas."""
    return '''id,name,description,tags,fragment_file
test-id,"Test Name, with comma","Description, with comma, multiple","tag1,tag2,tag3",knowledge/test.md
'''
