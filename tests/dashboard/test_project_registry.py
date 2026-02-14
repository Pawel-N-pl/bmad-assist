"""Tests for ProjectRegistry class.

Tests project registration, persistence, concurrency limiting, and queue management.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.dashboard.manager.project_context import LoopState
from bmad_assist.dashboard.manager.registry import (
    DEFAULT_MAX_CONCURRENT_LOOPS,
    ProjectRegistry,
)


class TestProjectRegistryInit:
    """Tests for ProjectRegistry initialization."""

    def test_init_with_defaults(self, tmp_path: Path):
        """Registry initializes with default settings."""
        config_dir = tmp_path / ".config" / "bmad-assist"
        registry = ProjectRegistry(config_dir=config_dir)

        assert registry.config_dir == config_dir
        assert registry.max_concurrent_loops == DEFAULT_MAX_CONCURRENT_LOOPS
        assert len(registry._projects) == 0

    def test_init_creates_config_dir(self, tmp_path: Path):
        """Registry creates config directory if missing."""
        config_dir = tmp_path / ".config" / "bmad-assist"
        assert not config_dir.exists()

        registry = ProjectRegistry(config_dir=config_dir)

        assert config_dir.exists()

    def test_init_loads_server_config(self, tmp_path: Path):
        """Registry loads settings from server.yaml."""
        config_dir = tmp_path / ".config" / "bmad-assist"
        config_dir.mkdir(parents=True)
        (config_dir / "server.yaml").write_text("""
server:
  max_concurrent_loops: 5
  queue_max_size: 20
""")

        registry = ProjectRegistry(config_dir=config_dir)

        assert registry.max_concurrent_loops == 5
        assert registry.queue_max_size == 20


class TestProjectRegistryRegister:
    """Tests for project registration."""

    def test_register_new_project(self, tmp_path: Path):
        """Register a new project returns UUID."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)

        assert project_uuid is not None
        assert len(project_uuid) == 36
        assert project_uuid in registry._projects

    def test_register_with_display_name(self, tmp_path: Path):
        """Register with custom display name."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path, display_name="My Cool Project")

        context = registry.get(project_uuid)
        assert context.display_name == "My Cool Project"

    def test_register_same_path_returns_existing(self, tmp_path: Path):
        """Registering same path returns existing UUID."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        uuid1 = registry.register(project_path)
        uuid2 = registry.register(project_path)

        assert uuid1 == uuid2
        assert len(registry._projects) == 1

    def test_register_nonexistent_path_raises(self, tmp_path: Path):
        """Register nonexistent path raises ValueError."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        with pytest.raises(ValueError, match="does not exist"):
            registry.register(tmp_path / "nonexistent")

    def test_register_persists_to_file(self, tmp_path: Path):
        """Registration persists to projects.yaml."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        registry.register(project_path)

        projects_file = config_dir / "projects.yaml"
        assert projects_file.exists()
        assert "my-project" in projects_file.read_text()


class TestProjectRegistryUnregister:
    """Tests for project unregistration."""

    def test_unregister_project(self, tmp_path: Path):
        """Unregister removes project from registry."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        registry.unregister(project_uuid)

        assert project_uuid not in registry._projects

    def test_unregister_nonexistent_raises(self, tmp_path: Path):
        """Unregister nonexistent UUID raises KeyError."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        with pytest.raises(KeyError):
            registry.unregister("nonexistent-uuid")

    def test_unregister_running_project_raises(self, tmp_path: Path):
        """Unregister running project raises RuntimeError."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        registry.get(project_uuid).state = LoopState.RUNNING

        with pytest.raises(RuntimeError, match="loop is active"):
            registry.unregister(project_uuid)


class TestProjectRegistryLookup:
    """Tests for project lookup methods."""

    def test_get_existing_project(self, tmp_path: Path):
        """get() returns existing project context."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        context = registry.get(project_uuid)

        assert context.project_uuid == project_uuid

    def test_get_nonexistent_raises(self, tmp_path: Path):
        """get() with nonexistent UUID raises KeyError."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        with pytest.raises(KeyError):
            registry.get("nonexistent-uuid")

    def test_get_by_path(self, tmp_path: Path):
        """get_by_path() returns context for path."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        context = registry.get_by_path(project_path)

        assert context is not None
        assert context.project_uuid == project_uuid

    def test_get_by_path_not_found(self, tmp_path: Path):
        """get_by_path() returns None for unknown path."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        context = registry.get_by_path(tmp_path / "unknown")

        assert context is None

    def test_list_all(self, tmp_path: Path):
        """list_all() returns all project summaries."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        for i in range(3):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            registry.register(project_path)

        projects = registry.list_all()

        assert len(projects) == 3
        assert all("uuid" in p for p in projects)


