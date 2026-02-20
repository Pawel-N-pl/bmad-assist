"""Tests for BoundaryAnalysisMethod class."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    MethodId,
    Severity,
)
from bmad_assist.deep_verify.methods import BoundaryAnalysisMethod, ChecklistItem, ChecklistLoader

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_checklist_items() -> list[ChecklistItem]:
    """Create sample checklist items for testing."""
    return [
        ChecklistItem(
            id="GEN-001",
            category="empty_input",
            question="Does the code handle empty input gracefully?",
            description="Empty strings, empty arrays, empty maps should not cause crashes",
            severity=Severity.ERROR,
            domain="general",
        ),
        ChecklistItem(
            id="GEN-002",
            category="null_handling",
            question="Does the code handle nil/null values safely?",
            description="Null pointer dereferences should be prevented",
            severity=Severity.CRITICAL,
            domain="general",
        ),
        ChecklistItem(
            id="SEC-BOUNDARY-001",
            category="auth_bypass",
            question="Are all authentication bypasses intentional?",
            description="Undocumented auth bypasses create security vulnerabilities",
            severity=Severity.CRITICAL,
            domain="security",
        ),
    ]


@pytest.fixture
def temp_checklist_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with test checklist files."""
    checklists_dir = tmp_path / "checklists"
    checklists_dir.mkdir()

    # General checklist
    general_yaml = {
        "checklist": [
            {
                "id": "GEN-001",
                "category": "empty_input",
                "question": "Does the code handle empty input gracefully?",
                "description": "Empty strings should not cause crashes",
                "severity_if_violated": "error",
                "domain": "general",
            },
            {
                "id": "GEN-002",
                "category": "null_handling",
                "question": "Does the code handle nil/null values safely?",
                "description": "Null pointer dereferences should be prevented",
                "severity_if_violated": "critical",
                "domain": "general",
            },
        ]
    }

    # Security checklist
    security_yaml = {
        "checklist": [
            {
                "id": "SEC-BOUNDARY-001",
                "category": "auth_bypass",
                "question": "Are all authentication bypasses intentional?",
                "description": "Undocumented auth bypasses create security vulnerabilities",
                "severity_if_violated": "critical",
                "domain": "security",
            },
        ]
    }

    # Storage checklist
    storage_yaml = {
        "checklist": [
            {
                "id": "STORAGE-BOUNDARY-001",
                "category": "transaction_boundaries",
                "question": "Are transactions properly scoped?",
                "description": "Missing transaction boundaries can cause data inconsistency",
                "severity_if_violated": "error",
                "domain": "storage",
            },
        ]
    }

    # Messaging checklist
    messaging_yaml = {
        "checklist": [
            {
                "id": "MSG-BOUNDARY-001",
                "category": "ordering_guarantees",
                "question": "Is message ordering handled correctly?",
                "description": "Out-of-order message processing can cause issues",
                "severity_if_violated": "error",
                "domain": "messaging",
            },
        ]
    }

    with open(checklists_dir / "general.yaml", "w") as f:
        yaml.dump(general_yaml, f)
    with open(checklists_dir / "security.yaml", "w") as f:
        yaml.dump(security_yaml, f)
    with open(checklists_dir / "storage.yaml", "w") as f:
        yaml.dump(storage_yaml, f)
    with open(checklists_dir / "messaging.yaml", "w") as f:
        yaml.dump(messaging_yaml, f)

    return checklists_dir


@pytest.fixture
def mock_llm_response_violated() -> str:
    """Mock LLM response indicating violation found."""
    return """```json
{
    "violated": true,
    "confidence": 0.95,
    "evidence_quote": "return data[0]",
    "line_number": 3,
    "explanation": "No check for empty list before accessing index 0"
}
```"""


@pytest.fixture
def mock_llm_response_clean() -> str:
    """Mock LLM response indicating no violation."""
    return """```json
{
    "violated": false,
    "confidence": 0.9,
    "evidence_quote": "",
    "explanation": "Code properly handles empty input with early return"
}
```"""


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock ClaudeSDKProvider."""
    mock = MagicMock()
    mock_result = MagicMock()
    mock_result.stdout = json.dumps([
        {
            "id": "GEN-001",
            "violated": True,
            "confidence": 0.95,
            "evidence_quote": "return data[0]",
            "line_number": 3,
            "explanation": "No check for empty list before accessing index 0",
        },
        {
            "id": "GEN-002",
            "violated": True,
            "confidence": 0.9,
            "evidence_quote": "data[0]",
            "line_number": 3,
            "explanation": "No null check",
        },
    ])
    mock_result.stderr = ""
    mock_result.exit_code = 0
    mock.invoke.return_value = mock_result
    mock.parse_output.return_value = mock_result.stdout
    return mock


# =============================================================================
# Test ChecklistItem
# =============================================================================


class TestChecklistItem:
    """Tests for ChecklistItem dataclass."""

    def test_checklist_item_creation(self) -> None:
        """Test creating a ChecklistItem."""
        item = ChecklistItem(
            id="GEN-001",
            category="empty_input",
            question="Does the code handle empty input?",
            description="Empty strings should not cause crashes",
            severity=Severity.ERROR,
            domain="general",
        )

        assert item.id == "GEN-001"
        assert item.category == "empty_input"
        assert item.question == "Does the code handle empty input?"
        assert item.severity == Severity.ERROR
        assert item.domain == "general"

    def test_checklist_item_repr(self) -> None:
        """Test ChecklistItem repr string."""
        item = ChecklistItem(
            id="GEN-001",
            category="empty_input",
            question="Does the code handle empty input?",
            description="Empty strings should not cause crashes",
            severity=Severity.ERROR,
            domain="general",
        )

        repr_str = repr(item)
        assert "ChecklistItem" in repr_str
        assert "GEN-001" in repr_str
        assert "empty_input" in repr_str


# =============================================================================
# Test ChecklistLoader
# =============================================================================


class TestChecklistLoader:
    """Tests for ChecklistLoader class."""

    def test_loader_creation(self, temp_checklist_dir: Path) -> None:
        """Test creating a ChecklistLoader."""
        loader = ChecklistLoader(temp_checklist_dir)

        assert loader._checklist_dir == temp_checklist_dir

    def test_load_general_only(self, temp_checklist_dir: Path) -> None:
        """Test loading only general checklist."""
        loader = ChecklistLoader(temp_checklist_dir)
        items = loader.load(domains=None)

        # Should only load general.yaml
        assert len(items) == 2
        assert all(item.domain == "general" for item in items)
        assert any(item.id == "GEN-001" for item in items)
        assert any(item.id == "GEN-002" for item in items)

    def test_load_with_security_domain(self, temp_checklist_dir: Path) -> None:
        """Test loading general + security checklists."""
        loader = ChecklistLoader(temp_checklist_dir)
        items = loader.load(domains=[ArtifactDomain.SECURITY])

        # Should load general.yaml + security.yaml
        assert len(items) == 3
        general_items = [i for i in items if i.domain == "general"]
        security_items = [i for i in items if i.domain == "security"]
        assert len(general_items) == 2
        assert len(security_items) == 1
        assert security_items[0].id == "SEC-BOUNDARY-001"

    def test_load_with_multiple_domains(self, temp_checklist_dir: Path) -> None:
        """Test loading with multiple domains."""
        loader = ChecklistLoader(temp_checklist_dir)
        items = loader.load(domains=[ArtifactDomain.SECURITY, ArtifactDomain.STORAGE])

        # Should load general + security + storage
        assert len(items) == 4
        assert any(item.id == "GEN-001" for item in items)
        assert any(item.id == "SEC-BOUNDARY-001" for item in items)
        assert any(item.id == "STORAGE-BOUNDARY-001" for item in items)

    def test_load_deduplication(self, temp_checklist_dir: Path) -> None:
        """Test that duplicate IDs are deduplicated."""
        # Create a checklist with duplicate ID
        duplicate_yaml = {
            "checklist": [
                {
                    "id": "GEN-001",  # Duplicate of general.yaml
                    "category": "duplicate",
                    "question": "Duplicate question?",
                    "description": "This should override the first",
                    "severity_if_violated": "warning",
                    "domain": "storage",
                },
            ]
        }
        with open(temp_checklist_dir / "storage.yaml", "w") as f:
            yaml.dump(duplicate_yaml, f)

        loader = ChecklistLoader(temp_checklist_dir)
        items = loader.load(domains=[ArtifactDomain.STORAGE])

        # Should have only one GEN-001 (from storage, loaded later)
        gen001_items = [i for i in items if i.id == "GEN-001"]
        assert len(gen001_items) == 1
        assert gen001_items[0].domain == "storage"

    def test_load_missing_file(self, temp_checklist_dir: Path) -> None:
        """Test loading when a domain file doesn't exist."""
        # Remove security.yaml
        (temp_checklist_dir / "security.yaml").unlink()

        loader = ChecklistLoader(temp_checklist_dir)
        items = loader.load(domains=[ArtifactDomain.SECURITY])

        # Should still load general items
        assert len(items) == 2
        assert all(item.domain == "general" for item in items)

    def test_load_invalid_yaml(self, temp_checklist_dir: Path) -> None:
        """Test loading with invalid YAML content raises error."""
        # Create invalid YAML file
        with open(temp_checklist_dir / "security.yaml", "w") as f:
            f.write("invalid: yaml: content: [")

        loader = ChecklistLoader(temp_checklist_dir)

        # Should raise RuntimeError for domain-specific checklist failures
        with pytest.raises(RuntimeError, match="Failed to parse checklist"):
            loader.load(domains=[ArtifactDomain.SECURITY])


# =============================================================================
# Test BoundaryAnalysisMethod Creation
# =============================================================================


class TestBoundaryAnalysisMethodCreation:
    """Tests for BoundaryAnalysisMethod instantiation."""

    def test_method_instantiation_defaults(self) -> None:
        """Test creating BoundaryAnalysisMethod with defaults."""
        method = BoundaryAnalysisMethod()

        assert method.method_id == MethodId("#154")
        assert method._threshold == 0.6
        assert method._model == "haiku"
        assert method._timeout == 60

    def test_method_instantiation_custom_threshold(self) -> None:
        """Test creating BoundaryAnalysisMethod with custom threshold."""
        method = BoundaryAnalysisMethod(threshold=0.8)

        assert method._threshold == 0.8

    def test_method_instantiation_custom_model(self) -> None:
        """Test creating BoundaryAnalysisMethod with custom model."""
        method = BoundaryAnalysisMethod(model="sonnet")

        assert method._model == "sonnet"

    def test_method_instantiation_custom_checklist_dir(
        self, temp_checklist_dir: Path
    ) -> None:
        """Test creating BoundaryAnalysisMethod with custom checklist directory."""
        method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

        assert method._loader._checklist_dir == temp_checklist_dir

    def test_invalid_threshold_raises_value_error(self) -> None:
        """Test that invalid threshold values raise ValueError."""
        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            BoundaryAnalysisMethod(threshold=-0.1)

        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            BoundaryAnalysisMethod(threshold=1.5)

    def test_method_repr(self) -> None:
        """Test method repr string."""
        method = BoundaryAnalysisMethod()
        repr_str = repr(method)

        assert "BoundaryAnalysisMethod" in repr_str
        assert "method_id='#154'" in repr_str
        assert "model='haiku'" in repr_str
        assert "threshold=0.6" in repr_str


# =============================================================================
# Test LLM Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for batched LLM response parsing."""

    def test_parse_json_array_in_code_block(self) -> None:
        """Test parsing JSON array inside markdown code block."""
        method = BoundaryAnalysisMethod()
        response = """```json
[
    {
        "id": "GEN-001",
        "violated": true,
        "confidence": 0.95,
        "evidence_quote": "test quote",
        "line_number": 5,
        "explanation": "test explanation"
    }
]
```"""

        results = method._parse_batch_response(response)

        assert len(results) == 1
        assert results[0].violated is True
        assert results[0].confidence == 0.95
        assert results[0].evidence_quote == "test quote"
        assert results[0].line_number == 5
        assert results[0].id == "GEN-001"

    def test_parse_json_array_without_language_tag(self) -> None:
        """Test parsing JSON array in code block without language tag."""
        method = BoundaryAnalysisMethod()
        response = """```
[{"id": "GEN-001", "violated": false, "confidence": 0.8}]
```"""

        results = method._parse_batch_response(response)

        assert len(results) == 1
        assert results[0].violated is False
        assert results[0].confidence == 0.8

    def test_parse_raw_json_array(self) -> None:
        """Test parsing raw JSON array without code block."""
        method = BoundaryAnalysisMethod()
        response = '[{"id": "GEN-001", "violated": true, "confidence": 0.9}]'

        results = method._parse_batch_response(response)

        assert len(results) == 1
        assert results[0].violated is True
        assert results[0].confidence == 0.9

    def test_parse_invalid_json_returns_empty(self) -> None:
        """Test that invalid JSON returns empty list via fallback."""
        method = BoundaryAnalysisMethod()
        response = "This is not JSON"

        results = method._parse_batch_response(response)

        assert results == []

    def test_parse_multiple_items(self) -> None:
        """Test parsing batch response with multiple items."""
        method = BoundaryAnalysisMethod()
        response = json.dumps([
            {"id": "GEN-001", "violated": True, "confidence": 0.9},
            {"id": "GEN-002", "violated": False, "confidence": 0.8},
        ])

        results = method._parse_batch_response(response)

        assert len(results) == 2
        assert results[0].id == "GEN-001"
        assert results[0].violated is True
        assert results[1].id == "GEN-002"
        assert results[1].violated is False

    def test_parse_missing_fields_uses_defaults(self) -> None:
        """Test parsing JSON with missing optional fields."""
        method = BoundaryAnalysisMethod()
        response = '[{"id": "GEN-001", "violated": true, "confidence": 0.7}]'

        results = method._parse_batch_response(response)

        assert len(results) == 1
        assert results[0].violated is True
        assert results[0].confidence == 0.7
        assert results[0].evidence_quote == ""
        assert results[0].line_number is None
        assert results[0].explanation == ""


# =============================================================================
# Test Finding Creation
# =============================================================================


class TestFindingCreation:
    """Tests for finding creation from analysis results."""

    def test_create_finding_with_all_fields(self) -> None:
        """Test creating a finding with all fields populated."""
        from bmad_assist.deep_verify.methods.boundary_analysis import (
            ChecklistAnalysisResponse,
        )

        method = BoundaryAnalysisMethod()
        result = ChecklistAnalysisResponse(
            violated=True,
            confidence=0.95,
            evidence_quote="return data[0]",
            line_number=5,
            explanation="No empty check",
        )
        item = ChecklistItem(
            id="GEN-001",
            category="empty_input",
            question="Does the code handle empty input?",
            description="Empty strings should not cause crashes",
            severity=Severity.ERROR,
            domain="general",
        )

        finding = method._create_finding(result, item, 0)

        assert finding.id == "#154-F1"
        assert finding.severity == Severity.ERROR
        assert finding.title == "Does the code handle empty input?"
        assert finding.method_id == MethodId("#154")
        assert finding.pattern_id == "GEN-001"
        assert len(finding.evidence) == 1
        assert finding.evidence[0].quote == "return data[0]"
        assert finding.evidence[0].line_number == 5

    def test_create_finding_no_evidence(self) -> None:
        """Test creating a finding without evidence quote."""
        from bmad_assist.deep_verify.methods.boundary_analysis import (
            ChecklistAnalysisResponse,
        )

        method = BoundaryAnalysisMethod()
        result = ChecklistAnalysisResponse(
            violated=True,
            confidence=0.9,
            evidence_quote="",
            line_number=None,
            explanation="",
        )
        item = ChecklistItem(
            id="GEN-001",
            category="empty_input",
            question="Does the code handle empty input?",
            description="Empty strings should not cause crashes",
            severity=Severity.ERROR,
            domain="general",
        )

        finding = method._create_finding(result, item, 0)

        assert len(finding.evidence) == 0

    def test_create_finding_title_truncation(self) -> None:
        """Test that long titles are truncated to 80 characters."""
        from bmad_assist.deep_verify.methods.boundary_analysis import (
            ChecklistAnalysisResponse,
        )

        method = BoundaryAnalysisMethod()
        result = ChecklistAnalysisResponse(
            violated=True,
            confidence=0.9,
            evidence_quote="test",
            explanation="",
        )
        long_question = "A" * 100
        item = ChecklistItem(
            id="GEN-001",
            category="test",
            question=long_question,
            description="Test",
            severity=Severity.ERROR,
            domain="general",
        )

        finding = method._create_finding(result, item, 0)

        assert len(finding.title) == 80
        assert finding.title.endswith("...")

    def test_create_finding_security_domain(self) -> None:
        """Test that security domain is properly mapped."""
        from bmad_assist.deep_verify.methods.boundary_analysis import (
            ChecklistAnalysisResponse,
        )

        method = BoundaryAnalysisMethod()
        result = ChecklistAnalysisResponse(
            violated=True,
            confidence=0.9,
            evidence_quote="test",
        )
        item = ChecklistItem(
            id="SEC-BOUNDARY-001",
            category="auth_bypass",
            question="Auth bypass intentional?",
            description="Undocumented bypasses are bad",
            severity=Severity.CRITICAL,
            domain="security",
        )

        finding = method._create_finding(result, item, 0)

        assert finding.domain == ArtifactDomain.SECURITY


# =============================================================================
# Test Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Tests for batch prompt building."""

    def test_build_batch_prompt_includes_all_items(self) -> None:
        """Test that batch prompt includes all checklist item details."""
        method = BoundaryAnalysisMethod()
        items = [
            ChecklistItem(
                id="GEN-001",
                category="empty_input",
                question="Does the code handle empty input?",
                description="Empty strings should not cause crashes",
                severity=Severity.ERROR,
                domain="general",
            ),
            ChecklistItem(
                id="GEN-002",
                category="null_handling",
                question="Does the code handle null?",
                description="Null should not cause crashes",
                severity=Severity.ERROR,
                domain="general",
            ),
        ]

        prompt = method._build_batch_prompt("code here", items)

        assert "GEN-001" in prompt
        assert "GEN-002" in prompt
        assert "empty_input" in prompt
        assert "null_handling" in prompt
        assert "Does the code handle empty input?" in prompt
        assert "Does the code handle null?" in prompt
        assert "code here" in prompt
        assert "(2 items)" in prompt

    def test_build_batch_prompt_truncates_artifact(self) -> None:
        """Test that long artifacts are truncated."""
        method = BoundaryAnalysisMethod()
        items = [
            ChecklistItem(
                id="GEN-001",
                category="empty_input",
                question="Does the code handle empty input?",
                description="Empty strings should not cause crashes",
                severity=Severity.ERROR,
                domain="general",
            ),
        ]
        long_artifact = "x" * 5000

        prompt = method._build_batch_prompt(long_artifact, items)

        # Should be truncated (MAX_ARTIFACT_LENGTH=3000)
        assert len(prompt) < 5500


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_artifact(self, temp_checklist_dir: Path) -> None:
        """Test that empty artifact returns empty findings list."""
        method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

        findings = await method.analyze("")

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_artifact(self, temp_checklist_dir: Path) -> None:
        """Test that whitespace-only artifact returns empty findings."""
        method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

        findings = await method.analyze("   \n\t  \n")

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_finding_id_format(self, temp_checklist_dir: Path, mock_provider: MagicMock) -> None:
        """Test that finding IDs use method-prefixed format."""
        with patch(
            "bmad_assist.deep_verify.methods.boundary_analysis.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

            artifact = (
                "def process_data(data):\n"
                "    return data[0]  # No empty check\n"
            )
            findings = await method.analyze(artifact)

            # Should have findings with proper IDs
            if findings:
                assert findings[0].id.startswith("#154-F")

    @pytest.mark.asyncio
    async def test_no_findings_when_not_violated(
        self, temp_checklist_dir: Path, mock_provider: MagicMock
    ) -> None:
        """Test that no findings returned when not violated."""
        # Mock batch response indicating no violations
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([
            {"id": "GEN-001", "violated": False, "confidence": 0.9, "explanation": "Properly handled"},
            {"id": "GEN-002", "violated": False, "confidence": 0.85, "explanation": "Handled"},
        ])
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        with patch(
            "bmad_assist.deep_verify.methods.boundary_analysis.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

            findings = await method.analyze("some code")

            # Should have no findings since not violated
            assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_no_findings_when_below_threshold(
        self, temp_checklist_dir: Path, mock_provider: MagicMock
    ) -> None:
        """Test that no findings returned when confidence below threshold."""
        # Mock batch response with low confidence
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([
            {"id": "GEN-001", "violated": True, "confidence": 0.3, "evidence_quote": "something"},
            {"id": "GEN-002", "violated": True, "confidence": 0.2, "evidence_quote": "other"},
        ])
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        with patch(
            "bmad_assist.deep_verify.methods.boundary_analysis.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = BoundaryAnalysisMethod(
                checklist_dir=temp_checklist_dir, threshold=0.6
            )

            findings = await method.analyze("some code")

            # Should have no findings since below threshold
            assert len(findings) == 0


# =============================================================================
# Test Domain Filtering
# =============================================================================


class TestDomainFiltering:
    """Tests for domain-aware checklist filtering."""

    @pytest.mark.asyncio
    async def test_general_checklist_always_loaded(
        self, temp_checklist_dir: Path, mock_provider: MagicMock
    ) -> None:
        """Test that general checklist is always loaded regardless of domains."""
        with patch(
            "bmad_assist.deep_verify.methods.boundary_analysis.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

            # Should load general + security items
            items = method._loader.load(domains=[ArtifactDomain.SECURITY])
            general_items = [i for i in items if i.domain == "general"]
            security_items = [i for i in items if i.domain == "security"]

            assert len(general_items) == 2
            assert len(security_items) == 1

    @pytest.mark.asyncio
    async def test_multiple_domains_load_all_checklists(
        self, temp_checklist_dir: Path
    ) -> None:
        """Test loading checklists for multiple domains."""
        method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

        items = method._loader.load(
            domains=[ArtifactDomain.SECURITY, ArtifactDomain.STORAGE]
        )

        # Should have general + security + storage
        assert len(items) == 4
        ids = {item.id for item in items}
        assert "GEN-001" in ids
        assert "SEC-BOUNDARY-001" in ids
        assert "STORAGE-BOUNDARY-001" in ids


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_graceful_failure_on_llm_error(
        self, temp_checklist_dir: Path, mock_provider: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that LLM errors return empty results with logged warning."""
        # Make provider raise exception (single batched call fails)
        mock_provider.invoke.side_effect = Exception("LLM error")

        with patch(
            "bmad_assist.deep_verify.methods.boundary_analysis.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = BoundaryAnalysisMethod(checklist_dir=temp_checklist_dir)

            with caplog.at_level(logging.WARNING):
                findings = await method.analyze("some code")

            # Should return empty and log warning
            assert len(findings) == 0
            assert "Boundary analysis failed" in caplog.text

    @pytest.mark.asyncio
    async def test_no_checklists_available(self, tmp_path: Path) -> None:
        """Test behavior when no checklists are available."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        method = BoundaryAnalysisMethod(checklist_dir=empty_dir)

        findings = await method.analyze("some code")

        assert len(findings) == 0
