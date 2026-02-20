"""Tests for the XML output generation module.

Tests the generate_output function which transforms CompiledWorkflow
data into well-formed XML output following recency-bias ordering.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bmad_assist.compiler.output import (
    FILE_ORDER_PATTERNS,
    GeneratedOutput,
    _generate_file_id,
    _get_file_order_key,
    _normalize_path,
    _serialize_value,
    generate_output,
)
from bmad_assist.compiler.types import CompiledWorkflow
from bmad_assist.core.exceptions import CompilerError


def create_test_compiled_workflow(
    workflow_name: str = "test-workflow",
    mission: str = "Test mission",
    context: str = "Test context",
    variables: dict | None = None,
    instructions: str = "<action>Test action</action>",
    output_template: str = "# Output",
    token_estimate: int = 0,
) -> CompiledWorkflow:
    """Create a CompiledWorkflow instance for testing."""
    return CompiledWorkflow(
        workflow_name=workflow_name,
        mission=mission,
        context=context,
        variables=variables or {},
        instructions=instructions,
        output_template=output_template,
        token_estimate=token_estimate,
    )


class TestXMLStructure:
    """Tests for AC1: XML structure and section order."""

    def test_xml_structure_order(self) -> None:
        """XML output has correct section order."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        # Parse to verify structure
        root = ET.fromstring(result.xml)
        assert root.tag == "compiled-workflow"

        # Verify section order (5 sections without file-index)
        children = list(root)
        assert len(children) == 5
        assert children[0].tag == "mission"
        assert children[1].tag == "context"
        assert children[2].tag == "variables"
        assert children[3].tag == "instructions"
        assert children[4].tag == "output-template"

    def test_root_element_is_compiled_workflow(self) -> None:
        """Root element is <compiled-workflow>."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        assert root.tag == "compiled-workflow"

    def test_xml_is_parseable(self) -> None:
        """Generated XML is valid and parseable."""
        compiled = create_test_compiled_workflow(
            mission="Complex <mission> with & chars",
            variables={"key": "value with <special> chars"},
        )
        result = generate_output(compiled)

        # Should not raise
        root = ET.fromstring(result.xml)
        assert root is not None

    def test_utf8_encoding(self) -> None:
        """Output uses UTF-8 encoding for Unicode content."""
        compiled = create_test_compiled_workflow(
            mission="日本語テスト ąęćżźół émoji 🎉",
        )
        result = generate_output(compiled)

        # Verify content preserved after encoding/decoding
        root = ET.fromstring(result.xml)
        mission = root.find("mission")
        assert mission is not None
        assert "日本語テスト" in mission.text
        assert "ąęćżźół" in mission.text
        assert "🎉" in mission.text


class TestContextSectionOrdering:
    """Tests for AC2: Context file ordering."""

    def test_context_file_ordering(self, tmp_path: Path) -> None:
        """Context files are ordered general to specific."""
        # Create real files for deterministic path resolution
        (tmp_path / "docs" / "epics").mkdir(parents=True)
        for name in ["project_context.md", "prd.md", "ux.md", "architecture.md"]:
            (tmp_path / "docs" / name).write_text(f"{name} content")
        (tmp_path / "docs" / "epics" / "epic-2.md").write_text("epic content")

        context_files = {
            str(tmp_path / "docs/epics/epic-2.md"): "epic content",
            str(tmp_path / "docs/project_context.md"): "project rules",
            str(tmp_path / "docs/architecture.md"): "arch content",
            str(tmp_path / "docs/prd.md"): "prd content",
            str(tmp_path / "docs/ux.md"): "ux content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        files = list(context_el)

        # Get file paths (now absolute)
        paths = [f.get("path") for f in files]

        # Find indices by substring match (paths are absolute)
        def find_idx(pattern: str) -> int:
            for i, p in enumerate(paths):
                if pattern in p:
                    return i
            raise ValueError(f"Pattern {pattern} not found in {paths}")

        # Verify ordering: project_context -> prd -> ux -> architecture -> epic
        idx_project = find_idx("project_context.md")
        idx_prd = find_idx("prd.md")
        idx_ux = find_idx("ux.md")
        idx_arch = find_idx("architecture.md")
        idx_epic = find_idx("epic-2.md")

        assert idx_project < idx_prd
        assert idx_prd < idx_ux
        assert idx_ux < idx_arch
        assert idx_arch < idx_epic

    def test_absolute_paths_in_output(self, tmp_path: Path) -> None:
        """File paths are absolute for matching with variable values."""
        test_file = tmp_path / "docs" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        context_files = {
            str(test_file): "content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        file_el = context_el.find("file")

        # Path is now relative to project_root (reduces noise)
        path = file_el.get("path")
        assert path == "docs/file.md"
        # Check that label attribute is present
        label = file_el.get("label")
        assert label in ("DOCUMENTATION", "FILE")

    def test_empty_content_files_skipped(self) -> None:
        """Files with empty content are not included."""
        context_files = {
            "/project/docs/file1.md": "has content",
            "/project/docs/file2.md": "",  # Empty - should be skipped
            "/project/docs/file3.md": "also has content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=Path("/project"),
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        files = list(context_el)

        # Only 2 files should be included
        assert len(files) == 2
        paths = [f.get("path") for f in files]
        assert "docs/file2.md" not in paths

    def test_file_wrapped_in_file_element(self, tmp_path: Path) -> None:
        """Each file is wrapped in <file id='...' path='...' label='...'> element."""
        test_file = tmp_path / "docs" / "test.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("test content")

        context_files = {
            str(test_file): "test content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        file_el = context_el.find("file")

        assert file_el is not None
        # Path is now relative to project_root
        assert file_el.get("path") == "docs/test.md"
        # Label attribute is present
        assert file_el.get("label") in ("DOCUMENTATION", "FILE")
        # File has deterministic ID
        assert file_el.get("id") is not None
        assert len(file_el.get("id")) == 8
        # Content is wrapped in CDATA with two newlines
        assert file_el.text == "\n\ntest content\n\n"


class TestVariablesSection:
    """Tests for AC3: Variable section generation."""

    def test_variables_sorted_alphabetically(self) -> None:
        """Variables are sorted alphabetically by name."""
        compiled = create_test_compiled_workflow(variables={"zebra": 1, "alpha": 2, "beta": 3})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")
        var_names = [v.get("name") for v in vars_el]

        assert var_names == ["alpha", "beta", "zebra"]

    def test_simple_variable_serialization(self) -> None:
        """Simple values are serialized as strings."""
        compiled = create_test_compiled_workflow(
            variables={
                "str_val": "hello",
                "int_val": 42,
                "float_val": 3.14,
                "bool_val": True,
            }
        )
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")

        str_var = vars_el.find("var[@name='str_val']")
        assert str_var.text == "hello"

        int_var = vars_el.find("var[@name='int_val']")
        assert int_var.text == "42"

        float_var = vars_el.find("var[@name='float_val']")
        assert float_var.text == "3.14"

        bool_var = vars_el.find("var[@name='bool_val']")
        assert bool_var.text == "True"

    def test_complex_variable_serialization(self) -> None:
        """Complex values are serialized as JSON with sorted keys."""
        compiled = create_test_compiled_workflow(
            variables={
                "list_val": [1, 2, 3],
                "dict_val": {"z_key": "z", "a_key": "a"},
            }
        )
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")

        list_var = vars_el.find("var[@name='list_val']")
        assert list_var.text == "[1, 2, 3]"

        dict_var = vars_el.find("var[@name='dict_val']")
        # Keys MUST be sorted for determinism (NFR11)
        assert dict_var.text == '{"a_key": "a", "z_key": "z"}'

    def test_none_variable_empty_element(self) -> None:
        """None values are represented as empty elements."""
        compiled = create_test_compiled_workflow(variables={"none_val": None})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")

        none_var = vars_el.find("var[@name='none_val']")
        assert none_var is not None
        # Empty element - text is None or empty string
        assert none_var.text is None or none_var.text == ""

    def test_non_serializable_variable_raises(self) -> None:
        """Non-JSON-serializable types raise CompilerError."""
        compiled = create_test_compiled_workflow(variables={"path_obj": Path("/some/path")})

        with pytest.raises(CompilerError, match="non-JSON-serializable"):
            generate_output(compiled)

    def test_variable_name_case_preserved(self) -> None:
        """Variable names preserve original case."""
        compiled = create_test_compiled_workflow(variables={"Epic_Num": 1, "story_KEY": "abc"})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")

        var_names = [v.get("name") for v in vars_el]
        assert "Epic_Num" in var_names
        assert "story_KEY" in var_names


class TestSpecialCharacterEscaping:
    """Tests for AC4: Content escaping and special characters."""

    def test_special_characters_escaped(self) -> None:
        """XML special characters are properly escaped."""
        compiled = create_test_compiled_workflow(
            mission='Task with <special> & "characters"',
            variables={"path": "a < b & c > d"},
        )
        result = generate_output(compiled)

        # Should be valid XML (parseable)
        root = ET.fromstring(result.xml)

        # Content should be preserved after parsing
        mission = root.find("mission").text
        assert "<special>" in mission
        assert "&" in mission
        assert '"' in mission

    def test_unicode_characters_preserved(self) -> None:
        """Unicode characters are preserved (UTF-8)."""
        compiled = create_test_compiled_workflow(
            mission="Emoji 🚀 and Kanji 漢字",
            output_template="Polish: żółć",
        )
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)

        mission = root.find("mission").text
        assert "🚀" in mission
        assert "漢字" in mission

        output = root.find("output-template").text
        assert "żółć" in output

    def test_embedded_xml_in_instructions_preserved(self) -> None:
        """Embedded XML in instructions is preserved as raw XML (not escaped).

        Instructions from filter_instructions() contain valid XML that must
        be embedded literally, not escaped as text content.
        """
        # Valid XML structure - instructions must be valid XML
        compiled = create_test_compiled_workflow(
            instructions="<action>Do something</action>",
        )
        result = generate_output(compiled)

        # Should be valid XML
        root = ET.fromstring(result.xml)

        instructions = root.find("instructions")
        # Instructions are embedded as XML, so we find child elements
        action = instructions.find("action")
        assert action is not None
        assert action.text == "Do something"


class TestTokenEstimation:
    """Tests for AC5: Token estimation."""

    def test_token_estimation(self) -> None:
        """Token estimate is calculated correctly."""
        compiled = create_test_compiled_workflow(
            mission="X" * 400  # 400 chars = ~100 tokens
        )
        result = generate_output(compiled)

        # Estimate should be approximately len(xml) / 4
        expected_min = len(result.xml) // 5
        expected_max = len(result.xml) // 3
        assert expected_min <= result.token_estimate <= expected_max

    def test_token_estimate_stored_in_result(self) -> None:
        """Token estimate is stored in return value."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        assert isinstance(result.token_estimate, int)
        assert result.token_estimate > 0


