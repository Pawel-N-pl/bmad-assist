"""Testarch module for Test Architect integration.

This module provides ATDD (Acceptance Test Driven Development) capabilities
for the bmad-assist development loop.

Note:
    ATDDHandler and TestarchBaseHandler are NOT imported here to avoid
    circular imports. Import directly:
    - `from bmad_assist.testarch.handlers import ATDDHandler`
    - `from bmad_assist.testarch.handlers import TestarchBaseHandler`

"""

from bmad_assist.testarch.config import (
    EligibilityConfig,
    PreflightConfig,
    TestarchConfig,
)
from bmad_assist.testarch.eligibility import (
    API_KEYWORDS,
    SKIP_KEYWORDS,
    UI_KEYWORDS,
    ATDDEligibilityDetector,
    ATDDEligibilityResult,
    KeywordScorer,
)
from bmad_assist.testarch.knowledge import (
    KnowledgeBaseLoader,
    KnowledgeFragment,
    KnowledgeIndex,
    get_knowledge_loader,
)
from bmad_assist.testarch.preflight import (
    PreflightChecker,
    PreflightResult,
    PreflightStatus,
)
from bmad_assist.testarch.evidence import (
    CoverageEvidence,
    EvidenceContext,
    EvidenceContextCollector,
    EvidenceSource,
    PerformanceEvidence,
    SecurityEvidence,
    SourceConfig,
    TestResultsEvidence,
    get_evidence_collector,
)
from bmad_assist.testarch.core import (
    CIPlatform,
    ReviewScope,
    TEAVariableResolver,
    detect_ci_platform,
    resolve_review_scope,
)
from bmad_assist.testarch.engagement import (
    STANDALONE_WORKFLOWS,
    WORKFLOW_MODE_FIELDS,
    should_run_workflow,
)
from bmad_assist.testarch.standalone import StandaloneRunner

__all__ = [
    "EligibilityConfig",
    "PreflightConfig",
    "TestarchConfig",
    "KeywordScorer",
    "UI_KEYWORDS",
    "API_KEYWORDS",
    "SKIP_KEYWORDS",
    "ATDDEligibilityResult",
    "ATDDEligibilityDetector",
    "KnowledgeBaseLoader",
    "KnowledgeFragment",
    "KnowledgeIndex",
    "get_knowledge_loader",
    "PreflightChecker",
    "PreflightResult",
    "PreflightStatus",
    "CoverageEvidence",
    "EvidenceContext",
    "EvidenceContextCollector",
    "EvidenceSource",
    "PerformanceEvidence",
    "SecurityEvidence",
    "SourceConfig",
    "TestResultsEvidence",
    "get_evidence_collector",
    # Core module exports (Story 25.6)
    "CIPlatform",
    "ReviewScope",
    "TEAVariableResolver",
    "detect_ci_platform",
    "resolve_review_scope",
    # Engagement module exports (Story 25.12)
    "STANDALONE_WORKFLOWS",
    "WORKFLOW_MODE_FIELDS",
    "should_run_workflow",
    # Standalone module exports (Story 25.13)
    "StandaloneRunner",
]
