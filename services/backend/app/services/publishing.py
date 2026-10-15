
from __future__ import annotations

from typing import Protocol

import anyio.from_thread

from app.websocket_manager import ConnectionManager


class DisplayPublisher(Protocol):
    def publish(self, channel: str, payload: dict) -> None: ...


class WebSocketPublisher:
    """Publishes from worker threads onto the event loop that owns the sockets."""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    def publish(self, channel: str, payload: dict) -> None:
        anyio.from_thread.run(self._manager.broadcast, channel, payload)
