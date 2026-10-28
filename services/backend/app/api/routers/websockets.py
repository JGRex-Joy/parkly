from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.core.config import Settings
from app.db.database import Database
from app.api.dependencies import get_connection_manager, get_database, get_provider, get_settings
from app.services.payment_providers import PaymentProvider
from app.repositories import Repositories
from app.services.display import DisplayPayloadBuilder
from app.websocket_manager import ConnectionManager

router = APIRouter(tags=["WebSocket дисплеи"])


def _snapshot(
    database: Database,
    settings: Settings,
    provider: PaymentProvider,
    build: Callable[[DisplayPayloadBuilder], dict],
) -> dict:
    with database.session() as db:
        return build(
            DisplayPayloadBuilder(
                Repositories.for_session(db),
                settings.base_url,
                currency=settings.currency,
                payment_simulated=provider.is_simulated,
                auth_ttl_seconds=settings.auth_ttl_seconds,
            )
        )


async def _serve(
    channel: str,
    websocket: WebSocket,
    manager: ConnectionManager,
    initial: Callable[[], dict],
) -> None:
    await manager.connect(channel, websocket)
    try:
        await websocket.send_json(await run_in_threadpool(initial))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(channel, websocket)


@router.websocket("/ws/entry-display")
async def ws_entry_display(
    websocket: WebSocket,
    manager: ConnectionManager = Depends(get_connection_manager),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    provider: PaymentProvider = Depends(get_provider),
):
    await _serve(
        "entry", websocket, manager,
        lambda: _snapshot(database, settings, provider, lambda b: b.entry_status()),
    )


@router.websocket("/ws/exit-display")
async def ws_exit_display(
    websocket: WebSocket,
    manager: ConnectionManager = Depends(get_connection_manager),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    provider: PaymentProvider = Depends(get_provider),
):
    await _serve(
        "exit", websocket, manager,
        lambda: _snapshot(database, settings, provider, lambda b: b.exit_status()),
    )
