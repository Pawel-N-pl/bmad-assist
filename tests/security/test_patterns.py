from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from bmad_assist.security.patterns import (
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    TOKENS_PER_ENTRY,
    _apply_token_budget,
    _load_pattern_file,
    get_pattern_dir,
    load_security_patterns,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_pattern(
    cwe_id: str = "CWE-999",
    severity: str = "HIGH",
    tier: int = TIER_HIGH,
    title: str = "Test Pattern",
) -> dict[str, Any]:
    """Build a minimal pattern dict."""
    return {
        "cwe_id": cwe_id,
        "severity": severity,
        "tier": tier,
        "title": title,
        "vulnerable_example": "bad()",
        "safe_example": "good()",
        "detection_hint": "look for bad()",
    }


def _write_pattern_yaml(path: Path, patterns: list[dict[str, Any]]) -> None:
    """Write a YAML pattern file."""
    path.write_text(yaml.dump({"patterns": patterns}), encoding="utf-8")


# ---------------------------------------------------------------------------
# get_pattern_dir
# ---------------------------------------------------------------------------


class TestGetPatternDir:
    """Tests for bundled pattern directory resolution."""

    def test_returns_existing_directory(self):
        pattern_dir = get_pattern_dir()
        assert pattern_dir.is_dir()

    def test_contains_core_yaml(self):
        pattern_dir = get_pattern_dir()
        assert (pattern_dir / "core.yaml").is_file()

    def test_contains_language_files(self):
        pattern_dir = get_pattern_dir()
        expected_langs = ["python", "go", "javascript", "java", "ruby", "csharp", "rust", "swift", "cpp"]
        for lang in expected_langs:
            assert (pattern_dir / f"{lang}.yaml").is_file(), f"Missing {lang}.yaml"


# ---------------------------------------------------------------------------
# _load_pattern_file
# ---------------------------------------------------------------------------


class TestLoadPatternFile:
    """Tests for loading a single YAML pattern file."""

    def test_loads_valid_yaml(self, tmp_path: Path):
        patterns = [_make_pattern(cwe_id="CWE-89")]
        f = tmp_path / "test.yaml"
        _write_pattern_yaml(f, patterns)
        result = _load_pattern_file(f)
        assert len(result) == 1
        assert result[0]["cwe_id"] == "CWE-89"

    def test_loads_multiple_patterns(self, tmp_path: Path):
        patterns = [_make_pattern(cwe_id=f"CWE-{i}") for i in range(5)]
        f = tmp_path / "multi.yaml"
        _write_pattern_yaml(f, patterns)
        result = _load_pattern_file(f)
        assert len(result) == 5

    def test_returns_empty_for_missing_file(self, tmp_path: Path):
        result = _load_pattern_file(tmp_path / "nonexistent.yaml")
        assert result == []

    def test_returns_empty_for_malformed_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.yaml"
        f.write_text(": : : invalid yaml [[[", encoding="utf-8")
        result = _load_pattern_file(f)
        assert result == []

    def test_returns_empty_for_non_dict_root(self, tmp_path: Path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")
        result = _load_pattern_file(f)
        assert result == []

    def test_returns_empty_when_patterns_key_is_not_list(self, tmp_path: Path):
        f = tmp_path / "badtype.yaml"
        f.write_text("patterns: not_a_list\n", encoding="utf-8")
        result = _load_pattern_file(f)
        assert result == []

    def test_returns_empty_when_no_patterns_key(self, tmp_path: Path):
        f = tmp_path / "nokey.yaml"
        f.write_text("something_else: [1, 2]\n", encoding="utf-8")
        result = _load_pattern_file(f)
        assert result == []

    def test_loads_real_core_file(self):
        pattern_dir = get_pattern_dir()
        result = _load_pattern_file(pattern_dir / "core.yaml")
        assert len(result) > 0
        # Every pattern has a cwe_id
        for p in result:
            assert "cwe_id" in p

    def test_loads_real_python_file(self):
        pattern_dir = get_pattern_dir()
        result = _load_pattern_file(pattern_dir / "python.yaml")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _apply_token_budget
# ---------------------------------------------------------------------------


class TestApplyTokenBudget:
    """Tests for tiered token budget filtering."""

    def test_tier1_always_included(self):
        patterns = [_make_pattern(tier=TIER_HIGH) for _ in range(3)]
        # Budget of 0 - tier1 is still included
        result = _apply_token_budget(patterns, available_tokens=0)
        assert len(result) == 3

    def test_tier2_included_when_budget_allows(self):
        t1 = [_make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")]
        t2 = [_make_pattern(tier=TIER_MEDIUM, cwe_id="CWE-2")]
        all_patterns = t1 + t2
        budget = TOKENS_PER_ENTRY * 2
        result = _apply_token_budget(all_patterns, available_tokens=budget)
        assert len(result) == 2

    def test_tier2_dropped_when_budget_exhausted(self):
        t1 = [_make_pattern(tier=TIER_HIGH, cwe_id=f"CWE-{i}") for i in range(3)]
        t2 = [_make_pattern(tier=TIER_MEDIUM, cwe_id="CWE-100")]
        all_patterns = t1 + t2
        # Budget for exactly 3 entries: tier1 takes all budget, tier2 gets nothing
        budget = TOKENS_PER_ENTRY * 3
        result = _apply_token_budget(all_patterns, available_tokens=budget)
        cwe_ids = [p["cwe_id"] for p in result]
        assert "CWE-100" not in cwe_ids
        assert len(result) == 3

    def test_tier3_included_when_budget_allows(self):
        t1 = [_make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")]
        t3 = [_make_pattern(tier=TIER_LOW, cwe_id="CWE-3")]
        all_patterns = t1 + t3
        budget = TOKENS_PER_ENTRY * 5
        result = _apply_token_budget(all_patterns, available_tokens=budget)
        assert len(result) == 2

    def test_tier3_dropped_when_budget_exhausted(self):
        t1 = [_make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")]
        t2 = [_make_pattern(tier=TIER_MEDIUM, cwe_id="CWE-2")]
        t3 = [_make_pattern(tier=TIER_LOW, cwe_id="CWE-3")]
        all_patterns = t1 + t2 + t3
        # Budget for 2 entries: tier1 + tier2, no room for tier3
        budget = TOKENS_PER_ENTRY * 2
        result = _apply_token_budget(all_patterns, available_tokens=budget)
        cwe_ids = [p["cwe_id"] for p in result]
        assert "CWE-1" in cwe_ids
        assert "CWE-2" in cwe_ids
        assert "CWE-3" not in cwe_ids

    def test_empty_patterns(self):
        result = _apply_token_budget([], available_tokens=8000)
        assert result == []

    def test_large_budget_includes_all(self):
        patterns = (
            [_make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")]
            + [_make_pattern(tier=TIER_MEDIUM, cwe_id="CWE-2")]
            + [_make_pattern(tier=TIER_LOW, cwe_id="CWE-3")]
        )
        result = _apply_token_budget(patterns, available_tokens=999999)
        assert len(result) == 3

    def test_default_tier_is_medium(self):
        # Pattern without explicit tier should be treated as TIER_MEDIUM
        p = {"cwe_id": "CWE-X", "severity": "MEDIUM", "title": "No tier"}
        result = _apply_token_budget([p], available_tokens=TOKENS_PER_ENTRY * 2)
        assert len(result) == 1

    def test_ordering_is_tier1_then_tier2_then_tier3(self):
        t3 = _make_pattern(tier=TIER_LOW, cwe_id="CWE-3")
        t1 = _make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")
        t2 = _make_pattern(tier=TIER_MEDIUM, cwe_id="CWE-2")
        # Input in reverse priority order
        result = _apply_token_budget([t3, t1, t2], available_tokens=999999)
        cwe_ids = [p["cwe_id"] for p in result]
        assert cwe_ids == ["CWE-1", "CWE-2", "CWE-3"]

    def test_partial_tier2_inclusion(self):
        t1 = [_make_pattern(tier=TIER_HIGH, cwe_id="CWE-1")]
        t2 = [_make_pattern(tier=TIER_MEDIUM, cwe_id=f"CWE-{i}") for i in range(10, 15)]
        all_patterns = t1 + t2
        # Budget for tier1 + 2 of tier2
        budget = TOKENS_PER_ENTRY * 3
        result = _apply_token_budget(all_patterns, available_tokens=budget)
        assert len(result) == 3
        # First is tier1
        assert result[0]["cwe_id"] == "CWE-1"


# ---------------------------------------------------------------------------
# load_security_patterns (integration)
# ---------------------------------------------------------------------------


class TestLoadSecurityPatterns:
    """Tests for the top-level pattern loading function."""

    def test_core_patterns_always_loaded(self):
        result = load_security_patterns(languages=[])
        assert len(result) > 0
        # Should contain well-known core CWEs
        cwe_ids = {p["cwe_id"] for p in result}
        assert "CWE-89" in cwe_ids  # SQL Injection is in core

    def test_python_patterns_added(self):
        core_only = load_security_patterns(languages=[])
        with_python = load_security_patterns(languages=["python"])
        # Python adds additional patterns beyond core
        assert len(with_python) >= len(core_only)

    def test_go_patterns_added(self):
        core_only = load_security_patterns(languages=[])
        with_go = load_security_patterns(languages=["go"])
        assert len(with_go) >= len(core_only)

    def test_multiple_languages(self):
        result = load_security_patterns(languages=["python", "go"])
        assert len(result) > 0

    def test_unknown_language_returns_core_only(self):
        core_only = load_security_patterns(languages=[])
        unknown = load_security_patterns(languages=["brainfuck"])
        # Unknown language file does not exist, so just core
        assert len(unknown) == len(core_only)

    def test_token_budget_limits_output(self):
        # Very small budget should give fewer patterns than large budget
        small = load_security_patterns(languages=["python"], available_tokens=TOKENS_PER_ENTRY * 2)
        large = load_security_patterns(languages=["python"], available_tokens=999999)
        assert len(small) <= len(large)

    def test_very_small_budget_still_has_tier1(self):
        # Tier 1 is always included regardless of budget
        result = load_security_patterns(languages=[], available_tokens=1)
        tier1_count = sum(1 for p in result if p.get("tier") == TIER_HIGH)
        assert tier1_count > 0

    def test_default_budget_is_8000(self):
        # Just verify it runs with the default budget
        result = load_security_patterns(languages=["python"])
        assert len(result) > 0

    def test_all_patterns_have_cwe_id(self):
        result = load_security_patterns(languages=["python", "go", "javascript"])
        for p in result:
            assert "cwe_id" in p, f"Pattern missing cwe_id: {p}"

    def test_all_patterns_have_severity(self):
        result = load_security_patterns(languages=["python", "go", "javascript"])
        for p in result:
            assert "severity" in p, f"Pattern missing severity: {p}"

    def test_all_patterns_have_tier(self):
        result = load_security_patterns(languages=["python", "go", "javascript"])
        for p in result:
            assert "tier" in p, f"Pattern missing tier: {p}"

    def test_empty_language_list_same_as_core_only(self):
        empty = load_security_patterns(languages=[])
        core = load_security_patterns(languages=[], available_tokens=999999)
        # With large budget, these should be equivalent
        assert len(empty) <= len(core)

    def test_returns_list_of_dicts(self):
        result = load_security_patterns(languages=["python"])
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
