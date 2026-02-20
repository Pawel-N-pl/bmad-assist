"""Tests for A/B test LLM analysis report generator.

Tests cover:
- Artifact collection from variant directories
- Prompt building with all artifacts
- File truncation for large files
- Budget estimation
- End-to-end generation with mocked provider
- Graceful handling of empty/missing artifacts
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bmad_assist.experiments.ab.analysis import (
    MAX_FILE_CHARS,
    _ArtifactFile,
    _build_prompt,
    _build_variant_section,
    _collect_variant_artifacts,
    _estimate_chars,
    _read_file_truncated,
    _StoryArtifacts,
    generate_ab_analysis,
)
from bmad_assist.experiments.ab.config import ABTestConfig, ABVariantConfig, StoryRef


def _make_config(**overrides: object) -> ABTestConfig:
    """Build an ABTestConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "test-ab-001",
        "fixture": "minimal",
        "stories": [StoryRef(id="3.1", ref="abc")],
        "phases": ["code-review", "code-review-synthesis"],
        "variant_a": ABVariantConfig(label="baseline", config="c1", patch_set="p1"),
        "variant_b": ABVariantConfig(label="experiment", config="c2", patch_set="p2"),
        "analysis": True,
    }
    defaults.update(overrides)
    return ABTestConfig(**defaults)  # type: ignore[arg-type]


def _setup_variant_dir(base: Path, variant: str, story_id: str) -> None:
    """Create a realistic variant directory structure with sample artifacts."""
    story_dir = base / f"variant-{variant}" / f"story-{story_id}"

    # Mapping file
    cache_dir = story_dir / "bmad-assist" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "code-review-mapping-uuid1.json").write_text(
        '{"mapping": {"Validator A": {"provider": "gemini", "model": "gemini-3"}}}'
    )
    # Non-mapping cache file (should be skipped)
    (cache_dir / "code-reviews-uuid1.json").write_text('{"reviews": []}')

    # Code review artifacts
    reviews_dir = story_dir / "artifacts" / "code-reviews"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "code-review-3-1-a-20260207T212810Z.md").write_text(
        "# Code Review\nFindings: 3 issues found"
    )
    (reviews_dir / "code-review-3-1-b-20260207T212810Z.md").write_text(
        "# Code Review\nFindings: 1 issue found"
    )
    (reviews_dir / "synthesis-3-1-20260207T213515Z.md").write_text(
        "# Synthesis Report\nVerdict: APPROVED"
    )

    # Benchmark files
    bench_dir = story_dir / "artifacts" / "benchmarks" / "2026-02"
    bench_dir.mkdir(parents=True)
    (bench_dir / "eval-3-1-a-20260207T213055Z.yaml").write_text(
        "evaluator:\n  provider: gemini\n  model: gemini-3\nexecution:\n  duration_ms: 12345"
    )


