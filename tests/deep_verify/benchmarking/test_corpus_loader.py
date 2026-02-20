"""Tests for corpus loading and validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from bmad_assist.deep_verify.metrics.corpus_loader import (
    ArtifactLabel,
    CorpusLoader,
    CorpusManifest,
)


class TestCorpusLoader:
    """Tests for CorpusLoader functionality."""

    def test_default_corpus_path(self) -> None:
        """Test that default corpus path is set correctly."""
        loader = CorpusLoader()
        # Should point to tests/deep_verify/corpus
        assert "tests/deep_verify/corpus" in str(loader.corpus_path)

    def test_custom_corpus_path(self) -> None:
        """Test custom corpus path."""
        custom_path = Path("/tmp/test_corpus")
        loader = CorpusLoader(custom_path)
        assert loader.corpus_path == custom_path

    def test_load_all_labels(self) -> None:
        """Test loading all labels from corpus."""
        loader = CorpusLoader()
        labels = loader.load_all_labels()

        # Should load all valid labels
        assert len(labels) > 0

        # All labels should have artifact_id
        for label in labels:
            assert label.artifact_id is not None
            assert label.artifact_type in ["code", "spec"]

    def test_load_all_golden_cases(self) -> None:
        """Test loading all golden cases."""
        loader = CorpusLoader()
        cases = loader.load_all_golden_cases()

        # Should load golden cases
        assert len(cases) > 0

        # All cases should have artifact_id and expected_verdict
        for case in cases:
            assert case.artifact_id is not None
            assert case.expected_verdict is not None

    def test_generate_manifest(self) -> None:
        """Test manifest generation."""
        loader = CorpusLoader()
        manifest = loader.generate_manifest()

        assert manifest.artifact_count > 0
        assert manifest.version == "1.0.0"
        assert manifest.created_at is not None

    def test_manifest_save_and_load(self) -> None:
        """Test saving and loading manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_path = Path(tmpdir)
            (corpus_path / "labels").mkdir(parents=True)
            (corpus_path / "artifacts").mkdir(parents=True)

            # Create a test label
            label_data = {
                "artifact_id": "test-001",
                "source": "test",
                "artifact_type": "code",
                "language": "python",
                "content_file": "artifacts/test.py",
                "expected_domains": [],
                "expected_findings": [],
                "known_false_positives": [],
                "metadata": {"lines_of_code": 10},
            }

            with open(corpus_path / "labels" / "test-001.yaml", "w") as f:
                yaml.dump(label_data, f)

            # Create dummy artifact
            (corpus_path / "artifacts" / "test.py").write_text("# test")

            # Generate and save manifest
            loader = CorpusLoader(corpus_path)
            manifest = loader.generate_manifest()
            loader.save_manifest(manifest)

            # Load manifest
            loaded = loader.load_manifest()
            assert loaded is not None
            assert loaded.artifact_count == manifest.artifact_count


class TestArtifactLabel:
    """Tests for ArtifactLabel dataclass."""

    def test_content_path_property(self) -> None:
        """Test content_path property returns Path."""
        from bmad_assist.deep_verify.metrics.corpus_loader import (
            ArtifactMetadata,
        )

        label = ArtifactLabel(
            artifact_id="test",
            source="test",
            artifact_type="code",
            language="python",
            content_file="artifacts/test.py",
            expected_domains=[],
            expected_findings=[],
            known_false_positives=[],
            metadata=ArtifactMetadata(),
        )

        assert isinstance(label.content_path, Path)
        assert str(label.content_path) == "artifacts/test.py"


class TestManifestVersioning:
    """Tests for manifest versioning."""

    def test_manifest_version_format(self) -> None:
        """Test manifest version is semver format."""
        manifest = CorpusManifest(version="1.0.0")
        assert manifest.version == "1.0.0"

    def test_manifest_timestamp_auto(self) -> None:
        """Test manifest auto-generates timestamp."""
        manifest = CorpusManifest()
        assert manifest.created_at is not None
        assert len(manifest.created_at) > 0

    def test_manifest_checksums(self) -> None:
        """Test manifest checksums dict."""
        manifest = CorpusManifest(
            checksums={"dv-001": "abc123", "dv-002": "def456"}
        )
        assert manifest.checksums["dv-001"] == "abc123"
        assert len(manifest.checksums) == 2
