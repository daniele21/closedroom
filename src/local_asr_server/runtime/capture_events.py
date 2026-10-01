from __future__ import annotations

import queue
import threading
from collections import OrderedDict, deque
from collections.abc import Iterator
from typing import Any


DEFAULT_CAPTURE_EVENT_CAPACITY = 512
DEFAULT_CAPTURE_HISTORY_CAPACITY = 512


class CoalescingCaptureEventQueue:
    """Queue-compatible bounded buffer for native capture events.

    High-frequency volume samples are latest-state telemetry, not durable events.
    Keep at most one pending sample per source while lifecycle/warning/error events
    use a bounded FIFO. When the discrete FIFO saturates, drop the oldest item and
    expose the count rather than growing memory for the lifetime of a meeting.
    """

    def __init__(self, capacity: int = DEFAULT_CAPTURE_EVENT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._events: deque[dict[str, Any]] = deque()
        self._volumes: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.dropped_events = 0
        self.coalesced_volume_events = 0

    def put(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "volume":
            source = str(event.get("source") or "unknown")
            with self._lock:
                if source in self._volumes:
                    self.coalesced_volume_events += 1
                    self._volumes.pop(source, None)
                self._volumes[source] = event
            return

        with self._lock:
            if len(self._events) >= self.capacity:
                self._events.popleft()
                self.dropped_events += 1
            self._events.append(event)

    def get_nowait(self) -> dict[str, Any]:
        with self._lock:
            if self._events:
                return self._events.popleft()
            if self._volumes:
                _, event = self._volumes.popitem(last=False)
                return event
        raise queue.Empty

    def qsize(self) -> int:
        with self._lock:
            return len(self._events) + len(self._volumes)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "capacity": self.capacity,
                "pending_discrete_events": len(self._events),
                "pending_volume_sources": len(self._volumes),
                "dropped_events": self.dropped_events,
                "coalesced_volume_events": self.coalesced_volume_events,
            }


class BoundedCaptureEventHistory:
    """Bounded diagnostics history that excludes high-rate volume samples."""

    def __init__(self, capacity: int = DEFAULT_CAPTURE_HISTORY_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.dropped_events = 0
        self.ignored_volume_events = 0

    def append(self, event: dict[str, Any]) -> None:
        if event.get("type") == "volume":
            with self._lock:
                self.ignored_volume_events += 1
            return
        with self._lock:
            if len(self._events) == self.capacity:
                self.dropped_events += 1
            self._events.append(event)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            snapshot = tuple(self._events)
        return iter(snapshot)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "capacity": self.capacity,
                "retained_events": len(self._events),
                "dropped_events": self.dropped_events,
                "ignored_volume_events": self.ignored_volume_events,
            }
