"""Unit tests for WSL2/WSL1 platform detection utilities.

Story 29.7: Tests cover is_wsl2(), is_wsl() detection logic, module-level
caching, and the _reset_wsl2_cache() test isolation helper.
"""

import platform
from collections import namedtuple
from unittest.mock import patch

import pytest

# Will fail until module is created (RED phase)
from bmad_assist.core.platform import (
    _reset_wsl2_cache,
    is_wsl,
    is_wsl2,
)


# Helper: create a fake uname_result with custom release string
_FakeUname = namedtuple("uname_result", ["system", "node", "release", "version", "machine"])


def _make_uname(release: str) -> _FakeUname:
    """Create a fake uname result with the given release string."""
    return _FakeUname(
        system="Linux",
        node="hostname",
        release=release,
        version="#1 SMP",
        machine="x86_64",
    )


# ============================================================================
# is_wsl2() detection
# ============================================================================


class TestIsWsl2:
    """Tests for is_wsl2() WSL2 detection."""

    def setup_method(self) -> None:
        """Reset cache before each test for isolation."""
        _reset_wsl2_cache()

    def test_wsl2_kernel_detected(self) -> None:
        """WSL2 kernel string 'microsoft-standard-WSL2' → True."""
        fake = _make_uname("5.15.90.1-microsoft-standard-WSL2")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl2() is True

    def test_native_linux_not_detected(self) -> None:
        """Native Linux kernel → False."""
        fake = _make_uname("6.1.0-17-amd64")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl2() is False

    def test_wsl1_kernel_not_wsl2(self) -> None:
        """WSL1 kernel (contains 'microsoft' but not 'wsl2') → False.

        is_wsl2() checks /proc/version as fallback when release has 'microsoft'.
        On WSL1, /proc/version also won't have 'wsl2'.
        """
        fake = _make_uname("4.4.0-19041-Microsoft")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            # /proc/version on WSL1 doesn't contain wsl2
            with patch("builtins.open", side_effect=OSError("not found")):
                assert is_wsl2() is False

    def test_wsl2_fallback_via_proc_version(self) -> None:
        """Older WSL2 kernel without 'wsl2' suffix, but /proc/version has it → True."""
        fake = _make_uname("5.10.0-microsoft-standard")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            from unittest.mock import mock_open

            m = mock_open(read_data="Linux version 5.10.0-microsoft-standard-WSL2")
            with patch("builtins.open", m):
                assert is_wsl2() is True

    def test_returns_bool(self) -> None:
        """Return type is always bool."""
        fake = _make_uname("6.1.0-17-amd64")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            result = is_wsl2()
            assert isinstance(result, bool)

    def test_caching_calls_uname_once(self) -> None:
        """is_wsl2() caches result: second call doesn't re-check platform.uname()."""
        fake = _make_uname("5.15.90.1-microsoft-standard-WSL2")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            # First call
            result1 = is_wsl2()
            assert result1 is True
            assert mock_platform.uname.call_count == 1
            # Second call should use cache
            result2 = is_wsl2()
            assert result2 is True
            assert mock_platform.uname.call_count == 1

    def test_reset_cache_allows_recheck(self) -> None:
        """_reset_wsl2_cache() clears the cache, allowing a fresh check."""
        fake_wsl2 = _make_uname("5.15.90.1-microsoft-standard-WSL2")
        fake_linux = _make_uname("6.1.0-17-amd64")

        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake_wsl2
            assert is_wsl2() is True

        _reset_wsl2_cache()

        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake_linux
            assert is_wsl2() is False


# ============================================================================
# is_wsl() detection (both WSL1 and WSL2)
# ============================================================================


class TestIsWsl:
    """Tests for is_wsl() WSL1/WSL2 detection."""

    def setup_method(self) -> None:
        """Reset cache before each test for isolation."""
        _reset_wsl2_cache()

    def test_wsl2_detected(self) -> None:
        """WSL2 kernel → True."""
        fake = _make_uname("5.15.90.1-microsoft-standard-WSL2")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl() is True

    def test_wsl1_detected(self) -> None:
        """WSL1 kernel (contains 'microsoft') → True."""
        fake = _make_uname("4.4.0-19041-Microsoft")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl() is True

    def test_native_linux_not_detected(self) -> None:
        """Native Linux kernel → False."""
        fake = _make_uname("6.1.0-17-amd64")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl() is False

    def test_macos_not_detected(self) -> None:
        """macOS kernel → False."""
        fake = _make_uname("23.2.0")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            assert is_wsl() is False

    def test_returns_bool(self) -> None:
        """Return type is always bool."""
        fake = _make_uname("6.1.0-17-amd64")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            result = is_wsl()
            assert isinstance(result, bool)

    def test_caching_calls_uname_once(self) -> None:
        """is_wsl() caches result: second call doesn't re-check."""
        fake = _make_uname("4.4.0-19041-Microsoft")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            result1 = is_wsl()
            assert result1 is True
            assert mock_platform.uname.call_count == 1
            result2 = is_wsl()
            assert result2 is True
            assert mock_platform.uname.call_count == 1


# ============================================================================
# _reset_wsl2_cache() isolation
# ============================================================================


class TestResetCache:
    """Tests for _reset_wsl2_cache() test isolation helper."""

    def test_resets_both_caches(self) -> None:
        """_reset_wsl2_cache() resets both _wsl2_cached and _wsl_cached."""
        fake = _make_uname("5.15.90.1-microsoft-standard-WSL2")
        with patch("bmad_assist.core.platform.platform") as mock_platform:
            mock_platform.uname.return_value = fake
            is_wsl2()
            is_wsl()

        _reset_wsl2_cache()

        # After reset, the module-level caches should be None
        import bmad_assist.core.platform as plat_mod

        assert plat_mod._wsl2_cached is None
        assert plat_mod._wsl_cached is None
