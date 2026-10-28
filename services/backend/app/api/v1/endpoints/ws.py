from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket dashboard"])


@router.websocket("/ws/parking")
async def ws_parking(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.dashboard_manager
    await manager.connect(websocket)
    try:
        await manager.send_personal(websocket, manager.snapshot())
        while True:
            await websocket.receive_text()  
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("dashboard websocket failed")
    finally:
        manager.disconnect(websocket)
