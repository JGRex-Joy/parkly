
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.db.models import Tariff


@dataclass(frozen=True)
class Bill:
    duration_seconds: int
    amount: float


class BillingCalculator:
    def calculate(self, entry_time: datetime, now: datetime, tariff: Tariff) -> Bill:
        duration_seconds = max(int((now - entry_time).total_seconds()), 0)
        billable_minutes = max(math.ceil(duration_seconds / 60) - tariff.free_minutes, 0)
        return Bill(
            duration_seconds=duration_seconds,
            amount=round(billable_minutes * tariff.price_per_minute, 2),
        )
