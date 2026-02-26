"""Tests for KnowledgeLoader and related classes.

This module provides comprehensive test coverage for the knowledge base
framework including KnowledgeLoader, KnowledgeRule, and KnowledgeRuleYaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

from bmad_assist.deep_verify.core.types import Severity
from bmad_assist.deep_verify.knowledge import (
    KnowledgeCategory,
    KnowledgeLoader,
    KnowledgeRule,
    KnowledgeRuleYaml,
)
from bmad_assist.deep_verify.knowledge.loader import KnowledgeBaseYaml

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_knowledge_dir(tmp_path: Path) -> Path:
    """Create a temporary knowledge directory with test YAML files."""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()

    # Create base.yaml
    base_data = {
        "knowledge_base": {
            "version": "1.0",
            "domain": "general",
            "description": "Base rules",
            "rules": [
                {
                    "id": "GEN-001",
                    "domain": "general",
                    "category": "best_practices",
                    "title": "Base Rule 1",
                    "description": "First base rule",
                    "severity": "warning",
                    "references": [],
                },
                {
                    "id": "GEN-002",
                    "domain": "general",
                    "category": "standards",
                    "title": "Base Rule 2",
                    "description": "Second base rule",
                    "severity": "critical",
                },
            ],
        }
    }

    with open(knowledge_dir / "base.yaml", "w") as f:
        yaml.dump(base_data, f)

    # Create security.yaml
    security_data = {
        "knowledge_base": {
            "version": "1.0",
            "domain": "security",
            "description": "Security rules",
            "rules": [
                {
                    "id": "SEC-001",
                    "domain": "security",
                    "category": "standards",
                    "title": "Security Rule 1",
                    "description": "First security rule",
                    "severity": "critical",
                    "references": ["https://example.com/sec1"],
                },
            ],
        }
    }

    with open(knowledge_dir / "security.yaml", "w") as f:
        yaml.dump(security_data, f)

    return knowledge_dir


@pytest.fixture
def loader(temp_knowledge_dir: Path) -> KnowledgeLoader:
    """Create a KnowledgeLoader with temp directory."""
    return KnowledgeLoader(temp_knowledge_dir)





# =============================================================================
# Test KnowledgeCategory
# =============================================================================


class TestKnowledgeCategory:
    """Tests for KnowledgeCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that all 4 knowledge categories are defined."""
        categories = list(KnowledgeCategory)
        assert len(categories) == 4
        assert KnowledgeCategory.STANDARDS in categories
        assert KnowledgeCategory.COMPLIANCE in categories
        assert KnowledgeCategory.BEST_PRACTICES in categories
        assert KnowledgeCategory.HEURISTICS in categories

    def test_category_values(self) -> None:
        """Test category string values."""
        assert KnowledgeCategory.STANDARDS.value == "standards"
        assert KnowledgeCategory.COMPLIANCE.value == "compliance"
        assert KnowledgeCategory.BEST_PRACTICES.value == "best_practices"
        assert KnowledgeCategory.HEURISTICS.value == "heuristics"

    def test_category_comparison(self) -> None:
        """Test category can be compared with string."""
        assert KnowledgeCategory.STANDARDS == "standards"
        assert KnowledgeCategory.COMPLIANCE == "compliance"


# =============================================================================
# Test KnowledgeRule
# =============================================================================


class TestKnowledgeRule:
    """Tests for KnowledgeRule dataclass."""

    def test_create_knowledge_rule(self) -> None:
        """Test creating a KnowledgeRule."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test Rule",
            description="Test description",
            severity=Severity.CRITICAL,
            references=["https://example.com"],
        )

        assert rule.id == "SEC-001"
        assert rule.domain == "security"
        assert rule.category == KnowledgeCategory.STANDARDS
        assert rule.title == "Test Rule"
        assert rule.description == "Test description"
        assert rule.severity == Severity.CRITICAL
        assert rule.references == ["https://example.com"]

    def test_knowledge_rule_defaults(self) -> None:
        """Test KnowledgeRule with default values."""
        rule = KnowledgeRule(
            id="GEN-001",
            domain="general",
            category=KnowledgeCategory.BEST_PRACTICES,
            title="General Rule",
            description="General description",
            severity=Severity.WARNING,
        )

        assert rule.references == []

    def test_knowledge_rule_repr(self) -> None:
        """Test KnowledgeRule repr."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test Rule",
            description="Test description",
            severity=Severity.CRITICAL,
        )

        repr_str = repr(rule)
        assert "KnowledgeRule" in repr_str
        assert "SEC-001" in repr_str
        assert "security" in repr_str
        assert "Test Rule" in repr_str

    def test_knowledge_rule_immutable(self) -> None:
        """Test KnowledgeRule is immutable (frozen dataclass)."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test Rule",
            description="Test description",
            severity=Severity.CRITICAL,
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            rule.id = "SEC-002"


# =============================================================================
# Test KnowledgeRuleYaml
# =============================================================================


class TestKnowledgeRuleYaml:
    """Tests for KnowledgeRuleYaml Pydantic model."""

    def test_valid_knowledge_rule_yaml(self) -> None:
        """Test creating valid KnowledgeRuleYaml."""
        rule_yaml = KnowledgeRuleYaml(
            id="SEC-001",
            domain="security",
            category="standards",
            title="Test Rule",
            description="Test description",
            severity="critical",
            references=["https://example.com"],
        )

        assert rule_yaml.id == "SEC-001"
        assert rule_yaml.severity == "critical"

    def test_category_validation(self) -> None:
        """Test category field validation."""
        # Valid categories
        for category in ["standards", "compliance", "best_practices", "heuristics"]:
            rule = KnowledgeRuleYaml(
                id="SEC-001",
                domain="security",
                category=category,
                title="Test",
                description="Test",
                severity="critical",
            )
            assert rule.category == category

        # Invalid category
        with pytest.raises(ValueError, match="Invalid category"):
            KnowledgeRuleYaml(
                id="SEC-001",
                domain="security",
                category="invalid_category",
                title="Test",
                description="Test",
                severity="critical",
            )

    def test_category_case_insensitive(self) -> None:
        """Test category validation is case-insensitive."""
        rule = KnowledgeRuleYaml(
            id="SEC-001",
            domain="security",
            category="STANDARDS",  # uppercase
            title="Test",
            description="Test",
            severity="critical",
        )
        assert rule.category == "standards"

    def test_severity_validation(self) -> None:
        """Test severity field validation."""
        # Valid severities
        for severity in ["critical", "error", "warning", "info"]:
            rule = KnowledgeRuleYaml(
                id="SEC-001",
                domain="security",
                category="standards",
                title="Test",
                description="Test",
                severity=severity,
            )
            assert rule.severity == severity

        # Invalid severity
        with pytest.raises(ValueError, match="Invalid severity"):
            KnowledgeRuleYaml(
                id="SEC-001",
                domain="security",
                category="standards",
                title="Test",
                description="Test",
                severity="invalid",
            )

    def test_to_knowledge_rule_conversion(self) -> None:
        """Test conversion to KnowledgeRule."""
        rule_yaml = KnowledgeRuleYaml(
            id="SEC-001",
            domain="security",
            category="standards",
            title="Test Rule",
            description="Test description",
            severity="critical",
            references=["https://example.com"],
        )

        rule = rule_yaml.to_knowledge_rule()

        assert isinstance(rule, KnowledgeRule)
        assert rule.id == "SEC-001"
        assert rule.domain == "security"
        assert rule.category == KnowledgeCategory.STANDARDS
        assert rule.title == "Test Rule"
        assert rule.severity == Severity.CRITICAL
        assert rule.references == ["https://example.com"]

    def test_default_references(self) -> None:
        """Test default empty references list."""
        rule_yaml = KnowledgeRuleYaml(
            id="SEC-001",
            domain="security",
            category="standards",
            title="Test",
            description="Test",
            severity="critical",
        )

        assert rule_yaml.references == []


# =============================================================================
# Test KnowledgeBaseYaml
# =============================================================================


class TestKnowledgeBaseYaml:
    """Tests for KnowledgeBaseYaml Pydantic model."""

    def test_valid_knowledge_base(self) -> None:
        """Test valid knowledge base YAML structure."""
        data = {
            "knowledge_base": {
                "version": "1.0",
                "domain": "security",
                "description": "Security rules",
                "rules": [],
            }
        }

        kb = KnowledgeBaseYaml(**data)
        assert kb.knowledge_base["version"] == "1.0"
        assert kb.knowledge_base["domain"] == "security"

    def test_missing_required_fields(self) -> None:
        """Test validation fails for missing required fields."""
        # Missing version
        with pytest.raises(ValueError, match="Missing required fields"):
            KnowledgeBaseYaml(
                knowledge_base={
                    "domain": "security",
                    "description": "Test",
                    "rules": [],
                }
            )

        # Missing rules
        with pytest.raises(ValueError, match="Missing required fields"):
            KnowledgeBaseYaml(
                knowledge_base={
                    "version": "1.0",
                    "domain": "security",
                    "description": "Test",
                }
            )

    def test_rules_must_be_list(self) -> None:
        """Test rules field must be a list."""
        with pytest.raises(ValueError, match="rules.*must be a list"):
            KnowledgeBaseYaml(
                knowledge_base={
                    "version": "1.0",
                    "domain": "security",
                    "description": "Test",
                    "rules": "not_a_list",
                }
            )


