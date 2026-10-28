from __future__ import annotations

from typing import Dict, List

from fastapi import WebSocket

CHANNELS = ("entry", "exit")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, List[WebSocket]] = {c: [] for c in CHANNELS}

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(channel, []).append(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        connections = self.active_connections.get(channel, [])
        if websocket in connections:
            connections.remove(websocket)

    async def broadcast(self, channel: str, data: dict) -> None:
        dead: List[WebSocket] = []
        for ws in list(self.active_connections.get(channel, [])):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)
