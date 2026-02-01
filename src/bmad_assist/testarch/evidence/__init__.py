"""Evidence Context System for TEA workflows.

This module provides evidence collection capabilities for test architecture
decisions by gathering test artifacts, coverage data, security scan results,
and performance metrics from the codebase.

Usage:
    from bmad_assist.testarch.evidence import get_evidence_collector

    collector = get_evidence_collector(project_root)
    evidence = collector.collect_all()
    print(evidence.to_markdown())
"""

from bmad_assist.testarch.evidence.collector import (
    EvidenceContextCollector,
    clear_all_collectors,
    get_evidence_collector,
)
from bmad_assist.testarch.evidence.models import (
    CoverageEvidence,
    EvidenceContext,
    PerformanceEvidence,
    SecurityEvidence,
    SourceConfig,
    TestResultsEvidence,
)
from bmad_assist.testarch.evidence.sources import (
    CoverageSource,
    EvidenceSource,
    PerformanceSource,
    SecuritySource,
    TestResultsSource,
)

__all__ = [
    "CoverageEvidence",
    "CoverageSource",
    "EvidenceContext",
    "EvidenceContextCollector",
    "EvidenceSource",
    "PerformanceEvidence",
    "PerformanceSource",
    "SecurityEvidence",
    "SecuritySource",
    "SourceConfig",
    "TestResultsEvidence",
    "TestResultsSource",
    "clear_all_collectors",
    "get_evidence_collector",
]
