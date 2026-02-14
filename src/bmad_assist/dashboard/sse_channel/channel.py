"""SSE channel for per-project streaming.

Provides bounded queue SSE channels with:
- Backpressure policy (drop oldest when full)
- Heartbeat for connection health
- Log buffer replay on connect

Based on design document: docs/multi-project-dashboard.md Section 6
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .project_context import ProjectContext

logger = logging.getLogger(__name__)

# Default channel configuration
DEFAULT_MAX_QUEUE_SIZE = 1000
DEFAULT_HEARTBEAT_INTERVAL = 15  # seconds
DEFAULT_DROP_POLICY = "oldest"


@dataclass
class SSEEvent:
    """Represents a single SSE event.

    Attributes:
        event: Event type name.
        data: Event payload (dict).
        id: Optional event ID for reconnection.
        retry: Optional retry interval in milliseconds.

    """

    event: str
    data: dict[str, Any]
    id: str | None = None
    retry: int | None = None

    def format(self) -> str:
        """Format event for SSE protocol.

        Returns:
            SSE-formatted string ready for transmission.

        """
        lines = []

        if self.id:
            lines.append(f"id: {self.id}")
        if self.retry:
            lines.append(f"retry: {self.retry}")

        lines.append(f"event: {self.event}")
        data_str = json.dumps(self.data)
        for line in data_str.split("\n"):
            lines.append(f"data: {line}")

        lines.append("")  # Empty line terminates message
        return "\n".join(lines) + "\n"


class SSEChannel:
    """Per-project SSE channel with bounded queue.

    Provides:
    - Bounded queue with backpressure (drop oldest)
    - Heartbeat for connection health
    - Log buffer replay on connect
    - Subscriber management

    Attributes:
        project_uuid: UUID of the project this channel serves.
        max_queue_size: Maximum events to queue per subscriber.
        drop_policy: What to drop when full ("oldest" or "newest").
        heartbeat_interval: Seconds between heartbeats.

    """

    def __init__(
        self,
        project_uuid: str,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        drop_policy: str = DEFAULT_DROP_POLICY,
        heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        """Initialize SSE channel.

        Args:
            project_uuid: UUID of the project.
            max_queue_size: Maximum queue size per subscriber.
            drop_policy: "oldest" or "newest" when queue full.
            heartbeat_interval: Seconds between heartbeat messages.

        """
        self.project_uuid = project_uuid
        self.max_queue_size = max_queue_size
        self.drop_policy = drop_policy
        self.heartbeat_interval = heartbeat_interval

        self._queues: set[asyncio.Queue[SSEEvent | None]] = set()
        self._message_counter = 0
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        """Get number of active subscribers."""
        return len(self._queues)

    async def subscribe(
        self,
        context: "ProjectContext | None" = None,
    ) -> AsyncGenerator[str, None]:
        """Subscribe to SSE stream with optional log replay.

        Args:
            context: Optional ProjectContext for log buffer replay.

        Yields:
            Formatted SSE messages as strings.

        """
        queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=self.max_queue_size)

        async with self._lock:
            self._queues.add(queue)
            logger.info(
                "SSE client connected to project %s (total: %d)",
                self.project_uuid[:8],
                len(self._queues),
            )

        try:
            # Send connection event
            yield SSEEvent(
                event="connected",
                data={
                    "project_id": self.project_uuid,
                    "connected": True,
                    "timestamp": time.time(),
                },
                retry=3000,
            ).format()

            # Replay log buffer if context provided
            if context is not None:
                logs = context.get_logs()
                if logs:
                    yield SSEEvent(
                        event="log_replay",
                        data={
                            "project_id": self.project_uuid,
                            "lines": logs,
                            "count": len(logs),
                        },
                    ).format()

            # Stream events
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=self.heartbeat_interval,
                    )

                    if event is None:
                        # Shutdown signal
                        break

                    yield event.format()

                except TimeoutError:
                    # Send heartbeat
                    yield SSEEvent(
                        event="heartbeat",
                        data={
                            "project_id": self.project_uuid,
                            "timestamp": time.time(),
                        },
                    ).format()

        finally:
            async with self._lock:
                self._queues.discard(queue)
                logger.info(
                    "SSE client disconnected from project %s (remaining: %d)",
                    self.project_uuid[:8],
                    len(self._queues),
                )

    async def broadcast(self, event: str, data: dict[str, Any]) -> int:
        """Broadcast event to all subscribers.

        Args:
            event: Event type name.
            data: Event payload.

        Returns:
            Number of subscribers event was sent to.

        """
        self._message_counter += 1

        # Add project_id and timestamp to all events
        enriched_data = {
            "project_id": self.project_uuid,
            "ts": time.time(),
            **data,
        }

        sse_event = SSEEvent(
            event=event,
            data=enriched_data,
            id=str(self._message_counter),
        )

        sent_count = 0
        async with self._lock:
            for queue in self._queues:
                try:
                    queue.put_nowait(sse_event)
                    sent_count += 1
                except asyncio.QueueFull:
                    if self.drop_policy == "oldest":
                        # Drop oldest, add newest
                        try:
                            queue.get_nowait()
                            queue.put_nowait(sse_event)
                            sent_count += 1
                        except (asyncio.QueueEmpty, asyncio.QueueFull):
                            pass
                    else:
                        # Drop this message (newest)
                        logger.warning(
                            "SSE queue full for project %s, dropping message",
                            self.project_uuid[:8],
                        )

        return sent_count

    async def broadcast_output(
        self,
        line: str,
        level: str = "info",
    ) -> int:
        """Broadcast subprocess output line.

        Args:
            line: Output line text.
            level: Log level (info, warn, error).

        Returns:
            Number of subscribers.

        """
        return await self.broadcast(
            "output",
            {
                "line": line,
                "level": level,
            },
        )

    async def broadcast_phase_changed(
        self,
        from_phase: str,
        to_phase: str,
        story_id: str,
    ) -> int:
        """Broadcast phase transition event.

        Args:
            from_phase: Previous phase.
            to_phase: New phase.
            story_id: Current story ID.

        Returns:
            Number of subscribers.

        """
        return await self.broadcast(
            "phase_changed",
            {
                "from": from_phase,
                "to": to_phase,
                "story_id": story_id,
            },
        )

    async def broadcast_story_started(
        self,
        epic_id: int | str,
        story_id: str,
        title: str,
    ) -> int:
        """Broadcast story started event.

        Args:
            epic_id: Epic identifier.
            story_id: Story identifier.
            title: Story title.

        Returns:
            Number of subscribers.

        """
        return await self.broadcast(
            "story_started",
            {
                "epic_id": epic_id,
                "story_id": story_id,
                "title": title,
            },
        )

    async def broadcast_story_completed(
        self,
        epic_id: int | str,
        story_id: str,
        result: str,
    ) -> int:
        """Broadcast story completed event.

        Args:
            epic_id: Epic identifier.
            story_id: Story identifier.
            result: "success" or "fail".

        Returns:
            Number of subscribers.

        """
        return await self.broadcast(
            "story_completed",
            {
                "epic_id": epic_id,
                "story_id": story_id,
                "result": result,
            },
        )

    async def broadcast_loop_status(
        self,
        status: str,
        reason: str | None = None,
    ) -> int:
        """Broadcast loop status change.

        Args:
            status: New status (running, paused, stopped, error).
            reason: Optional reason for status change.

        Returns:
            Number of subscribers.

        """
        data: dict[str, Any] = {"status": status}
        if reason:
            data["reason"] = reason
        return await self.broadcast("loop_status", data)

    async def broadcast_error(
        self,
        message: str,
        code: str = "unknown",
    ) -> int:
        """Broadcast error event.

        Args:
            message: Error message.
            code: Error code.

        Returns:
            Number of subscribers.

        """
        return await self.broadcast(
            "error",
            {
                "message": message,
                "code": code,
            },
        )

    async def shutdown(self) -> None:
        """Shutdown channel and disconnect all subscribers."""
        async with self._lock:
            for queue in self._queues:
                await queue.put(None)  # Send shutdown signal

            logger.info(
                "SSE channel for project %s shutdown, disconnected %d clients",
                self.project_uuid[:8],
                len(self._queues),
            )
            self._queues.clear()


class SSEChannelManager:
    """Manages SSE channels for all projects.

    Creates channels on-demand and handles cleanup.
    """

    def __init__(self) -> None:
        """Initialize channel manager."""
        self._channels: dict[str, SSEChannel] = {}

    def get_or_create(self, project_uuid: str) -> SSEChannel:
        """Get existing channel or create new one.

        Args:
            project_uuid: Project UUID.

        Returns:
            SSEChannel for the project.

        """
        if project_uuid not in self._channels:
            self._channels[project_uuid] = SSEChannel(project_uuid)
            logger.debug("Created SSE channel for project %s", project_uuid[:8])
        return self._channels[project_uuid]

    def get(self, project_uuid: str) -> SSEChannel | None:
        """Get channel if it exists.

        Args:
            project_uuid: Project UUID.

        Returns:
            SSEChannel or None.

        """
        return self._channels.get(project_uuid)

    def remove(self, project_uuid: str) -> bool:
        """Remove channel for project.

        Args:
            project_uuid: Project UUID.

        Returns:
            True if channel was removed.

        """
        if project_uuid in self._channels:
            del self._channels[project_uuid]
            return True
        return False

    async def shutdown(self) -> None:
        """Shutdown all channels."""
        for channel in self._channels.values():
            await channel.shutdown()
        self._channels.clear()
        logger.info("All SSE channels shutdown")
