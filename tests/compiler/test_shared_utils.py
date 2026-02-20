"""Tests for shared_utils module.

Tests cover:
- context_snapshot() context manager for state preservation
- apply_post_process() helper for patch application
- Enhanced load_workflow_template() with embedded template support
"""

from pathlib import Path

import pytest

from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.core.exceptions import CompilerError


class TestContextSnapshotAC3:
    """Test AC3: Context manager for state preservation."""

    def test_context_snapshot_preserves_state_on_success(self, tmp_path: Path) -> None:
        """State modifications are kept on successful execution."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            resolved_variables={"key": "original"},
            discovered_files={"file1": Path("/a")},
            file_contents={"file1": "content1"},
        )

        with context_snapshot(context):
            context.resolved_variables["key"] = "modified"
            context.resolved_variables["new_key"] = "new_value"
            context.discovered_files["file2"] = Path("/b")
            context.file_contents["file2"] = "content2"

        # Changes should persist
        assert context.resolved_variables["key"] == "modified"
        assert context.resolved_variables["new_key"] == "new_value"
        assert "file2" in context.discovered_files
        assert "file2" in context.file_contents

    def test_context_snapshot_restores_state_on_exception(self, tmp_path: Path) -> None:
        """State is restored to original on exception."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            resolved_variables={"key": "original"},
            discovered_files={"file1": Path("/a")},
            file_contents={"file1": "content1"},
        )

        with pytest.raises(ValueError, match="test error"), context_snapshot(context):
            context.resolved_variables["key"] = "modified"
            context.resolved_variables["new_key"] = "new_value"
            context.discovered_files["file2"] = Path("/b")
            context.file_contents["file2"] = "content2"
            raise ValueError("test error")

        # Changes should be rolled back
        assert context.resolved_variables["key"] == "original"
        assert "new_key" not in context.resolved_variables
        assert "file2" not in context.discovered_files
        assert "file2" not in context.file_contents

    def test_context_snapshot_preserves_resolved_variables(self, tmp_path: Path) -> None:
        """Specifically tests resolved_variables preservation."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            resolved_variables={"epic_num": 10, "story_num": 5},
        )

        with pytest.raises(RuntimeError), context_snapshot(context):
            context.resolved_variables["epic_num"] = 99
            context.resolved_variables["extra"] = "data"
            raise RuntimeError("rollback trigger")

        assert context.resolved_variables["epic_num"] == 10
        assert context.resolved_variables["story_num"] == 5
        assert "extra" not in context.resolved_variables

    def test_context_snapshot_preserves_discovered_files(self, tmp_path: Path) -> None:
        """Specifically tests discovered_files preservation."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        original_path = Path("/original/path")
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            discovered_files={"existing": original_path},
        )

        with pytest.raises(RuntimeError), context_snapshot(context):
            context.discovered_files["existing"] = Path("/modified")
            context.discovered_files["new"] = Path("/new")
            raise RuntimeError("rollback trigger")

        assert context.discovered_files["existing"] == original_path
        assert "new" not in context.discovered_files

    def test_context_snapshot_preserves_file_contents(self, tmp_path: Path) -> None:
        """Specifically tests file_contents preservation."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            file_contents={"file.py": "# original code"},
        )

        with pytest.raises(RuntimeError), context_snapshot(context):
            context.file_contents["file.py"] = "# modified code"
            context.file_contents["new_file.py"] = "# new code"
            raise RuntimeError("rollback trigger")

        assert context.file_contents["file.py"] == "# original code"
        assert "new_file.py" not in context.file_contents

    def test_context_snapshot_yields_context(self, tmp_path: Path) -> None:
        """Context manager yields the context object."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        with context_snapshot(context) as ctx:
            assert ctx is context

    def test_context_snapshot_handles_empty_context(self, tmp_path: Path) -> None:
        """Works with empty/default context values."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )
        # Ensure empty dicts by default
        assert context.resolved_variables == {}
        assert context.discovered_files == {}
        assert context.file_contents == {}

        with pytest.raises(RuntimeError), context_snapshot(context):
            context.resolved_variables["new"] = "value"
            raise RuntimeError("trigger")

        assert context.resolved_variables == {}

    def test_context_snapshot_nested_exceptions(self, tmp_path: Path) -> None:
        """Exception type is preserved through context manager."""
        from bmad_assist.compiler.shared_utils import context_snapshot

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            resolved_variables={"key": "value"},
        )

        # Test with CompilerError
        with pytest.raises(CompilerError, match="compiler error"):
            with context_snapshot(context):
                context.resolved_variables["key"] = "modified"
                raise CompilerError("compiler error")

        # State should be restored
        assert context.resolved_variables["key"] == "value"


class TestApplyPostProcessAC2:
    """Test AC2: apply_post_process() helper for patch application."""

    def test_apply_post_process_with_patch(self, tmp_path: Path) -> None:
        """Applies post_process rules from patch file."""
        from bmad_assist.compiler.shared_utils import apply_post_process

        # Create a valid patch file with all required fields
        patch_path = tmp_path / "test.patch.yaml"
        patch_path.write_text("""
patch:
  name: test-patch
  version: "1.0.0"
compatibility:
  bmad_version: "6.0.0"
  workflow: "test-workflow"
transforms:
  - "No-op transform"
post_process:
  - pattern: "PLACEHOLDER"
    replacement: "REPLACED"
""")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            patch_path=patch_path,
        )

        xml_content = "<compiled-workflow>PLACEHOLDER content</compiled-workflow>"
        result = apply_post_process(xml_content, context)

        assert "REPLACED content" in result
        assert "PLACEHOLDER" not in result

    def test_apply_post_process_no_patch(self, tmp_path: Path) -> None:
        """Returns original XML when no patch_path is set."""
        from bmad_assist.compiler.shared_utils import apply_post_process

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            patch_path=None,
        )

        xml_content = "<compiled-workflow>Original content</compiled-workflow>"
        result = apply_post_process(xml_content, context)

        assert result == xml_content

    def test_apply_post_process_patch_not_found(self, tmp_path: Path) -> None:
        """Returns original XML when patch file doesn't exist."""
        from bmad_assist.compiler.shared_utils import apply_post_process

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            patch_path=tmp_path / "nonexistent.patch.yaml",
        )

        xml_content = "<compiled-workflow>Original content</compiled-workflow>"
        result = apply_post_process(xml_content, context)

        assert result == xml_content

    def test_apply_post_process_empty_rules(self, tmp_path: Path) -> None:
        """Returns original XML when patch has no post_process rules."""
        from bmad_assist.compiler.shared_utils import apply_post_process

        patch_path = tmp_path / "empty.patch.yaml"
        patch_path.write_text("""
# No post_process section
template_transforms: []
""")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
            patch_path=patch_path,
        )

        xml_content = "<compiled-workflow>Content</compiled-workflow>"
        result = apply_post_process(xml_content, context)

        assert result == xml_content


class TestLoadWorkflowTemplateEnhancedAC2:
    """Test AC2: Enhanced load_workflow_template() with embedded template support."""

    def test_load_workflow_template_embedded_template(self, tmp_path: Path) -> None:
        """Uses embedded output_template when available."""
        from bmad_assist.compiler.shared_utils import load_workflow_template

        workflow_ir = WorkflowIR(
            name="test-workflow",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=str(tmp_path / "template.md"),  # Should be ignored
            validation_path=None,
            raw_config={},
            raw_instructions="",
            output_template="# Embedded Template\n\nContent from cache",  # Has embedded
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        # Even though template_path is set, embedded should take priority
        result = load_workflow_template(workflow_ir, context)

        assert result == "# Embedded Template\n\nContent from cache"

    def test_load_workflow_template_file_fallback(self, tmp_path: Path) -> None:
        """Falls back to file when no embedded template."""
        from bmad_assist.compiler.shared_utils import load_workflow_template

        # Create template file
        template_path = tmp_path / "template.md"
        template_path.write_text("# File Template\n\n{{placeholder}}")

        workflow_ir = WorkflowIR(
            name="test-workflow",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=str(template_path),
            validation_path=None,
            raw_config={},
            raw_instructions="",
            output_template=None,  # No embedded
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = load_workflow_template(workflow_ir, context)

        assert "# File Template" in result
        assert "{{placeholder}}" in result

    def test_load_workflow_template_no_template(self, tmp_path: Path) -> None:
        """Returns empty string when no template defined."""
        from bmad_assist.compiler.shared_utils import load_workflow_template

        workflow_ir = WorkflowIR(
            name="test-workflow",
            config_path=tmp_path / "workflow.yaml",
            instructions_path=tmp_path / "instructions.xml",
            template_path=None,
            validation_path=None,
            raw_config={},
            raw_instructions="",
            output_template=None,
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = load_workflow_template(workflow_ir, context)

        assert result == ""

    def test_load_workflow_template_path_resolution(self, tmp_path: Path) -> None:
        """Resolves {installed_path} and {project-root} placeholders."""
        from bmad_assist.compiler.shared_utils import load_workflow_template

        # Create workflow directory structure
        workflow_dir = tmp_path / "workflows" / "test"
        workflow_dir.mkdir(parents=True)
        template_file = workflow_dir / "template.md"
        template_file.write_text("# Template with path resolution")

        workflow_ir = WorkflowIR(
            name="test-workflow",
            config_path=workflow_dir / "workflow.yaml",
            instructions_path=workflow_dir / "instructions.xml",
            template_path="{installed_path}/template.md",
            validation_path=None,
            raw_config={},
            raw_instructions="",
            output_template=None,
        )

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = load_workflow_template(workflow_ir, context)

        assert "# Template with path resolution" in result


class TestFindEpicFileAC2:
    """Test AC2: Enhanced find_epic_file() with fallback logic.

    Tests cover three search paths:
    1. output_folder/epics/epic-{epic_num}*.md (sharded epics)
    2. output_folder/epics.md (single file)
    3. output_folder/*epic*.md (glob fallback)
    """

    def test_find_epic_file_sharded_epics_directory(self, tmp_path: Path) -> None:
        """Search 1: Finds epic in sharded epics directory."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # Create sharded epics directory structure
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()
        epic_file = epics_dir / "epic-12-compiler-consolidation.md"
        epic_file.write_text("# Epic 12: Compiler Consolidation")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 12)

        assert result is not None
        assert result.name == "epic-12-compiler-consolidation.md"

    def test_find_epic_file_single_epics_file(self, tmp_path: Path) -> None:
        """Search 2: Falls back to single epics.md file."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # No sharded directory, but single epics.md exists
        epics_file = tmp_path / "epics.md"
        epics_file.write_text("# All Epics\n\n## Epic 5: Test")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 5)

        assert result is not None
        assert result.name == "epics.md"

    def test_find_epic_file_glob_fallback(self, tmp_path: Path) -> None:
        """Search 3: Falls back to glob pattern *epic*.md."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # No sharded directory, no epics.md, but file with 'epic' in name
        epic_file = tmp_path / "project-epic-definitions.md"
        epic_file.write_text("# Project Epics")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 3)

        assert result is not None
        assert "epic" in result.name.lower()

    def test_find_epic_file_priority_sharded_over_single(self, tmp_path: Path) -> None:
        """Sharded epics have priority over single epics.md."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # Create both sharded and single epics
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()
        sharded_epic = epics_dir / "epic-7-dashboard.md"
        sharded_epic.write_text("# Epic 7: Dashboard")

        single_epics = tmp_path / "epics.md"
        single_epics.write_text("# All Epics")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 7)

        # Should find sharded epic, not single file
        assert result is not None
        assert result.name == "epic-7-dashboard.md"

    def test_find_epic_file_priority_single_over_glob(self, tmp_path: Path) -> None:
        """Single epics.md has priority over glob fallback."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # Create single epics.md and another epic-like file
        single_epics = tmp_path / "epics.md"
        single_epics.write_text("# All Epics")

        other_epic = tmp_path / "my-epic-file.md"
        other_epic.write_text("# Other Epic File")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 1)

        # Should find epics.md, not my-epic-file.md
        assert result is not None
        assert result.name == "epics.md"

    def test_find_epic_file_no_match(self, tmp_path: Path) -> None:
        """Returns None when no epic file found."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # Empty output folder
        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, 99)

        assert result is None

    def test_find_epic_file_string_epic_num(self, tmp_path: Path) -> None:
        """Works with string epic identifiers like 'testarch'."""
        from bmad_assist.compiler.shared_utils import find_epic_file

        # Create sharded epic with string identifier
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()
        epic_file = epics_dir / "epic-testarch-test-architect.md"
        epic_file.write_text("# Module: testarch")

        context = CompilerContext(
            project_root=tmp_path,
            output_folder=tmp_path,
        )

        result = find_epic_file(context, "testarch")

        assert result is not None
        assert "testarch" in result.name


class TestEstimateTokensAC2:
    """Test AC2: estimate_tokens() for token estimation.

    This function provides a simple heuristic (~4 chars/token) for estimating
    token counts, moved from dev_story.py and code_review.py to shared_utils.
    """

    def test_estimate_tokens_simple_content(self) -> None:
        """Estimates tokens for simple content."""
        from bmad_assist.compiler.shared_utils import estimate_tokens

        # 40 characters / 4 = 10 tokens
        content = "a" * 40
        result = estimate_tokens(content)
        assert result == 10

    def test_estimate_tokens_empty_string(self) -> None:
        """Returns 0 for empty content."""
        from bmad_assist.compiler.shared_utils import estimate_tokens

        result = estimate_tokens("")
        assert result == 0

    def test_estimate_tokens_short_content(self) -> None:
        """Handles content shorter than 4 characters."""
        from bmad_assist.compiler.shared_utils import estimate_tokens

        # 3 chars / 4 = 0 tokens (integer division)
        result = estimate_tokens("abc")
        assert result == 0

        # 4 chars / 4 = 1 token
        result = estimate_tokens("abcd")
        assert result == 1

    def test_estimate_tokens_realistic_code(self) -> None:
        """Estimates tokens for realistic code content."""
        from bmad_assist.compiler.shared_utils import estimate_tokens

        code = '''def hello_world():
    """Say hello to the world."""
    print("Hello, World!")
    return True
'''
        result = estimate_tokens(code)
        # ~100 chars / 4 = ~25 tokens
        assert result > 20
        assert result < 40

    def test_estimate_tokens_multiline(self) -> None:
        """Counts all characters including newlines."""
        from bmad_assist.compiler.shared_utils import estimate_tokens

        # Each line is 10 chars + newline = 11 chars
        # 5 lines = 55 chars / 4 = 13 tokens
        content = "0123456789\n" * 5
        result = estimate_tokens(content)
        assert result == 13  # 55 / 4 = 13 (integer division)


class TestFormatDvFindingsForPrompt:
    """Tests for format_dv_findings_for_prompt()."""

    def _make_findings(self, **overrides: object) -> dict:
        """Build a code_review handler-style DV findings dict."""
        base: dict = {
            "verdict": "REJECT",
            "score": 8.5,
            "findings_count": 1,
            "critical_count": 1,
            "error_count": 0,
            "domains": [{"domain": "security", "confidence": 0.95}],
            "methods": ["#153"],
            "findings": [
                {
                    "id": "F1",
                    "severity": "critical",
                    "title": "SQL Injection Risk",
                    "description": "User input not sanitized",
                    "method": "#153",
                    "domain": "security",
                    "evidence": [
                        {"quote": 'query = f"SELECT * FROM {table}"', "line_number": 42}
                    ],
                }
            ],
        }
        base.update(overrides)
        return base

    def _make_serialize_findings(self, **overrides: object) -> dict:
        """Build a serialize_validation_result-style DV findings dict."""
        base: dict = {
            "verdict": "REJECT",
            "score": 7.0,
            "domains_detected": [{"domain": "concurrency", "confidence": 0.8}],
            "methods_executed": ["#201", "#202"],
            "findings": [
                {
                    "id": "F1",
                    "severity": "error",
                    "title": "Race Condition",
                    "description": "Shared state without lock",
                    "method_id": "#201",
                    "domain": "concurrency",
                    "evidence": [
                        {"quote": "self.data[key] = value", "line_number": 99, "confidence": 0.9}
                    ],
                }
            ],
        }
        base.update(overrides)
        return base

    def test_basic_formatting(self) -> None:
        """Basic code_review handler format produces expected markdown."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        result = format_dv_findings_for_prompt(self._make_findings())
        assert "# Deep Verify Analysis Results" in result
        assert "**Verdict:** REJECT" in result
        assert "**Score:** 8.5" in result
        assert "SQL Injection Risk" in result
        assert "Line 42" in result
        assert "**Method:** #153" in result

    def test_serialize_format(self) -> None:
        """serialize_validation_result format (domains_detected/methods_executed/method_id)."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        result = format_dv_findings_for_prompt(self._make_serialize_findings())
        assert "**Verdict:** REJECT" in result
        assert "concurrency" in result
        assert "#201" in result
        assert "Race Condition" in result
        assert "**Method:** #201" in result
        assert "Line 99" in result

    def test_counts_computed_from_findings_when_missing(self) -> None:
        """When pre-computed count fields absent, compute from findings list."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        data = self._make_serialize_findings()
        # serialize format has no count fields
        assert "findings_count" not in data
        result = format_dv_findings_for_prompt(data)
        assert "**Findings:** 1 " in result
        assert "(0 critical, 1 error)" in result

    def test_invalid_input_returns_fallback(self) -> None:
        """Non-dict input returns safe fallback string."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        assert "No data available" in format_dv_findings_for_prompt("not a dict")  # type: ignore[arg-type]
        assert "No data available" in format_dv_findings_for_prompt(None)  # type: ignore[arg-type]

    def test_empty_findings_no_orphan_header(self) -> None:
        """Empty findings list doesn't produce orphan ## Findings header."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        data = self._make_findings(findings=[])
        result = format_dv_findings_for_prompt(data)
        assert "## Findings" not in result

    def test_malformed_domain_skipped(self) -> None:
        """Non-dict domain entries are skipped gracefully."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        data = self._make_findings(domains=["not-a-dict", {"domain": "security", "confidence": 0.9}])
        result = format_dv_findings_for_prompt(data)
        assert "security" in result
        # no crash

    def test_line_number_without_quote(self) -> None:
        """Line number shown even when quote is empty."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        data = self._make_findings(
            findings=[
                {
                    "id": "F1",
                    "severity": "warning",
                    "title": "Test",
                    "description": "desc",
                    "method": "#1",
                    "evidence": [{"quote": "", "line_number": 77}],
                }
            ]
        )
        result = format_dv_findings_for_prompt(data)
        assert "Line 77" in result

    def test_no_findings_no_domains_no_methods(self) -> None:
        """Minimal dict with no optional fields still produces valid output."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        result = format_dv_findings_for_prompt({"verdict": "ACCEPT", "score": 0.0})
        assert "**Verdict:** ACCEPT" in result
        assert "## Findings" not in result
        assert "None" in result  # methods fallback


class TestPrioritizeFindings:
    """Tests for _prioritize_findings() helper."""

    def _make_finding(
        self,
        finding_id: str = "F1",
        severity: str = "warning",
        domain: str = "security",
        file_path: str = "src/app.py",
        confidence: float = 0.8,
        line_number: int = 10,
    ) -> dict:
        return {
            "id": finding_id,
            "severity": severity,
            "title": f"Finding {finding_id}",
            "description": f"Description for {finding_id}",
            "method": "#153",
            "domain": domain,
            "file_path": file_path,
            "evidence": [
                {"quote": "code here", "line_number": line_number, "confidence": confidence}
            ],
        }

    def test_prioritize_critical_never_truncated(self) -> None:
        """25 critical findings with max_findings=20 -> all 25 included."""
        from bmad_assist.compiler.shared_utils import _prioritize_findings

        findings = [
            self._make_finding(f"F{i}", severity="critical", confidence=0.9)
            for i in range(25)
        ]
        result, omitted, omitted_by_sev = _prioritize_findings(findings, max_findings=20)
        assert len(result) == 25
        assert omitted == 0
        assert omitted_by_sev == {}

    def test_prioritize_sort_order(self) -> None:
        """Verify severity -> domain_conf -> file -> evidence_conf ordering."""
        from bmad_assist.compiler.shared_utils import _prioritize_findings

        findings = [
            self._make_finding("F1", severity="warning", domain="a", confidence=0.5),
            self._make_finding("F2", severity="critical", domain="b", confidence=0.3),
            self._make_finding("F3", severity="error", domain="c", confidence=0.9),
            self._make_finding("F4", severity="info", domain="d", confidence=0.99),
        ]
        result, _, _ = _prioritize_findings(findings, max_findings=50)
        severities = [f["severity"] for f in result]
        assert severities == ["critical", "error", "warning", "info"]

    def test_prioritize_domain_integrity(self) -> None:
        """Domain group of 5 at budget edge -> included with overflow; group of 8 -> skipped."""
        from bmad_assist.compiler.shared_utils import _prioritize_findings

        # 3 criticals + budget for 2 more = 5 total budget
        criticals = [
            self._make_finding(f"C{i}", severity="critical") for i in range(3)
        ]
        # A domain group of 5 warnings (within overflow_tolerance=6)
        small_group = [
            self._make_finding(f"S{i}", severity="warning", domain="small-domain")
            for i in range(5)
        ]
        # A domain group of 8 warnings (exceeds overflow_tolerance=6)
        big_group = [
            self._make_finding(f"B{i}", severity="warning", domain="big-domain", confidence=0.1)
            for i in range(8)
        ]

        findings = criticals + small_group + big_group
        result, omitted, omitted_by_sev = _prioritize_findings(
            findings, max_findings=5, overflow_tolerance=6
        )

        # 3 criticals + budget=2 filled from small_group + remaining 3 within overflow
        included_ids = {f["id"] for f in result}
        # All criticals included
        for i in range(3):
            assert f"C{i}" in included_ids
        # Small group (5 items) should be included via overflow tolerance
        for i in range(5):
            assert f"S{i}" in included_ids
        # Big group (8 items) exceeds overflow tolerance -> skipped
        assert omitted == 8
        assert omitted_by_sev.get("warning") == 8

    def test_prioritize_overflow_tolerance_6(self) -> None:
        """Verify +6 overflow tolerance works, +7 doesn't."""
        from bmad_assist.compiler.shared_utils import _prioritize_findings

        # Budget = 0 (0 criticals, max_findings=0)
        # Group of 6 -> fits within overflow_tolerance=6
        group_6 = [
            self._make_finding(f"G{i}", severity="error", domain="dom") for i in range(6)
        ]
        result, omitted, _ = _prioritize_findings(group_6, max_findings=0, overflow_tolerance=6)
        assert len(result) == 6
        assert omitted == 0

        # Group of 7 -> exceeds overflow_tolerance=6
        group_7 = [
            self._make_finding(f"G{i}", severity="error", domain="dom") for i in range(7)
        ]
        result, omitted, _ = _prioritize_findings(group_7, max_findings=0, overflow_tolerance=6)
        assert len(result) == 0
        assert omitted == 7

    def test_domain_avg_confidence_across_files(self) -> None:
        """Same domain from 2 files -> confidences averaged across both."""
        from bmad_assist.compiler.shared_utils import _prioritize_findings

        findings = [
            self._make_finding("F1", domain="auth", file_path="a.py", confidence=0.9,
                               severity="error"),
            self._make_finding("F2", domain="auth", file_path="b.py", confidence=0.5,
                               severity="error"),
            self._make_finding("F3", domain="storage", file_path="c.py", confidence=0.95,
                               severity="error"),
        ]
        result, _, _ = _prioritize_findings(findings, max_findings=50)
        # storage has higher avg confidence (0.95) than auth (0.7)
        # Both are "error" severity, so storage should come first
        assert result[0]["domain"] == "storage"
        assert result[1]["domain"] == "auth"


class TestRenderGroupedFindings:
    """Tests for _render_grouped_findings() and dispatch logic."""

    def _make_finding(
        self,
        finding_id: str = "F1",
        severity: str = "critical",
        domain: str = "security",
        file_path: str = "src/auth/login.py",
        title: str = "SQL injection",
        confidence: float = 0.95,
        line_number: int = 42,
    ) -> dict:
        return {
            "id": finding_id,
            "severity": severity,
            "title": title,
            "description": f"Description for {finding_id}",
            "method": "#153",
            "domain": domain,
            "file_path": file_path,
            "evidence": [
                {"quote": "code here", "line_number": line_number, "confidence": confidence}
            ],
        }

    def test_grouped_rendering_line_ranges(self) -> None:
        """File header shows correct L{min}-L{max}."""
        from bmad_assist.compiler.shared_utils import _render_grouped_findings

        findings = [
            self._make_finding("F1", line_number=42),
            self._make_finding("F2", line_number=112),
        ]
        dv = {"verdict": "REJECT", "score": 8.5, "findings": findings,
              "domains": [], "methods": []}
        result = _render_grouped_findings(findings, 0, {}, dv)
        assert "(L42-L112)" in result

    def test_grouped_rendering_single_line(self) -> None:
        """Single line -> (L42) not (L42-L42)."""
        from bmad_assist.compiler.shared_utils import _render_grouped_findings

        findings = [self._make_finding("F1", line_number=42)]
        dv = {"verdict": "REJECT", "score": 8.5, "findings": findings,
              "domains": [], "methods": []}
        result = _render_grouped_findings(findings, 0, {}, dv)
        assert "(L42)" in result
        assert "(L42-L42)" not in result

    def test_grouped_rendering_omitted_footer(self) -> None:
        """Footer shows correct breakdown."""
        from bmad_assist.compiler.shared_utils import _render_grouped_findings

        findings = [self._make_finding("F1")]
        omitted_by_sev = {"warning": 12, "info": 13}
        dv = {"verdict": "REJECT", "score": 8.5, "findings": findings,
              "domains": [], "methods": []}
        result = _render_grouped_findings(findings, 25, omitted_by_sev, dv)
        assert "25 lower-priority findings omitted" in result
        assert "13 info" in result
        assert "12 warning" in result

    def test_grouped_rendering_severity_domain_file_hierarchy(self) -> None:
        """Correct nesting: severity-domain header, file header, finding lines."""
        from bmad_assist.compiler.shared_utils import _render_grouped_findings

        findings = [
            self._make_finding("F1", severity="critical", domain="security",
                               file_path="src/auth.py", line_number=10),
            self._make_finding("F2", severity="error", domain="error-handling",
                               file_path="src/handler.py", line_number=22),
        ]
        dv = {"verdict": "REJECT", "score": 7.0, "findings": findings,
              "domains": [], "methods": []}
        result = _render_grouped_findings(findings, 0, {}, dv)
        # Severity-domain headers
        assert "### CRITICAL — security" in result
        assert "### ERROR — error-handling" in result
        # File headers
        assert "**src/auth.py**" in result
        assert "**src/handler.py**" in result
        # Finding lines with confidence
        assert "[0.95]" in result
        # CRITICAL comes before ERROR
        crit_pos = result.index("### CRITICAL")
        err_pos = result.index("### ERROR")
        assert crit_pos < err_pos

    def test_dispatch_with_file_path(self) -> None:
        """Findings with file_path -> grouped rendering."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        dv = {
            "verdict": "REJECT",
            "score": 8.5,
            "findings": [self._make_finding("F1", file_path="src/app.py")],
            "domains": [{"domain": "security", "confidence": 0.95}],
            "methods": ["#153"],
        }
        result = format_dv_findings_for_prompt(dv)
        # Grouped format uses "## Findings (N of M" header
        assert "## Findings (1 of 1" in result
        # Has severity-domain header style
        assert "### CRITICAL — security" in result

    def test_dispatch_without_file_path(self) -> None:
        """Findings without file_path -> flat rendering (backward compat)."""
        from bmad_assist.compiler.shared_utils import format_dv_findings_for_prompt

        dv = {
            "verdict": "REJECT",
            "score": 8.5,
            "findings_count": 1,
            "critical_count": 1,
            "error_count": 0,
            "domains": [{"domain": "security", "confidence": 0.95}],
            "methods": ["#153"],
            "findings": [
                {
                    "id": "F1",
                    "severity": "critical",
                    "title": "SQL Injection Risk",
                    "description": "User input not sanitized",
                    "method": "#153",
                    "domain": "security",
                    "evidence": [{"quote": "query = ...", "line_number": 42}],
                }
            ],
        }
        result = format_dv_findings_for_prompt(dv)
        # Flat format uses "## Findings" without count
        assert "## Findings" in result
        assert "## Findings (" not in result
        # Has original-style headers
        assert "### [CRITICAL] F1:" in result
