"""Tests for _deep_merge helper function.

Part of Story 1.4 tests for project configuration override.
Tests the deep merge functionality used for combining global and project configs.

Extracted from test_config.py as part of Story 1.8 (Test Suite Refactoring).
"""

from bmad_assist.core.config import _deep_merge


class TestDeepMergeScalars:
    """Tests for _deep_merge with scalar values."""

    def test_scalar_override(self) -> None:
        """Override scalar values replace base values."""
        base = {"timeout": 300, "retries": 3}
        override = {"timeout": 600}
        result = _deep_merge(base, override)
        assert result["timeout"] == 600
        assert result["retries"] == 3

    def test_base_keys_preserved(self) -> None:
        """Keys only in base are preserved."""
        base = {"key1": "value1", "key2": "value2"}
        override = {"key3": "value3"}
        result = _deep_merge(base, override)
        assert result["key1"] == "value1"
        assert result["key2"] == "value2"
        assert result["key3"] == "value3"

    def test_override_keys_added(self) -> None:
        """Keys only in override are added."""
        base = {"existing": "value"}
        override = {"new_key": "new_value"}
        result = _deep_merge(base, override)
        assert result["existing"] == "value"
        assert result["new_key"] == "new_value"

    def test_base_not_modified(self) -> None:
        """Original base dict is not modified."""
        base = {"key": "original"}
        override = {"key": "override"}
        _deep_merge(base, override)
        assert base["key"] == "original"

    def test_override_not_modified(self) -> None:
        """Original override dict is not modified."""
        base = {"key": "base"}
        override = {"key": "override"}
        _deep_merge(base, override)
        assert override["key"] == "override"

    def test_base_list_not_mutated(self) -> None:
        """Lists in result are deep copied, not shared with base."""
        base = {"items": [{"name": "foo"}]}
        override = {"other": "value"}
        result = _deep_merge(base, override)

        # Mutate result
        result["items"].append({"name": "bar"})

        # Base should be unchanged
        assert len(base["items"]) == 1
        assert base["items"][0]["name"] == "foo"

    def test_override_list_not_mutated(self) -> None:
        """Lists from override are deep copied, not shared with result."""
        base = {"other": "value"}
        override = {"items": [{"name": "foo"}]}
        result = _deep_merge(base, override)

        # Mutate result
        result["items"].append({"name": "bar"})

        # Override should be unchanged
        assert len(override["items"]) == 1
        assert override["items"][0]["name"] == "foo"


