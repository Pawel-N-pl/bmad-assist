"""Project loop control route handlers.

Provides per-project loop control endpoints:
- /api/projects/{id}/loop/start
- /api/projects/{id}/loop/pause
- /api/projects/{id}/loop/resume
- /api/projects/{id}/loop/stop
- /api/projects/{id}/status
- /api/projects/{id}/sse/output

Based on design document: docs/multi-project-dashboard.md Section 7.1
"""

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from bmad_assist.dashboard.manager import LoopState, ProjectRegistry
from bmad_assist.dashboard.sse_channel import SSEChannelManager, parse_line

logger = logging.getLogger(__name__)


def _get_registry(request: Request) -> ProjectRegistry:
    """Get project registry from app state."""
    return request.app.state.project_registry


def _get_sse_manager(request: Request) -> SSEChannelManager:
    """Get SSE channel manager from app state."""
    return request.app.state.sse_channel_manager


async def start_project_loop(request: Request) -> JSONResponse:
    """POST /api/projects/{id}/loop/start - Start loop for project.

    If max concurrent loops reached, project is queued.

    Returns:
        200: Loop started or queued.
        404: Project not found.
        409: Loop already running.

    """
    registry = _get_registry(request)
    supervisor = request.app.state.process_supervisor
    sse_manager = _get_sse_manager(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    # Check if already running
    if context.is_active():
        return JSONResponse(
            {
                "error": f"Loop already {context.state.value}",
                "state": context.state.value,
            },
            status_code=409,
        )

    # Check concurrency limit
    if not registry.can_start_loop():
        try:
            position = registry.enqueue(project_uuid)
            return JSONResponse({
                "status": "queued",
                "queue_position": position,
                "message": f"Max concurrent loops reached, queued at position {position}",
            })
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=429)

    # Get or create SSE channel
    channel = sse_manager.get_or_create(project_uuid)

    async def on_output(line: str) -> None:
        """Handle subprocess output line."""
        parsed = parse_line(line)
        await channel.broadcast(parsed.event_type, parsed.data)

    async def on_crash(error_msg: str) -> None:
        """Handle subprocess crash."""
        await channel.broadcast_error(error_msg, code="subprocess_crash")

    # Start subprocess
    context.state = LoopState.STARTING
    try:
        await supervisor.spawn_subprocess(
            context,
            on_output=on_output,
            on_crash=on_crash,
        )

        await channel.broadcast_loop_status("running")

        return JSONResponse({
            "status": "running",
            "project_uuid": project_uuid,
            "message": "Loop started",
        })

    except Exception as e:
        context.set_error(str(e))
        await channel.broadcast_error(str(e), code="start_failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def pause_project_loop(request: Request) -> JSONResponse:
    """POST /api/projects/{id}/loop/pause - Pause loop for project.

    Pause takes effect after current step completes.

    Returns:
        200: Pause requested.
        404: Project not found.
        409: Loop not running.

    """
    registry = _get_registry(request)
    supervisor = request.app.state.process_supervisor
    sse_manager = _get_sse_manager(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    if context.state not in (LoopState.RUNNING, LoopState.PAUSE_REQUESTED):
        return JSONResponse(
            {
                "error": f"Cannot pause: loop is {context.state.value}",
                "state": context.state.value,
            },
            status_code=409,
        )

    # Write pause flag
    success = await supervisor.write_pause_flag(context)
    if success:
        context.state = LoopState.PAUSE_REQUESTED

    # Notify via SSE
    channel = sse_manager.get(project_uuid)
    if channel:
        await channel.broadcast_loop_status("pause_requested")

    return JSONResponse({
        "status": "pause_requested",
        "message": "Pause will take effect after current step",
    })


async def resume_project_loop(request: Request) -> JSONResponse:
    """POST /api/projects/{id}/loop/resume - Resume paused loop.

    Returns:
        200: Loop resumed.
        404: Project not found.
        409: Loop not paused.

    """
    registry = _get_registry(request)
    supervisor = request.app.state.process_supervisor
    sse_manager = _get_sse_manager(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    if context.state not in (LoopState.PAUSED, LoopState.PAUSE_REQUESTED):
        return JSONResponse(
            {
                "error": f"Cannot resume: loop is {context.state.value}",
                "state": context.state.value,
            },
            status_code=409,
        )

    # Remove pause flag
    success = await supervisor.remove_pause_flag(context)
    if success:
        context.state = LoopState.RUNNING

    # Notify via SSE
    channel = sse_manager.get(project_uuid)
    if channel:
        await channel.broadcast_loop_status("running")

    return JSONResponse({
        "status": "running",
        "message": "Loop resumed",
    })


async def stop_project_loop(request: Request) -> JSONResponse:
    """POST /api/projects/{id}/loop/stop - Stop loop for project.

    Terminates subprocess gracefully then forcefully if needed.

    Returns:
        200: Loop stopped.
        404: Project not found.

    """
    registry = _get_registry(request)
    supervisor = request.app.state.process_supervisor
    sse_manager = _get_sse_manager(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    # Handle queued projects
    if context.state == LoopState.QUEUED:
        registry.cancel_queue(project_uuid)
        return JSONResponse({
            "status": "idle",
            "message": "Removed from queue",
        })

    # Handle non-active projects
    if not context.is_active():
        return JSONResponse({
            "status": context.state.value,
            "message": "Loop was not running",
        })

    # Stop subprocess
    try:
        await supervisor.stop_subprocess(context)
    except Exception as e:
        logger.exception("Error stopping subprocess")
        context.set_error(str(e))

    # Notify via SSE
    channel = sse_manager.get(project_uuid)
    if channel:
        await channel.broadcast_loop_status("stopped", reason="user_requested")

    return JSONResponse({
        "status": "idle",
        "message": "Loop stopped",
    })


async def get_project_status(request: Request) -> JSONResponse:
    """GET /api/projects/{id}/status - Get sprint status for project.

    Returns:
        Sprint status including current epic, story, and phase.

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

    # Read sprint-status.yaml from project
    sprint_status_path = context.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"

    status: dict[str, Any] = context.to_summary()

    if sprint_status_path.exists():
        try:
            import yaml
            with sprint_status_path.open() as f:
                sprint_data = yaml.safe_load(f) or {}

            status["sprint"] = {
                "epics": sprint_data.get("epics", []),
                "current_epic": sprint_data.get("current_epic"),
                "current_story": sprint_data.get("current_story"),
                "development_status": sprint_data.get("development_status", {}),
            }
        except Exception:
            logger.exception("Failed to load sprint-status.yaml for %s", context.display_name)

    return JSONResponse(status)


async def project_sse_output(request: Request) -> StreamingResponse:
    """GET /api/projects/{id}/sse/output - SSE stream for project.

    Streams real-time events for the project including:
    - Output lines from subprocess
    - Phase transitions
    - Story events
    - Loop status changes

    Returns:
        SSE stream.

    """
    registry = _get_registry(request)
    sse_manager = _get_sse_manager(request)
    project_uuid = request.path_params["id"]

    try:
        context = registry.get(project_uuid)
    except KeyError:
        return JSONResponse(
            {"error": f"Project not found: {project_uuid}"},
            status_code=404,
        )

    channel = sse_manager.get_or_create(project_uuid)

    return StreamingResponse(
        channel.subscribe(context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def get_project_config(request: Request) -> JSONResponse:
    """GET /api/projects/{id}/config - Get project configuration.

    Returns:
        Project-level bmad-assist configuration.

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

    # Try to load project config
    config_path = context.project_root / "bmad-assist.yaml"

    if not config_path.exists():
        return JSONResponse({
            "exists": False,
            "path": str(config_path),
        })

    try:
        import yaml
        with config_path.open() as f:
            config_data = yaml.safe_load(f) or {}

        # Filter out dangerous fields (API keys, etc.)
        safe_config = {k: v for k, v in config_data.items() if k not in ("llm", "api_key")}

        return JSONResponse({
            "exists": True,
            "path": str(config_path),
            "config": safe_config,
        })
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to load config: {e}"},
            status_code=500,
        )


async def update_project_config(request: Request) -> JSONResponse:
    """PUT /api/projects/{id}/config - Update project configuration.

    Body:
        Configuration object to merge with existing config.
        Dangerous fields (llm.api_key) are rejected.

    Returns:
        Updated configuration.

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

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # Reject dangerous fields
    dangerous_fields = ("llm", "api_key", "secrets")
    for field in dangerous_fields:
        if field in body:
            return JSONResponse(
                {"error": f"Cannot modify dangerous field: {field}"},
                status_code=403,
            )

    config_path = context.project_root / "bmad-assist.yaml"

    try:
        import yaml

        # Load existing config
        if config_path.exists():
            with config_path.open() as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # Merge updates
        config_data.update(body)

        # Save
        with config_path.open("w") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)

        return JSONResponse({
            "message": "Configuration updated",
            "path": str(config_path),
        })

    except Exception as e:
        logger.exception("Failed to update config for %s", context.display_name)
        return JSONResponse({"error": str(e)}, status_code=500)


routes = [
    Route("/api/projects/{id}/loop/start", start_project_loop, methods=["POST"]),
    Route("/api/projects/{id}/loop/pause", pause_project_loop, methods=["POST"]),
    Route("/api/projects/{id}/loop/resume", resume_project_loop, methods=["POST"]),
    Route("/api/projects/{id}/loop/stop", stop_project_loop, methods=["POST"]),
    Route("/api/projects/{id}/status", get_project_status, methods=["GET"]),
    Route("/api/projects/{id}/sse/output", project_sse_output, methods=["GET"]),
    Route("/api/projects/{id}/config", get_project_config, methods=["GET"]),
    Route("/api/projects/{id}/config", update_project_config, methods=["PUT"]),
]
