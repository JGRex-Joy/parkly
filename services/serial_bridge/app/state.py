from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.protocol import DeviceState


@dataclass
class GateRuntime:
    present: bool = False
    phase: str = "IDLE"          # IDLE | PROCESSING | DONE
    generation: int = 0          
    attempts: int = 0
    last_outcome: Optional[dict] = None
    barrier: str = "UNKNOWN"     # last BARRIER event: OPENED | CLOSED
    last_open: Optional[dict] = None
    last_cid: Optional[str] = None   

    def public(self) -> dict:
        return {
            "present": self.present,
            "phase": self.phase,
            "attempts": self.attempts,
            "last_outcome": self.last_outcome,
            "barrier": self.barrier,
            "last_open": None if self.last_open is None else {
                k: v for k, v in self.last_open.items() if k != "opened_at"},
            "last_cid": self.last_cid,
        }


@dataclass
class Counters:
    events_duplicate: int = 0
    events_invalid: int = 0
    gate_triggers: int = 0
    gate_triggers_suppressed: int = 0
    ocr_calls: int = 0
    ocr_forwarded: int = 0
    slot_forwarded: int = 0
    slot_failed: int = 0
    slot_skipped: int = 0
    slot_unmatched: int = 0
    slot_coalesced: int = 0          # flaps absorbed: value changed back before it was ever sent
    slot_dup_suppressed: int = 0     # device repeated a state the backend already has: no HTTP call
    unexpected_resets: int = 0       # Arduino rebooted while the USB link stayed up (brown-out?)
    open_reasserted: int = 0         # OPEN re-sent after a reset inside the authorised hold window
    open_sent: int = 0
    open_duplicates_suppressed: int = 0
    open_failed: int = 0
    auth_executed: int = 0
    auth_ack_failed: int = 0
    reports_sent: int = 0
    reports_failed: int = 0


@dataclass
class BridgeState:
    started_at: float = field(default_factory=time.time)
    epoch: int = 0                                  
    device: Optional[DeviceState] = None
    device_firmware: str = ""
    last_device_message: Optional[float] = None
    gates: dict = field(default_factory=lambda: {"entry": GateRuntime(), "exit": GateRuntime()})
    slot_forwarded: dict = field(default_factory=dict)  
    dist: dict = field(default_factory=dict)         # latest filtered distance per sensor (dbg=1)
    ws_connected: dict = field(default_factory=lambda: {"entry": False, "exit": False})
    counters: Counters = field(default_factory=Counters)
    recent: deque = field(default_factory=lambda: deque(maxlen=60))

    def note(self, event: str, /, **data) -> None:
        self.recent.append({"t": round(time.time(), 3), "event": event, **data})
