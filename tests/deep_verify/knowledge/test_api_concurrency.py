"""Tests for API and CONCURRENCY domain knowledge bases.

This module provides comprehensive test coverage for the API and CONCURRENCY
domain knowledge bases, including rule loading, validation, and cross-domain
integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from bmad_assist.deep_verify.core.types import Severity
from bmad_assist.deep_verify.knowledge import KnowledgeCategory, KnowledgeLoader

if TYPE_CHECKING:
    pass


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
        assert len(rules) >= 20

        api_rules = [r for r in rules if r.domain == "api"]
        assert len(api_rules) == 17

    def test_api_rest_rules(self) -> None:
        """Test that REST rules are present and valid."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        rest_rules = [r for r in rules if r.id.startswith("API-REST")]
        assert len(rest_rules) == 4

        expected_ids = {"API-REST-001", "API-REST-002", "API-REST-003", "API-REST-004"}
        actual_ids = {r.id for r in rest_rules}
        assert actual_ids == expected_ids

    def test_api_http_rules(self) -> None:
        """Test that HTTP semantics rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        http_rules = [r for r in rules if r.id.startswith("API-HTTP")]
        assert len(http_rules) == 4

        expected_ids = {"API-HTTP-001", "API-HTTP-002", "API-HTTP-003", "API-HTTP-004"}
        actual_ids = {r.id for r in http_rules}
        assert actual_ids == expected_ids

    def test_api_rate_rules(self) -> None:
        """Test that rate limiting rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        rate_rules = [r for r in rules if r.id.startswith("API-RATE")]
        assert len(rate_rules) == 3

        expected_ids = {"API-RATE-001", "API-RATE-002", "API-RATE-003"}
        actual_ids = {r.id for r in rate_rules}
        assert actual_ids == expected_ids

    def test_api_idempotency_rules(self) -> None:
        """Test that idempotency rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        idem_rules = [r for r in rules if r.id.startswith("API-IDEMPOTENCY")]
        assert len(idem_rules) == 3

        expected_ids = {
            "API-IDEMPOTENCY-001",
            "API-IDEMPOTENCY-002",
            "API-IDEMPOTENCY-003",
        }
        actual_ids = {r.id for r in idem_rules}
        assert actual_ids == expected_ids

    def test_api_error_rules(self) -> None:
        """Test that error handling rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        error_rules = [r for r in rules if r.id.startswith("API-ERROR")]
        assert len(error_rules) == 3

        expected_ids = {"API-ERROR-001", "API-ERROR-002", "API-ERROR-003"}
        actual_ids = {r.id for r in error_rules}
        assert actual_ids == expected_ids

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
            ), f"Rule {rule.id} has unexpected category {rule.category}"

    def test_api_rule_severities(self) -> None:
        """Test that API rules have valid severity levels."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        for rule in api_rules:
            assert rule.severity in (
                Severity.CRITICAL,
                Severity.ERROR,
                Severity.WARNING,
                Severity.INFO,
            ), f"Rule {rule.id} has invalid severity {rule.severity}"

    def test_api_critical_rules(self) -> None:
        """Test that critical API rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        # Key API rules should be CRITICAL
        assert "API-RATE-001" in critical_ids  # Missing rate limiting
        assert "API-IDEMPOTENCY-001" in critical_ids  # Unsafe method assumed safe
        assert "API-ERROR-003" in critical_ids  # Internal details leakage

    def test_api_references(self) -> None:
        """Test that API rules have proper references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        # Most rules should have references
        rules_with_refs = [r for r in api_rules if r.references]
        assert len(rules_with_refs) >= 10

    def test_api_standards_rules_have_references(self) -> None:
        """Test that STANDARDS category API rules have references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        standards_rules = [
            r for r in rules if r.domain == "api" and r.category == KnowledgeCategory.STANDARDS
        ]

        for rule in standards_rules:
            assert len(rule.references) > 0, f"STANDARDS rule {rule.id} should have references"


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
        assert len(rules) >= 20

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

        expected_ids = {
            "CC-PATTERN-001",
            "CC-PATTERN-002",
            "CC-PATTERN-003",
            "CC-PATTERN-004",
        }
        actual_ids = {r.id for r in pattern_rules}
        assert actual_ids == expected_ids

    def test_concurrency_mutex_rules(self) -> None:
        """Test that mutex rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        mutex_rules = [r for r in rules if r.id.startswith("CC-MUTEX")]
        assert len(mutex_rules) == 4

        expected_ids = {"CC-MUTEX-001", "CC-MUTEX-002", "CC-MUTEX-003", "CC-MUTEX-004"}
        actual_ids = {r.id for r in mutex_rules}
        assert actual_ids == expected_ids

    def test_concurrency_channel_rules(self) -> None:
        """Test that channel rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        channel_rules = [r for r in rules if r.id.startswith("CC-CHANNEL")]
        assert len(channel_rules) == 4

        expected_ids = {
            "CC-CHANNEL-001",
            "CC-CHANNEL-002",
            "CC-CHANNEL-003",
            "CC-CHANNEL-004",
        }
        actual_ids = {r.id for r in channel_rules}
        assert actual_ids == expected_ids

    def test_concurrency_context_rules(self) -> None:
        """Test that context rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        context_rules = [r for r in rules if r.id.startswith("CC-CONTEXT")]
        assert len(context_rules) == 3

        expected_ids = {"CC-CONTEXT-001", "CC-CONTEXT-002", "CC-CONTEXT-003"}
        actual_ids = {r.id for r in context_rules}
        assert actual_ids == expected_ids

    def test_concurrency_sync_rules(self) -> None:
        """Test that sync rules are present."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        sync_rules = [r for r in rules if r.id.startswith("CC-SYNC")]
        assert len(sync_rules) == 2

        expected_ids = {"CC-SYNC-001", "CC-SYNC-002"}
        actual_ids = {r.id for r in sync_rules}
        assert actual_ids == expected_ids

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
            ), f"Rule {rule.id} has unexpected category {rule.category}"

    def test_concurrency_rule_severities(self) -> None:
        """Test that CONCURRENCY rules have valid severity levels."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        for rule in concurrency_rules:
            assert rule.severity in (
                Severity.CRITICAL,
                Severity.ERROR,
                Severity.WARNING,
                Severity.INFO,
            ), f"Rule {rule.id} has invalid severity {rule.severity}"

    def test_concurrency_critical_rules(self) -> None:
        """Test that critical CONCURRENCY rules are marked critical."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        critical_rules = [r for r in rules if r.severity == Severity.CRITICAL]
        critical_ids = {r.id for r in critical_rules}

        # Key concurrency rules should be CRITICAL
        assert "CC-PATTERN-001" in critical_ids  # Goroutine leak
        assert "CC-PATTERN-002" in critical_ids  # Unbounded goroutine spawn
        assert "CC-MUTEX-002" in critical_ids  # Lock ordering violation
        assert "CC-MUTEX-004" in critical_ids  # Copying mutex
        assert "CC-CHANNEL-002" in critical_ids  # Closing closed channel
        assert "CC-SYNC-001" in critical_ids  # WaitGroup counter mismatch

    def test_concurrency_references(self) -> None:
        """Test that CONCURRENCY rules have proper references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        # Most rules should have references
        rules_with_refs = [r for r in concurrency_rules if r.references]
        assert len(rules_with_refs) >= 10

    def test_concurrency_standards_rules_have_references(self) -> None:
        """Test that STANDARDS category CONCURRENCY rules have references."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        standards_rules = [
            r
            for r in rules
            if r.domain == "concurrency" and r.category == KnowledgeCategory.STANDARDS
        ]

        for rule in standards_rules:
            assert (
                len(rule.references) > 0
            ), f"STANDARDS rule {rule.id} should have references"


