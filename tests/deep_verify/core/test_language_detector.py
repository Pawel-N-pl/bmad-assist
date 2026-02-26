"""Unit tests for LanguageDetector.

This module provides comprehensive test coverage for the LanguageDetector class,
including extension detection, shebang detection, heuristic detection, and
the fallback chain behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bmad_assist.deep_verify.core.language_detector import (
    EXTENSION_MAP,
    HEURISTIC_PATTERNS,
    SHEBANG_PATTERNS,
    TEST_PATTERNS,
    LanguageDetector,
    LanguageInfo,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def detector():
    """Create LanguageDetector with default settings."""
    return LanguageDetector()


@pytest.fixture
def detector_no_cache():
    """Create LanguageDetector with caching disabled."""
    return LanguageDetector(cache_enabled=False)


# =============================================================================
# LanguageInfo Dataclass Tests (AC-1)
# =============================================================================


class TestLanguageInfo:
    """Tests for LanguageInfo dataclass."""

    def test_basic_creation(self):
        """Should create LanguageInfo with all fields."""
        info = LanguageInfo(
            language="python",
            confidence=0.95,
            file_type="source",
            detection_method="extension",
        )
        assert info.language == "python"
        assert info.confidence == 0.95
        assert info.file_type == "source"
        assert info.detection_method == "extension"

    def test_unknown_classmethod(self):
        """Should create unknown LanguageInfo via classmethod."""
        info = LanguageInfo.unknown()
        assert info.language == "unknown"
        assert info.confidence == 0.0
        assert info.file_type == "unknown"
        assert info.detection_method == "unknown"

    def test_is_unknown_property_true(self):
        """is_unknown should be True for unknown language."""
        info = LanguageInfo.unknown()
        assert info.is_unknown is True

    def test_is_unknown_property_false(self):
        """is_unknown should be False for known language."""
        info = LanguageInfo(
            language="go",
            confidence=0.95,
            file_type="source",
            detection_method="extension",
        )
        assert info.is_unknown is False

    def test_repr_formatting(self):
        """Should format confidence to 2 decimal places in repr."""
        info = LanguageInfo(
            language="python",
            confidence=0.951234,
            file_type="source",
            detection_method="extension",
        )
        repr_str = repr(info)
        assert "confidence=0.95" in repr_str
        assert "language='python'" in repr_str

    def test_frozen_dataclass(self):
        """Should be immutable (frozen dataclass)."""
        info = LanguageInfo(
            language="python",
            confidence=0.95,
            file_type="source",
            detection_method="extension",
        )
        with pytest.raises(AttributeError):
            info.language = "go"


# =============================================================================
# Extension Detection Tests (AC-2)
# =============================================================================


class TestExtensionDetection:
    """Tests for file extension detection."""

    def test_go_extension(self, detector):
        """Should detect Go from .go extension."""
        info = detector._detect_by_extension(Path("main.go"))
        assert info is not None
        assert info.language == "go"
        assert info.confidence == 0.95
        assert info.file_type == "source"
        assert info.detection_method == "extension"

    def test_python_extension(self, detector):
        """Should detect Python from .py extension."""
        info = detector._detect_by_extension(Path("script.py"))
        assert info is not None
        assert info.language == "python"
        assert info.confidence == 0.95
        assert info.file_type == "source"

    def test_typescript_extension(self, detector):
        """Should detect TypeScript from .ts extension."""
        info = detector._detect_by_extension(Path("app.ts"))
        assert info is not None
        assert info.language == "typescript"
        assert info.confidence == 0.95

    def test_javascript_extension(self, detector):
        """Should detect JavaScript from .js extension."""
        info = detector._detect_by_extension(Path("app.js"))
        assert info is not None
        assert info.language == "javascript"
        assert info.confidence == 0.95

    def test_rust_extension(self, detector):
        """Should detect Rust from .rs extension."""
        info = detector._detect_by_extension(Path("main.rs"))
        assert info is not None
        assert info.language == "rust"
        assert info.confidence == 0.95

    def test_java_extension(self, detector):
        """Should detect Java from .java extension."""
        info = detector._detect_by_extension(Path("Main.java"))
        assert info is not None
        assert info.language == "java"
        assert info.confidence == 0.95

    def test_ruby_extension(self, detector):
        """Should detect Ruby from .rb extension."""
        info = detector._detect_by_extension(Path("script.rb"))
        assert info is not None
        assert info.language == "ruby"
        assert info.confidence == 0.95

    def test_python_interface_file(self, detector):
        """Should detect Python interface from .pyi extension."""
        info = detector._detect_by_extension(Path("module.pyi"))
        assert info is not None
        assert info.language == "python"
        assert info.file_type == "interface"

    def test_javascript_mjs_extension(self, detector):
        """Should detect JavaScript from .mjs extension."""
        info = detector._detect_by_extension(Path("module.mjs"))
        assert info is not None
        assert info.language == "javascript"

    def test_case_insensitive_extension(self, detector):
        """Should handle case-insensitive extensions."""
        info = detector._detect_by_extension(Path("main.GO"))
        assert info is not None
        assert info.language == "go"

        info = detector._detect_by_extension(Path("script.PY"))
        assert info is not None
        assert info.language == "python"

    def test_unknown_extension_returns_none(self, detector):
        """Should return None for unknown extensions."""
        info = detector._detect_by_extension(Path("file.unknown"))
        assert info is None

        info = detector._detect_by_extension(Path("file.txt"))
        assert info is None

    def test_no_extension_returns_none(self, detector):
        """Should return None for files without extension."""
        info = detector._detect_by_extension(Path("Makefile"))
        assert info is None

        info = detector._detect_by_extension(Path("Dockerfile"))
        assert info is None


# =============================================================================
# Test File Pattern Tests (AC-2)
# =============================================================================


class TestTestFilePatterns:
    """Tests for test file pattern detection."""

    def test_go_test_file(self, detector):
        """Should detect Go test from _test.go suffix."""
        info = detector._detect_by_extension(Path("main_test.go"))
        assert info is not None
        assert info.language == "go"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_python_test_file(self, detector):
        """Should detect Python test from _test.py suffix."""
        info = detector._detect_by_extension(Path("main_test.py"))
        assert info is not None
        assert info.language == "python"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_typescript_test_file(self, detector):
        """Should detect TypeScript test from .test.ts suffix."""
        info = detector._detect_by_extension(Path("app.test.ts"))
        assert info is not None
        assert info.language == "typescript"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_typescript_spec_file(self, detector):
        """Should detect TypeScript test from .spec.ts suffix."""
        info = detector._detect_by_extension(Path("app.spec.ts"))
        assert info is not None
        assert info.language == "typescript"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_javascript_test_file(self, detector):
        """Should detect JavaScript test from .test.js suffix."""
        info = detector._detect_by_extension(Path("app.test.js"))
        assert info is not None
        assert info.language == "javascript"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_javascript_spec_file(self, detector):
        """Should detect JavaScript test from .spec.js suffix."""
        info = detector._detect_by_extension(Path("app.spec.js"))
        assert info is not None
        assert info.language == "javascript"
        assert info.file_type == "test"
        assert info.confidence == 0.90

    def test_rust_test_file(self, detector):
        """Should detect Rust test from _test.rs suffix."""
        info = detector._detect_by_extension(Path("main_test.rs"))
        assert info is not None
        assert info.language == "rust"
        assert info.file_type == "test"
        assert info.confidence == 0.90


# =============================================================================
# Shebang Detection Tests (AC-3)
# =============================================================================


class TestShebangDetection:
    """Tests for shebang line detection."""

    def test_python_env_shebang(self, detector):
        """Should detect Python from #!/usr/bin/env python."""
        content = "#!/usr/bin/env python\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert info.language == "python"
        assert info.confidence == 0.90
        assert info.file_type == "script"
        assert info.detection_method == "shebang"

    def test_python3_env_shebang(self, detector):
        """Should detect Python from #!/usr/bin/env python3."""
        content = "#!/usr/bin/env python3\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert info.language == "python"

    def test_python_versioned_shebang(self, detector):
        """Should detect Python from versioned interpreter (python3.11)."""
        content = "#!/usr/bin/env python3.11\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert info.language == "python"

    def test_python_direct_path_shebang(self, detector):
        """Should detect Python from direct path shebang."""
        content = "#!/usr/bin/python3\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert info.language == "python"
        assert info.confidence == 0.85

    def test_python_env_with_options(self, detector):
        """Should handle env with options (-S flag)."""
        content = "#!/usr/bin/env -S python3 -u\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert info.language == "python"

    def test_bash_shebang_returns_none(self, detector):
        """Should return None for bash (unsupported)."""
        content = "#!/bin/bash\necho 'hello'"
        info = detector._detect_by_shebang(content)
        assert info is None

    def test_sh_shebang_returns_none(self, detector):
        """Should return None for sh (unsupported)."""
        content = "#!/bin/sh\necho 'hello'"
        info = detector._detect_by_shebang(content)
        assert info is None

    def test_no_shebang_returns_none(self, detector):
        """Should return None for files without shebang."""
        content = "print('hello')\n"
        info = detector._detect_by_shebang(content)
        assert info is None

    def test_empty_content_returns_none(self, detector):
        """Should return None for empty content."""
        info = detector._detect_by_shebang("")
        assert info is None


