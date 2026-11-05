from __future__ import annotations

import asyncio
import json
from typing import Optional

import websockets

from app.authorizations import AuthorizationDispatcher
from app.commands import BarrierCommands
from app.config import Settings
from app.logging_setup import get_logger
from app.state import BridgeState

log = get_logger("backend_ws")

CHANNELS = {"entry": "/ws/entry-display", "exit": "/ws/exit-display"}


class BackendListener:
    def __init__(
        self,
        settings: Settings,
        commands: BarrierCommands,
        state: BridgeState,
        dispatcher: Optional[AuthorizationDispatcher] = None,
    ) -> None:
        self._s = settings
        self._commands = commands
        self._state = state
        self._dispatcher = dispatcher
        self._tasks: list[asyncio.Task] = []
        self._open_tasks: set[asyncio.Task] = set()

    def _url(self, channel: str) -> str:
        base = self._s.backend_url.rstrip("/")
        scheme = "wss" if base.startswith("https") else "ws"
        return f"{scheme}://{base.split('://', 1)[-1]}{CHANNELS[channel]}"

    def start(self) -> None:
        if not self._s.backend_ws_enabled:
            log.warning("backend websocket disabled; barrier authorisations arrive by polling only")
            return
        self._tasks = [asyncio.create_task(self._listen(c), name=f"ws-{c}") for c in CHANNELS]

    async def stop(self) -> None:
        for task in [*self._tasks, *self._open_tasks]:
            task.cancel()
        await asyncio.gather(*self._tasks, *self._open_tasks, return_exceptions=True)

    async def _listen(self, channel: str) -> None:
        backoff = 0.5
        while True:
            try:
                async with websockets.connect(self._url(channel), open_timeout=5, ping_interval=20) as ws:
                    self._state.ws_connected[channel] = True
                    backoff = 0.5
                    log.info("backend websocket connected", extra={"channel": channel})
                    async for raw in ws:
                        self._on_message(channel, raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("backend websocket down", extra={"channel": channel, "error": str(exc),
                                                             "retry_in_s": backoff})
            finally:
                self._state.ws_connected[channel] = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    def _on_message(self, channel: str, raw) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("non-JSON websocket message ignored", extra={"channel": channel})
            return
        if not isinstance(data, dict) or data.get("event") != "barrier_open":
            return  
        gate: Optional[str] = data.get("gate")
        if gate not in CHANNELS or gate != channel:
            log.warning("barrier_open with unexpected gate ignored", extra={"channel": channel, "gate": gate})
            return
        plate = data.get("plate_number")
        log.info("backend authorised barrier", extra={"gate": gate, "plate": plate,
                                                       "auth": data.get("authorization_id")})
        if self._dispatcher is not None and data.get("authorization_id") and data.get("session_id") is not None:
            self._dispatcher.submit(gate, data, "backend-ws")
            return
        task = asyncio.create_task(self._commands.open(gate, plate=plate, source="backend-ws"))
        self._open_tasks.add(task)
        task.add_done_callback(self._open_tasks.discard)