# =============================================================================
# Test Cross-Domain Integration
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

    def test_load_all_domains(self) -> None:
        """Test loading all domain knowledge bases."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        mock_security = MagicMock(value="security")

        rules = loader.load(domains=[mock_api, mock_concurrency, mock_security])

        # Should include rules from all domains
        api_rules = [r for r in rules if r.domain == "api"]
        concurrency_rules = [r for r in rules if r.domain == "concurrency"]
        security_rules = [r for r in rules if r.domain == "security"]

        assert len(api_rules) == 17
        assert len(concurrency_rules) == 17
        assert len(security_rules) >= 15

    def test_no_rule_id_collisions(self) -> None:
        """Test that API and CONCURRENCY rules have unique IDs."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        all_ids = [r.id for r in rules]
        unique_ids = set(all_ids)

        assert len(all_ids) == len(
            unique_ids
        ), f"Duplicate IDs: {[id for id in all_ids if all_ids.count(id) > 1]}"

    def test_api_prefix_distinct(self) -> None:
        """Test that API rules use API- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        for rule in api_rules:
            assert rule.id.startswith(
                "API-"
            ), f"Rule {rule.id} does not use API- prefix"

    def test_concurrency_prefix_distinct(self) -> None:
        """Test that CONCURRENCY rules use CC- prefix."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        for rule in concurrency_rules:
            assert rule.id.startswith(
                "CC-"
            ), f"Rule {rule.id} does not use CC- prefix"

    def test_prefixes_no_overlap(self) -> None:
        """Test that API-* and CC-* prefixes don't overlap with other domains."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        mock_security = MagicMock(value="security")
        mock_storage = MagicMock(value="storage")
        mock_messaging = MagicMock(value="messaging")

        rules = loader.load(
            domains=[mock_api, mock_concurrency, mock_security, mock_storage, mock_messaging]
        )

        api_ids = {r.id for r in rules if r.id.startswith("API-")}
        cc_ids = {r.id for r in rules if r.id.startswith("CC-")}
        sec_ids = {r.id for r in rules if r.id.startswith("SEC-")}
        db_ids = {r.id for r in rules if r.id.startswith("DB-")}
        msg_ids = {r.id for r in rules if r.id.startswith("MSG-")}
        gen_ids = {r.id for r in rules if r.id.startswith("GEN-")}

        # All sets should be disjoint
        assert not (api_ids & cc_ids), "API and CC prefixes overlap"
        assert not (api_ids & sec_ids), "API and SEC prefixes overlap"
        assert not (api_ids & db_ids), "API and DB prefixes overlap"
        assert not (api_ids & msg_ids), "API and MSG prefixes overlap"
        assert not (cc_ids & sec_ids), "CC and SEC prefixes overlap"
        assert not (cc_ids & db_ids), "CC and DB prefixes overlap"
        assert not (cc_ids & msg_ids), "CC and MSG prefixes overlap"

        # Each domain should have expected number of rules
        assert len(api_ids) == 17
        assert len(cc_ids) == 17
        assert len(sec_ids) >= 15
        assert len(db_ids) == 17
        assert len(msg_ids) == 17
        assert len(gen_ids) == 8

    def test_rule_ids_follow_pattern(self) -> None:
        """Test that rule IDs follow the expected patterns."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        api_rules = [r for r in rules if r.domain == "api"]
        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        # API rules: API-CATEGORY-NNN
        for rule in api_rules:
            parts = rule.id.split("-")
            assert len(parts) == 3, f"API rule {rule.id} doesn't follow API-CATEGORY-NNN"
            assert parts[0] == "API"
            assert parts[2].isdigit()

        # CC rules: CC-CATEGORY-NNN
        for rule in concurrency_rules:
            parts = rule.id.split("-")
            assert len(parts) == 3, f"CC rule {rule.id} doesn't follow CC-CATEGORY-NNN"
            assert parts[0] == "CC"
            assert parts[2].isdigit()


