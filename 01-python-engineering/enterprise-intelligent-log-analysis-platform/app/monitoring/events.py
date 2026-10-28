"""Thread-safe fan-out of monitor events to asyncio subscribers (SSE clients)."""

import asyncio
import threading
from typing import Set, Tuple


class EventBus:
    def __init__(self, max_queue: int = 100) -> None:
        self._subscribers: Set[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = {item for item in self._subscribers if item[1] is not queue}

    def publish(self, event: dict) -> None:
        """Called from the monitor thread; slow clients drop events instead of blocking."""
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_put_nowait, queue, event)
            except RuntimeError:  # loop closed
                self.unsubscribe(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _put_nowait(queue: asyncio.Queue, event: dict) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass
