"""Tests for the extraction pipeline."""


from bmad_assist.context.extractor import extract_context


class TestDiffAwareMode:
    """Tests for diff-aware extraction."""

    def test_diff_aware_marks_modified_symbols(self) -> None:
        code = (
            "import os\n"
            "\n"
            "def foo():\n"
            "    pass\n"
            "\n"
            "def bar():\n"
            "    pass\n"
        )
        ctx = extract_context(code, "test.py", budget=4000, hunk_ranges=[(3, 4)])
        assert ctx.extraction_mode == "diff_aware"
        assert len(ctx.modified_symbols) == 1
        assert ctx.modified_symbols[0].name == "foo"

    def test_two_modified_functions(self) -> None:
        code = (
            "import os\n"
            "\n"
            "def alpha():\n"
            "    return 1\n"
            "\n"
            "def beta():\n"
            "    return 2\n"
            "\n"
            "def gamma():\n"
            "    return 3\n"
        )
        ctx = extract_context(code, "test.py", budget=4000, hunk_ranges=[(3, 4), (9, 10)])
        assert ctx.extraction_mode == "diff_aware"
        assert len(ctx.modified_symbols) == 2
        names = [s.name for s in ctx.modified_symbols]
        assert "alpha" in names
        assert "gamma" in names

    def test_hunk_ranges_dont_overlap_symbols(self) -> None:
        code = (
            "import os\n"
            "# A comment on line 2\n"
            "\n"
            "def foo():\n"
            "    pass\n"
        )
        # Hunk range on the comment line (between imports and function)
        ctx = extract_context(code, "test.py", budget=4000, hunk_ranges=[(2, 2)])
        assert ctx.extraction_mode == "no_diff"
        assert len(ctx.modified_symbols) == 0

    def test_invalid_hunk_ranges_filtered(self) -> None:
        code = "def foo():\n    pass\n"
        # (0, 0) is invalid and should be filtered
        ctx = extract_context(code, "test.py", budget=4000, hunk_ranges=[(0, 0), (1, 2)])
        assert ctx.extraction_mode == "diff_aware"
        assert len(ctx.modified_symbols) == 1


class TestNoDiffMode:
    """Tests for no-diff mode."""

    def test_no_hunk_ranges(self) -> None:
        code = "def foo():\n    pass\n"
        ctx = extract_context(code, "test.py", budget=4000)
        assert ctx.extraction_mode == "no_diff"
        assert len(ctx.modified_symbols) == 0
        assert len(ctx.unmodified_symbols) == 1


class TestFallbackMode:
    """Tests for fallback mode."""

    def test_unknown_language(self) -> None:
        code = "some ruby code\nend\n"
        ctx = extract_context(code, "test.rb", budget=4000)
        assert ctx.extraction_mode == "fallback"
        assert ctx.language == "unknown"

    def test_python_syntax_error_fallback(self) -> None:
        code = "def foo(\n    # broken\n"
        ctx = extract_context(code, "test.py", budget=4000)
        assert ctx.extraction_mode == "fallback"
        assert ctx.budget_used > 0

    def test_empty_file(self) -> None:
        ctx = extract_context("", "test.py", budget=4000)
        assert ctx.extraction_mode == "fallback"
        assert ctx.budget_used == 0


class TestBudgetEnforcement:
    """Tests for budget allocation."""

    def test_budget_respected(self) -> None:
        # Create a file with many functions
        funcs = "\n".join(
            f"def func_{i}():\n    return {i}\n" for i in range(50)
        )
        code = "import os\nimport sys\n\n" + funcs
        ctx = extract_context(code, "test.py", budget=4000)
        assert ctx.budget_used <= 4000

    def test_minimum_budget_enforced(self) -> None:
        code = "def foo():\n    pass\n"
        ctx = extract_context(code, "test.py", budget=500)
        # Should enforce minimum of 2000
        assert ctx.budget_total == 2000

    def test_imports_always_first(self) -> None:
        code = "import os\nimport sys\n\ndef foo():\n    pass\n"
        ctx = extract_context(code, "test.py", budget=2000)
        # Imports should be present
        assert ctx.imports.content != ""


class TestLanguageDetection:
    """Tests for language detection."""

    def test_python_detection(self) -> None:
        ctx = extract_context("x = 1", "src/main.py", budget=4000)
        assert ctx.language == "python"

    def test_javascript_detection(self) -> None:
        ctx = extract_context("const x = 1;", "src/app.js", budget=4000)
        assert ctx.language == "javascript"

    def test_typescript_detection(self) -> None:
        ctx = extract_context("const x: number = 1;", "src/app.ts", budget=4000)
        assert ctx.language == "typescript"

    def test_go_detection(self) -> None:
        ctx = extract_context("package main", "main.go", budget=4000)
        assert ctx.language == "go"

    def test_language_override(self) -> None:
        ctx = extract_context("x = 1", "file.txt", budget=4000, language="python")
        assert ctx.language == "python"


class TestImportBudgetCap:
    """Tests for import budget cap (50%)."""

    def test_imports_capped_at_half_budget(self) -> None:
        # Create many imports exceeding 50% of budget
        imports = "\n".join(
            f"from package_{i}.module import Class{i}" for i in range(100)
        )
        code = imports + "\n\ndef main():\n    pass\n"
        ctx = extract_context(code, "test.py", budget=2000)
        # Imports should exist but be capped
        assert ctx.imports.content != ""
        # Truncation marker should be present
        assert "more imports" in ctx.imports.content
        # Budget should not exceed total
        assert ctx.budget_used <= 2000


class TestFallbackContent:
    """Tests for fallback content storage."""

    def test_fallback_stores_truncated_content(self) -> None:
        code = "some ruby code\n" * 100
        ctx = extract_context(code, "test.rb", budget=2000)
        assert ctx.extraction_mode == "fallback"
        assert ctx.fallback_content != ""
        assert len(ctx.fallback_content) <= 2000
        assert ctx.budget_used == len(ctx.fallback_content)

    def test_fallback_short_content(self) -> None:
        code = "short content"
        ctx = extract_context(code, "test.rb", budget=4000)
        assert ctx.extraction_mode == "fallback"
        assert ctx.fallback_content == code
        assert ctx.budget_used == len(code)


class TestEndToEnd:
    """Integration tests: extract_context -> formatters."""

    def test_extract_and_format_for_dv_python(self) -> None:
        from bmad_assist.context.formatter import format_for_dv

        code = (
            "import os\n"
            "\n"
            "def foo():\n"
            "    return 1\n"
            "\n"
            "def bar():\n"
            "    return 2\n"
        )
        ctx = extract_context(code, "test.py", budget=4000, hunk_ranges=[(3, 4)])
        result = format_for_dv(ctx)
        assert "foo" in result
        assert "import os" in result
        assert len(result) <= 4000

    def test_extract_and_format_for_source_context(self) -> None:
        from bmad_assist.context.formatter import format_for_source_context

        code = "def hello():\n    print('hi')\n"
        ctx = extract_context(code, "test.py", budget=4000)
        result = format_for_source_context(ctx, 4000)
        assert "def hello" in result

    def test_extract_and_format_fallback(self) -> None:
        from bmad_assist.context.formatter import format_for_dv, format_for_source_context

        code = "some unknown language code"
        ctx = extract_context(code, "test.rb", budget=4000)
        dv_result = format_for_dv(ctx)
        assert "some unknown" in dv_result
        # source_context returns empty for fallback — caller handles truncation
        sc_result = format_for_source_context(ctx, 4000)
        assert sc_result == ""