# =============================================================================
# Test Integration with Real Knowledge Base
# =============================================================================


class TestApiConcurrencyIntegration:
    """Integration tests for API and CONCURRENCY with real files."""

    def test_api_yaml_validates_with_pydantic(self) -> None:
        """Test that api.yaml passes Pydantic validation."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        # This will validate the YAML structure using Pydantic models
        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        # Verify all API rules are properly parsed
        assert len(api_rules) == 17

        for rule in api_rules:
            assert rule.id
            assert rule.domain == "api"
            assert rule.title
            assert rule.description
            assert rule.category
            assert rule.severity

    def test_concurrency_yaml_validates_with_pydantic(self) -> None:
        """Test that concurrency.yaml passes Pydantic validation."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        # Verify all CONCURRENCY rules are properly parsed
        assert len(concurrency_rules) == 17

        for rule in concurrency_rules:
            assert rule.id
            assert rule.domain == "concurrency"
            assert rule.title
            assert rule.description
            assert rule.category
            assert rule.severity

    def test_severity_conversion_from_string(self) -> None:
        """Test that severity strings are properly converted to enums."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        domain_rules = [r for r in rules if r.domain in ("api", "concurrency")]

        for rule in domain_rules:
            assert isinstance(
                rule.severity, Severity
            ), f"Rule {rule.id} severity is not a Severity enum"

    def test_category_conversion_from_string(self) -> None:
        """Test that category strings are properly converted to enums."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_api, mock_concurrency])

        domain_rules = [r for r in rules if r.domain in ("api", "concurrency")]

        for rule in domain_rules:
            assert isinstance(
                rule.category, KnowledgeCategory
            ), f"Rule {rule.id} category is not a KnowledgeCategory enum"

    def test_combined_loading_with_other_domains(self) -> None:
        """Test combining API and CONCURRENCY with all other domains."""
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
            "general": len([r for r in rules if r.domain == "general"]),
            "api": len([r for r in rules if r.domain == "api"]),
            "concurrency": len([r for r in rules if r.domain == "concurrency"]),
            "security": len([r for r in rules if r.domain == "security"]),
            "storage": len([r for r in rules if r.domain == "storage"]),
            "messaging": len([r for r in rules if r.domain == "messaging"]),
        }

        assert counts["general"] == 8
        assert counts["api"] == 17
        assert counts["concurrency"] == 17
        assert counts["security"] >= 15
        assert counts["storage"] == 17
        assert counts["messaging"] == 17

        # Total should be 8 + 17 + 17 + N + 17 + 17 (where N >= 15)
        assert len(rules) >= 8 + 17 + 17 + 15 + 17 + 17


