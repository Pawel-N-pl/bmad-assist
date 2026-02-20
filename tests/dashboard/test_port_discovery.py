"""Tests for port auto-discovery - Story 16.11: Port Auto-Discovery.

Tests verify:
- AC1: is_port_available() function checks port availability
- AC2: find_available_port() finds first available port (incrementing by +2)
- AC3: Server integration with port discovery
- AC4: --no-auto-port flag disables auto-discovery
- AC5: Error message shows range of tried ports
"""

import socket
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import DashboardError
from bmad_assist.dashboard.server import find_available_port, is_port_available

# =============================================================================
# Fixtures for socket mocking
# =============================================================================


@pytest.fixture
def free_port() -> Generator[int, None, None]:
    """Get a dynamically allocated free port for testing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    yield port


@pytest.fixture
def occupied_port() -> Generator[int, None, None]:
    """Create an occupied port for testing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    yield port
    sock.close()


# =============================================================================
# Test: is_port_available() - AC1
# =============================================================================


class TestIsPortAvailableAC1:
    """Tests for is_port_available() function (AC1)."""

    def test_returns_true_for_free_port(self, free_port: int) -> None:
        """GIVEN a free port
        WHEN is_port_available() is called
        THEN it returns True.
        """
        # WHEN: Check if free port is available
        result = is_port_available(free_port)

        # THEN: Returns True
        assert result is True

    def test_returns_false_for_occupied_port(self, occupied_port: int) -> None:
        """GIVEN an occupied port
        WHEN is_port_available() is called
        THEN it returns False.
        """
        # WHEN: Check if occupied port is available
        result = is_port_available(occupied_port)

        # THEN: Returns False
        assert result is False

    def test_uses_socket_bind_test(self) -> None:
        """GIVEN is_port_available() is called
        WHEN checking port availability
        THEN it uses socket bind (not connect) test.
        """
        # GIVEN: Mock socket operations
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_sock

            # WHEN: Check port availability
            is_port_available(9600, "127.0.0.1")

            # THEN: bind() is called with host and port
            mock_sock.bind.assert_called_once_with(("127.0.0.1", 9600))

    def test_accepts_host_parameter(self, free_port: int) -> None:
        """GIVEN a host parameter is specified
        WHEN is_port_available() is called
        THEN it checks availability on that host.
        """
        # WHEN: Check with explicit host
        result = is_port_available(free_port, host="127.0.0.1")

        # THEN: Returns True (port is free on localhost)
        assert result is True

    def test_default_host_is_localhost(self) -> None:
        """GIVEN no host parameter is specified
        WHEN is_port_available() is called
        THEN it defaults to 127.0.0.1.
        """
        # GIVEN: Mock socket operations
        with patch("socket.socket") as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_sock

            # WHEN: Check port without host
            is_port_available(9600)

            # THEN: bind() is called with default host
            mock_sock.bind.assert_called_once_with(("127.0.0.1", 9600))


# =============================================================================
# Test: find_available_port() - AC2
# =============================================================================