# =============================================================================
# Test KnowledgeLoader
# =============================================================================


class TestKnowledgeLoader:
    """Tests for KnowledgeLoader class."""

    def test_loader_initialization(self, temp_knowledge_dir: Path) -> None:
        """Test KnowledgeLoader initialization."""
        loader = KnowledgeLoader(temp_knowledge_dir)

        assert loader._knowledge_dir == temp_knowledge_dir
        assert loader._cache == {}

    def test_loader_default_directory(self) -> None:
        """Test KnowledgeLoader uses default directory."""
        loader = KnowledgeLoader()

        expected_path = Path(__file__).parent.parent.parent.parent / "src" / "bmad_assist" / "deep_verify" / "knowledge" / "data"
        assert "deep_verify/knowledge/data" in str(loader._knowledge_dir)

    def test_loader_repr(self, loader: KnowledgeLoader) -> None:
        """Test KnowledgeLoader repr."""
        repr_str = repr(loader)
        assert "KnowledgeLoader" in repr_str

    def test_load_base_rules_only(self, loader: KnowledgeLoader) -> None:
        """Test loading only base rules."""
        rules = loader.load(domains=None, use_base=True)

        assert len(rules) == 2
        ids = {r.id for r in rules}
        assert "GEN-001" in ids
        assert "GEN-002" in ids

    def test_load_no_base(self, loader: KnowledgeLoader) -> None:
        """Test loading with use_base=False."""
        rules = loader.load(domains=None, use_base=False)

        assert len(rules) == 0

    def test_load_with_security_domain(
        self, loader: KnowledgeLoader
    ) -> None:
        """Test loading base + security domain rules."""
        mock_security = MagicMock()
        mock_security.value = "security"
        rules = loader.load(domains=[mock_security])

        assert len(rules) == 3
        ids = {r.id for r in rules}
        assert "GEN-001" in ids
        assert "GEN-002" in ids
        assert "SEC-001" in ids

    def test_load_with_string_domains(self, loader: KnowledgeLoader) -> None:
        """Test loading with string domain values."""
        # Create a mock domain that has value attribute
        mock_domain = MagicMock()
        mock_domain.value = "security"

        rules = loader.load(domains=[mock_domain])

        assert len(rules) == 3

    def test_load_caching(self, loader: KnowledgeLoader) -> None:
        """Test that loaded rules are cached."""
        # First load
        rules1 = loader.load(domains=None, use_base=True)

        # Check cache
        assert "base" in loader._cache
        assert len(loader._cache["base"]) == 2

        # Second load should use cache
        rules2 = loader.load(domains=None, use_base=True)
        assert rules1 == rules2

    def test_clear_cache(self, loader: KnowledgeLoader) -> None:
        """Test clearing the cache."""
        loader.load(domains=None, use_base=True)
        assert "base" in loader._cache

        loader.clear_cache()
        assert loader._cache == {}

    def test_deduplication(self, temp_knowledge_dir: Path) -> None:
        """Test rule deduplication by ID."""
        # Create a security.yaml that overrides a base rule
        security_data = {
            "knowledge_base": {
                "version": "1.0",
                "domain": "security",
                "description": "Security rules",
                "rules": [
                    {
                        "id": "GEN-001",  # Same ID as base rule
                        "domain": "security",
                        "category": "standards",
                        "title": "Overridden Rule",
                        "description": "Overridden description",
                        "severity": "critical",
                    },
                ],
            }
        }

        with open(temp_knowledge_dir / "security.yaml", "w") as f:
            yaml.dump(security_data, f)

        loader = KnowledgeLoader(temp_knowledge_dir)

        mock_domain = MagicMock()
        mock_domain.value = "security"

        with patch("bmad_assist.deep_verify.knowledge.loader.logger") as mock_logger:
            rules = loader.load(domains=[mock_domain])

            # Should have 2 rules (GEN-002 from base, GEN-001 overridden)
            assert len(rules) == 2

            # Check that override was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "GEN-001" in str(call_args)

    def test_missing_domain_file(self, loader: KnowledgeLoader) -> None:
        """Test loading non-existent domain file."""
        mock_domain = MagicMock()
        mock_domain.value = "nonexistent"

        # Should not raise, just return base rules
        rules = loader.load(domains=[mock_domain], use_base=True)
        assert len(rules) == 2  # Only base rules

    def test_empty_knowledge_base(self, temp_knowledge_dir: Path) -> None:
        """Test loading empty knowledge base file."""
        # Create empty file
        with open(temp_knowledge_dir / "empty.yaml", "w") as f:
            f.write("")

        loader = KnowledgeLoader(temp_knowledge_dir)
        rules = loader._load_knowledge_file("empty")

        assert rules == []

    def test_invalid_yaml(self, temp_knowledge_dir: Path) -> None:
        """Test handling of invalid YAML."""
        # Create invalid YAML
        with open(temp_knowledge_dir / "invalid.yaml", "w") as f:
            f.write("invalid: yaml: [")

        loader = KnowledgeLoader(temp_knowledge_dir)
        rules = loader._load_knowledge_file("invalid")

        assert rules == []

    def test_load_multiple_domains(self, temp_knowledge_dir: Path) -> None:
        """Test loading multiple domain files."""
        # Create storage.yaml
        storage_data = {
            "knowledge_base": {
                "version": "1.0",
                "domain": "storage",
                "description": "Storage rules",
                "rules": [
                    {
                        "id": "DB-001",
                        "domain": "storage",
                        "category": "best_practices",
                        "title": "Storage Rule",
                        "description": "Storage description",
                        "severity": "warning",
                    },
                ],
            }
        }

        with open(temp_knowledge_dir / "storage.yaml", "w") as f:
            yaml.dump(storage_data, f)

        loader = KnowledgeLoader(temp_knowledge_dir)

        mock_security = MagicMock(value="security")
        mock_storage = MagicMock(value="storage")

        rules = loader.load(domains=[mock_security, mock_storage])

        assert len(rules) == 4  # 2 base + 1 security + 1 storage
        ids = {r.id for r in rules}
        assert "GEN-001" in ids
        assert "SEC-001" in ids
        assert "DB-001" in ids

    def test_duplicate_domain_loading(self, temp_knowledge_dir: Path) -> None:
        """Test that duplicate domains are only loaded once."""
        loader = KnowledgeLoader(temp_knowledge_dir)

        mock_security = MagicMock(value="security")

        # Load same domain twice
        rules = loader.load(domains=[mock_security, mock_security])

        # Should still be 3 rules (not 4)
        assert len(rules) == 3

    def test_rule_parsing_error(self, temp_knowledge_dir: Path) -> None:
        """Test handling of rule parsing errors."""
        # Create knowledge base with one valid and one invalid rule
        data = {
            "knowledge_base": {
                "version": "1.0",
                "domain": "test",
                "description": "Test",
                "rules": [
                    {
                        "id": "VALID-001",
                        "domain": "test",
                        "category": "standards",
                        "title": "Valid Rule",
                        "description": "Valid description",
                        "severity": "critical",
                    },
                    {
                        "id": "INVALID-001",
                        "domain": "test",
                        # Missing required fields
                    },
                ],
            }
        }

        with open(temp_knowledge_dir / "test.yaml", "w") as f:
            yaml.dump(data, f)

        loader = KnowledgeLoader(temp_knowledge_dir)
        rules = loader._load_knowledge_file("test")

        # Should only have the valid rule
        assert len(rules) == 1
        assert rules[0].id == "VALID-001"


