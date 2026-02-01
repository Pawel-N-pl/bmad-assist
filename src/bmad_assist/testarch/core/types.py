"""Type definitions for TEA Core module.

This module provides enum types for CI platform detection and review scope resolution.

Usage:
    from bmad_assist.testarch.core.types import CIPlatform, ReviewScope

    # Check CI platform
    if platform == CIPlatform.GITHUB:
        print("Using GitHub Actions")

    # Check review scope
    if scope == ReviewScope.SINGLE:
        print("Single story review")
"""

from enum import Enum


class CIPlatform(Enum):
    """CI/CD platform type detected from project structure.

    Attributes:
        GITHUB: GitHub Actions (`.github/workflows/*.yml`)
        GITLAB: GitLab CI (`.gitlab-ci.yml`)
        CIRCLECI: CircleCI (`.circleci/config.yml`)
        AZURE: Azure Pipelines (`azure-pipelines.yml`)
        JENKINS: Jenkins (`Jenkinsfile`)
        UNKNOWN: No CI platform detected

    """

    GITHUB = "github"
    GITLAB = "gitlab"
    CIRCLECI = "circleci"
    AZURE = "azure"
    JENKINS = "jenkins"
    UNKNOWN = "unknown"


class ReviewScope(Enum):
    """Test review scope based on context.

    Attributes:
        SINGLE: Single story review (story_file is provided)
        DIRECTORY: Directory-level review (test_dir points to subdirectory)
        SUITE: Full test suite review (default)

    """

    SINGLE = "single"
    DIRECTORY = "directory"
    SUITE = "suite"
