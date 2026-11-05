from __future__ import annotations

import os
from dataclasses import dataclass, fields

VACANT_POLICIES = ("forward", "skip_staff", "ignore")


def _parse_slot_map(text: str) -> tuple[tuple[int, str], ...]:
    pairs = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        index, _, number = item.partition(":")
        pairs.append((int(index), number.strip()))
    if not pairs:
        raise ValueError("BRIDGE_SLOT_MAP is empty")
    return tuple(pairs)


def _parse_kv(text: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"expected key=value, got {item!r}")
        pairs.append((key.strip(), value.strip()))
    return tuple(pairs)


def _bool(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    serial_port: str = "auto"          
    serial_baud: int = 115200
    serial_boot_delay: float = 2.0     
    reconnect_min: float = 1.0
    reconnect_max: float = 10.0
    link_timeout: float = 8.0          
    ack_timeout: float = 0.6
    ack_retries: int = 3
    backend_url: str = "http://localhost:8000"
    ocr_url: str = "http://localhost:8001"
    http_timeout: float = 5.0
    ocr_timeout: float = 30.0
    ocr_max_attempts: int = 3
    ocr_retry_delay: float = 2.0
    slot_map: tuple[tuple[int, str], ...] = ((1, "P1"), (2, "P2"), (3, "P3"), (4, "P4"))
    slot_vacant_policy: str = "forward"   # forward | skip_staff | ignore
    slot_retry_attempts: int = 5
    slot_reconcile_interval: float = 10.0
    slot_unmatched_max: int = 30
    slot_settle_s: float = 0.3         # a slot value must stay unchanged this long before it is POSTed
    slot_min_interval_s: float = 1.0   # at most one POST per slot per interval (rate limit)
    rx_backlog_max: int = 1024         # bytes waiting in the OS buffer before stale input is flushed
    bad_frame_log_interval: float = 1.0  # log at most one "bad frame" line per interval (count the rest)
    unexpected_boot_window_s: float = 6.0  # BOOT this long after link-up = board reset by itself
    open_hold_ms: int = 8000
    open_deadline: float = 10.0        
    open_dedupe_seconds: float = 15.0
    api_token: str = ""                
    service_token: str = ""            
    backend_ws_enabled: bool = True    
    auth_poll_interval: float = 3.0    
    report_attempts: int = 5           
    clear_report_window: float = 300.0 
    device_cfg: tuple[tuple[str, str], ...] = ()  
    log_level: str = "INFO"
    log_format: str = "json"           
    mock_hold_ms: int = 3000
    mock_clear_ms: int = 300
    mock_heartbeat_s: float = 1.0

    @property
    def mock(self) -> bool:
        return self.serial_port.startswith("mock://")

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        defaults = cls()
        values = {}
        for f in fields(cls):
            raw = env.get(f"BRIDGE_{f.name.upper()}")
            if raw is None:
                continue
            default = getattr(defaults, f.name)
            if f.name == "slot_map":
                values[f.name] = _parse_slot_map(raw)
            elif f.name == "device_cfg":
                values[f.name] = _parse_kv(raw)
            elif isinstance(default, bool):
                values[f.name] = _bool(raw)
            elif isinstance(default, int):
                values[f.name] = int(raw)
            elif isinstance(default, float):
                values[f.name] = float(raw)
            else:
                values[f.name] = raw
        settings = cls(**values)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.slot_vacant_policy not in VACANT_POLICIES:
            raise ValueError(f"BRIDGE_SLOT_VACANT_POLICY must be one of {VACANT_POLICIES}")
        if self.log_format not in ("json", "text"):
            raise ValueError("BRIDGE_LOG_FORMAT must be json or text")
        if self.ack_retries < 0 or self.ack_timeout <= 0:
            raise ValueError("invalid ACK settings")
        if min(self.slot_settle_s, self.slot_min_interval_s, self.bad_frame_log_interval) < 0 or self.rx_backlog_max < 128:
            raise ValueError("invalid slot rate-limit / backlog settings")
        if sorted(i for i, _ in self.slot_map) != list(range(1, len(self.slot_map) + 1)):
            raise ValueError("BRIDGE_SLOT_MAP indexes must be 1..N")
