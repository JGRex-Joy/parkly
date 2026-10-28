from __future__ import annotations

from typing import Optional, Protocol

import anyio.from_thread

from app.core.websocket import ConnectionManager as DashboardManager
from app.websocket_manager import ConnectionManager

PARKING_CHANNEL = "parking"


class DisplayPublisher(Protocol):
    def publish(self, channel: str, payload: dict) -> None: ...


class WebSocketPublisher:
    """Routes outbox messages: ``entry``/``exit`` -> gate displays, ``parking`` -> dashboard."""

    def __init__(
        self, manager: ConnectionManager, dashboard: Optional[DashboardManager] = None
    ) -> None:
        self._manager = manager
        self._dashboard = dashboard

    def publish(self, channel: str, payload: dict) -> None:
        if channel == PARKING_CHANNEL:
            if self._dashboard is not None:
                anyio.from_thread.run(self._dashboard.publish_event, payload)
            return
        anyio.from_thread.run(self._manager.broadcast, channel, payload)