# =============================================================================
# Heuristic Detection Tests (AC-4)
# =============================================================================


class TestHeuristicDetection:
    """Tests for content heuristic detection."""

    def test_go_package_heuristic(self, detector):
        """Should detect Go from package declaration."""
        content = "package main\n\nimport 'fmt'"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "go"
        assert info.detection_method == "heuristic"

    def test_go_func_heuristic(self, detector):
        """Should detect Go from func declaration."""
        content = "func main() {\n    fmt.Println(\"hello\")\n}"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "go"

    def test_go_goroutine_heuristic(self, detector):
        """Should detect Go from goroutine pattern."""
        content = "go func() {\n    // concurrent\n}()"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "go"

    def test_python_def_heuristic(self, detector):
        """Should detect Python from def declaration."""
        content = "def hello():\n    pass"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "python"

    def test_python_async_def_heuristic(self, detector):
        """Should detect Python from async def declaration."""
        content = "async def fetch():\n    pass"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "python"

    def test_python_main_heuristic(self, detector):
        """Should detect Python from __main__ pattern."""
        content = "if __name__ == '__main__':\n    main()"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "python"
        assert info.confidence == 0.95

    def test_javascript_arrow_heuristic(self, detector):
        """Should detect JavaScript from arrow function pattern."""
        content = "const fn = (x) => x * 2"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "javascript"

    def test_javascript_async_heuristic(self, detector):
        """Should detect JavaScript from async function pattern."""
        content = "async function fetch() {\n    return await get();\n}"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "javascript"

    def test_rust_main_heuristic(self, detector):
        """Should detect Rust from fn main pattern."""
        content = "fn main() {\n    println!(\"hello\");\n}"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "rust"

    def test_rust_use_std_heuristic(self, detector):
        """Should detect Rust from use std:: pattern."""
        content = "use std::collections::HashMap;"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "rust"

    def test_java_public_class_heuristic(self, detector):
        """Should detect Java from public class pattern."""
        content = "public class Main {\n    // ...\n}"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "java"

    def test_java_import_heuristic(self, detector):
        """Should detect Java from import java. pattern."""
        content = "import java.util.List;"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert info.language == "java"

    def test_no_match_returns_none(self, detector):
        """Should return None when no heuristics match."""
        content = "hello world\nfoo bar"
        info = detector._detect_by_heuristics(content)
        assert info is None


