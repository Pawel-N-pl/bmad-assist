"""Dashboard API routes package.

This package contains all HTTP route handlers organized by domain:
- loop: Development loop control (start, pause, resume, stop)
- status: Sprint status and story information
- content: Prompt, validation, and report content
- sse: Server-sent events for live output
- playwright: Playwright installation status
- config: Configuration CRUD with security filtering
- experiments: Experiment run management and comparison
- projects: Multi-project registration and management
- project_loop: Per-project loop control
- filesystem: Directory browsing for project selection
"""

from .config import routes as config_routes
from .content import routes as content_routes
from .experiments import routes as experiments_routes
from .filesystem import filesystem_routes
from .loop import routes as loop_routes
from .playwright import routes as playwright_routes
from .project_loop import routes as project_loop_routes
from .projects import routes as projects_routes
from .sse import routes as sse_routes
from .sse import sse_output
from .status import routes as status_routes

# Aggregate all routes
API_ROUTES = (
    status_routes
    + loop_routes
    + content_routes
    + sse_routes
    + config_routes
    + playwright_routes
    + experiments_routes
    + projects_routes
    + project_loop_routes
    + filesystem_routes
)

__all__ = ["API_ROUTES", "sse_output"]