class TestFindAvailablePortAC2:
    """Tests for find_available_port() function (AC2)."""

    def test_returns_start_port_if_available(self, free_port: int) -> None:
        """GIVEN start_port is available
        WHEN find_available_port() is called
        THEN it returns start_port.
        """
        # WHEN: Find available port starting from free port
        result = find_available_port(start_port=free_port)

        # THEN: Returns the start port
        assert result == free_port

    def test_increments_by_2(self) -> None:
        """GIVEN start_port is busy
        WHEN find_available_port() is called
        THEN it tries port + 2, port + 4, etc.
        """
        # GIVEN: Mock to simulate first port busy, second port available
        call_count = 0

        def mock_is_available(port: int, host: str = "127.0.0.1") -> bool:
            nonlocal call_count
            call_count += 1
            # First port (9600) busy, second port (9602) available
            return port != 9600

        with patch("bmad_assist.dashboard.server.is_port_available", side_effect=mock_is_available):
            # WHEN: Find available port
            result = find_available_port(start_port=9600)

        # THEN: Returns 9602 (9600 + 2)
        assert result == 9602

    def test_odd_start_port_increments_correctly(self) -> None:
        """GIVEN start_port is odd (e.g., 8081)
        WHEN find_available_port() increments
        THEN it follows pattern 8081 → 8083 → 8085.
        """

        # GIVEN: Mock to simulate first two ports busy
        def mock_is_available(port: int, host: str = "127.0.0.1") -> bool:
            return port >= 8085  # Only 8085+ available

        with patch("bmad_assist.dashboard.server.is_port_available", side_effect=mock_is_available):
            # WHEN: Find available port starting from 8081
            result = find_available_port(start_port=8081)

        # THEN: Returns 8085 (8081 + 4)
        assert result == 8085

    def test_accepts_host_parameter(self) -> None:
        """GIVEN a host parameter is specified
        WHEN find_available_port() is called
        THEN it passes host to is_port_available().
        """
        # GIVEN: Mock to verify host parameter
        with patch("bmad_assist.dashboard.server.is_port_available") as mock_check:
            mock_check.return_value = True

            # WHEN: Find available port with custom host
            find_available_port(start_port=9600, host="0.0.0.0")

        # THEN: is_port_available called with correct host
        mock_check.assert_called_once_with(9600, "0.0.0.0")

    def test_max_attempts_default_is_10(self) -> None:
        """GIVEN no max_attempts specified
        WHEN all ports are busy
        THEN it tries exactly 10 ports.
        """
        # GIVEN: All ports busy
        with patch(
            "bmad_assist.dashboard.server.is_port_available", return_value=False
        ) as mock_check:
            # WHEN: Find available port
            with pytest.raises(DashboardError):
                find_available_port(start_port=9600)

        # THEN: Exactly 10 attempts made
        assert mock_check.call_count == 10

    def test_raises_dashboard_error_when_all_ports_busy(self) -> None:
        """GIVEN all ports are busy
        WHEN find_available_port() is called
        THEN it raises DashboardError.
        """
        # GIVEN: All ports busy
        with patch("bmad_assist.dashboard.server.is_port_available", return_value=False):
            # WHEN/THEN: DashboardError raised
            with pytest.raises(DashboardError):
                find_available_port(start_port=9600)

    def test_custom_max_attempts(self) -> None:
        """GIVEN custom max_attempts=5
        WHEN all ports busy
        THEN it tries exactly 5 ports.
        """
        # GIVEN: All ports busy
        with patch(
            "bmad_assist.dashboard.server.is_port_available", return_value=False
        ) as mock_check:
            # WHEN: Find available port with max_attempts=5
            with pytest.raises(DashboardError):
                find_available_port(start_port=9600, max_attempts=5)

        # THEN: Exactly 5 attempts made
        assert mock_check.call_count == 5


# =============================================================================
# Test: Error Message Format - AC5
# =============================================================================


class TestErrorMessageAC5:
    """Tests for error message format (AC5)."""

    def test_error_message_shows_port_range(self) -> None:
        """GIVEN all ports are busy
        WHEN DashboardError is raised
        THEN message shows range of tried ports.
        """
        # GIVEN: All ports busy
        with patch("bmad_assist.dashboard.server.is_port_available", return_value=False):
            # WHEN: Find available port
            with pytest.raises(DashboardError) as exc_info:
                find_available_port(start_port=9600, max_attempts=10)

        # THEN: Message includes port range
        # 9600 + (9 * 2) = 9618 for 10 attempts
        assert "9600" in str(exc_info.value)
        assert "9618" in str(exc_info.value)

    def test_error_message_suggests_port_flag(self) -> None:
        """GIVEN all ports are busy
        WHEN DashboardError is raised
        THEN message suggests using --port flag.
        """
        # GIVEN: All ports busy
        with patch("bmad_assist.dashboard.server.is_port_available", return_value=False):
            # WHEN: Find available port
            with pytest.raises(DashboardError) as exc_info:
                find_available_port(start_port=9600)

        # THEN: Message suggests --port flag
        assert "--port" in str(exc_info.value)


# =============================================================================
# Test: DashboardError Exception (AC2)
# =============================================================================


class TestDashboardErrorException:
    """Tests for DashboardError exception class."""

    def test_dashboard_error_inherits_from_bmad_assist_error(self) -> None:
        """GIVEN DashboardError class
        WHEN checking inheritance
        THEN it inherits from BmadAssistError.
        """
        from bmad_assist.core.exceptions import BmadAssistError

        # THEN: DashboardError is a subclass
        assert issubclass(DashboardError, BmadAssistError)

    def test_dashboard_error_can_be_raised(self) -> None:
        """GIVEN DashboardError class
        WHEN raising with message
        THEN message is accessible.
        """
        # WHEN: Raise DashboardError
        with pytest.raises(DashboardError) as exc_info:
            raise DashboardError("Test error message")

        # THEN: Message accessible
        assert "Test error message" in str(exc_info.value)