class TestEmptyAndEdgeCases:
    """Tests for AC6: Empty and edge cases."""

    def test_empty_mission(self) -> None:
        """Empty mission generates valid XML."""
        compiled = create_test_compiled_workflow(mission="")
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        mission = root.find("mission")
        assert mission is not None

    def test_empty_context(self) -> None:
        """Empty context generates valid XML."""
        compiled = create_test_compiled_workflow(context="")
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        context = root.find("context")
        assert context is not None

    def test_empty_variables(self) -> None:
        """Empty variables dict generates valid XML."""
        compiled = create_test_compiled_workflow(variables={})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        variables = root.find("variables")
        assert variables is not None
        assert len(list(variables)) == 0

    def test_empty_instructions(self) -> None:
        """Empty instructions generates valid XML."""
        compiled = create_test_compiled_workflow(instructions="")
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        instructions = root.find("instructions")
        assert instructions is not None

    def test_empty_output_template(self) -> None:
        """Empty output template generates valid XML."""
        compiled = create_test_compiled_workflow(output_template="")
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        output = root.find("output-template")
        assert output is not None

    def test_all_empty_sections(self) -> None:
        """All empty sections generate valid XML."""
        compiled = CompiledWorkflow(
            workflow_name="test",
            mission="",
            context="",
            variables={},
            instructions="",
            output_template="",
        )
        result = generate_output(compiled)

        # Should be valid XML
        root = ET.fromstring(result.xml)

        # All sections should exist
        assert root.find("mission") is not None
        assert root.find("context") is not None
        assert root.find("variables") is not None
        assert root.find("instructions") is not None
        assert root.find("output-template") is not None

    def test_large_content(self) -> None:
        """Large content (>100KB) is handled."""
        large_content = "X" * (150 * 1024)  # 150KB
        compiled = create_test_compiled_workflow(mission=large_content)

        # Should not raise
        result = generate_output(compiled)
        assert result.size_bytes > 100 * 1024


