from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from app import protocol
from app.transports import TransportError

_GATE_INDEX = {"entry": 0, "exit": 1}


class MockArduino:
    def __init__(
        self,
        hold_ms: int = 3000,
        clear_ms: int = 300,
        heartbeat_s: float = 1.0,
        num_slots: int = 4,
        firmware: str = "mock-1.0.0",
    ) -> None:
        self._lock = threading.RLock()
        self._out: "queue.Queue[bytes]" = queue.Queue()
        self.hold_ms = hold_ms
        self.clear_ms = clear_ms
        self.heartbeat_s = heartbeat_s
        self.num_slots = num_slots
        self.firmware = firmware

        self.world_slots = [False] * num_slots
        self.world_gate = {"entry": False, "exit": False}

        self._is_open = False
        self._unplugged_until = 0.0
        self.drop_acks = 0
        self.boots = 0
        self.rx_bad_frames = 0
        self.flushed = 0                    # Transport contract: stale-input flush counter (never in mock)

        self.executed: list[tuple] = []
        self.open_count = {"entry": 0, "exit": 0}
        self.barrier_log: list[tuple[str, str]] = []

        self._reset_device()

    def open(self) -> None:
        with self._lock:
            if time.monotonic() < self._unplugged_until:
                raise TransportError("mock device unplugged")
            self._is_open = True
            self._drain()
            self._reset_device()  
            self.boots += 1
            self._emit("BOOT", self.firmware)
            self._emit_state()

    def close(self) -> None:
        with self._lock:
            self._is_open = False

    def readline(self) -> bytes:
        self._check_link()
        self._tick()
        try:
            return self._out.get(timeout=0.05)
        except queue.Empty:
            self._check_link()
            return b""

    def write(self, data: bytes) -> None:
        self._check_link()
        with self._lock:
            self._receive(data)

    def set_slot(self, index: int, occupied: bool) -> None:
        with self._lock:
            self.world_slots[index - 1] = occupied

    def set_gate(self, gate: str, present: bool) -> None:
        with self._lock:
            self.world_gate[gate] = present

    def unplug(self, seconds: float) -> None:
        with self._lock:
            self._unplugged_until = time.monotonic() + seconds

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "link_open": self._is_open,
                "unplugged": time.monotonic() < self._unplugged_until,
                "boots": self.boots,
                "world": {"slots": list(self.world_slots), "gates": dict(self.world_gate)},
                "reported": {"slots": list(self._slots), "gates": dict(self._gate)},
                "barrier_open": {g: self._barrier_open[i] for g, i in _GATE_INDEX.items()},
                "open_count": dict(self.open_count),
                "drop_acks": self.drop_acks,
                "executed": len(self.executed),
            }

    def _reset_device(self) -> None:
        self._slots = [False] * self.num_slots
        self._gate = {"entry": False, "exit": False}
        self._barrier_open = [False, False]
        self._hold_until = [0.0, 0.0]
        self._clear_since: list[Optional[float]] = [None, None]
        self._evt_seq = 0
        self._done: dict[tuple[int, int], tuple[bool, str]] = {}
        self._last_hb = time.monotonic()

    def _drain(self) -> None:
        try:
            while True:
                self._out.get_nowait()
        except queue.Empty:
            pass

    def _check_link(self) -> None:
        if not self._is_open:
            raise TransportError("port closed")
        if time.monotonic() < self._unplugged_until:
            self._is_open = False
            raise TransportError("mock device unplugged")

    def _push(self, fields) -> None:
        self._out.put(protocol.encode(fields))

    def _emit(self, name: str, *args) -> None:
        self._evt_seq = self._evt_seq % 65535 + 1
        self._push(("EVT", self._evt_seq, name, *args))

    def _state_args(self) -> list[str]:
        return [
            "".join("1" if s else "0" for s in self._slots),
            "1" if self._gate["entry"] else "0",
            "1" if self._gate["exit"] else "0",
            "1" if self._barrier_open[0] else "0",
            "1" if self._barrier_open[1] else "0",
        ]

    def _emit_state(self) -> None:
        self._emit("STATE", *self._state_args())

    def _tick(self) -> None:
        with self._lock:
            if not self._is_open:
                return
            now = time.monotonic()
            for i in range(self.num_slots):
                if self.world_slots[i] != self._slots[i]:
                    self._slots[i] = self.world_slots[i]
                    self._emit("SLOT", i + 1, "1" if self._slots[i] else "0")
            for gate, g in _GATE_INDEX.items():
                if self.world_gate[gate] != self._gate[gate]:
                    self._gate[gate] = self.world_gate[gate]
                    self._emit("GATE", gate, "1" if self._gate[gate] else "0")
                if self._barrier_open[g] and now >= self._hold_until[g]:
                    if self._gate[gate]:
                        self._clear_since[g] = None
                    elif self._clear_since[g] is None:
                        self._clear_since[g] = now
                    elif now - self._clear_since[g] >= self.clear_ms / 1000:
                        self._barrier_open[g] = False
                        self._clear_since[g] = None
                        self.barrier_log.append((gate, "CLOSED"))
                        self._emit("BARRIER", gate, "CLOSED")
            if now - self._last_hb >= self.heartbeat_s:
                self._last_hb = now
                self._emit("HB", int(now) % 100000, *self._state_args())

    def _receive(self, data: bytes) -> None:
        for raw in data.splitlines():
            if not raw.strip():
                continue
            try:
                fields = protocol.decode(raw)
            except protocol.ProtocolError:
                self.rx_bad_frames += 1
                self._push(("NAK", 0, "CHECKSUM"))
                continue
            if len(fields) < 3 or fields[0] != "CMD" or not fields[1].isdigit() or int(fields[1]) == 0:
                self._push(("NAK", 0, "BAD_FRAME"))
                continue
            seq = int(fields[1])
            # like firmware 1.1: a retransmit is identified by (seq, frame checksum), not by seq alone
            key = (seq, protocol.checksum(",".join(fields)))
            if key in self._done:
                ok, detail = self._done[key]
                self._answer(seq, ok, "DUP" if ok else detail)
                continue
            ok, detail = self._run(fields[2], fields[3:])
            self._done[key] = (ok, detail)
            if len(self._done) > 4:
                self._done.pop(next(iter(self._done)))
            self._answer(seq, ok, detail)
            if ok and fields[2] == "SYNC":
                self._emit_state()

    def _answer(self, seq: int, ok: bool, detail: str) -> None:
        if self.drop_acks > 0:
            self.drop_acks -= 1
            return
        if ok:
            self._push(("ACK", seq, "OK", *([detail] if detail else [])))
        else:
            self._push(("NAK", seq, detail))

    def _run(self, name: str, args: list[str]) -> tuple[bool, str]:
        if name in ("PING", "SYNC"):
            return True, ""
        if name in ("OPEN", "CLOSE"):
            if not args:
                return False, "BAD_ARGS"
            if args[0] not in _GATE_INDEX:
                return False, "BAD_GATE"
            g = _GATE_INDEX[args[0]]
            if name == "CLOSE":
                if self._gate[args[0]]:
                    return False, "VEHICLE_PRESENT"
                self._close(args[0], g)
                return True, ""
            hold = self.hold_ms
            if len(args) > 1:
                if not args[1].isdigit() or not 500 <= int(args[1]) <= 60000:
                    return False, "BAD_VALUE"
                hold = int(args[1])
            already = self._barrier_open[g]
            self._barrier_open[g] = True
            self._hold_until[g] = time.monotonic() + hold / 1000
            self._clear_since[g] = None
            self.open_count[args[0]] += 1
            self.executed.append(("OPEN", args[0]))
            if not already:
                self.barrier_log.append((args[0], "OPENED"))
                self._emit("BARRIER", args[0], "OPENED")
            return True, "REFRESHED" if already else ""
        if name == "CFG":
            if len(args) != 2:
                return False, "BAD_ARGS"
            known = {"gate_thr", "slot_thr", "hyst", "debounce", "debounce_free", "median", "sample_ms",
                     "hold_ms", "clear_ms", "open_deg", "closed_deg", "hb_ms", "dbg"}
            if args[0] not in known:
                return False, "BAD_KEY"
            if not args[1].isdigit():
                return False, "BAD_VALUE"
            if args[0] == "hold_ms":
                self.hold_ms = int(args[1])
            self.executed.append(("CFG", args[0]))
            return True, ""
        return False, "UNKNOWN_CMD"

    def _close(self, gate: str, g: int) -> None:
        if self._barrier_open[g]:
            self._barrier_open[g] = False
            self.barrier_log.append((gate, "CLOSED"))
            self._emit("BARRIER", gate, "CLOSED")
