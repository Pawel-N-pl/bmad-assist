"""Evidence source implementations.

This module provides source classes for collecting various types of evidence
from test artifacts, coverage reports, security scans, and performance metrics.

Usage:
    from bmad_assist.testarch.evidence.sources import CoverageSource

    source = CoverageSource()
    evidence = source.collect(project_root)
"""

from bmad_assist.testarch.evidence.sources.base import EvidenceSource
from bmad_assist.testarch.evidence.sources.coverage import CoverageSource
from bmad_assist.testarch.evidence.sources.performance import PerformanceSource
from bmad_assist.testarch.evidence.sources.security import SecuritySource
from bmad_assist.testarch.evidence.sources.test_results import TestResultsSource

__all__ = [
    "CoverageSource",
    "EvidenceSource",
    "PerformanceSource",
    "SecuritySource",
    "TestResultsSource",
]
