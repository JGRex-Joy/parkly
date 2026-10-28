from __future__ import annotations

import asyncio
import logging
from typing import Dict, Iterable, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

ENTERING, PARKED, EXITING = "ENTERING", "PARKED", "EXITING"


class ConnectionManager:
    def __init__(self, slot_ids: Iterable[int] = (1, 2, 3, 4)) -> None:
        self.active_connections: List[WebSocket] = []
        self.slot_plates: Dict[int, Optional[str]] = {}
        self.sessions: Dict[str, dict] = {}
        self.configure_slots(slot_ids)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        await websocket.send_json(message)

    async def broadcast(self, message: dict) -> None:
        clients = list(self.active_connections)
        if not clients:
            return
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in clients), return_exceptions=True
        )
        for ws, result in zip(clients, results):
            if isinstance(result, Exception):
                logger.debug("dropping dead dashboard websocket: %r", result)
                self.disconnect(ws)

    def configure_slots(self, slot_ids: Iterable[int]) -> None:
        self.slot_plates = {int(i): None for i in slot_ids}

    def reset_state(self) -> None:
        self.configure_slots(self.slot_plates.keys())
        self.sessions.clear()

    def apply(self, msg: dict) -> None:
        """Fold one pipeline event into the in-memory state (event loop thread only)."""
        kind, plate, slot_id = msg.get("event"), msg.get("plate"), msg.get("slot_id")
        if kind == "ENTRY_OCR" and plate:
            self.sessions[plate] = {"plate": plate, "phase": ENTERING, "slot_id": None,
                                    "duration": None, "fee": None}
        elif kind == "SLOT_OCCUPIED" and plate and slot_id is not None:
            self.slot_plates[slot_id] = plate
            s = self.sessions.setdefault(plate, {"plate": plate, "duration": None, "fee": None})
            s.update(phase=PARKED, slot_id=slot_id)
        elif kind == "SLOT_RELEASED" and slot_id is not None:
            gone = self.slot_plates.get(slot_id)
            self.slot_plates[slot_id] = None
            if gone and self.sessions.get(gone, {}).get("phase") == PARKED:
                self.sessions.pop(gone, None)
        elif kind == "EXIT_OCR" and plate:
            if slot_id is not None and self.slot_plates.get(slot_id) in (plate, None, ""):
                self.slot_plates[slot_id] = None
            s = self.sessions.setdefault(plate, {"plate": plate})
            s.update(phase=EXITING, slot_id=slot_id, duration=msg.get("duration"), fee=msg.get("fee"))
        elif kind == "PAYMENT_CONFIRMED" and plate:
            self.sessions.pop(plate, None)

    async def publish_event(self, msg: dict) -> None:
        self.apply(msg)
        await self.broadcast(msg)

    def snapshot(self) -> dict:
        slots = [
            {"slot_id": sid, "status": "OCCUPIED" if plate else "FREE", "plate": plate}
            for sid, plate in sorted(self.slot_plates.items())
        ]
        return {
            "event": "INITIAL_STATE",
            "total_slots": len(slots),
            "free_slots": sum(1 for s in slots if s["status"] == "FREE"),
            "slots": slots,
            "sessions": [dict(s) for s in self.sessions.values()],
        }
