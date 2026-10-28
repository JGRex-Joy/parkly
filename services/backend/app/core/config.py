from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ParkingLayout:
    slots: tuple[str, ...] = ("P1", "P2", "P3", "P4")

    @property
    def total(self) -> int:
        return len(self.slots)


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://localhost:8000"  
    database_url: str = "sqlite:///./parkly.db"
    pending_entry_ttl_seconds: int = 900
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"          # development | test | production
    payment_mode: str = "webhook"
    payment_webhook_secret: str = ""          # HMAC-SHA256 key shared with the provider
    currency: str = "KGS"
    billing_start: str = "parked"             # parked | entry
    auth_ttl_seconds: int = 120
    auto_settle_free_stays: bool = True
    entry_stale_seconds: int = 6 * 3600
    ambiguous_slot_policy: str = "fifo"
    service_token: str = ""                   
    admin_token: str = ""                     
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
            environment=os.getenv("PARKING_ENV", defaults.environment).lower(),
            payment_mode=os.getenv("PARKING_PAYMENT_MODE", defaults.payment_mode).lower(),
            payment_webhook_secret=os.getenv("PARKING_PAYMENT_WEBHOOK_SECRET", ""),
            currency=os.getenv("PARKING_CURRENCY", defaults.currency),
            billing_start=os.getenv("PARKING_BILLING_START", defaults.billing_start).lower(),
            auth_ttl_seconds=int(os.getenv("PARKING_AUTH_TTL_SECONDS", defaults.auth_ttl_seconds)),
            entry_stale_seconds=int(
                os.getenv("PARKING_ENTRY_STALE_SECONDS", defaults.entry_stale_seconds)
            ),
            ambiguous_slot_policy=os.getenv(
                "PARKING_AMBIGUOUS_SLOT_POLICY", defaults.ambiguous_slot_policy
            ).lower(),
            auto_settle_free_stays=os.getenv("PARKING_AUTO_SETTLE_FREE_STAYS", "true").lower()
            in ("1", "true", "yes", "on"),
            service_token=os.getenv("PARKING_SERVICE_TOKEN", ""),
            admin_token=os.getenv("PARKING_ADMIN_TOKEN", ""),
        ).validated()

    def validated(self) -> "Settings":
        if self.payment_mode not in ("webhook", "simulated"):
            raise ValueError("PARKING_PAYMENT_MODE must be 'webhook' or 'simulated'")
        if self.payment_mode == "simulated" and self.environment not in ("development", "test"):
            raise ValueError(
                "PARKING_PAYMENT_MODE=simulated is only allowed with PARKING_ENV=development|test"
            )
        if self.billing_start not in ("parked", "entry"):
            raise ValueError("PARKING_BILLING_START must be 'parked' or 'entry'")
        if self.ambiguous_slot_policy not in ("fifo", "reject"):
            raise ValueError("PARKING_AMBIGUOUS_SLOT_POLICY must be 'fifo' or 'reject'")
        return self
