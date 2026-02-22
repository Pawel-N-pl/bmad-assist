"""Tests for HardeningCompiler logic changes.

Verifies:
- next_epic_id removed from variables
- Mission text updated for triage
- Variables resolved correctly
"""

import pytest
from unittest.mock import MagicMock

from bmad_assist.compiler.workflows.hardening import HardeningCompiler


class TestHardeningCompiler:
    """Tests for HardeningCompiler."""

    @pytest.fixture
    def compiler(self):
        return HardeningCompiler()

    def test_get_variables_removed_next_epic_id(self, compiler):
        """next_epic_id should not be in required variables anymore."""
        vars = compiler.get_variables()
        assert "epic_num" in vars
        assert "next_epic_id" not in vars

    def test_build_mission_updated_for_triage(self, compiler):
        """Mission text should reflect triage behavior."""
        workflow_ir = MagicMock()
        workflow_ir.raw_config = {"description": "Initial desc"}
        resolved = {"epic_num": "5"}
        
        mission = compiler._build_mission(workflow_ir, resolved)
        
        assert "Target: Epic 5 Hardening Triage" in mission
        assert "Assess action items and decide" in mission
        assert "no_action / direct_fix / story_needed" in mission

    def test_compile_resolves_variables_without_next_epic_id(self, compiler):
        """Verify compile flow doesn't compute next_epic_id."""
        from unittest.mock import patch, MagicMock
        
        context = MagicMock()
        context.workflow_ir = MagicMock()
        context.resolved_variables = {"epic_num": "5"}
        
        # Mock everything called by compile() to avoid side effects
        resolved_vars = {"epic_num": "5"}
        with patch("bmad_assist.compiler.workflows.hardening.context_snapshot"):
            with patch("bmad_assist.compiler.workflows.hardening.find_sprint_status_file"):
                with patch("bmad_assist.compiler.workflows.hardening.resolve_variables", return_value=resolved_vars):
                    with patch.object(HardeningCompiler, "_build_context_files", return_value={}):
                        with patch("bmad_assist.compiler.workflows.hardening.filter_instructions", return_value="instr"):
                            with patch("bmad_assist.compiler.workflows.hardening.substitute_variables", return_value="instr"):
                                with patch("bmad_assist.compiler.workflows.hardening.generate_output") as mock_gen:
                                    mock_gen.return_value = MagicMock(xml="<xml/>", token_estimate=100)
                                    with patch("bmad_assist.compiler.workflows.hardening.apply_post_process", return_value="<xml/>"):
                                        with patch.object(HardeningCompiler, "_build_mission", return_value="mission"):
                                            result = compiler.compile(context)
        
        # Ensure next_epic_id was NOT added to resolved vars in compile()
        assert "next_epic_id" not in resolved_vars
        mock_gen.assert_called_once()
        assert result.mission == "mission"
        assert result.variables == {"epic_num": "5"}