# =============================================================================
# Test Integration with Real Knowledge Base
# =============================================================================


class TestRealKnowledgeBase:
    """Tests using the actual knowledge base files."""

    def test_load_real_base_yaml(self) -> None:
        """Test loading the actual base.yaml file."""
        loader = KnowledgeLoader()
        rules = loader.load(domains=None, use_base=True)

        # Should have base rules
        assert len(rules) >= 5  # At least 5 rules in base.yaml

        ids = {r.id for r in rules}
        assert "GEN-001" in ids
        assert "GEN-002" in ids

    def test_load_real_security_yaml(self) -> None:
        """Test loading the actual security.yaml file."""
        loader = KnowledgeLoader()

        mock_security = MagicMock(value="security")
        rules = loader.load(domains=[mock_security])

        # Should have base + security rules
        assert len(rules) >= 20  # At least 5 base + 15 security

        ids = {r.id for r in rules}
        # Check OWASP rules exist
        assert "SEC-OWASP-A01" in ids
        assert "SEC-OWASP-A02" in ids
        # Check CWE rules exist
        assert "SEC-CWE-089" in ids

    def test_security_rule_categories(self) -> None:
        """Test that security rules have proper categories."""
        loader = KnowledgeLoader()

        mock_security = MagicMock(value="security")
        rules = loader.load(domains=[mock_security])

        # Find OWASP rules
        owasp_rules = [r for r in rules if r.id.startswith("SEC-OWASP")]
        assert len(owasp_rules) >= 5

        for rule in owasp_rules:
            assert rule.category == KnowledgeCategory.STANDARDS
            assert rule.severity in (Severity.CRITICAL, Severity.ERROR)

    def test_rule_severity_types(self) -> None:
        """Test that all rules have valid severity types."""
        loader = KnowledgeLoader()

        mock_security = MagicMock(value="security")
        rules = loader.load(domains=[mock_security])

        for rule in rules:
            assert isinstance(rule.severity, Severity)
            assert rule.severity in (
                Severity.CRITICAL,
                Severity.ERROR,
                Severity.WARNING,
                Severity.INFO,
            )


