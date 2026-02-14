"""Multi-project manager for bmad-assist dashboard.

This package provides classes for managing multiple bmad-assist projects
concurrently from a single dashboard instance.

Public API:
    ProjectContext: State encapsulation for one registered project
    ProjectRegistry: Collection manager with persistence
    ProcessSupervisor: PID monitoring and cleanup
    LoopState: State machine for project lifecycle

Based on design document: docs/multi-project-dashboard.md
"""

from .project_context import LoopState, ProjectContext
from .process_supervisor import ProcessSupervisor
from .registry import ProjectRegistry

__all__ = [
    "LoopState",
    "ProcessSupervisor",
    "ProjectContext",
    "ProjectRegistry",
]