# =============================================================================
# Fallback Chain Tests (AC-5)
# =============================================================================


class TestFallbackChain:
    """Tests for detection fallback chain behavior."""

    def test_extension_wins_over_shebang(self, detector):
        """Extension detection should be used when available."""
        # File with .py extension but bash shebang (weird but possible)
        info = detector.detect(
            Path("script.py"),
            "#!/bin/bash\necho 'hello'",
        )
        assert info.language == "python"
        assert info.detection_method == "extension"

    def test_shebang_fallback_when_no_extension(self, detector):
        """Shebang should be used when no extension match."""
        info = detector.detect(
            Path("script"),
            "#!/usr/bin/env python3\nprint('hello')",
        )
        assert info.language == "python"
        assert info.detection_method == "shebang"

    def test_heuristic_fallback_when_no_extension_or_shebang(self, detector):
        """Heuristics should be used when extension and shebang fail."""
        info = detector.detect(
            Path("script"),
            "def hello():\n    pass",
        )
        assert info.language == "python"
        assert info.detection_method == "heuristic"

    def test_unknown_when_all_fail(self, detector):
        """Should return unknown when all methods fail."""
        info = detector.detect(
            Path("script"),
            "hello world",
        )
        assert info.is_unknown
        assert info.language == "unknown"

    def test_unknown_for_no_content_no_file(self, detector):
        """Should return unknown for non-existent file without content."""
        info = detector.detect(Path("/nonexistent/path/script.xyz"))
        assert info.is_unknown


# =============================================================================
# File Reading Tests (AC-5)
# =============================================================================