# =============================================================================
# Test STORAGE Knowledge Base
# =============================================================================


class TestStorageKnowledgeBase:
    """Tests for STORAGE domain knowledge base."""

    def test_load_storage_yaml(self) -> None:
        """Test loading the actual storage.yaml file."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        # Should have base + storage rules (8 base + 17 storage = 25)
        assert len(rules) >= 20

        storage_rules = [r for r in rules if r.domain == "storage"]
        assert len(storage_rules) == 17

    def test_storage_acid_rules(self) -> None:
        """Test that ACID rules are present and valid."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        acid_rules = [r for r in rules if r.id.startswith("DB-ACID")]
        assert len(acid_rules) == 4

        expected_ids = {"DB-ACID-001", "DB-ACID-002", "DB-ACID-003", "DB-ACID-004"}
        actual_ids = {r.id for r in acid_rules}
        assert actual_ids == expected_ids

    def test_storage_index_rules(self) -> None:
        """Test that indexing rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        index_rules = [r for r in rules if r.id.startswith("DB-INDEX")]
        assert len(index_rules) == 4

    def test_storage_query_rules(self) -> None:
        """Test that query optimization rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        query_rules = [r for r in rules if r.id.startswith("DB-QUERY")]
        assert len(query_rules) == 4

    def test_storage_pool_rules(self) -> None:
        """Test that connection pool rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        pool_rules = [r for r in rules if r.id.startswith("DB-POOL")]
        assert len(pool_rules) == 3

    def test_storage_rule_categories(self) -> None:
        """Test that storage rules have proper categories."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        storage_rules = [r for r in rules if r.domain == "storage"]

        for rule in storage_rules:
            assert rule.category in (
                KnowledgeCategory.STANDARDS,
                KnowledgeCategory.BEST_PRACTICES,
            )

    def test_storage_rule_severities(self) -> None:
        """Test that storage rules have valid severity levels."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        storage_rules = [r for r in rules if r.domain == "storage"]

        for rule in storage_rules:
            assert rule.severity in (
                Severity.CRITICAL,
                Severity.ERROR,
                Severity.WARNING,
                Severity.INFO,
            )

    def test_storage_critical_rules(self) -> None:
        """Test that critical ACID and query rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        # DB-ACID-001, DB-ACID-003, DB-QUERY-003 should be CRITICAL
        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        assert "DB-ACID-001" in critical_ids
        assert "DB-ACID-003" in critical_ids
        assert "DB-QUERY-003" in critical_ids

    def test_storage_references(self) -> None:
        """Test that storage rules have proper references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        storage_rules = [r for r in rules if r.domain == "storage"]

        # Most rules should have references
        rules_with_refs = [r for r in storage_rules if r.references]
        assert len(rules_with_refs) >= 10


# =============================================================================
# Test MESSAGING Knowledge Base
# =============================================================================


class TestMessagingKnowledgeBase:
    """Tests for MESSAGING domain knowledge base."""

    def test_load_messaging_yaml(self) -> None:
        """Test loading the actual messaging.yaml file."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        # Should have base + messaging rules (8 base + 17 messaging = 25)
        assert len(rules) >= 20

        messaging_rules = [r for r in rules if r.domain == "messaging"]
        assert len(messaging_rules) == 17

    def test_messaging_semantics_rules(self) -> None:
        """Test that delivery semantics rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        semantics_rules = [r for r in rules if r.id.startswith("MSG-SEMANTICS")]
        assert len(semantics_rules) == 4

    def test_messaging_ordering_rules(self) -> None:
        """Test that ordering rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        ordering_rules = [r for r in rules if r.id.startswith("MSG-ORDER")]
        assert len(ordering_rules) == 3

    def test_messaging_dlq_rules(self) -> None:
        """Test that DLQ rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        dlq_rules = [r for r in rules if r.id.startswith("MSG-DLQ")]
        assert len(dlq_rules) == 4

    def test_messaging_backoff_rules(self) -> None:
        """Test that backoff rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        backoff_rules = [r for r in rules if r.id.startswith("MSG-BACKOFF")]
        assert len(backoff_rules) == 4

    def test_messaging_rule_categories(self) -> None:
        """Test that messaging rules have proper categories."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        messaging_rules = [r for r in rules if r.domain == "messaging"]

        for rule in messaging_rules:
            assert rule.category in (
                KnowledgeCategory.STANDARDS,
                KnowledgeCategory.BEST_PRACTICES,
            )

    def test_messaging_rule_severities(self) -> None:
        """Test that messaging rules have valid severity levels."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        messaging_rules = [r for r in rules if r.domain == "messaging"]

        for rule in messaging_rules:
            assert rule.severity in (
                Severity.CRITICAL,
                Severity.ERROR,
                Severity.WARNING,
                Severity.INFO,
            )

    def test_messaging_critical_rules(self) -> None:
        """Test that critical messaging rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        # Key messaging rules should be CRITICAL
        assert "MSG-SEMANTICS-001" in critical_ids  # Missing idempotency
        # Note: MSG-BACKOFF-001 is ERROR severity, not CRITICAL

    def test_messaging_references(self) -> None:
        """Test that messaging rules have proper references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        messaging_rules = [r for r in rules if r.domain == "messaging"]

        # Most rules should have references
        rules_with_refs = [r for r in messaging_rules if r.references]
        assert len(rules_with_refs) >= 10


