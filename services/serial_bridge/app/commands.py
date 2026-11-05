from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from app.config import Settings
from app.logging_setup import get_logger
from app.serial_manager import CommandRejected, CommandTimeout, SerialDisconnected, SerialManager
from app.state import BridgeState

log = get_logger("commands")


@dataclass(frozen=True)
class OpenResult:
    ok: bool
    status: str
    detail: str = ""

    def public(self) -> dict:
        return {"ok": self.ok, "status": self.status, "detail": self.detail}


class BarrierCommands:
    """Gate commands. Every command is one explicit, '\\n'-terminated, checksummed frame
    (`$CMD,<seq>,OPEN,entry,8000*CS\\n`) sent through the serial manager's TX thread and acknowledged by
    the device; this class never blocks the event loop."""

    def __init__(self, settings: Settings, serial: SerialManager, state: BridgeState) -> None:
        self._s = settings
        self._serial = serial
        self._state = state
        self._locks = {"entry": asyncio.Lock(), "exit": asyncio.Lock()}
        # key -> (time of ack, gate, explicit). explicit=True: caller supplied an idempotency key
        # (backend authorization_id / request_id) -> it stays valid for the whole dedupe window.
        self._recent: dict[str, tuple[float, str, bool]] = {}
        # gate -> monotonic time until which the barrier is supposed to be open (authorised hold).
        self._open_until: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        for key in [k for k, (t, _, _) in self._recent.items() if now - t > self._s.open_dedupe_seconds]:
            del self._recent[key]

    def on_barrier_closed(self, gate: str) -> None:
        """The servo physically reached CLOSED. A NEW authorisation for the same plate is now legitimate.

        Heuristic keys (`gate:plate`, used when the caller gave no request_id) must not outlive the
        physical open cycle: with the old 15 s window, re-testing the same toy car/plate within 15 s of
        the previous pass had its OPEN silently swallowed ("works every other time"). Explicit
        request_ids stay, because the same authorisation must never open the barrier twice."""
        self._open_until.pop(gate, None)
        for key in [k for k, (_, g, explicit) in self._recent.items() if g == gate and not explicit]:
            del self._recent[key]

    async def open(
        self,
        gate: str,
        *,
        plate: Optional[str] = None,
        request_id: Optional[str] = None,
        hold_ms: Optional[int] = None,
        source: str = "api",
    ) -> OpenResult:
        key = request_id or f"{gate}:{plate or '-'}"
        explicit = request_id is not None
        hold = hold_ms or self._s.open_hold_ms
        async with self._locks[gate]:
            now = time.monotonic()
            self._prune(now)
            if key in self._recent:
                self._state.counters.open_duplicates_suppressed += 1
                log.info("open suppressed (duplicate)", extra={"gate": gate, "key": key, "source": source})
                return OpenResult(True, "duplicate_suppressed")

            deadline = now + self._s.open_deadline
            last_error = ""
            while True:
                try:
                    ack = await self._serial.send_command("OPEN", gate, hold)
                except CommandRejected as exc:  # definite "no" from the device
                    self._state.counters.open_failed += 1
                    log.error("open rejected by device", extra={"gate": gate, "reason": exc.reason})
                    return OpenResult(False, "failed", f"device rejected: {exc.reason}")
                except (SerialDisconnected, CommandTimeout) as exc:
                    last_error = str(exc)
                else:
                    done = time.monotonic()
                    self._recent[key] = (done, gate, explicit)
                    self._open_until[gate] = done + hold / 1000.0
                    self._state.counters.open_sent += 1
                    status = "refreshed" if ack.detail == "REFRESHED" else "opened"
                    log.info("barrier open acknowledged", extra={
                        "gate": gate, "plate": plate, "source": source, "ack": ack.detail or "OK"})
                    self._state.note("open", gate=gate, plate=plate, source=source, status=status)
                    return OpenResult(True, status, ack.detail)
                if time.monotonic() >= deadline:
                    self._state.counters.open_failed += 1
                    log.error("open failed", extra={"gate": gate, "plate": plate, "error": last_error})
                    return OpenResult(False, "failed", last_error)
                await asyncio.sleep(0.4)

    async def reassert_open(self) -> None:
        """The board rebooted (brown-out, watchdog, USB re-plug) INSIDE an authorised hold window.

        The reboot closed the barrier, but the ACK for the OPEN was already delivered, so nothing would
        ever re-send it: the driver is authorised yet faces a closed gate. Re-send OPEN with the
        remaining hold time."""
        now = time.monotonic()
        for gate, until in list(self._open_until.items()):
            remaining_ms = int((until - now) * 1000)
            if remaining_ms < 1000:
                self._open_until.pop(gate, None)
                continue
            async with self._locks[gate]:
                try:
                    await self._serial.send_command("OPEN", gate, min(remaining_ms, 60000))
                except (CommandRejected, SerialDisconnected, CommandTimeout) as exc:
                    log.error("re-open after device reset failed", extra={"gate": gate, "error": str(exc)})
                    continue
            self._state.counters.open_reasserted += 1
            log.warning("barrier re-opened after device reset", extra={"gate": gate, "remaining_ms": remaining_ms})

    async def close(self, gate: str) -> OpenResult:
        async with self._locks[gate]:
            try:
                await self._serial.send_command("CLOSE", gate)
            except CommandRejected as exc:
                return OpenResult(False, "failed", f"device rejected: {exc.reason}")
            except (SerialDisconnected, CommandTimeout) as exc:
                return OpenResult(False, "failed", str(exc))
            self._open_until.pop(gate, None)
            return OpenResult(True, "closed")
