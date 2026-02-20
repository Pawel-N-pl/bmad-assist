"""Tests for Story 16.6: Terminal Output Panel - SSE Provider Support.

RED Phase: These tests verify the SSE output event format requirements for Story 16.6.

Tests cover:
- AC1: Output lines have provider identification (claude, opus, gemini, glm) or null (bmad)
- AC2: broadcast_output() correctly handles all provider values

These tests extend the existing test_sse.py infrastructure.
"""

import asyncio
import json

import pytest

from bmad_assist.dashboard.sse import SSEBroadcaster

# =============================================================================
# Task 6.1: Test broadcast_output() with provider field (AC: 1, 2)
# =============================================================================


class TestSSEOutputProviderField:
    """Tests for SSE output event provider field verification - Story 16.6 AC1/AC2."""

    @pytest.mark.asyncio
    async def test_broadcast_output_includes_provider_claude(self) -> None:
        """Test that output event includes provider='claude' when specified.

        AC1: Lines show provider identification (claude, opus, gemini, glm)
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:  # Initial + broadcast
                    break

        # Start consumer
        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)  # Let it subscribe

        # WHEN: Broadcast output with claude provider
        await broadcaster.broadcast_output("test line from claude", "claude")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Output event has provider='claude'
        output_msg = received[1]
        assert "event: output" in output_msg
        assert '"provider": "claude"' in output_msg or '"provider":"claude"' in output_msg

    @pytest.mark.asyncio
    async def test_broadcast_output_includes_provider_opus(self) -> None:
        """Test that output event includes provider='opus' when specified.

        AC1: Lines show provider identification (claude, opus, gemini, glm)
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast output with opus provider
        await broadcaster.broadcast_output("test line from opus", "opus")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Output event has provider='opus'
        output_msg = received[1]
        assert "event: output" in output_msg
        assert '"provider": "opus"' in output_msg or '"provider":"opus"' in output_msg

    @pytest.mark.asyncio
    async def test_broadcast_output_includes_provider_gemini(self) -> None:
        """Test that output event includes provider='gemini' when specified.

        AC1: Lines show provider identification (claude, opus, gemini, glm)
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast output with gemini provider
        await broadcaster.broadcast_output("test line from gemini", "gemini")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Output event has provider='gemini'
        output_msg = received[1]
        assert "event: output" in output_msg
        assert '"provider": "gemini"' in output_msg or '"provider":"gemini"' in output_msg

    @pytest.mark.asyncio
    async def test_broadcast_output_includes_provider_glm(self) -> None:
        """Test that output event includes provider='glm' when specified.

        AC1: Lines show provider identification (claude, opus, gemini, glm)
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast output with glm provider
        await broadcaster.broadcast_output("test line from glm", "glm")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Output event has provider='glm'
        output_msg = received[1]
        assert "event: output" in output_msg
        assert '"provider": "glm"' in output_msg or '"provider":"glm"' in output_msg

    @pytest.mark.asyncio
    async def test_broadcast_output_provider_null_for_bmad(self) -> None:
        """Test that output event has provider=null when None is passed.

        AC1: Lines default to 'bmad' if provider is null
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast output with None provider (bmad default)
        await broadcaster.broadcast_output("bmad internal output", None)

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Output event has provider=null (JSON null)
        output_msg = received[1]
        assert "event: output" in output_msg
        assert '"provider": null' in output_msg or '"provider":null' in output_msg

    @pytest.mark.asyncio
    async def test_broadcast_output_event_structure_complete(self) -> None:
        """Test that output event contains all required fields: line, provider, timestamp.

        AC1: Lines appear with timestamp prefix in [HH:MM:SS] format and provider identification
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast output
        await broadcaster.broadcast_output("complete structure test", "claude")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: All three fields present
        output_msg = received[1]

        # Parse JSON data
        data_start = output_msg.find("data: ") + 6
        data_end = output_msg.find("\n", data_start)
        data_json = output_msg[data_start:data_end]
        data = json.loads(data_json)

        # Verify all required fields
        assert "line" in data, "Missing 'line' field"
        assert "provider" in data, "Missing 'provider' field"
        assert "timestamp" in data, "Missing 'timestamp' field"

        # Verify field values
        assert data["line"] == "complete structure test"
        assert data["provider"] == "claude"
        assert isinstance(data["timestamp"], (int, float))

    @pytest.mark.asyncio
    async def test_broadcast_output_provider_case_sensitivity(self) -> None:
        """Test that provider names are passed through as-is (lowercase expected).

        AC1: Provider SSE value sent as lowercase (claude, opus, gemini, glm)
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast with lowercase provider (expected format)
        await broadcaster.broadcast_output("test", "claude")

        await asyncio.wait_for(task, timeout=1.0)

        # THEN: Provider preserved exactly as passed
        output_msg = received[1]
        data_start = output_msg.find("data: ") + 6
        data_end = output_msg.find("\n", data_start)
        data = json.loads(output_msg[data_start:data_end])

        assert data["provider"] == "claude", "Provider should be lowercase 'claude'"


# =============================================================================
# Task 6.2: Test all provider values in sequence (AC: 1, 2)
# =============================================================================


class TestSSEAllProvidersSequence:
    """Tests for verifying all provider types work correctly in sequence."""

    @pytest.mark.asyncio
    async def test_multiple_providers_in_sequence(self) -> None:
        """Test that different providers can be broadcast in sequence.

        AC1, AC2: Multiple providers identified correctly
        """
        # GIVEN: Broadcaster with subscriber
        broadcaster = SSEBroadcaster(heartbeat_interval=60)
        received = []

        async def consumer():
            count = 0
            async for msg in broadcaster.subscribe():
                received.append(msg)
                count += 1
                if count >= 5:  # Initial + 4 broadcasts
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # WHEN: Broadcast from all providers
        await broadcaster.broadcast_output("from claude", "claude")
        await broadcaster.broadcast_output("from opus", "opus")
        await broadcaster.broadcast_output("from gemini", "gemini")
        await broadcaster.broadcast_output("from glm", "glm")

        await asyncio.wait_for(task, timeout=2.0)

        # THEN: Each message has correct provider
        # Skip initial status message (received[0])
        providers = []
        for msg in received[1:]:
            data_start = msg.find("data: ") + 6
            data_end = msg.find("\n", data_start)
            data = json.loads(msg[data_start:data_end])
            providers.append(data["provider"])

        assert providers == ["claude", "opus", "gemini", "glm"]
