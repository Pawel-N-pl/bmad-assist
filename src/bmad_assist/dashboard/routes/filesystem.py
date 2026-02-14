"""Filesystem browsing routes for multi-project dashboard.

Provides:
- /api/filesystem/browse - List directory contents for project selection

Security:
- Restricted to user's home directory
- No symlink following
- Read-only operations only
"""

import logging
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

# Security: Only allow browsing within home directory
HOME_DIR = Path.home()


def _is_safe_path(path: Path) -> bool:
    """Check if path is within allowed browsing scope.
    
    Args:
        path: Path to check.
        
    Returns:
        True if path is safe to browse.
    """
    try:
        # Resolve to canonical path (no symlinks)
        resolved = path.resolve()
        # Must be within home directory
        resolved.relative_to(HOME_DIR)
        return True
    except ValueError:
        return False


def _is_bmad_project(path: Path) -> bool:
    """Check if directory is a bmad-assist project.
    
    Args:
        path: Directory path to check.
        
    Returns:
        True if .bmad-assist/ subdirectory exists.
    """
    bmad_dir = path / ".bmad-assist"
    return bmad_dir.exists() and bmad_dir.is_dir()


async def browse_directory(request: Request) -> JSONResponse:
    """GET /api/filesystem/browse - List directory contents.
    
    Query params:
        path: Directory path to list (optional, defaults to home)
        
    Returns:
        JSON with path, parent, and entries list.
    """
    # Get path from query params, default to home
    path_str = request.query_params.get("path", str(HOME_DIR))
    
    try:
        path = Path(path_str).expanduser()
        
        # Security check
        if not _is_safe_path(path):
            return JSONResponse(
                {"error": "Access denied: path outside allowed scope"},
                status_code=403,
            )
        
        # Check path exists and is directory
        if not path.exists():
            return JSONResponse(
                {"error": f"Path does not exist: {path}"},
                status_code=404,
            )
        
        if not path.is_dir():
            return JSONResponse(
                {"error": f"Not a directory: {path}"},
                status_code=400,
            )
        
        # Get parent path (if within scope)
        parent = None
        if path != HOME_DIR and _is_safe_path(path.parent):
            parent = str(path.parent)
        
        # List directory entries
        entries = []
        try:
            for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                # Skip hidden files except .bmad-assist
                if entry.name.startswith(".") and entry.name != ".bmad-assist":
                    continue
                
                # Skip symlinks for security
                if entry.is_symlink():
                    continue
                
                # Only include directories
                if not entry.is_dir():
                    continue
                
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "directory",
                    "is_project": _is_bmad_project(entry),
                })
        except PermissionError:
            return JSONResponse(
                {"error": f"Permission denied: {path}"},
                status_code=403,
            )
        
        return JSONResponse({
            "path": str(path),
            "parent": parent,
            "home": str(HOME_DIR),
            "entries": entries,
        })
        
    except Exception as e:
        logger.exception("Error browsing directory: %s", path_str)
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


# Route definitions
filesystem_routes = [
    Route("/api/filesystem/browse", browse_directory, methods=["GET"]),
]