# =============================================================================
# Test Rule Descriptions
# =============================================================================


class TestRuleDescriptions:
    """Tests for rule descriptions and content."""

    def test_api_rules_have_meaningful_descriptions(self) -> None:
        """Test that API rules have meaningful descriptions."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        for rule in api_rules:
            assert len(rule.description) > 50, f"Rule {rule.id} description is too short"
            assert "\n" in rule.description or " " in rule.description

    def test_concurrency_rules_have_meaningful_descriptions(self) -> None:
        """Test that CONCURRENCY rules have meaningful descriptions."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        for rule in concurrency_rules:
            assert len(rule.description) > 50, f"Rule {rule.id} description is too short"
            assert "\n" in rule.description or " " in rule.description

    def test_api_rules_have_code_examples(self) -> None:
        """Test that many API rules include code examples."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        api_rules = [r for r in rules if r.domain == "api"]

        # Count rules with code blocks (triple backticks or single backticks)
        rules_with_code = [r for r in api_rules if "```" in r.description or "`" in r.description]

        # At least 20% of rules should have code examples
        assert len(rules_with_code) >= len(api_rules) * 0.2

    def test_concurrency_rules_have_code_examples(self) -> None:
        """Test that many CONCURRENCY rules include code examples."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        concurrency_rules = [r for r in rules if r.domain == "concurrency"]

        # Count rules with code blocks
        rules_with_code = [
            r for r in concurrency_rules if "```" in r.description or "`" in r.description
        ]

        # At least 80% of rules should have code examples
        assert len(rules_with_code) >= len(concurrency_rules) * 0.8


# =============================================================================
# Test Deduplication Behavior
# =============================================================================


class TestDeduplicationBehavior:
    """Tests for rule deduplication behavior."""

    def test_api_does_not_override_base(self) -> None:
        """Test that API rules don't override base rules (no ID collision)."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        rules = loader.load(domains=[mock_api])

        # Get all rule IDs
        ids = [r.id for r in rules]

        # Should have both base rules (GEN-*) and API rules (API-*)
        gen_rules = [r for r in rules if r.id.startswith("GEN-")]
        api_rules = [r for r in rules if r.id.startswith("API-")]

        assert len(gen_rules) == 8
        assert len(api_rules) == 17

        # No duplicates
        assert len(ids) == len(set(ids))

    def test_concurrency_does_not_override_base(self) -> None:
        """Test that CONCURRENCY rules don't override base rules."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_concurrency = MagicMock(value="concurrency")
        rules = loader.load(domains=[mock_concurrency])

        gen_rules = [r for r in rules if r.id.startswith("GEN-")]
        cc_rules = [r for r in rules if r.id.startswith("CC-")]

        assert len(gen_rules) == 8
        assert len(cc_rules) == 17

    def test_api_and_concurrency_together_no_override(self) -> None:
        """Test that API and CONCURRENCY rules don't override each other."""
        loader = KnowledgeLoader()
        loader.clear_cache()

        mock_api = MagicMock(value="api")
        mock_concurrency = MagicMock(value="concurrency")

        with patch("bmad_assist.deep_verify.knowledge.loader.logger") as mock_logger:
            rules = loader.load(domains=[mock_api, mock_concurrency])

            # Should have no override warnings
            for call in mock_logger.warning.call_args_list:
                assert "override" not in str(call).lower()

        api_rules = [r for r in rules if r.id.startswith("API-")]
        cc_rules = [r for r in rules if r.id.startswith("CC-")]
        gen_rules = [r for r in rules if r.id.startswith("GEN-")]

        assert len(api_rules) == 17
        assert len(cc_rules) == 17
        assert len(gen_rules) == 8