# =============================================================================
# Test Cross-Domain Loading
# =============================================================================


class TestCrossDomainLoading:
    """Tests for loading multiple domain knowledge bases together."""

    def test_load_storage_and_messaging(self) -> None:
        """Test loading STORAGE and MESSAGING domains together."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_storage, mock_messaging])

        # Should have base + storage + messaging (8 + 17 + 17 = 42)
        assert len(rules) == 42

        storage_count = len([r for r in rules if r.domain == "storage"])
        messaging_count = len([r for r in rules if r.domain == "messaging"])
        general_count = len([r for r in rules if r.domain == "general"])

        assert storage_count == 17
        assert messaging_count == 17
        assert general_count == 8

    def test_load_all_domains(self) -> None:
        """Test loading all domain knowledge bases."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        mock_messaging = MagicMock(value="messaging")
        mock_security = MagicMock(value="security")

        rules = loader.load(domains=[mock_storage, mock_messaging, mock_security])

        # Should include rules from all domains
        storage_rules = [r for r in rules if r.domain == "storage"]
        messaging_rules = [r for r in rules if r.domain == "messaging"]
        security_rules = [r for r in rules if r.domain == "security"]

        assert len(storage_rules) == 17
        assert len(messaging_rules) == 17
        assert len(security_rules) >= 15

    def test_no_rule_id_collisions(self) -> None:
        """Test that STORAGE and MESSAGING rules have unique IDs."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_storage, mock_messaging])

        all_ids = [r.id for r in rules]
        unique_ids = set(all_ids)

        assert len(all_ids) == len(unique_ids), f"Duplicate IDs: {[id for id in all_ids if all_ids.count(id) > 1]}"

    def test_storage_prefix_distinct(self) -> None:
        """Test that STORAGE rules use DB- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")
        rules = loader.load(domains=[mock_storage])

        storage_rules = [r for r in rules if r.domain == "storage"]

        for rule in storage_rules:
            assert rule.id.startswith("DB-"), f"Rule {rule.id} does not use DB- prefix"

    def test_messaging_prefix_distinct(self) -> None:
        """Test that MESSAGING rules use MSG- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_messaging = MagicMock(value="messaging")
        rules = loader.load(domains=[mock_messaging])

        messaging_rules = [r for r in rules if r.domain == "messaging"]

        for rule in messaging_rules:
            assert rule.id.startswith("MSG-"), f"Rule {rule.id} does not use MSG- prefix"

    def test_domain_specific_rules_override_base(self) -> None:
        """Test that domain rules can override base rules."""
        # This tests the deduplication behavior
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_storage = MagicMock(value="storage")

        with patch("bmad_assist.deep_verify.knowledge.loader.logger") as mock_logger:
            rules = loader.load(domains=[mock_storage])

            # Check that we have base rules and storage rules
            base_rules = [r for r in rules if r.domain == "general"]
            storage_rules = [r for r in rules if r.domain == "storage"]

            assert len(base_rules) == 8
            assert len(storage_rules) == 17


# =============================================================================
# Test API Knowledge Base
# =============================================================================


class TestApiKnowledgeBase:
    """Tests for API domain knowledge base."""

    def test_load_api_yaml(self) -> None:
        """Test loading the actual api.yaml file."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        # Should have base + api rules (8 base + 17 api = 25)
        assert len(rules) == 25

        api_rules = [r for r in rules if r.domain == "api"]
        assert len(api_rules) == 17

    def test_api_rest_rules(self) -> None:
        """Test that REST rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        rest_rules = [r for r in rules if r.id.startswith("API-REST")]
        assert len(rest_rules) == 4

    def test_api_http_rules(self) -> None:
        """Test that HTTP semantics rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        http_rules = [r for r in rules if r.id.startswith("API-HTTP")]
        assert len(http_rules) == 4

    def test_api_rate_rules(self) -> None:
        """Test that rate limiting rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        rate_rules = [r for r in rules if r.id.startswith("API-RATE")]
        assert len(rate_rules) == 3

    def test_api_idempotency_rules(self) -> None:
        """Test that idempotency rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        idem_rules = [r for r in rules if r.id.startswith("API-IDEMPOTENCY")]
        assert len(idem_rules) == 3

    def test_api_error_rules(self) -> None:
        """Test that error handling rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        error_rules = [r for r in rules if r.id.startswith("API-ERROR")]
        assert len(error_rules) == 3

    def test_api_rule_categories(self) -> None:
        """Test that API rules have proper categories."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        for rule in api_rules:
            assert rule.category in (
                KnowledgeCategory.STANDARDS,
                KnowledgeCategory.BEST_PRACTICES,
            )

    def test_api_critical_rules(self) -> None:
        """Test that critical API rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        assert "API-RATE-001" in critical_ids
        assert "API-IDEMPOTENCY-001" in critical_ids
        assert "API-ERROR-003" in critical_ids


# =============================================================================
# Test CONCURRENCY Knowledge Base
# =============================================================================


class TestConcurrencyKnowledgeBase:
    """Tests for CONCURRENCY domain knowledge base."""

    def test_load_concurrency_yaml(self) -> None:
        """Test loading the actual concurrency.yaml file."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        # Should have base + concurrency rules (8 base + 17 concurrency = 25)
        assert len(rules) == 25

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]
        assert len(concurrency_rules) == 17

    def test_concurrency_pattern_rules(self) -> None:
        """Test that pattern rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        pattern_rules = [r for r in rules if r.id.startswith("CC-PATTERN")]
        assert len(pattern_rules) == 4

    def test_concurrency_mutex_rules(self) -> None:
        """Test that mutex rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        mutex_rules = [r for r in rules if r.id.startswith("CC-MUTEX")]
        assert len(mutex_rules) == 4

    def test_concurrency_channel_rules(self) -> None:
        """Test that channel rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        channel_rules = [r for r in rules if r.id.startswith("CC-CHANNEL")]
        assert len(channel_rules) == 4

    def test_concurrency_context_rules(self) -> None:
        """Test that context rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        context_rules = [r for r in rules if r.id.startswith("CC-CONTEXT")]
        assert len(context_rules) == 3

    def test_concurrency_sync_rules(self) -> None:
        """Test that sync rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        sync_rules = [r for r in rules if r.id.startswith("CC-SYNC")]
        assert len(sync_rules) == 2

    def test_concurrency_rule_categories(self) -> None:
        """Test that CONCURRENCY rules have proper categories."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        for rule in concurrency_rules:
            assert rule.category in (
                KnowledgeCategory.STANDARDS,
                KnowledgeCategory.BEST_PRACTICES,
            )

    def test_concurrency_critical_rules(self) -> None:
        """Test that critical CONCURRENCY rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        assert "CC-PATTERN-001" in critical_ids  # Goroutine leak
        assert "CC-PATTERN-002" in critical_ids  # Unbounded spawn
        assert "CC-MUTEX-002" in critical_ids  # Lock ordering
        assert "CC-MUTEX-004" in critical_ids  # Copying mutex
        assert "CC-CHANNEL-002" in critical_ids  # Closing closed channel
        assert "CC-SYNC-001" in critical_ids  # WaitGroup mismatch


# =============================================================================
# Test Cross-Domain Loading (API + CONCURRENCY)
# =============================================================================


class TestApiConcurrencyCrossDomain:
    """Tests for API + CONCURRENCY cross-domain loading."""

    def test_load_api_and_concurrency(self) -> None:
        """Test loading API and CONCURRENCY domains together."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        # Should have base + api + concurrency (8 + 17 + 17 = 42)
        assert len(rules) == 42

        api_count = len([r for r in rules if r.domain == "api"])
        concurrency_count = len([r for r in rules if r.domain == "concurrency"])
        general_count = len([r for r in rules if r.domain == "general"])

        assert api_count == 17
        assert concurrency_count == 17
        assert general_count == 8

    def test_load_all_six_domains(self) -> None:
        """Test loading all six domain knowledge bases."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        domains = [
            MagicMock(value="api"),
            MagicMock(value="concurrency"),
            MagicMock(value="security"),
            MagicMock(value="storage"),
            MagicMock(value="messaging"),
        ]

        rules = loader.load(domains=domains)

        # Count rules per domain
        counts = {
            "api": len([r for r in rules if r.domain == "api"]),
            "concurrency": len([r for r in rules if r.domain == "concurrency"]),
            "security": len([r for r in rules if r.domain == "security"]),
            "storage": len([r for r in rules if r.domain == "storage"]),
            "messaging": len([r for r in rules if r.domain == "messaging"]),
            "general": len([r for r in rules if r.domain == "general"]),
        }

        assert counts["api"] == 17
        assert counts["concurrency"] == 17
        assert counts["storage"] == 17
        assert counts["messaging"] == 17
        assert counts["security"] >= 15
        assert counts["general"] == 8

    def test_api_concurrency_no_id_collisions(self) -> None:
        """Test that API and CONCURRENCY rules have unique IDs."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        all_ids = [r.id for r in rules]
        unique_ids = set(all_ids)

        assert len(all_ids) == len(unique_ids)

    def test_api_prefix_distinct(self) -> None:
        """Test that API rules use API- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        for rule in api_rules:
            assert rule.id.startswith("API-")

    def test_concurrency_prefix_distinct(self) -> None:
        """Test that CONCURRENCY rules use CC- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        for rule in concurrency_rules:
            assert rule.id.startswith("CC-")


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_artifact_text(self, loader: KnowledgeLoader) -> None:
        """Test loader with empty domains list."""
        rules = loader.load(domains=[], use_base=True)

        # Should still load base rules
        assert len(rules) == 2

    def test_nonexistent_knowledge_dir(self) -> None:
        """Test loader with non-existent directory."""
        loader = KnowledgeLoader(Path("/nonexistent/path"))

        rules = loader.load(domains=None, use_base=True)
        assert rules == []

    def test_knowledge_rule_with_unicode(self) -> None:
        """Test KnowledgeRule with unicode characters."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Unicode Test: 中文",
            description="Description with unicode: café, naïve",
            severity=Severity.CRITICAL,
        )

        assert "中文" in rule.title
        assert "café" in rule.description

    def test_large_number_of_rules(self, temp_knowledge_dir: Path) -> None:
        """Test loader with large number of rules."""
        # Create knowledge base with many rules
        rules_data = []
        for i in range(100):
            rules_data.append({
                "id": f"RULE-{i:03d}",
                "domain": "test",
                "category": "best_practices",
                "title": f"Rule {i}",
                "description": f"Description {i}",
                "severity": "warning",
            })

        data = {
            "knowledge_base": {
                "version": "1.0",
                "domain": "test",
                "description": "Many rules",
                "rules": rules_data,
            }
        }

        with open(temp_knowledge_dir / "many.yaml", "w") as f:
            yaml.dump(data, f)

        loader = KnowledgeLoader(temp_knowledge_dir)
        rules = loader._load_knowledge_file("many")

        assert len(rules) == 100
