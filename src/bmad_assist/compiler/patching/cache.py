"""Cache management for compiled workflow templates.

This module handles caching compiled templates with hash-based
invalidation for source files and patches.

Classes:
    CacheMeta: Metadata stored with cached templates
    TemplateCache: Cache operations (save, load, validate)

Functions:
    compute_file_hash: Compute SHA-256 hash of a file
"""

import contextlib
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from bmad_assist import __version__
from bmad_assist.core.exceptions import PatchError

logger = logging.getLogger(__name__)

# Cache directory names
CACHE_DIR_NAME = ".bmad-assist/cache"


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file.

    Args:
        path: Path to the file.

    Returns:
        Hex digest of the SHA-256 hash.

    Raises:
        FileNotFoundError: If file doesn't exist.

    """
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@dataclass
class CacheMeta:
    """Metadata stored with cached templates.

    Attributes:
        compiled_at: ISO 8601 timestamp of compilation.
        bmad_version: Version of bmad_assist that compiled the template.
        source_hashes: Dict mapping file paths to SHA-256 hex digests.
        patch_hash: SHA-256 hex digest of patch file content.
        defaults_hash: Combined SHA-256 of defaults files, or None if no defaults.

    """

    compiled_at: str
    bmad_version: str
    source_hashes: dict[str, str]
    patch_hash: str
    defaults_hash: str | None = None


class TemplateCache:
    """Cache operations for compiled workflow templates.

    Handles saving, loading, and validating cached templates with
    hash-based invalidation.

    """

    def get_cache_path(
        self,
        workflow: str,
        project_root: Path | None = None,
    ) -> Path:
        """Get the cache path for a workflow.

        Args:
            workflow: Workflow name (e.g., "create-story").
            project_root: Project root for project-level cache.
                If None, returns global cache path.

        Returns:
            Path to the cached template file.

        """
        if project_root is not None:
            # Project-level cache
            return project_root / CACHE_DIR_NAME / f"{workflow}.tpl.xml"
        else:
            # Global cache includes version in path
            return Path.home() / CACHE_DIR_NAME / __version__ / f"{workflow}.tpl.xml"

    def _get_meta_path(self, cache_path: Path) -> Path:
        """Get the metadata file path for a cache path.

        Returns workflow-specific meta file (e.g., create-story.tpl.xml.meta.yaml)
        to avoid collision when multiple workflows are cached in same directory.
        """
        return cache_path.with_suffix(cache_path.suffix + ".meta.yaml")

    def is_valid(
        self,
        workflow: str,
        project_root: Path | None,
        source_files: dict[str, Path],
        patch_path: Path,
        defaults_hash: str | None = None,
    ) -> bool:
        """Check if cached template is valid.

        Validates:
        - Cache file exists
        - Metadata file exists
        - bmad_version matches current version
        - Source file hashes match stored hashes
        - Patch file hash matches stored hash

        Args:
            workflow: Workflow name.
            project_root: Project root path or None for global.
            source_files: Dict mapping names to source file paths.
            patch_path: Path to the patch file.

        Returns:
            True if cache is valid, False otherwise.

        """
        cache_path = self.get_cache_path(workflow, project_root)
        meta_path = self._get_meta_path(cache_path)

        # Check cache file exists
        if not cache_path.exists():
            logger.debug("Cache file does not exist: %s", cache_path)
            return False

        # Check meta file exists
        if not meta_path.exists():
            logger.debug("Cache meta does not exist: %s", meta_path)
            return False

        try:
            # Load metadata
            with meta_path.open("r") as f:
                meta_data = yaml.safe_load(f)

            # Note: We don't check bmad_version here - file hashes are sufficient
            # for cache invalidation. Version is stored for documentation only.

            # Check source file hashes
            stored_hashes = meta_data.get("source_hashes", {})
            for name, path in source_files.items():
                if not path.exists():
                    logger.debug("Source file does not exist: %s", path)
                    return False
                current_hash = compute_file_hash(path)
                stored_hash = stored_hashes.get(name)
                if current_hash != stored_hash:
                    logger.debug(
                        "Source hash mismatch for %s: cached=%s, current=%s",
                        name,
                        stored_hash,
                        current_hash,
                    )
                    return False

            # Check patch hash
            if not patch_path.exists():
                logger.debug("Patch file does not exist: %s", patch_path)
                return False
            current_patch_hash = compute_file_hash(patch_path)
            stored_patch_hash = meta_data.get("patch_hash")
            if current_patch_hash != stored_patch_hash:
                logger.debug(
                    "Patch hash mismatch: cached=%s, current=%s",
                    stored_patch_hash,
                    current_patch_hash,
                )
                return False

            # Check defaults_hash (backward compat: skip if either is None)
            stored_defaults_hash = meta_data.get("defaults_hash")
            if (
                stored_defaults_hash is not None
                and defaults_hash is not None
                and stored_defaults_hash != defaults_hash
            ):
                logger.debug(
                    "Defaults hash mismatch: cached=%s, current=%s",
                    stored_defaults_hash,
                    defaults_hash,
                )
                return False

            return True

        except Exception as e:
            logger.debug("Error validating cache: %s", e)
            return False

    def load_cached(
        self,
        workflow: str,
        project_root: Path | None,
    ) -> str | None:
        """Load cached template content.

        Args:
            workflow: Workflow name.
            project_root: Project root path or None for global.

        Returns:
            Cached template content, or None if not found.

        """
        cache_path = self.get_cache_path(workflow, project_root)

        if not cache_path.exists():
            return None

        try:
            return cache_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Error loading cached template: %s", e)
            return None

    def save(
        self,
        workflow: str,
        content: str,
        metadata: CacheMeta,
        project_root: Path | None,
    ) -> None:
        """Save compiled template to cache.

        Uses atomic write pattern (temp file + rename).

        Args:
            workflow: Workflow name.
            content: Compiled template content.
            metadata: Cache metadata.
            project_root: Project root path or None for global.

        Raises:
            PatchError: If cache directory is not writable.

        """
        cache_path = self.get_cache_path(workflow, project_root)
        meta_path = self._get_meta_path(cache_path)

        # Ensure directory exists
        cache_dir = cache_path.parent
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PatchError(
                f"Cannot write to cache directory: {cache_dir}. Check permissions."
            ) from e

        # Prepare metadata dict
        meta_dict: dict[str, str | dict[str, str] | None] = {
            "compiled_at": metadata.compiled_at,
            "bmad_version": metadata.bmad_version,
            "source_hashes": metadata.source_hashes,
            "patch_hash": metadata.patch_hash,
        }
        if metadata.defaults_hash is not None:
            meta_dict["defaults_hash"] = metadata.defaults_hash

        # Atomic write for template
        temp_path = cache_path.with_suffix(".tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            # Use os.replace() for Windows compatibility (overwrites existing files)
            os.replace(temp_path, cache_path)
        except PermissionError as e:
            # Clean up temp file if it exists (use missing_ok to avoid race condition)
            with contextlib.suppress(PermissionError):
                temp_path.unlink(missing_ok=True)
            raise PatchError(
                f"Cannot write to cache directory: {cache_dir}. Check permissions."
            ) from e
        except OSError as e:
            # Handle other OS errors that might be permission-related
            # Clean up temp file if it exists (use missing_ok to avoid race condition)
            with contextlib.suppress(PermissionError, OSError):
                temp_path.unlink(missing_ok=True)
            if "permission" in str(e).lower() or e.errno == 13:
                raise PatchError(
                    f"Cannot write to cache directory: {cache_dir}. Check permissions."
                ) from e
            raise

        # Atomic write for metadata
        temp_meta_path = meta_path.with_suffix(".tmp")
        try:
            with temp_meta_path.open("w") as f:
                yaml.dump(meta_dict, f, default_flow_style=False)
            # Use os.replace() for Windows compatibility (overwrites existing files)
            os.replace(temp_meta_path, meta_path)
        except Exception:
            # Clean up temp file if it exists
            if temp_meta_path.exists():
                temp_meta_path.unlink()
            raise

        logger.debug("Saved cache for %s to %s", workflow, cache_path)
