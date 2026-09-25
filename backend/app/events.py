"""Tiny publish/subscribe hub for Server-Sent Events. Thread-safe publish into asyncio queues."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: str, data: Any) -> None:
        if not self._subscribers or self._loop is None:
            return
        message = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
        with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            self._loop.call_soon_threadsafe(self._offer, queue, message)

    @staticmethod
    def _offer(queue: asyncio.Queue[str], message: str) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # slow client: drop backlog and ask it to reload the full state instead
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait('event: reload\ndata: {}\n\n')