class TestReadFileTruncated:
    """Tests for _read_file_truncated."""

    def test_reads_small_file(self, tmp_path: Path) -> None:
        f = tmp_path / "small.md"
        f.write_text("hello world")
        assert _read_file_truncated(f) == "hello world"

    def test_truncates_large_file(self, tmp_path: Path) -> None:
        f = tmp_path / "large.md"
        content = "x" * (MAX_FILE_CHARS + 1000)
        f.write_text(content)
        result = _read_file_truncated(f)
        assert len(result) < len(content)
        assert "truncated" in result

    def test_returns_empty_for_missing(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.md"
        assert _read_file_truncated(f) == ""


class TestCollectVariantArtifacts:
    """Tests for _collect_variant_artifacts."""

    def test_collects_all_artifact_types(self, tmp_path: Path) -> None:
        _setup_variant_dir(tmp_path, "a", "3.1")
        variant_dir = tmp_path / "variant-a"

        stories = _collect_variant_artifacts(variant_dir)

        assert len(stories) == 1
        story = stories[0]
        assert story.story_id == "3.1"
        assert len(story.mappings) == 1
        assert "mapping" in story.mappings[0].relative_name
        assert len(story.artifacts) == 3  # 2 reviews + 1 synthesis
        assert len(story.benchmarks) == 1

    def test_skips_non_mapping_cache_files(self, tmp_path: Path) -> None:
        _setup_variant_dir(tmp_path, "a", "3.1")
        variant_dir = tmp_path / "variant-a"

        stories = _collect_variant_artifacts(variant_dir)
        # Only mapping file collected, not code-reviews-*.json
        assert len(stories[0].mappings) == 1

    def test_handles_empty_variant_dir(self, tmp_path: Path) -> None:
        variant_dir = tmp_path / "variant-a"
        variant_dir.mkdir(parents=True)
        stories = _collect_variant_artifacts(variant_dir)
        assert stories == []

    def test_handles_multiple_stories(self, tmp_path: Path) -> None:
        _setup_variant_dir(tmp_path, "a", "3.1")
        _setup_variant_dir(tmp_path, "a", "3.2")
        variant_dir = tmp_path / "variant-a"

        stories = _collect_variant_artifacts(variant_dir)
        assert len(stories) == 2
        assert stories[0].story_id == "3.1"
        assert stories[1].story_id == "3.2"

    def test_synthesis_gets_higher_priority(self, tmp_path: Path) -> None:
        _setup_variant_dir(tmp_path, "a", "3.1")
        variant_dir = tmp_path / "variant-a"

        stories = _collect_variant_artifacts(variant_dir)
        synthesis_files = [
            a for a in stories[0].artifacts
            if a.path.name.startswith("synthesis")
        ]
        review_files = [
            a for a in stories[0].artifacts
            if a.path.name.startswith("code-review")
        ]
        assert len(synthesis_files) > 0
        assert len(review_files) > 0
        # Synthesis priority (1) < review priority (2) → synthesis more important
        assert all(s.priority < r.priority for s in synthesis_files for r in review_files)


class TestBuildVariantSection:
    """Tests for _build_variant_section."""

    def test_produces_xml_structure(self) -> None:
        story = _StoryArtifacts(
            story_id="3.1",
            mappings=[
                _ArtifactFile(
                    path=Path("m.json"), relative_name="m.json",
                    content='{"mapping": {}}', priority=0,
                )
            ],
            artifacts=[
                _ArtifactFile(
                    path=Path("r.md"), relative_name="code-reviews/r.md",
                    content="# Review", priority=2,
                )
            ],
            benchmarks=[
                _ArtifactFile(
                    path=Path("b.yaml"), relative_name="benchmarks/b.yaml",
                    content="duration_ms: 123", priority=3,
                )
            ],
        )
        result = _build_variant_section("baseline", [story])
        assert '<variant label="baseline">' in result
        assert '<story id="3.1">' in result
        assert "<mappings>" in result
        assert "<artifacts>" in result
        assert "<benchmarks>" in result
        assert "# Review" in result


class TestEstimateChars:
    """Tests for _estimate_chars."""

    def test_estimates_correctly(self) -> None:
        story = _StoryArtifacts(
            story_id="3.1",
            mappings=[
                _ArtifactFile(
                    path=Path("m.json"), relative_name="m.json",
                    content="x" * 100, priority=0,
                )
            ],
        )
        estimate = _estimate_chars([story])
        # Content (100) + overhead (100) = 200
        assert estimate == 200


class TestBuildPrompt:
    """Tests for _build_prompt."""

    def test_includes_all_sections(self, tmp_path: Path) -> None:
        config = _make_config()

        # Create test-definition and comparison files
        (tmp_path / "test-definition.yaml").write_text("name: test-ab-001\n")
        (tmp_path / "comparison.md").write_text("# Comparison\nDelta: +10%\n")

        story_a = _StoryArtifacts(story_id="3.1")
        story_b = _StoryArtifacts(story_id="3.1")

        prompt = _build_prompt(config, tmp_path, [story_a], [story_b])
        assert "<ab-test-analysis>" in prompt
        assert "<test-definition>" in prompt
        assert "<comparison-summary>" in prompt
        assert '<variant label="baseline">' in prompt
        assert '<variant label="experiment">' in prompt
        assert "<analysis-template>" in prompt
        assert "test-ab-001" in prompt


class TestGenerateAbAnalysis:
    """Tests for generate_ab_analysis end-to-end."""

    def test_writes_analysis_file(self, tmp_path: Path) -> None:
        config = _make_config()

        # Set up directory structure
        _setup_variant_dir(tmp_path, "a", "3.1")
        _setup_variant_dir(tmp_path, "b", "3.1")
        (tmp_path / "test-definition.yaml").write_text("name: test-ab-001\n")
        (tmp_path / "comparison.md").write_text("# Comparison\n")

        mock_result = MagicMock()
        mock_result.stdout = "# Analysis Report\n\nFindings here."
        mock_result.exit_code = 0

        mock_provider = MagicMock()
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = "# Analysis Report\n\nFindings here."

        with patch(
            "bmad_assist.providers.registry.get_provider",
            return_value=mock_provider,
        ):
            result = generate_ab_analysis(config=config, result_dir=tmp_path)

        assert result is not None
        assert result.name == "analysis.md"
        assert result.exists()
        content = result.read_text()
        assert "# Analysis Report" in content
        assert "Findings here." in content

        # Verify provider was called correctly
        mock_provider.invoke.assert_called_once()
        call_kwargs = mock_provider.invoke.call_args
        assert call_kwargs.kwargs["model"] == "opus"
        assert call_kwargs.kwargs["disable_tools"] is True

    def test_returns_none_when_no_artifacts(self, tmp_path: Path) -> None:
        config = _make_config()

        # Create empty variant dirs
        (tmp_path / "variant-a").mkdir(parents=True)
        (tmp_path / "variant-b").mkdir(parents=True)

        result = generate_ab_analysis(config=config, result_dir=tmp_path)
        assert result is None

    def test_returns_none_when_llm_returns_empty(self, tmp_path: Path) -> None:
        config = _make_config()

        _setup_variant_dir(tmp_path, "a", "3.1")
        _setup_variant_dir(tmp_path, "b", "3.1")
        (tmp_path / "test-definition.yaml").write_text("name: test\n")
        (tmp_path / "comparison.md").write_text("# Comp\n")

        mock_provider = MagicMock()
        mock_provider.invoke.return_value = MagicMock()
        mock_provider.parse_output.return_value = ""

        with patch(
            "bmad_assist.providers.registry.get_provider",
            return_value=mock_provider,
        ):
            result = generate_ab_analysis(config=config, result_dir=tmp_path)

        assert result is None

    def test_prompt_contains_artifact_content(self, tmp_path: Path) -> None:
        config = _make_config()

        _setup_variant_dir(tmp_path, "a", "3.1")
        _setup_variant_dir(tmp_path, "b", "3.1")
        (tmp_path / "test-definition.yaml").write_text("name: test\n")
        (tmp_path / "comparison.md").write_text("# Comp\n")

        captured_prompt = {}
        mock_provider = MagicMock()

        def capture_invoke(prompt, **kwargs):
            captured_prompt["text"] = prompt
            result = MagicMock()
            result.stdout = "# Report"
            return result

        mock_provider.invoke.side_effect = capture_invoke
        mock_provider.parse_output.return_value = "# Report"

        with patch(
            "bmad_assist.providers.registry.get_provider",
            return_value=mock_provider,
        ):
            generate_ab_analysis(config=config, result_dir=tmp_path)

        prompt = captured_prompt["text"]
        # Should contain actual artifact content
        assert "3 issues found" in prompt
        assert "APPROVED" in prompt
        assert "gemini" in prompt


class TestAnalysisConfigField:
    """Tests for the analysis field on ABTestConfig."""

    def test_defaults_to_false(self) -> None:
        config = _make_config(analysis=False)
        assert config.analysis is False

    def test_can_be_enabled(self) -> None:
        config = _make_config(analysis=True)
        assert config.analysis is True

    def test_absent_defaults_false(self) -> None:
        config = ABTestConfig(
            name="t",
            fixture="f",
            stories=[StoryRef(id="1.1", ref="abc")],
            phases=["code-review"],
            variant_a=ABVariantConfig(label="a", config="c", patch_set="p"),
            variant_b=ABVariantConfig(label="b", config="c", patch_set="p"),
        )
        assert config.analysis is False