class TestReturnType:
    """Tests for AC7: Return type and API."""

    def test_return_type_is_generated_output(self) -> None:
        """Return type is GeneratedOutput dataclass."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        assert isinstance(result, GeneratedOutput)

    def test_return_type_fields(self) -> None:
        """Return type has correct field types."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        assert isinstance(result.xml, str)
        assert isinstance(result.token_estimate, int)
        assert isinstance(result.size_bytes, int)

    def test_size_bytes_is_utf8_size(self) -> None:
        """size_bytes matches UTF-8 encoded size."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        assert result.size_bytes == len(result.xml.encode("utf-8"))

    def test_idempotency(self) -> None:
        """Same input produces identical output."""
        compiled = create_test_compiled_workflow(
            mission="Test mission",
            variables={"a": 1, "b": 2},
        )

        result1 = generate_output(compiled)
        result2 = generate_output(compiled)

        assert result1.xml == result2.xml
        assert result1.token_estimate == result2.token_estimate
        assert result1.size_bytes == result2.size_bytes

    def test_generated_output_is_frozen(self) -> None:
        """GeneratedOutput is immutable (frozen dataclass)."""
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled)

        # Should raise FrozenInstanceError
        with pytest.raises(AttributeError):
            result.xml = "new value"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_serialize_value_string(self) -> None:
        """String values are serialized as-is."""
        assert _serialize_value("hello") == "hello"

    def test_serialize_value_int(self) -> None:
        """Int values are serialized as string."""
        assert _serialize_value(42) == "42"

    def test_serialize_value_float(self) -> None:
        """Float values are serialized as string."""
        assert _serialize_value(3.14) == "3.14"

    def test_serialize_value_bool(self) -> None:
        """Bool values are serialized as string."""
        assert _serialize_value(True) == "True"
        assert _serialize_value(False) == "False"

    def test_serialize_value_none(self) -> None:
        """None is serialized as empty string."""
        assert _serialize_value(None) == ""

    def test_serialize_value_list(self) -> None:
        """Lists are serialized as JSON."""
        assert _serialize_value([1, 2, 3]) == "[1, 2, 3]"

    def test_serialize_value_dict_sorted(self) -> None:
        """Dicts are serialized as JSON with sorted keys."""
        assert _serialize_value({"z": 1, "a": 2}) == '{"a": 2, "z": 1}'

    def test_serialize_value_nested(self) -> None:
        """Nested structures are serialized correctly."""
        value = {"outer": {"inner": [1, 2, 3]}}
        result = _serialize_value(value)
        assert result == '{"outer": {"inner": [1, 2, 3]}}'

    def test_get_file_order_key_project_context(self) -> None:
        """project_context files have lowest order."""
        key = _get_file_order_key("docs/project_context.md")
        assert key[0] == 0

    def test_get_file_order_key_prd(self) -> None:
        """Prd files have order 1."""
        key = _get_file_order_key("docs/prd.md")
        assert key[0] == 1

    def test_get_file_order_key_epic(self) -> None:
        """Epic files have high order."""
        key = _get_file_order_key("docs/epics/epic-2.md")
        epic_order = key[0]
        # Epics should be last in defined patterns
        assert epic_order == len(FILE_ORDER_PATTERNS) - 1

    def test_get_file_order_key_unknown(self) -> None:
        """Unknown files get maximum order."""
        key = _get_file_order_key("docs/random-file.md")
        assert key[0] == len(FILE_ORDER_PATTERNS)

    def test_normalize_path_returns_absolute(self, tmp_path: Path) -> None:
        """_normalize_path returns absolute path string."""
        test_file = tmp_path / "docs" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("test")

        result = _normalize_path(test_file)

        assert result.startswith("/") or result[1] == ":"  # Unix or Windows
        assert str(tmp_path) in result

    def test_normalize_path_forward_slashes(self, tmp_path: Path) -> None:
        """Paths always use forward slashes (NFR11 determinism)."""
        test_file = tmp_path / "docs" / "sub" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("test")

        result = _normalize_path(test_file)

        # Should NOT contain backslashes
        assert "\\" not in result
        assert "/" in result

    def test_generate_file_id_deterministic(self) -> None:
        """Same path produces same ID."""
        path = "/project/docs/file.md"
        id1 = _generate_file_id(path)
        id2 = _generate_file_id(path)

        assert id1 == id2
        assert len(id1) == 8

    def test_generate_file_id_different_paths(self) -> None:
        """Different paths produce different IDs."""
        id1 = _generate_file_id("/project/docs/file1.md")
        id2 = _generate_file_id("/project/docs/file2.md")

        assert id1 != id2


class TestEdgeCasesExtended:
    """Extended edge case tests."""

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        """File paths with spaces are handled correctly."""
        test_file = tmp_path / "docs" / "my file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        context_files = {
            str(test_file): "content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        file_el = context_el.find("file")
        # Path is absolute and contains the space
        assert "my file.md" in file_el.get("path")

    def test_deeply_nested_dict_variable(self) -> None:
        """Deeply nested dict variables are serialized."""
        deep_dict = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        compiled = create_test_compiled_workflow(variables={"deep": deep_dict})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")
        var = vars_el.find("var[@name='deep']")
        assert "deep" in var.text

    def test_empty_string_variable(self) -> None:
        """Empty string variable is preserved."""
        compiled = create_test_compiled_workflow(variables={"empty": ""})
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        vars_el = root.find("variables")
        var = vars_el.find("var[@name='empty']")
        # Empty string should be preserved (not None)
        assert var is not None
        assert var.text == "" or var.text is None  # Both valid for empty

    def test_default_project_root(self) -> None:
        """Default project_root uses cwd."""
        compiled = create_test_compiled_workflow()
        # Should not raise even without project_root
        result = generate_output(compiled)
        assert result.xml is not None

    def test_context_fallback_to_compiled_context(self) -> None:
        """Without context_files, uses compiled.context."""
        compiled = create_test_compiled_workflow(context="Raw context content")
        result = generate_output(compiled)

        root = ET.fromstring(result.xml)
        context_el = root.find("context")
        # Context is wrapped in CDATA with two newlines
        assert context_el.text == "\n\nRaw context content\n\n"

    def test_datetime_raises_compiler_error(self) -> None:
        """Datetime objects raise CompilerError."""
        from datetime import datetime

        compiled = create_test_compiled_workflow(variables={"dt": datetime.now()})

        with pytest.raises(CompilerError, match="non-JSON-serializable"):
            generate_output(compiled)

    def test_custom_object_raises_compiler_error(self) -> None:
        """Custom objects raise CompilerError."""

        class CustomClass:
            pass

        compiled = create_test_compiled_workflow(variables={"obj": CustomClass()})

        with pytest.raises(CompilerError, match="non-JSON-serializable"):
            generate_output(compiled)

    def test_empty_path_in_context_files_skipped(self, tmp_path: Path) -> None:
        """Empty paths in context_files are skipped."""
        test_file = tmp_path / "docs" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("valid content")

        context_files = {
            "": "content for empty path",
            str(test_file): "valid content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        root = ET.fromstring(result.xml)
        files = list(root.find("context"))
        # Only the valid path should be included
        assert len(files) == 1
        assert "file.md" in files[0].get("path")

    def test_empty_context_files_dict(self) -> None:
        """Empty context_files dict generates empty context element."""
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=Path("/project"),
            context_files={},  # Empty dict - should use structured context path
        )

        root = ET.fromstring(result.xml)
        context = root.find("context")
        assert context is not None
        # Empty dict should result in empty context (no files)
        assert len(list(context)) == 0

    def test_path_separator_normalization_in_xml(self, tmp_path: Path) -> None:
        """Paths in XML output use forward slashes on all platforms."""
        test_file = tmp_path / "docs" / "sub" / "nested" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        context_files = {
            str(test_file): "content",
        }
        compiled = create_test_compiled_workflow()
        result = generate_output(
            compiled,
            project_root=tmp_path,
            context_files=context_files,
        )

        # Raw XML should NOT contain backslashes in path attribute
        assert "\\" not in result.xml
        # Path contains forward slashes (absolute path now)
        assert "docs/sub/nested/file.md" in result.xml


# ==============================================================================
# Attributed Variable Tests
# ==============================================================================


class TestAttributedVariables:
    """Tests for attributed variables with XML attributes."""

    def test_attributed_var_with_all_attributes(self) -> None:
        """Attributed variable renders all attributes."""
        variables = {
            "architecture_file": {
                "_value": "/project/docs/architecture.md",
                "_description": "Architecture documentation",
                "_load_strategy": "FULL_LOAD",
                "_sharded": "true",
                "_token_approx": "1500",
            }
        }
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled)

        assert 'name="architecture_file"' in result.xml
        assert 'description="Architecture documentation"' in result.xml
        assert 'load_strategy="FULL_LOAD"' in result.xml
        assert 'sharded="true"' in result.xml
        assert 'token_approx="1500"' in result.xml
        assert "/project/docs/architecture.md" in result.xml

    def test_attributed_var_without_value(self) -> None:
        """Attributed variable without value renders as self-closing tag."""
        variables = {
            "missing_file": {
                "_description": "File not found",
            }
        }
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled)

        assert 'name="missing_file"' in result.xml
        assert 'description="File not found"' in result.xml
        # Self-closing tag
        assert "<var " in result.xml
        assert "/>" in result.xml

    def test_attributed_var_token_approx_only(self) -> None:
        """Attributed variable can have token_approx without other optional attrs."""
        variables = {
            "small_file": {
                "_value": "/project/docs/small.md",
                "_description": "Small file",
                "_load_strategy": "FULL_LOAD",
                "_token_approx": "250",
            }
        }
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled)

        assert 'token_approx="250"' in result.xml
        # Should not have sharded
        assert "sharded=" not in result.xml

    def test_simple_and_attributed_vars_mixed(self) -> None:
        """Simple and attributed variables render correctly together."""
        variables = {
            "simple_var": "simple_value",
            "attributed_var": {
                "_value": "/some/path",
                "_description": "A file",
                "_load_strategy": "FULL_LOAD",
                "_token_approx": "100",
            },
        }
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled)

        # Both should be present
        assert 'name="simple_var"' in result.xml
        assert ">simple_value<" in result.xml
        assert 'name="attributed_var"' in result.xml
        assert 'token_approx="100"' in result.xml


# ==============================================================================
# File ID Cross-Referencing Tests
# ==============================================================================


class TestFileIdCrossReferencing:
    """Tests for file ID cross-referencing between context files and variables."""

    def test_file_has_id_attribute(self, tmp_path: Path) -> None:
        """Each file element has deterministic id attribute."""
        test_file = tmp_path / "docs" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        context_files = {str(test_file): "content"}
        compiled = create_test_compiled_workflow()
        result = generate_output(compiled, project_root=tmp_path, context_files=context_files)

        root = ET.fromstring(result.xml)
        file_el = root.find("context/file")

        assert file_el.get("id") is not None
        assert len(file_el.get("id")) == 8

    def test_variable_gets_file_id_when_matching_embedded_file(self, tmp_path: Path) -> None:
        """Variable pointing to embedded file gets file_id and EMBEDDED strategy."""
        test_file = tmp_path / "docs" / "architecture.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("architecture content")

        abs_path = str(test_file.resolve())
        context_files = {abs_path: "architecture content"}
        variables = {
            "architecture_file": {
                "_value": abs_path,
                "_description": "Architecture docs",
                "_load_strategy": "FULL_LOAD",  # Should be overridden to EMBEDDED
            }
        }
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled, project_root=tmp_path, context_files=context_files)

        root = ET.fromstring(result.xml)

        # Get the file ID from context
        file_el = root.find("context/file")
        file_id = file_el.get("id")

        # Variable should have same file_id
        var_el = root.find("variables/var[@name='architecture_file']")
        assert var_el.get("file_id") == file_id
        # load_strategy should be overridden to EMBEDDED
        assert var_el.get("load_strategy") == "EMBEDDED"

    def test_simple_variable_gets_file_id(self, tmp_path: Path) -> None:
        """Simple string variable with file path gets file_id."""
        test_file = tmp_path / "docs" / "epics.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("epics content")

        abs_path = str(test_file.resolve())
        context_files = {abs_path: "epics content"}
        variables = {"epics_path": abs_path}  # Simple variable, not attributed
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled, project_root=tmp_path, context_files=context_files)

        root = ET.fromstring(result.xml)
        var_el = root.find("variables/var[@name='epics_path']")

        assert var_el.get("file_id") is not None
        assert len(var_el.get("file_id")) == 8

    def test_variable_without_matching_file_has_no_file_id(self) -> None:
        """Variable not matching any embedded file has no file_id."""
        variables = {"some_path": "/nonexistent/path/file.md"}
        compiled = create_test_compiled_workflow(variables=variables)
        result = generate_output(compiled, context_files={})

        root = ET.fromstring(result.xml)
        var_el = root.find("variables/var[@name='some_path']")

        assert var_el.get("file_id") is None

    def test_file_id_is_deterministic(self, tmp_path: Path) -> None:
        """Same file path produces same ID across multiple generations."""
        test_file = tmp_path / "docs" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        context_files = {str(test_file): "content"}
        compiled = create_test_compiled_workflow()

        # Generate twice
        result1 = generate_output(compiled, project_root=tmp_path, context_files=context_files)
        result2 = generate_output(compiled, project_root=tmp_path, context_files=context_files)

        root1 = ET.fromstring(result1.xml)
        root2 = ET.fromstring(result2.xml)

        id1 = root1.find("context/file").get("id")
        id2 = root2.find("context/file").get("id")

        assert id1 == id2
