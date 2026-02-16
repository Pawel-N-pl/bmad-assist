"""Project management route handlers.

Provides endpoints for managing multiple projects:
- /api/projects - List and register projects
- /api/projects/scan - Scan for projects
- /api/projects/control/stop-all - Stop all running loops
- /api/projects/{id} - Get/delete project

Based on design document: docs/multi-project-dashboard.md Section 7.1
"""

import logging
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bmad_assist.dashboard.manager import ProjectRegistry

logger = logging.getLogger(__name__)


def _get_registry(request: Request) -> ProjectRegistry:
    """Get project registry from app state."""
    return request.app.state.project_registry


async def list_projects(request: Request) -> JSONResponse:
    """GET /api/projects - List all registered projects.

    Returns:
        JSON array of project summaries with state and metadata.

    """
    registry = _get_registry(request)
    projects = registry.list_all()

    return JSONResponse({
        "projects": projects,
        "count": len(projects),
        "running_count": registry.get_running_count(),
        "max_concurrent": registry.max_concurrent_loops,
        "queue_size": len(registry._queue),
    })


async def register_project(request: Request) -> JSONResponse:
    """POST /api/projects - Register a new project.

    Body:
        {
            "path": "/path/to/project",
            "name": "Optional Display Name"
        }

    Returns:
        201: Project registered successfully.
        400: Invalid path or already registered.
        409: Project already registered (returns existing UUID).

    """
    registry = _get_registry(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    path_str = body.get("path")
    if not path_str:
        return JSONResponse({"error": "Missing 'path' field"}, status_code=400)

    display_name = body.get("name")

    try:
        path = Path(path_str).expanduser().resolve()
        project_uuid = registry.register(path, display_name=display_name)

        # Check if this was an existing registration
        context = registry.get(project_uuid)
        is_new = context.last_status == "IDLE"

        status_code = 201 if is_new else 200
        return JSONResponse(
            {
                "uuid": project_uuid,
                "path": str(context.project_root),
                "display_name": context.display_name,
                "message": "Project registered" if is_new else "Project already registered",
            },
            status_code=status_code,
        )

    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("Failed to register project: %s", path_str)
        return JSONResponse({"error": str(e)}, status_code=500)


async def scan_projects(request: Request) -> JSONResponse:
    """POST /api/projects/scan - Scan directory for bmad-assist projects.

    Body:
        {
            "directory": "/path/to/scan"
        }

    Returns:
        List of newly discovered project UUIDs.

    """
    registry = _get_registry(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    directory_str = body.get("directory")
    if not directory_str:
        return JSONResponse({"error": "Missing 'directory' field"}, status_code=400)

    try:
        directory = Path(directory_str).expanduser().resolve()

        if not directory.exists():
            return JSONResponse(
                {"error": f"Directory does not exist: {directory}"},
                status_code=404,
            )

        if not directory.is_dir():
            return JSONResponse(
                {"error": f"Path is not a directory: {directory}"},
                status_code=400,
            )

        discovered_uuids = registry.scan_directory(directory)

        return JSONResponse({
            "discovered": discovered_uuids,
            "count": len(discovered_uuids),
            "scanned_directory": str(directory),
        })

    except Exception as e:
        logger.exception("Failed to scan directory: %s", directory_str)
        return JSONResponse({"error": str(e)}, status_code=500)


async def stop_all_loops(request: Request) -> JSONResponse:
    """POST /api/projects/control/stop-all - Stop all running loops.

    Sends stop signal to all running/paused projects.

    Returns:
        List of project UUIDs that were stopped.

    """
    registry = _get_registry(request)
    supervisor = request.app.state.process_supervisor

    stopped_uuids: list[str] = []

    for project_uuid, context in registry._projects.items():
        if context.is_active():
            try:
                await supervisor.stop_subprocess(context)
                stopped_uuids.append(project_uuid)
                logger.info("Stopped project: %s", context.display_name)
            except Exception:
                logger.exception("Failed to stop project: %s", context.display_name)

    # Clear queue
    while registry._queue:
        project_uuid = registry.dequeue()
        if project_uuid:
            context = registry.get(project_uuid)
            context.set_idle(success=False)

    return JSONResponse({
        "stopped": stopped_uuids,
        "count": len(stopped_uuids),
    })


async def get_project(request: Request) -> JSONResponse:
    """GET /api/projects/{id} - Get project details.

    Path params:
        id: Project UUID.

    Returns:
        Project details including logs, state, and metadata.

    """
    registry = _get_registry(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    # Get full details including recent logs
    details = context.to_summary()
    details["logs"] = context.get_logs(count=100)  # Last 100 logs
    details["log_count"] = len(context.log_buffer)

    return JSONResponse(details)


async def delete_project(request: Request) -> JSONResponse:
    """DELETE /api/projects/{id} - Unregister a project.

    Path params:
        id: Project UUID.

    Returns:
        204: Project unregistered successfully.
        404: Project not found.
        409: Project loop is running.

    """
    registry = _get_registry(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)

        if context.is_active():
            return JSONResponse(
                {
                    "error": f"Cannot unregister: loop is {context.state.value}",
                    "state": context.state.value,
                },
                status_code=409,
            )

        registry.unregister(project_uuid)

        return JSONResponse(
            {"message": "Project unregistered", "uuid": project_uuid},
            status_code=200,
        )

    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        logger.exception("Failed to unregister project: %s", project_uuid)
        return JSONResponse({"error": str(e)}, status_code=500)


routes = [
    Route("/api/projects", list_projects, methods=["GET"]),
    Route("/api/projects", register_project, methods=["POST"]),
    Route("/api/projects/scan", scan_projects, methods=["POST"]),
    Route("/api/projects/control/stop-all", stop_all_loops, methods=["POST"]),
    Route("/api/projects/{id}", get_project, methods=["GET"]),
    Route("/api/projects/{id}", delete_project, methods=["DELETE"]),
]