class TestProjectRegistryConcurrency:
    """Tests for concurrency limiting."""

    def test_can_start_loop_under_limit(self, tmp_path: Path):
        """can_start_loop() returns True when under limit."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir, max_concurrent_loops=2)

        assert registry.can_start_loop() is True

    def test_can_start_loop_at_limit(self, tmp_path: Path):
        """can_start_loop() returns False when at limit."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir, max_concurrent_loops=2)

        # Register and start 2 projects
        for i in range(2):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            project_uuid = registry.register(project_path)
            registry.get(project_uuid).state = LoopState.RUNNING

        assert registry.can_start_loop() is False

    def test_get_running_count(self, tmp_path: Path):
        """get_running_count() returns correct count."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        # Register 3 projects, start 2
        for i in range(3):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            project_uuid = registry.register(project_path)
            if i < 2:
                registry.get(project_uuid).state = LoopState.RUNNING

        assert registry.get_running_count() == 2


class TestProjectRegistryQueue:
    """Tests for queue management."""

    def test_enqueue_project(self, tmp_path: Path):
        """enqueue() adds project to queue."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        position = registry.enqueue(project_uuid)

        assert position == 1
        assert project_uuid in registry._queue

    def test_enqueue_returns_existing_position(self, tmp_path: Path):
        """enqueue() returns existing position if already queued."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        registry.enqueue(project_uuid)
        position = registry.enqueue(project_uuid)

        assert position == 1
        assert list(registry._queue).count(project_uuid) == 1

    def test_enqueue_full_raises(self, tmp_path: Path):
        """enqueue() raises when queue is full."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir, queue_max_size=2)

        # Fill queue
        for i in range(2):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            project_uuid = registry.register(project_path)
            registry.enqueue(project_uuid)

        # Try to add one more
        project_path = tmp_path / "project-overflow"
        project_path.mkdir()
        project_uuid = registry.register(project_path)

        with pytest.raises(ValueError, match="Queue is full"):
            registry.enqueue(project_uuid)

    def test_dequeue_returns_first(self, tmp_path: Path):
        """dequeue() returns first project (FIFO)."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        uuids = []
        for i in range(3):
            project_path = tmp_path / f"project-{i}"
            project_path.mkdir()
            project_uuid = registry.register(project_path)
            registry.enqueue(project_uuid)
            uuids.append(project_uuid)

        first = registry.dequeue()

        assert first == uuids[0]

    def test_dequeue_empty_returns_none(self, tmp_path: Path):
        """dequeue() returns None when queue is empty."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        result = registry.dequeue()

        assert result is None

    def test_cancel_queue(self, tmp_path: Path):
        """cancel_queue() removes project from queue."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        registry = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry.register(project_path)
        registry.enqueue(project_uuid)

        result = registry.cancel_queue(project_uuid)

        assert result is True
        assert project_uuid not in registry._queue


class TestProjectRegistryScan:
    """Tests for directory scanning."""

    def test_scan_directory_finds_projects(self, tmp_path: Path):
        """scan_directory() finds projects with .bmad-assist/."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        # Create some projects
        for i in range(2):
            project_path = tmp_path / "projects" / f"project-{i}"
            (project_path / ".bmad-assist").mkdir(parents=True)

        # Create non-project directory
        (tmp_path / "projects" / "not-a-project").mkdir(parents=True)

        discovered = registry.scan_directory(tmp_path / "projects")

        assert len(discovered) == 2
        assert len(registry._projects) == 2

    def test_scan_directory_skips_registered(self, tmp_path: Path):
        """scan_directory() skips already registered projects."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        # Create and register a project
        project_path = tmp_path / "projects" / "project-1"
        (project_path / ".bmad-assist").mkdir(parents=True)
        registry.register(project_path)

        discovered = registry.scan_directory(tmp_path / "projects")

        assert len(discovered) == 0

    def test_scan_nonexistent_directory(self, tmp_path: Path):
        """scan_directory() returns empty for nonexistent dir."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        discovered = registry.scan_directory(tmp_path / "nonexistent")

        assert len(discovered) == 0


class TestProjectRegistryReconcile:
    """Tests for registry reconciliation."""

    def test_reconcile_marks_broken_projects(self, tmp_path: Path):
        """reconcile() marks projects with missing paths."""
        config_dir = tmp_path / "config"
        registry = ProjectRegistry(config_dir=config_dir)

        # Register a project
        project_path = tmp_path / "my-project"
        project_path.mkdir()
        project_uuid = registry.register(project_path)

        # Remove the project directory
        project_path.rmdir()

        broken = registry.reconcile()

        assert project_uuid in broken
        assert registry.get(project_uuid).state == LoopState.ERROR

    def test_reconcile_cleans_stale_flags(self, tmp_path: Path):
        """reconcile() removes stale flag files."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        # Create stale flags
        bmad_dir = project_path / ".bmad-assist"
        bmad_dir.mkdir()
        (bmad_dir / "pause.flag").touch()
        (bmad_dir / "stop.flag").touch()

        registry = ProjectRegistry(config_dir=config_dir)
        registry.register(project_path)
        registry.reconcile()

        assert not (bmad_dir / "pause.flag").exists()
        assert not (bmad_dir / "stop.flag").exists()


class TestProjectRegistryPersistence:
    """Tests for persistence and reload."""

    def test_load_persisted_projects(self, tmp_path: Path):
        """Registry loads projects from disk on init."""
        config_dir = tmp_path / "config"
        project_path = tmp_path / "my-project"
        project_path.mkdir()

        # Create and save registry
        registry1 = ProjectRegistry(config_dir=config_dir)
        project_uuid = registry1.register(project_path)

        # Create new registry - should load from disk
        registry2 = ProjectRegistry(config_dir=config_dir)

        assert project_uuid in registry2._projects
        assert registry2.get(project_uuid).project_root == project_path.resolve()
