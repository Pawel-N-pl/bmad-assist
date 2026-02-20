"""Test fixtures for BMAD parsing tests.

Provides sample BMAD file fixtures used across test modules.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

# =============================================================================
# Shared Mock State for StateComparable Protocol
# =============================================================================


@dataclass
class MockInternalState:
    """Mock internal state for testing StateComparable protocol.

    This fixture provides a simple implementation of the StateComparable
    protocol for use in discrepancy detection and correction tests.
    """

    current_epic: int | None = 2
    current_story: str | None = "2.3"
    completed_stories: list[str] = field(default_factory=lambda: ["1.1", "1.2"])


@pytest.fixture
def mock_internal_state() -> MockInternalState:
    """Fixture providing default MockInternalState for tests."""
    return MockInternalState()


# =============================================================================
# Real BMAD Sample Project Fixture
# =============================================================================


@pytest.fixture
def sample_bmad_project() -> Path:
    """Path to real BMAD sample project with authentic documentation.

    This fixture provides access to a complete BMAD project structure with:
    - docs/prd.md - Product requirements document
    - docs/architecture.md - Architecture document
    - docs/epics.md - 9 epics, 60 stories, 132 story points
    - docs/sprint-artifacts/sprint-status.yaml - Sprint tracking
    - docs/sprint-artifacts/*.md - Story files
    - docs/sprint-artifacts/code-reviews/*.md - Code review reports

    Returns:
        Path to tests/fixtures/bmad-sample-project/docs/

    """
    project_path = Path(__file__).parent.parent / "fixtures" / "bmad-sample-project" / "docs"
    if not project_path.exists():
        pytest.skip("Sample BMAD project not found at tests/fixtures/bmad-sample-project/")
    return project_path


@pytest.fixture
def sample_sprint_artifacts(sample_bmad_project: Path) -> Path:
    """Path to sprint-artifacts directory in sample project."""
    return sample_bmad_project / "sprint-artifacts"


@pytest.fixture
def sample_bmad_file(tmp_path: Path) -> Path:
    """Create a sample BMAD file with standard frontmatter."""
    content = """---
title: PRD Document
status: complete
date: 2025-12-08
---

# Content here
"""
    path = tmp_path / "test.md"
    path.write_text(content)
    return path


@pytest.fixture
def file_without_frontmatter(tmp_path: Path) -> Path:
    """Create a markdown file without frontmatter."""
    content = """# Just Content

Some markdown text.
"""
    path = tmp_path / "no_frontmatter.md"
    path.write_text(content)
    return path


@pytest.fixture
def malformed_yaml_file(tmp_path: Path) -> Path:
    """Create a file with invalid YAML frontmatter."""
    content = """---
invalid: [unclosed bracket
---
"""
    path = tmp_path / "malformed.md"
    path.write_text(content)
    return path


@pytest.fixture
def complex_frontmatter_file(tmp_path: Path) -> Path:
    """Create a file with complex YAML types in frontmatter."""
    content = """---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - docs/prd.md
  - docs/architecture.md
metadata:
  author: Pawel
  validated: true
---

# Complex Content
"""
    path = tmp_path / "complex.md"
    path.write_text(content)
    return path


@pytest.fixture
def empty_frontmatter_file(tmp_path: Path) -> Path:
    """Create a file with empty frontmatter."""
    content = """---
---

# Content
"""
    path = tmp_path / "empty_frontmatter.md"
    path.write_text(content)
    return path


@pytest.fixture
def content_with_delimiters_file(tmp_path: Path) -> Path:
    """Create a file with --- delimiters in content (code blocks, horizontal rules)."""
    content = """---
title: Architecture Doc
---

## Code Example

```yaml
---
config: value
---
```

---

More content after horizontal rule.
"""
    path = tmp_path / "delimiters.md"
    path.write_text(content)
    return path


@pytest.fixture
def real_prd_style_file(tmp_path: Path) -> Path:
    """Create a file mimicking real PRD frontmatter structure."""
    content = """---
stepsCompleted: [1, 2, 3, 4, 7, 8, 9, 10, 11]
inputDocuments: []
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 0
  projectDocs: 0
workflowType: 'prd'
lastStep: 11
project_name: 'bmad-assist'
user_name: 'Pawel'
date: '2025-12-08'
---

# Product Requirements Document

## Introduction

This document describes the requirements for bmad-assist.
"""
    path = tmp_path / "prd.md"
    path.write_text(content)
    return path


@pytest.fixture
def real_architecture_style_file(tmp_path: Path) -> Path:
    """Create a file mimicking real architecture frontmatter structure."""
    content = """---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - docs/prd.md
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2025-12-08'
project_name: 'bmad-assist'
user_name: 'Pawel'
date: '2025-12-08'
---

# Architecture Document

## System Overview

Architecture description here.
"""
    path = tmp_path / "architecture.md"
    path.write_text(content)
    return path


# Epic file fixtures for Story 2.2


@pytest.fixture
def single_epic_file(tmp_path: Path) -> Path:
    """Create a single epic file with standard structure."""
    content = """---
epic_num: 2
title: BMAD File Integration
status: in-progress
---

# Epic 2: BMAD File Integration

## Story 2.1: Markdown Frontmatter Parser

**As a** developer,
**I want** to parse BMAD markdown files with YAML frontmatter,
**So that** I can extract metadata without using an LLM.

**Estimate:** 2 SP
**Status:** done

---

## Story 2.2: Epic File Parser

**As a** developer,
**I want** to extract story list and status from epic files,
**So that** the system knows which stories exist.

**Estimate:** 3 SP
**Status:** in-progress
**Dependencies:** Story 2.1 (Markdown Frontmatter Parser)

**Acceptance Criteria:**
- [x] AC1: Parse standard story sections
- [x] AC2: Extract story estimates
- [ ] AC3: Handle malformed headers
"""
    path = tmp_path / "epic-2.md"
    path.write_text(content)
    return path


@pytest.fixture
def consolidated_epics_file(tmp_path: Path) -> Path:
    """Create a consolidated epics file with multiple epics."""
    content = """---
total_epics: 2
total_stories: 4
---

# Epic 1: Project Foundation

## Story 1.1: Project Initialization

**Estimate:** 2 SP

## Story 1.2: Configuration Models

**Estimate:** 3 SP

# Epic 2: BMAD File Integration

## Story 2.1: Markdown Frontmatter Parser

**Estimate:** 2 SP

## Story 2.2: Epic File Parser

**Estimate:** 3 SP
"""
    path = tmp_path / "epics.md"
    path.write_text(content)
    return path


@pytest.fixture
def epic_with_no_stories(tmp_path: Path) -> Path:
    """Create an epic file with no story sections."""
    content = """---
epic_num: 5
title: Power-Prompts Engine
---

# Epic 5: Power-Prompts Engine

**Goal:** System can load and inject context-aware prompts...

**FRs:** FR22, FR23, FR24, FR25
"""
    path = tmp_path / "epic-5.md"
    path.write_text(content)
    return path


@pytest.fixture
def epic_with_dependencies(tmp_path: Path) -> Path:
    """Create an epic file with story dependencies."""
    content = """---
epic_num: 3
---

## Story 3.5: Resume Interrupted Loop

**Dependencies:** Story 3.2 (Atomic State Persistence), Story 3.4 (Loop Position Tracking)

**Estimate:** 3 SP
"""
    path = tmp_path / "epic-3.md"
    path.write_text(content)
    return path
