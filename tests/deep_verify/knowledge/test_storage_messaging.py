"""Tests for STORAGE and MESSAGING knowledge bases.

This module provides comprehensive test coverage for the STORAGE and MESSAGING
domain knowledge bases, including rule loading, validation, and integration
with the DomainExpertMethod.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.knowledge import (
    KnowledgeCategory,
    KnowledgeLoader,
)
from bmad_assist.deep_verify.methods.domain_expert import (
    DomainExpertMethod,
    DomainExpertViolationData,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider() -> Generator[MagicMock, None, None]:
    """Mock the ClaudeSDKProvider - must be before method fixture."""
    with patch(
        "bmad_assist.deep_verify.methods.domain_expert.ClaudeSDKProvider"
    ) as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def method(mock_provider: MagicMock) -> DomainExpertMethod:
    """Create DomainExpertMethod with mocked provider."""
    return DomainExpertMethod()


# =============================================================================
# Test STORAGE Domain Integration
# =============================================================================


class TestStorageDomainIntegration:
    """Tests for STORAGE domain knowledge base integration."""

    @pytest.mark.asyncio
    async def test_loads_storage_rules(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test that method loads STORAGE rules when STORAGE domain is detected."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        # Clear cache to ensure fresh load
        method._loader.clear_cache()

        findings = await method.analyze(
            "some storage code",
            domains=[ArtifactDomain.STORAGE]
        )

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_storage_acid_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for ACID violation."""
        # Get real storage rules
        rules = method._loader.load([ArtifactDomain.STORAGE])

        violation = DomainExpertViolationData(
            rule_id="DB-ACID-001",
            rule_title="Atomicity Violation",
            evidence_quote='db.Exec("UPDATE accounts SET balance = balance - 100")',
            line_number=42,
            violation_explanation="Multiple operations without transaction wrapper",
            remediation="Wrap in transaction with BEGIN/COMMIT",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.CRITICAL
        assert finding.pattern_id == PatternId("DB-ACID-001")
        assert finding.domain == ArtifactDomain.STORAGE
        assert "Atomicity" in finding.title

    @pytest.mark.asyncio
    async def test_storage_n_plus_one_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for N+1 query violation."""
        rules = method._loader.load([ArtifactDomain.STORAGE])

        violation = DomainExpertViolationData(
            rule_id="DB-QUERY-001",
            rule_title="N+1 Query Pattern",
            evidence_quote="for user in users: orders = db.query(f'SELECT * FROM orders WHERE user_id = {user.id}')",
            line_number=25,
            violation_explanation="Query inside loop causes N+1 pattern",
            remediation="Use JOIN to fetch all data in single query",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.ERROR
        assert finding.pattern_id == PatternId("DB-QUERY-001")
        assert finding.domain == ArtifactDomain.STORAGE

    @pytest.mark.asyncio
    async def test_storage_connection_leak_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for connection leak violation."""
        rules = method._loader.load([ArtifactDomain.STORAGE])

        violation = DomainExpertViolationData(
            rule_id="DB-POOL-002",
            rule_title="Connection Leak",
            evidence_quote="conn = pool.get_connection()\n# No conn.close() or defer",
            line_number=30,
            violation_explanation="Connection not returned to pool",
            remediation="Use defer or context manager to ensure connection cleanup",
            confidence=0.8,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.ERROR
        assert finding.pattern_id == PatternId("DB-POOL-002")
        assert finding.domain == ArtifactDomain.STORAGE

    @pytest.mark.asyncio
    async def test_storage_select_star_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for SELECT * violation (WARNING severity)."""
        rules = method._loader.load([ArtifactDomain.STORAGE])

        violation = DomainExpertViolationData(
            rule_id="DB-QUERY-004",
            rule_title="SELECT * Anti-Pattern",
            evidence_quote='rows = db.query("SELECT * FROM large_table")',
            line_number=15,
            violation_explanation="Selecting all columns when only few needed",
            remediation="Explicitly list required columns only",
            confidence=0.75,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.WARNING
        assert finding.pattern_id == PatternId("DB-QUERY-004")
        assert finding.domain == ArtifactDomain.STORAGE

    def test_storage_rule_categories(self, method: DomainExpertMethod) -> None:
        """Test that STORAGE rules have correct categories."""
        rules = method._loader.load([ArtifactDomain.STORAGE])
        storage_rules = [r for r in rules if r.domain == "storage"]

        # ACID rules should be STANDARDS
        acid_rules = [r for r in storage_rules if r.id.startswith("DB-ACID")]
        for rule in acid_rules:
            assert rule.category == KnowledgeCategory.STANDARDS

        # INDEX rules should be BEST_PRACTICES
        index_rules = [r for r in storage_rules if r.id.startswith("DB-INDEX")]
        for rule in index_rules:
            assert rule.category == KnowledgeCategory.BEST_PRACTICES

    def test_storage_rule_severities(self, method: DomainExpertMethod) -> None:
        """Test that STORAGE rules have appropriate severities."""
        rules = method._loader.load([ArtifactDomain.STORAGE])
        storage_rules = {r.id: r for r in rules if r.domain == "storage"}

        # Critical ACID violations
        assert storage_rules["DB-ACID-001"].severity == Severity.CRITICAL
        assert storage_rules["DB-ACID-003"].severity == Severity.CRITICAL

        # Error-level query issues
        assert storage_rules["DB-QUERY-001"].severity == Severity.ERROR
        assert storage_rules["DB-QUERY-002"].severity == Severity.ERROR
        assert storage_rules["DB-QUERY-003"].severity == Severity.CRITICAL

        # Warning-level best practices
        assert storage_rules["DB-INDEX-002"].severity == Severity.WARNING

        # Info-level suggestions
        assert storage_rules["DB-INDEX-004"].severity == Severity.INFO


# =============================================================================
# Test MESSAGING Domain Integration
# =============================================================================


class TestMessagingDomainIntegration:
    """Tests for MESSAGING domain knowledge base integration."""

    @pytest.mark.asyncio
    async def test_loads_messaging_rules(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test that method loads MESSAGING rules when MESSAGING domain is detected."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        method._loader.clear_cache()

        findings = await method.analyze(
            "some messaging code",
            domains=[ArtifactDomain.MESSAGING]
        )

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_messaging_idempotency_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for idempotency violation."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-SEMANTICS-001",
            rule_title="Missing Idempotency",
            evidence_quote="def process_payment(msg): charge_card(msg.card_id, msg.amount)",
            line_number=45,
            violation_explanation="At-least-once delivery without idempotent consumer",
            remediation="Add idempotency key check before processing",
            confidence=0.95,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.CRITICAL
        assert finding.pattern_id == PatternId("MSG-SEMANTICS-001")
        assert finding.domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_messaging_fixed_backoff_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for fixed interval backoff violation."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-BACKOFF-001",
            rule_title="Fixed Interval Backoff",
            evidence_quote="time.Sleep(5 * time.Second)  // Fixed retry interval",
            line_number=52,
            violation_explanation="Fixed interval causes thundering herd",
            remediation="Use exponential backoff with jitter",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.ERROR
        assert finding.pattern_id == PatternId("MSG-BACKOFF-001")
        assert finding.domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_messaging_dlq_missing_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for missing DLQ violation."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-DLQ-001",
            rule_title="Missing DLQ Configuration",
            evidence_quote="sqs.CreateQueue(&sqs.CreateQueueInput{QueueName: strPtr(\"main-queue\")})",
            line_number=20,
            violation_explanation="No dead letter queue configured for failed messages",
            remediation="Configure DLQ with maxReceiveCount redrive policy",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.ERROR
        assert finding.pattern_id == PatternId("MSG-DLQ-001")
        assert finding.domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_messaging_fifo_assumption_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for FIFO assumption violation."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-ORDER-001",
            rule_title="FIFO Assumption Without Guarantee",
            evidence_quote="# Process messages in order received\nfor msg := range msgs { process(msg) }",
            line_number=35,
            violation_explanation="Code assumes ordering broker doesn't provide",
            remediation="Use FIFO queue or implement ordering in application",
            confidence=0.8,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.ERROR
        assert finding.pattern_id == PatternId("MSG-ORDER-001")
        assert finding.domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_messaging_oversized_message_violation(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation for oversized message violation (WARNING)."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-SIZE-001",
            rule_title="Oversized Messages",
            evidence_quote="msg.Body = string(largeJSON)  // 200KB payload",
            line_number=28,
            violation_explanation="Message exceeds recommended size limit",
            remediation="Use S3 with message containing reference to S3 object",
            confidence=0.7,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.WARNING
        assert finding.pattern_id == PatternId("MSG-SIZE-001")
        assert finding.domain == ArtifactDomain.MESSAGING

    def test_messaging_rule_categories(self, method: DomainExpertMethod) -> None:
        """Test that MESSAGING rules have correct categories."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])
        messaging_rules = [r for r in rules if r.domain == "messaging"]

        # Semantics rules should be STANDARDS or BEST_PRACTICES
        semantics_rules = [r for r in messaging_rules if r.id.startswith("MSG-SEMANTICS")]
        for rule in semantics_rules:
            assert rule.category in (KnowledgeCategory.STANDARDS, KnowledgeCategory.BEST_PRACTICES)

        # Backoff rules should be STANDARDS or BEST_PRACTICES
        backoff_rules = [r for r in messaging_rules if r.id.startswith("MSG-BACKOFF")]
        for rule in backoff_rules:
            assert rule.category in (KnowledgeCategory.STANDARDS, KnowledgeCategory.BEST_PRACTICES)

    def test_messaging_rule_severities(self, method: DomainExpertMethod) -> None:
        """Test that MESSAGING rules have appropriate severities."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])
        messaging_rules = {r.id: r for r in rules if r.domain == "messaging"}

        # Critical semantics violation
        assert messaging_rules["MSG-SEMANTICS-001"].severity == Severity.CRITICAL

        # Error-level standards
        assert messaging_rules["MSG-BACKOFF-001"].severity == Severity.ERROR
        assert messaging_rules["MSG-BACKOFF-002"].severity == Severity.ERROR
        assert messaging_rules["MSG-BACKOFF-003"].severity == Severity.ERROR

        # Warning-level best practices
        assert messaging_rules["MSG-SIZE-001"].severity == Severity.WARNING


# =============================================================================
# Test Cross-Domain Integration
# =============================================================================


class TestCrossDomainIntegration:
    """Tests for cross-domain scenarios."""

    @pytest.mark.asyncio
    async def test_storage_and_messaging_together(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test loading both STORAGE and MESSAGING domains together."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        method._loader.clear_cache()

        findings = await method.analyze(
            "code with both storage and messaging",
            domains=[ArtifactDomain.STORAGE, ArtifactDomain.MESSAGING]
        )

        assert isinstance(findings, list)

    def test_no_rule_id_collisions(self, method: DomainExpertMethod) -> None:
        """Test that rule IDs don't collide between domains."""
        method._loader.clear_cache()
        rules = method._loader.load([ArtifactDomain.STORAGE, ArtifactDomain.MESSAGING])

        all_ids = [r.id for r in rules]
        unique_ids = set(all_ids)

        assert len(all_ids) == len(unique_ids), "Duplicate IDs found"

    def test_distinct_id_prefixes(self, method: DomainExpertMethod) -> None:
        """Test that domains use distinct ID prefixes."""
        method._loader.clear_cache()

        storage_rules = method._loader.load([ArtifactDomain.STORAGE])
        storage_ids = {r.id for r in storage_rules if r.domain == "storage"}

        method._loader.clear_cache()

        messaging_rules = method._loader.load([ArtifactDomain.MESSAGING])
        messaging_ids = {r.id for r in messaging_rules if r.domain == "messaging"}

        # STORAGE uses DB- prefix
        for rule_id in storage_ids:
            assert rule_id.startswith("DB-"), f"Storage rule {rule_id} doesn't use DB- prefix"

        # MESSAGING uses MSG- prefix
        for rule_id in messaging_ids:
            assert rule_id.startswith("MSG-"), f"Messaging rule {rule_id} doesn't use MSG- prefix"

        # No overlap
        assert not storage_ids.intersection(messaging_ids)

    @pytest.mark.asyncio
    async def test_correct_domain_assignment_storage(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test that STORAGE violations are assigned STORAGE domain."""
        rules = method._loader.load([ArtifactDomain.STORAGE])

        violation = DomainExpertViolationData(
            rule_id="DB-ACID-001",
            rule_title="Atomicity Violation",
            evidence_quote="code",
            violation_explanation="test",
            remediation="fix",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.domain == ArtifactDomain.STORAGE

    @pytest.mark.asyncio
    async def test_correct_domain_assignment_messaging(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
    ) -> None:
        """Test that MESSAGING violations are assigned MESSAGING domain."""
        rules = method._loader.load([ArtifactDomain.MESSAGING])

        violation = DomainExpertViolationData(
            rule_id="MSG-SEMANTICS-001",
            rule_title="Missing Idempotency",
            evidence_quote="code",
            violation_explanation="test",
            remediation="fix",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.domain == ArtifactDomain.MESSAGING

    def test_all_domains_with_security(self, method: DomainExpertMethod) -> None:
        """Test loading all three domains together."""
        method._loader.clear_cache()
        rules = method._loader.load([
            ArtifactDomain.SECURITY,
            ArtifactDomain.STORAGE,
            ArtifactDomain.MESSAGING
        ])

        security_count = len([r for r in rules if r.domain == "security"])
        storage_count = len([r for r in rules if r.domain == "storage"])
        messaging_count = len([r for r in rules if r.domain == "messaging"])
        general_count = len([r for r in rules if r.domain == "general"])

        assert security_count >= 15
        assert storage_count == 17
        assert messaging_count == 17
        assert general_count == 8


# =============================================================================
# Test Real Knowledge Base Content
# =============================================================================


class TestRealKnowledgeBaseContent:
    """Tests verifying actual knowledge base content."""

    def test_storage_yaml_structure(self) -> None:
        """Test that storage.yaml has proper structure."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        rules = loader.load([ArtifactDomain.STORAGE])
        storage_rules = [r for r in rules if r.domain == "storage"]

        # Verify minimum 15 rules
        assert len(storage_rules) >= 15

        # Verify rule ID format
        for rule in storage_rules:
            assert rule.id.startswith("DB-"), f"Invalid ID format: {rule.id}"
            parts = rule.id.split("-")
            assert len(parts) >= 2, f"Invalid ID structure: {rule.id}"

    def test_messaging_yaml_structure(self) -> None:
        """Test that messaging.yaml has proper structure."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        rules = loader.load([ArtifactDomain.MESSAGING])
        messaging_rules = [r for r in rules if r.domain == "messaging"]

        # Verify minimum 15 rules
        assert len(messaging_rules) >= 15

        # Verify rule ID format
        for rule in messaging_rules:
            assert rule.id.startswith("MSG-"), f"Invalid ID format: {rule.id}"
            parts = rule.id.split("-")
            assert len(parts) >= 2, f"Invalid ID structure: {rule.id}"

    def test_storage_references_present(self) -> None:
        """Test that STORAGE rules have references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        rules = loader.load([ArtifactDomain.STORAGE])
        storage_rules = [r for r in rules if r.domain == "storage"]

        # Most rules should have references
        rules_with_refs = [r for r in storage_rules if r.references]
        assert len(rules_with_refs) >= 10

        # References should be URLs
        for rule in rules_with_refs:
            for ref in rule.references:
                assert ref.startswith("http"), f"Invalid reference in {rule.id}: {ref}"

    def test_messaging_references_present(self) -> None:
        """Test that MESSAGING rules have references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        rules = loader.load([ArtifactDomain.MESSAGING])
        messaging_rules = [r for r in rules if r.domain == "messaging"]

        # Most rules should have references
        rules_with_refs = [r for r in messaging_rules if r.references]
        assert len(rules_with_refs) >= 10

        # References should be URLs
        for rule in rules_with_refs:
            for ref in rule.references:
                assert ref.startswith("http"), f"Invalid reference in {rule.id}: {ref}"
