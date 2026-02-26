from __future__ import annotations

from pathlib import Path

from bmad_assist.security.tech_stack import (
    EXTENSION_MAP,
    MARKER_MAP,
    _detect_from_diff,
    _detect_from_markers,
    _get_extension,
    detect_tech_stack,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_diff(*file_paths: str) -> str:
    """Build minimal unified diff content with the given file paths."""
    lines: list[str] = []
    for fp in file_paths:
        lines.append(f"--- a/{fp}")
        lines.append(f"+++ b/{fp}")
        lines.append("@@ -1,3 +1,3 @@")
        lines.append("+// changed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# _get_extension
# ---------------------------------------------------------------------------


class TestGetExtension:
    """Tests for the _get_extension helper."""

    def test_simple_extension(self):
        assert _get_extension("main.go") == ".go"

    def test_nested_path(self):
        assert _get_extension("src/pkg/handler.py") == ".py"

    def test_uppercase_normalised(self):
        assert _get_extension("README.MD") == ".md"

    def test_double_extension_returns_last(self):
        assert _get_extension("archive.tar.gz") == ".gz"

    def test_no_extension(self):
        assert _get_extension("Makefile") == ""

    def test_dotfile(self):
        assert _get_extension(".gitignore") == ""

    def test_empty_string(self):
        assert _get_extension("") == ""


# ---------------------------------------------------------------------------
# _detect_from_diff
# ---------------------------------------------------------------------------


class TestDetectFromDiff:
    """Tests for diff-based language detection."""

    def test_single_go_file(self):
        diff = _make_diff("cmd/server/main.go")
        assert _detect_from_diff(diff) == {"go"}

    def test_single_python_file(self):
        diff = _make_diff("src/app.py")
        assert _detect_from_diff(diff) == {"python"}

    def test_multiple_languages(self):
        diff = _make_diff("main.go", "utils.py", "index.js")
        result = _detect_from_diff(diff)
        assert result == {"go", "python", "javascript"}

    def test_typescript_maps_to_javascript(self):
        diff = _make_diff("app.ts", "component.tsx")
        assert _detect_from_diff(diff) == {"javascript"}

    def test_kotlin_maps_to_java(self):
        diff = _make_diff("Main.kt", "build.gradle.kts")
        # .kts is in EXTENSION_MAP mapping to java
        assert "java" in _detect_from_diff(diff)

    def test_cpp_extensions(self):
        diff = _make_diff("lib.cpp", "header.hpp", "util.h")
        assert _detect_from_diff(diff) == {"cpp"}

    def test_c_extension(self):
        diff = _make_diff("driver.c")
        assert _detect_from_diff(diff) == {"cpp"}

    def test_rust_extension(self):
        diff = _make_diff("src/lib.rs")
        assert _detect_from_diff(diff) == {"rust"}

    def test_swift_extension(self):
        diff = _make_diff("Sources/App.swift")
        assert _detect_from_diff(diff) == {"swift"}

    def test_ruby_extensions(self):
        diff = _make_diff("app.rb", "views/index.erb")
        assert _detect_from_diff(diff) == {"ruby"}

    def test_csharp_extension(self):
        diff = _make_diff("Program.cs")
        assert _detect_from_diff(diff) == {"csharp"}

    def test_unknown_extension_ignored(self):
        diff = _make_diff("README.md", "data.json", "image.png")
        assert _detect_from_diff(diff) == set()

    def test_empty_diff(self):
        assert _detect_from_diff("") == set()

    def test_deduplication(self):
        diff = _make_diff("a.py", "b.py", "c.py")
        assert _detect_from_diff(diff) == {"python"}

    def test_mixed_known_and_unknown(self):
        diff = _make_diff("main.go", "README.md", "Dockerfile")
        assert _detect_from_diff(diff) == {"go"}

    def test_jsx_maps_to_javascript(self):
        diff = _make_diff("Component.jsx")
        assert _detect_from_diff(diff) == {"javascript"}

    def test_mjs_cjs_maps_to_javascript(self):
        diff = _make_diff("module.mjs", "common.cjs")
        assert _detect_from_diff(diff) == {"javascript"}

    def test_pyw_maps_to_python(self):
        diff = _make_diff("gui.pyw")
        assert _detect_from_diff(diff) == {"python"}


# ---------------------------------------------------------------------------
# _detect_from_markers
# ---------------------------------------------------------------------------


class TestDetectFromMarkers:
    """Tests for marker-file-based language detection."""

    def test_pyproject_toml(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        assert "python" in _detect_from_markers(tmp_path)

    def test_setup_py(self, tmp_path: Path):
        (tmp_path / "setup.py").touch()
        assert "python" in _detect_from_markers(tmp_path)

    def test_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").touch()
        assert "python" in _detect_from_markers(tmp_path)

    def test_pipfile(self, tmp_path: Path):
        (tmp_path / "Pipfile").touch()
        assert "python" in _detect_from_markers(tmp_path)

    def test_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").touch()
        assert "go" in _detect_from_markers(tmp_path)

    def test_go_sum(self, tmp_path: Path):
        (tmp_path / "go.sum").touch()
        assert "go" in _detect_from_markers(tmp_path)

    def test_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").touch()
        assert "javascript" in _detect_from_markers(tmp_path)

    def test_tsconfig_json(self, tmp_path: Path):
        (tmp_path / "tsconfig.json").touch()
        assert "javascript" in _detect_from_markers(tmp_path)

    def test_yarn_lock(self, tmp_path: Path):
        (tmp_path / "yarn.lock").touch()
        assert "javascript" in _detect_from_markers(tmp_path)

    def test_pnpm_lock(self, tmp_path: Path):
        (tmp_path / "pnpm-lock.yaml").touch()
        assert "javascript" in _detect_from_markers(tmp_path)

    def test_pom_xml(self, tmp_path: Path):
        (tmp_path / "pom.xml").touch()
        assert "java" in _detect_from_markers(tmp_path)

    def test_build_gradle(self, tmp_path: Path):
        (tmp_path / "build.gradle").touch()
        assert "java" in _detect_from_markers(tmp_path)

    def test_build_gradle_kts(self, tmp_path: Path):
        (tmp_path / "build.gradle.kts").touch()
        assert "java" in _detect_from_markers(tmp_path)

    def test_gemfile(self, tmp_path: Path):
        (tmp_path / "Gemfile").touch()
        assert "ruby" in _detect_from_markers(tmp_path)

    def test_cargo_toml(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").touch()
        assert "rust" in _detect_from_markers(tmp_path)

    def test_package_swift(self, tmp_path: Path):
        (tmp_path / "Package.swift").touch()
        assert "swift" in _detect_from_markers(tmp_path)

    def test_cmakelists(self, tmp_path: Path):
        (tmp_path / "CMakeLists.txt").touch()
        assert "cpp" in _detect_from_markers(tmp_path)

    def test_csproj_glob(self, tmp_path: Path):
        (tmp_path / "MyApp.csproj").touch()
        assert "csharp" in _detect_from_markers(tmp_path)

    def test_sln_glob(self, tmp_path: Path):
        (tmp_path / "Solution.sln").touch()
        assert "csharp" in _detect_from_markers(tmp_path)

    def test_no_markers(self, tmp_path: Path):
        assert _detect_from_markers(tmp_path) == set()

    def test_nonexistent_directory(self, tmp_path: Path):
        fake = tmp_path / "nonexistent"
        assert _detect_from_markers(fake) == set()

    def test_multiple_markers_deduplicates(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "setup.py").touch()
        (tmp_path / "requirements.txt").touch()
        result = _detect_from_markers(tmp_path)
        assert result == {"python"}

    def test_multiple_languages(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "go.mod").touch()
        (tmp_path / "package.json").touch()
        result = _detect_from_markers(tmp_path)
        assert result == {"python", "go", "javascript"}


# ---------------------------------------------------------------------------
# detect_tech_stack (integration of both strategies)
# ---------------------------------------------------------------------------


class TestDetectTechStack:
    """Tests for the top-level detect_tech_stack function."""

    def test_diff_only(self, tmp_path: Path):
        diff = _make_diff("main.go")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        assert result == ["go"]

    def test_markers_only(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        result = detect_tech_stack(tmp_path)
        assert result == ["python"]

    def test_combined_detection(self, tmp_path: Path):
        (tmp_path / "go.mod").touch()
        diff = _make_diff("app.py")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        assert result == ["go", "python"]

    def test_deduplication_across_strategies(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        diff = _make_diff("main.py")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        assert result == ["python"]

    def test_result_is_sorted(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").touch()
        diff = _make_diff("main.go", "app.py")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        assert result == sorted(result)
        assert set(result) == {"go", "python", "rust"}

    def test_empty_diff_no_markers(self, tmp_path: Path):
        result = detect_tech_stack(tmp_path, diff_content="")
        assert result == []

    def test_none_diff_no_markers(self, tmp_path: Path):
        result = detect_tech_stack(tmp_path, diff_content=None)
        assert result == []

    def test_no_diff_no_markers_returns_empty(self, tmp_path: Path):
        result = detect_tech_stack(tmp_path)
        assert result == []

    def test_diff_with_unknown_extensions_only(self, tmp_path: Path):
        diff = _make_diff("README.md", "Dockerfile")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        assert result == []

    def test_many_languages(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "go.mod").touch()
        (tmp_path / "package.json").touch()
        (tmp_path / "Cargo.toml").touch()
        diff = _make_diff("Main.java", "App.swift")
        result = detect_tech_stack(tmp_path, diff_content=diff)
        expected = sorted(["python", "go", "javascript", "rust", "java", "swift"])
        assert result == expected


class TestExtensionMapCompleteness:
    """Verify that EXTENSION_MAP and MARKER_MAP are consistent."""

    def test_all_extensions_have_dots(self):
        for ext in EXTENSION_MAP:
            assert ext.startswith("."), f"Extension {ext!r} should start with '.'"

    def test_all_extension_values_are_lowercase(self):
        for lang in EXTENSION_MAP.values():
            assert lang == lang.lower(), f"Language {lang!r} should be lowercase"

    def test_all_marker_values_are_lowercase(self):
        for lang in MARKER_MAP.values():
            assert lang == lang.lower(), f"Language {lang!r} should be lowercase"
