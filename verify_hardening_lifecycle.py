import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from bmad_assist.core.epic_lifecycle import get_epic_lifecycle_status, EpicLifecycleStatus
from bmad_assist.core.state import Phase
from bmad_assist.core.types import EpicId

class TestEpicLifecycleStatus(unittest.TestCase):
    def setUp(self):
        self.project_path = Path("/tmp/mock-project")
        self.config = MagicMock()
        self.config.loop.epic_teardown = ["hardening"]
        self.project_state = MagicMock()
        
        # Mock stories - all done
        story1 = MagicMock()
        story1.number = "4.1"
        story1.status = "done"
        self.project_state.all_stories = [story1]

    @patch("bmad_assist.core.epic_lifecycle._check_retro_exists")
    @patch("bmad_assist.core.epic_lifecycle._check_hardening_completed")
    @patch("bmad_assist.core.epic_lifecycle.is_qa_enabled")
    def test_hardening_required(self, mock_is_qa, mock_check_hardening, mock_check_retro):
        mock_is_qa.return_value = False
        mock_check_retro.return_value = True
        mock_check_hardening.return_value = False # Pending

        status = get_epic_lifecycle_status(
            epic_id=4,
            project_state=self.project_state,
            config=self.config,
            project_path=self.project_path
        )

        self.assertTrue(status.all_stories_done)
        self.assertTrue(status.retro_completed)
        self.assertTrue(status.hardening_enabled)
        self.assertFalse(status.hardening_completed)
        self.assertEqual(status.next_phase, Phase.HARDENING)
        self.assertFalse(status.is_fully_completed)

    @patch("bmad_assist.core.epic_lifecycle._check_retro_exists")
    @patch("bmad_assist.core.epic_lifecycle._check_hardening_completed")
    @patch("bmad_assist.core.epic_lifecycle.is_qa_enabled")
    def test_hardening_completed(self, mock_is_qa, mock_check_hardening, mock_check_retro):
        mock_is_qa.return_value = False
        mock_check_retro.return_value = True
        mock_check_hardening.return_value = True # Completed

        status = get_epic_lifecycle_status(
            epic_id=4,
            project_state=self.project_state,
            config=self.config,
            project_path=self.project_path
        )

        self.assertTrue(status.all_stories_done)
        self.assertTrue(status.retro_completed)
        self.assertTrue(status.hardening_enabled)
        self.assertTrue(status.hardening_completed)
        self.assertIsNone(status.next_phase)
        self.assertTrue(status.is_fully_completed)

if __name__ == "__main__":
    unittest.main()
