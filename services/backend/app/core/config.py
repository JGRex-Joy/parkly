
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ParkingLayout:
    """The physical layout of the lot: exactly four shared spaces.

    Every space can be used by any vehicle, staff or customer. The layout is a
    business invariant and deliberately not overridable through the environment.
    """

    slots: tuple[str, ...] = ("P1", "P2", "P3", "P4")

    @property
    def total(self) -> int:
        return len(self.slots)


@dataclass(frozen=True)
class Settings:
    base_url: str = "10.46.227.79:8000"
    database_url: str = "sqlite:///./parkly.db"
    # An admitted vehicle that never reaches a space stops reserving capacity
    # after this many seconds (it may still park later if a space is free).
    pending_entry_ttl_seconds: int = 900
    cors_origins: tuple[str, ...] = ()
    layout: ParkingLayout = field(default_factory=ParkingLayout)
    templates_dir: Path = APP_DIR / "templates"
    static_dir: Path = APP_DIR / "static"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        origins = os.getenv("PARKING_CORS_ORIGINS", "")
        return cls(
            base_url=os.getenv("PARKING_BASE_URL", defaults.base_url),
            database_url=os.getenv("PARKING_DATABASE_URL", defaults.database_url),
            pending_entry_ttl_seconds=int(
                os.getenv(
                    "PARKING_PENDING_ENTRY_TTL_SECONDS", defaults.pending_entry_ttl_seconds
                )
            ),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )
