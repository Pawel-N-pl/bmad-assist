import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, io
import sys
from bmad_assist.cli_start_point import _interactive_phase_selection
from bmad_assist.core.state import Phase
from bmad_assist.core.epic_lifecycle import EpicLifecycleStatus

class TestCLISelection(unittest.TestCase):
    def setUp(self):
        self.epic = 4
        self.epic_stories = []
        self.config = MagicMock()
        self.project_path = Path("/tmp/mock-project")
        self.lifecycle = MagicMock(spec=EpicLifecycleStatus)
        self.lifecycle.epic_id = 4
        self.lifecycle.describe.return_value = "ready for hardening"
        self.lifecycle.retro_completed = True
        self.lifecycle.hardening_enabled = True
        self.lifecycle.hardening_completed = False
        self.lifecycle.qa_plan_generated = True
        self.lifecycle.qa_plan_executed = True
        self.lifecycle.last_story = "4.5"

    @patch("bmad_assist.cli_start_point.is_non_interactive")
    @patch("bmad_assist.cli_start_point.console")
    @patch("bmad_assist.cli_start_point._save_phase_state")
    @patch("bmad_assist.core.epic_lifecycle.is_qa_enabled")
    def test_hardening_selection(self, mock_is_qa, mock_save, mock_console, mock_non_interactive):
        mock_non_interactive.return_value = False
        mock_is_qa.return_value = False
        
        # Simulate user typing 'h' and then 'Enter'
        with patch("sys.stdin", io.StringIO("h\n")):
            result = _interactive_phase_selection(
                self.epic, self.epic_stories, self.config, self.project_path, self.lifecycle
            )
            
        self.assertIsNone(result)
        mock_save.assert_called_once_with(
            self.config, self.project_path, self.epic, "4.5", Phase.HARDENING
        )

if __name__ == "__main__":
    unittest.main()