class TestFileReading:
    """Tests for file reading with safety checks."""

    def test_reads_file_content(self, tmp_path, detector_no_cache):
        """Should read content from existing file."""
        file_path = tmp_path / "script"
        file_path.write_text("#!/usr/bin/env python3\nprint('hello')")

        info = detector_no_cache.detect(file_path)
        assert info.language == "python"
        assert info.detection_method == "shebang"

    def test_handles_binary_file(self, tmp_path, detector_no_cache):
        """Should return unknown for binary files."""
        file_path = tmp_path / "binary"
        file_path.write_bytes(b"\x00\x01\x02\x03\x04\x05")

        info = detector_no_cache.detect(file_path)
        assert info.is_unknown

    def test_handles_large_file(self, tmp_path, detector_no_cache):
        """Should handle large files efficiently."""
        file_path = tmp_path / "large.py"
        # Write a 2MB file
        file_path.write_text("x" * (2 * 1024 * 1024))

        # Should still detect from extension without reading full content
        info = detector_no_cache.detect(file_path)
        assert info.language == "python"

    def test_handles_permission_error(self, tmp_path, detector_no_cache):
        """Should handle permission errors gracefully."""
        file_path = tmp_path / "secret"
        file_path.write_text("def hello(): pass")
        file_path.chmod(0o000)

        try:
            info = detector_no_cache.detect(file_path)
            assert info.is_unknown
        finally:
            # Restore permissions for cleanup
            file_path.chmod(0o644)

    def test_handles_nonexistent_file(self, detector_no_cache):
        """Should handle non-existent files gracefully."""
        info = detector_no_cache.detect(Path("/does/not/exist"))
        assert info.is_unknown

    def test_handles_directory(self, tmp_path, detector_no_cache):
        """Should handle directories gracefully."""
        dir_path = tmp_path / "directory"
        dir_path.mkdir()

        info = detector_no_cache.detect(dir_path)
        assert info.is_unknown


# =============================================================================
# Cache Tests
# =============================================================================


class TestCaching:
    """Tests for LRU cache behavior."""

    def test_cache_enabled_by_default(self):
        """Should enable cache by default."""
        detector = LanguageDetector()
        assert detector._cache_enabled is True

    def test_cache_disabled(self):
        """Should disable cache when requested."""
        detector = LanguageDetector(cache_enabled=False)
        assert detector._cache_enabled is False
        assert detector._cached_detect is None

    def test_caches_results(self, tmp_path, detector):
        """Should cache detection results."""
        file_path = tmp_path / "test.py"
        file_path.write_text("# python file")

        # First detection
        info1 = detector.detect(file_path)

        # Second detection (should hit cache)
        info2 = detector.detect(file_path)

        # Results should be identical
        assert info1 == info2

    def test_cache_respects_maxsize(self):
        """Should respect cache maxsize."""
        detector = LanguageDetector(cache_enabled=True, cache_maxsize=5)
        assert detector._cache_maxsize == 5

    def test_cache_invalidation_on_mtime_change(self, tmp_path, detector):
        """Should invalidate cache when file mtime changes."""
        file_path = tmp_path / "test.py"
        file_path.write_text("# python file")

        # First detection
        info1 = detector.detect(file_path)
        assert info1.language == "python"

        # Modify file
        file_path.write_text("# modified python file")

        # Detection after modification (should re-read)
        info2 = detector.detect(file_path)
        assert info2.language == "python"


# =============================================================================
# Confidence Tests
# =============================================================================


class TestConfidenceScores:
    """Tests for confidence score ranges."""

    def test_extension_confidence_range(self, detector):
        """Extension detection confidence should be 0.90-0.95."""
        # Standard extension
        info = detector._detect_by_extension(Path("main.py"))
        assert info is not None
        assert 0.0 <= info.confidence <= 1.0

        # Test file extension
        info = detector._detect_by_extension(Path("main_test.py"))
        assert info is not None
        assert 0.0 <= info.confidence <= 1.0

    def test_shebang_confidence_range(self, detector):
        """Shebang detection confidence should be 0.85-0.90."""
        content = "#!/usr/bin/env python3\nprint('hello')"
        info = detector._detect_by_shebang(content)
        assert info is not None
        assert 0.0 <= info.confidence <= 1.0

    def test_heuristic_confidence_range(self, detector):
        """Heuristic detection confidence should be 0.65-0.95."""
        content = "def hello():\n    pass"
        info = detector._detect_by_heuristics(content)
        assert info is not None
        assert 0.0 <= info.confidence <= 1.0

    def test_unknown_confidence_is_zero(self, detector):
        """Unknown language should have confidence 0.0."""
        info = LanguageInfo.unknown()
        assert info.confidence == 0.0


# =============================================================================
# Mapping Constants Tests
# =============================================================================


