"""Все настройки лежат здесь. Хотите что-то поменять - правьте значения прямо в этом файле."""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

PORT = 8000                                   

BASE_URL: str | None = None

DATABASE_URL = "sqlite:///./smart_parking.db"
CURRENCY = "KGS"
BILLING_START = "parked"                      
PENDING_ENTRY_TTL_SECONDS = 900               
AUTH_TTL_SECONDS = 120                        
AUTO_SETTLE_FREE_STAYS = True                 
ENTRY_STALE_SECONDS = 6 * 3600
AMBIGUOUS_SLOT_POLICY = "fifo"                
SLOTS = ("P1", "P2", "P3", "P4")              


def _detect_base_url() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  
            ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    return f"http://{ip}:{PORT}"


@dataclass(frozen=True)
class ParkingLayout:
    slots: tuple[str, ...] = SLOTS

    @property
    def total(self) -> int:
        return len(self.slots)


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://localhost:8000"
    database_url: str = DATABASE_URL
    pending_entry_ttl_seconds: int = PENDING_ENTRY_TTL_SECONDS
    currency: str = CURRENCY
    billing_start: str = BILLING_START
    auth_ttl_seconds: int = AUTH_TTL_SECONDS
    auto_settle_free_stays: bool = AUTO_SETTLE_FREE_STAYS
    entry_stale_seconds: int = ENTRY_STALE_SECONDS
    ambiguous_slot_policy: str = AMBIGUOUS_SLOT_POLICY
    layout: ParkingLayout = field(default_factory=ParkingLayout)
    templates_dir: Path = APP_DIR / "templates"
    static_dir: Path = APP_DIR / "static"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(base_url=BASE_URL or _detect_base_url()).validated()

    def validated(self) -> "Settings":
        if self.billing_start not in ("parked", "entry"):
            raise ValueError("BILLING_START must be 'parked' or 'entry'")
        if self.ambiguous_slot_policy not in ("fifo", "reject"):
            raise ValueError("AMBIGUOUS_SLOT_POLICY must be 'fifo' or 'reject'")
        return self
