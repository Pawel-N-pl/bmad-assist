"""Tests for gitignore setup utilities."""

from pathlib import Path

from bmad_assist.git.gitignore import (
    check_gitignore,
    ensure_gitignore,
    setup_gitignore,
)


class TestCheckGitignore:
    """Tests for check_gitignore function."""

    def test_no_gitignore_returns_all_missing(self, tmp_path: Path) -> None:
        """When .gitignore doesn't exist, all patterns are missing."""
        all_present, missing = check_gitignore(tmp_path)

        assert all_present is False
        assert ".bmad-assist/cache/" in missing
        assert "*.meta.yaml" in missing
        assert "*.tpl.xml" in missing

    def test_empty_gitignore_returns_all_missing(self, tmp_path: Path) -> None:
        """Empty .gitignore means all patterns missing."""
        (tmp_path / ".gitignore").write_text("")

        all_present, missing = check_gitignore(tmp_path)

        assert all_present is False
        assert len(missing) == 3  # 3 non-comment patterns

    def test_complete_gitignore_returns_all_present(self, tmp_path: Path) -> None:
        """When all patterns exist, returns True with empty missing list."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "# bmad-assist artifacts\n.bmad-assist/cache/\n*.meta.yaml\n*.tpl.xml\n"
        )

        all_present, missing = check_gitignore(tmp_path)

        assert all_present is True
        assert missing == []

    def test_partial_gitignore_returns_missing(self, tmp_path: Path) -> None:
        """When some patterns exist, returns the missing ones."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".bmad-assist/cache/\n")

        all_present, missing = check_gitignore(tmp_path)

        assert all_present is False
        assert "*.meta.yaml" in missing
        assert "*.tpl.xml" in missing
        assert ".bmad-assist/cache/" not in missing


class TestSetupGitignore:
    """Tests for setup_gitignore function."""

    def test_creates_gitignore_if_missing(self, tmp_path: Path) -> None:
        """Creates new .gitignore with patterns when none exists."""
        changed, message = setup_gitignore(tmp_path)

        assert changed is True
        assert "Created" in message

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".bmad-assist/cache/" in content
        assert "*.meta.yaml" in content
        assert "*.tpl.xml" in content

    def test_appends_to_existing_gitignore(self, tmp_path: Path) -> None:
        """Appends patterns to existing .gitignore."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# Existing content\nnode_modules/\n")

        changed, message = setup_gitignore(tmp_path)

        assert changed is True
        content = gitignore.read_text()
        # Original content preserved
        assert "node_modules/" in content
        # New patterns added
        assert ".bmad-assist/cache/" in content
        assert "*.meta.yaml" in content

    def test_idempotent_when_already_setup(self, tmp_path: Path) -> None:
        """Running setup twice doesn't duplicate patterns."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "# bmad-assist artifacts (auto-generated, never commit)\n"
            ".bmad-assist/cache/\n"
            "*.meta.yaml\n"
            "*.tpl.xml\n"
        )

        changed, message = setup_gitignore(tmp_path)

        assert changed is False
        assert "already" in message.lower()

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Dry run reports changes but doesn't make them."""
        changed, message = setup_gitignore(tmp_path, dry_run=True)

        assert changed is True
        assert "Would" in message
        assert not (tmp_path / ".gitignore").exists()


class TestEnsureGitignore:
    """Tests for ensure_gitignore function."""

    def test_auto_creates_gitignore(self, tmp_path: Path) -> None:
        """Silently creates .gitignore if missing."""
        ensure_gitignore(tmp_path)

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".bmad-assist/cache/" in content

    def test_no_op_when_already_setup(self, tmp_path: Path) -> None:
        """Does nothing when patterns already present."""
        gitignore = tmp_path / ".gitignore"
        original = "# Complete setup\n.bmad-assist/cache/\n*.meta.yaml\n*.tpl.xml\n"
        gitignore.write_text(original)

        ensure_gitignore(tmp_path)

        # Content unchanged
        assert gitignore.read_text() == original