class TestMappings:
    """Tests for mapping constants."""

    def test_extension_map_has_required_languages(self):
        """EXTENSION_MAP should include all required languages."""
        required = [".go", ".py", ".ts", ".js", ".rs"]
        for ext in required:
            assert ext in EXTENSION_MAP

    def test_test_patterns_have_required_suffixes(self):
        """TEST_PATTERNS should include all required test suffixes."""
        suffixes = [p[0] for p in TEST_PATTERNS]
        assert "_test.go" in suffixes
        assert "_test.py" in suffixes
        assert ".test.ts" in suffixes

    def test_shebang_patterns_are_compiled_regex(self):
        """SHEBANG_PATTERNS should contain compiled regex patterns."""
        for pattern, lang, conf in SHEBANG_PATTERNS:
            assert hasattr(pattern, "match")

    def test_heuristic_patterns_are_compiled_regex(self):
        """HEURISTIC_PATTERNS should contain compiled regex patterns."""
        for pattern, lang, conf in HEURISTIC_PATTERNS:
            assert hasattr(pattern, "search")


# =============================================================================
# Integration Tests with Context
# =============================================================================


@pytest.mark.slow  # Real LLM calls via engine.verify() - 25-26s per test
class TestVerificationContextIntegration:
    """Tests for VerificationContext integration."""

    @pytest.mark.asyncio
    async def test_engine_auto_detects_language(self, tmp_path):
        """Engine should auto-detect language from file_path."""
        from bmad_assist.deep_verify.core.engine import (
            DeepVerifyEngine,
            VerificationContext,
        )

        # Create engine
        engine = DeepVerifyEngine(project_root=tmp_path)

        # Create a Python file
        py_file = tmp_path / "script.py"
        py_file.write_text("def hello():\n    pass")

        # Verify with context containing file_path
        context = VerificationContext(file_path=py_file)
        verdict = await engine.verify("def hello():\n    pass", context=context)

        # Should complete without error
        assert verdict is not None

    @pytest.mark.asyncio
    async def test_engine_uses_provided_language(self, tmp_path):
        """Engine should use provided language from context."""
        from bmad_assist.deep_verify.core.engine import (
            DeepVerifyEngine,
            VerificationContext,
        )

        engine = DeepVerifyEngine(project_root=tmp_path)

        # Provide explicit language
        context = VerificationContext(
            file_path=tmp_path / "script.xyz",
            language="go",
        )

        verdict = await engine.verify("func main() {}", context=context)
        assert verdict is not None

    @pytest.mark.asyncio
    async def test_engine_no_file_path_no_detection(self, tmp_path):
        """Engine should skip language detection without file_path."""
        from bmad_assist.deep_verify.core.engine import DeepVerifyEngine

        engine = DeepVerifyEngine(project_root=tmp_path)

        # Verify without context
        verdict = await engine.verify("def hello(): pass")

        # Should complete without error
        assert verdict is not None


# =============================================================================
# DomainDetector Integration Tests
# =============================================================================


@pytest.mark.slow  # Real LLM calls via DomainDetector - 5-6s per test
class TestDomainDetectorIntegration:
    """Tests for DomainDetector language hint integration."""

    def test_domain_detector_accepts_language_hint(self, tmp_path):
        """DomainDetector should accept language_hint parameter."""
        from bmad_assist.deep_verify.core.domain_detector import DomainDetector

        detector = DomainDetector(project_root=tmp_path)

        # Should not raise error with language_hint
        result = detector.detect("func main() {}", language_hint="go")
        assert result is not None

    def test_detect_domains_accepts_language_hint(self, tmp_path):
        """detect_domains convenience function should accept language_hint."""
        from bmad_assist.deep_verify.core.domain_detector import detect_domains

        # Should not raise error with language_hint
        result = detect_domains("def hello(): pass", language_hint="python")
        assert result is not None


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_string_content(self, detector):
        """Should handle empty string content."""
        info = detector.detect(Path("script"), "")
        assert info.is_unknown

    def test_whitespace_only_content(self, detector):
        """Should handle whitespace-only content."""
        info = detector.detect(Path("script"), "   \n\t  ")
        assert info.is_unknown

    def test_path_as_string(self, detector):
        """Should accept path as string."""
        info = detector.detect("main.py")
        assert info.language == "python"

    def test_detector_repr(self, detector):
        """Should have informative repr."""
        repr_str = repr(detector)
        assert "LanguageDetector" in repr_str
        assert "cache" in repr_str.lower()

    def test_concurrent_detection(self, detector, tmp_path):
        """Should handle concurrent detection requests."""
        import threading

        results = []
        errors = []

        def detect():
            try:
                file_path = tmp_path / "test.py"
                file_path.write_text("# test")
                info = detector.detect(file_path)
                results.append(info.language)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

        # Run multiple threads
        threads = [threading.Thread(target=detect) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert len(errors) == 0
        assert all(lang == "python" for lang in results)