class TestDeepMergeNestedDicts:
    """Tests for _deep_merge with nested dictionaries."""

    def test_nested_dict_merge(self) -> None:
        """Nested dicts are merged recursively."""
        base = {"providers": {"master": {"provider": "claude", "model": "opus_4"}}}
        override = {"providers": {"master": {"model": "sonnet_4"}}}
        result = _deep_merge(base, override)
        assert result["providers"]["master"]["provider"] == "claude"
        assert result["providers"]["master"]["model"] == "sonnet_4"

    def test_deeply_nested_merge(self) -> None:
        """Multiple levels of nesting are merged correctly."""
        base = {"a": {"b": {"c": {"d": "base_value"}}}}
        override = {"a": {"b": {"c": {"e": "new_value"}}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"]["d"] == "base_value"
        assert result["a"]["b"]["c"]["e"] == "new_value"

    def test_partial_nested_override(self) -> None:
        """Partial override of nested structure preserves non-overridden keys."""
        base = {
            "providers": {"master": {"provider": "claude", "model": "opus_4", "settings": "/path"}}
        }
        override = {"providers": {"master": {"model": "sonnet_4"}}}
        result = _deep_merge(base, override)
        assert result["providers"]["master"]["provider"] == "claude"
        assert result["providers"]["master"]["model"] == "sonnet_4"
        assert result["providers"]["master"]["settings"] == "/path"


class TestDeepMergeLists:
    """Tests for _deep_merge with lists (AC7: List replacement)."""

    def test_list_replacement(self) -> None:
        """Lists are replaced, not merged."""
        base = {"multi": [{"provider": "gemini"}]}
        override = {"multi": [{"provider": "codex"}]}
        result = _deep_merge(base, override)
        assert len(result["multi"]) == 1
        assert result["multi"][0]["provider"] == "codex"

    def test_list_replaced_not_appended(self) -> None:
        """Override list completely replaces base list."""
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = _deep_merge(base, override)
        assert result["items"] == [4, 5]

    def test_nested_list_replacement(self) -> None:
        """Lists in nested dicts are also replaced."""
        base = {"providers": {"multi": [{"provider": "gemini"}, {"provider": "claude"}]}}
        override = {"providers": {"multi": [{"provider": "codex"}]}}
        result = _deep_merge(base, override)
        assert len(result["providers"]["multi"]) == 1
        assert result["providers"]["multi"][0]["provider"] == "codex"

    def test_empty_list_replaces_non_empty(self) -> None:
        """Empty list in override replaces non-empty list in base."""
        base = {"items": [1, 2, 3]}
        override = {"items": []}
        result = _deep_merge(base, override)
        assert result["items"] == []


class TestDeepMergeShallowKeys:
    """Tests for _deep_merge with _SHALLOW_MERGE_KEYS (phase_models)."""

    def test_phase_models_entries_replaced_not_merged(self) -> None:
        """phase_models children are replaced atomically, not deep-merged.

        When CWD has phase_models.validate_story_synthesis with model_name/settings
        and project overrides the same phase with different provider/model,
        the CWD-only fields (model_name, settings) must NOT leak through.
        """
        base = {
            "phase_models": {
                "validate_story_synthesis": {
                    "provider": "claude",
                    "model": "sonnet",
                    "model_name": "glm-4.7",
                    "settings": "~/.claude/glm.json",
                },
            }
        }
        override = {
            "phase_models": {
                "validate_story_synthesis": {
                    "provider": "kimi",
                    "model": "kimi-code/kimi-for-coding",
                    "thinking": True,
                },
            }
        }
        result = _deep_merge(base, override)
        vss = result["phase_models"]["validate_story_synthesis"]
        assert vss["provider"] == "kimi"
        assert vss["model"] == "kimi-code/kimi-for-coding"
        assert vss.get("thinking") is True
        # CWD-only fields must NOT leak through
        assert "model_name" not in vss
        assert "settings" not in vss

    def test_phase_models_phases_from_both_sources_preserved(self) -> None:
        """Phases defined only in base are preserved (shallow merge, not replace)."""
        base = {
            "phase_models": {
                "create_story": {"provider": "claude", "model": "opus"},
                "dev_story": {"provider": "claude", "model": "opus"},
            }
        }
        override = {
            "phase_models": {
                "create_story": {"provider": "gemini", "model": "flash"},
            }
        }
        result = _deep_merge(base, override)
        # Override wins for create_story
        assert result["phase_models"]["create_story"]["provider"] == "gemini"
        # dev_story from base is preserved
        assert result["phase_models"]["dev_story"]["provider"] == "claude"

    def test_phase_models_base_not_mutated(self) -> None:
        """Base phase_models dict is not mutated by shallow merge."""
        base = {
            "phase_models": {
                "create_story": {"provider": "claude", "model": "opus"},
            }
        }
        override = {
            "phase_models": {
                "create_story": {"provider": "kimi", "model": "kimi-for-coding"},
            }
        }
        _deep_merge(base, override)
        assert base["phase_models"]["create_story"]["provider"] == "claude"


class TestDeepMergeEdgeCases:
    """Edge cases for _deep_merge."""

    def test_empty_base(self) -> None:
        """Empty base gets all keys from override."""
        base: dict[str, object] = {}
        override = {"key": "value"}
        result = _deep_merge(base, override)
        assert result == {"key": "value"}

    def test_empty_override(self) -> None:
        """Empty override preserves all base keys."""
        base = {"key": "value"}
        override: dict[str, object] = {}
        result = _deep_merge(base, override)
        assert result == {"key": "value"}

    def test_both_empty(self) -> None:
        """Both empty returns empty dict."""
        base: dict[str, object] = {}
        override: dict[str, object] = {}
        result = _deep_merge(base, override)
        assert result == {}

    def test_dict_replaces_non_dict(self) -> None:
        """Dict in override replaces non-dict value in base."""
        base = {"key": "string_value"}
        override = {"key": {"nested": "value"}}
        result = _deep_merge(base, override)
        assert result["key"] == {"nested": "value"}

    def test_non_dict_replaces_dict(self) -> None:
        """Non-dict in override replaces dict in base."""
        base = {"key": {"nested": "value"}}
        override = {"key": "string_value"}
        result = _deep_merge(base, override)
        assert result["key"] == "string_value"
