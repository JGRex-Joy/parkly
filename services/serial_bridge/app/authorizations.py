from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Optional

import httpx

from app.clients import BackendClient
from app.commands import BarrierCommands
from app.config import Settings
from app.logging_setup import get_logger
from app.state import BridgeState

log = get_logger("authorizations")
GATES = ("entry", "exit")


class AuthorizationDispatcher:
    def __init__(
        self, settings: Settings, commands: BarrierCommands, backend: BackendClient, state: BridgeState
    ) -> None:
        self._s = settings
        self._commands = commands
        self._backend = backend
        self._state = state
        self._inflight: set[str] = set()
        self._opened: "OrderedDict[str, tuple[str, int]]" = OrderedDict()  
        self._acked: "OrderedDict[str, None]" = OrderedDict()
        self._tasks: set[asyncio.Task] = set()
        self._poller: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._s.auth_poll_interval > 0:
            self._poller = asyncio.create_task(self._poll_loop(), name="auth-poll")

    async def stop(self) -> None:
        tasks = [t for t in (self._poller, *self._tasks) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def submit(self, gate: str, auth: dict, source: str) -> None:
        task = asyncio.create_task(self.execute(gate, auth, source))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def execute(self, gate: str, auth: dict, source: str) -> None:
        auth_id = str(auth.get("authorization_id") or "")
        session_id = auth.get("session_id")
        plate = auth.get("plate_number")
        if not auth_id or session_id is None or gate not in GATES:
            log.warning("malformed authorisation ignored", extra={"auth": auth})
            return
        if auth_id in self._acked or auth_id in self._inflight:
            return
        if auth_id in self._opened:  
            await self._ack(gate, int(session_id), auth_id)
            return

        self._inflight.add(auth_id)
        try:
            result = await self._commands.open(gate, plate=plate, request_id=auth_id, source=source)
            if not result.ok:
                log.error("authorised open failed", extra={
                    "gate": gate, "auth": auth_id, "plate": plate, "detail": result.detail})
                return  
            self._state.counters.auth_executed += 1
            g = self._state.gates[gate]
            g.last_open = {
                "authorization_id": auth_id, "session_id": session_id, "plate": plate,
                "opened_at": time.monotonic(),
                "saw_vehicle": g.present, "cleared_reported": False,
            }
            self._remember(self._opened, auth_id, (gate, int(session_id)))
            await self._ack(gate, int(session_id), auth_id)
        finally:
            self._inflight.discard(auth_id)

    async def _ack(self, gate: str, session_id: int, auth_id: str) -> None:
        delay = 0.3
        for attempt in range(1, 4):
            try:
                await self._backend.ack_open(gate, session_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 409):  
                    log.warning("backend refused open acknowledgement", extra={
                        "gate": gate, "auth": auth_id, "status": exc.response.status_code})
                    self._finish(auth_id)
                    return
                log.warning("open acknowledgement failed", extra={"auth": auth_id, "attempt": attempt})
            except httpx.HTTPError as exc:
                log.warning("open acknowledgement failed", extra={
                    "auth": auth_id, "attempt": attempt, "error": exc.__class__.__name__})
            else:
                self._finish(auth_id)
                return
            await asyncio.sleep(delay)
            delay *= 2
        self._state.counters.auth_ack_failed += 1 

    def _finish(self, auth_id: str) -> None:
        self._opened.pop(auth_id, None)
        self._remember(self._acked, auth_id, None)

    @staticmethod
    def _remember(store: OrderedDict, key: str, value) -> None:
        store[key] = value
        while len(store) > 512:
            store.popitem(last=False)

    async def poll_once(self) -> int:
        started = 0
        for gate in GATES:
            for auth in await self._backend.pending_authorizations(gate):
                auth_id = auth.get("authorization_id")
                if auth_id in self._acked or auth_id in self._inflight:
                    continue
                self.submit(gate, auth, "poll")
                started += 1
        return started

    async def _poll_loop(self) -> None:
        warned = False
        while True:
            try:
                await self.poll_once()
                warned = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:  
                if not warned:
                    log.warning("authorisation poll failed", extra={"error": exc.__class__.__name__})
                    warned = True
            await asyncio.sleep(self._s.auth_poll_interval)
