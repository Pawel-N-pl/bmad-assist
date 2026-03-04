"""Platform detection utilities for WSL2 and WSL1 environments.

Story 29.7: Provides is_wsl2() and is_wsl() detection functions with
module-level caching. These are utility functions for documentation test
scripts and future platform-specific code paths — they are never called
automatically by bmad-assist.

Detection strategy:
- Primary: check platform.uname().release for 'microsoft-standard-wsl2'
- Fallback: if release contains 'microsoft', check /proc/version for WSL2 marker
- is_wsl() detects both WSL1 and WSL2 via 'microsoft' in release string
"""

import platform

__all__ = [
    "is_wsl2",
    "is_wsl",
]

# Module-level caches — WSL status cannot change during process lifetime
_wsl2_cached: bool | None = None
_wsl_cached: bool | None = None


def is_wsl2() -> bool:
    """Detect if running inside a WSL2 environment.

    Uses platform.uname().release to check for the WSL2 kernel identifier.
    Falls back to reading /proc/version if release contains 'microsoft'
    but not the 'wsl2' suffix (older WSL2 kernels).

    Results are cached at module level since WSL2 status cannot change
    during process lifetime.

    Returns:
        True if running inside WSL2, False otherwise.

    """
    global _wsl2_cached
    if _wsl2_cached is not None:
        return _wsl2_cached

    release = platform.uname().release.lower()

    if "microsoft-standard-wsl2" in release:
        _wsl2_cached = True
        return True

    # Fallback: older WSL2 kernels may not have "wsl2" suffix
    if "microsoft" in release:
        try:
            with open("/proc/version") as f:
                # 512 bytes is more than enough for the kernel version string;
                # cap read to avoid unbounded memory allocation on pathological
                # virtual filesystems.
                content = f.read(512).lower()
                if "microsoft-standard-wsl2" in content:
                    _wsl2_cached = True
                    return True
        except OSError:
            pass

    _wsl2_cached = False
    return False


def is_wsl() -> bool:
    """Detect if running inside any WSL environment (WSL1 or WSL2).

    Checks for 'microsoft' in platform.uname().release, which is present
    in both WSL1 and WSL2 kernel release strings.

    Results are cached at module level since WSL status cannot change
    during process lifetime.

    Returns:
        True if running inside WSL1 or WSL2, False otherwise.

    """
    global _wsl_cached
    if _wsl_cached is not None:
        return _wsl_cached

    release = platform.uname().release.lower()
    _wsl_cached = "microsoft" in release
    return _wsl_cached


def _reset_wsl2_cache() -> None:
    """Reset both WSL2 and WSL caches for test isolation.

    Internal function — not part of the public API. Call between test
    cases to ensure deterministic behavior with mocked platform.uname().
    """
    global _wsl2_cached, _wsl_cached
    _wsl2_cached = None
    _wsl_cached = None
