"""Request / response models (the public API contract)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import SessionStatus, SlotStatus, SlotType


class SimEntryRequest(BaseModel):
    plate_number: str = "C123CC"


class SimSensorRequest(BaseModel):
    occupied: bool = True
    plate_number: Optional[str] = None


class SimExitRequest(BaseModel):
    plate_number: str = "C123CC"


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price_per_minute: float
    free_minutes: int
    is_active: bool


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slot_number: str
    slot_type: SlotType
    status: SlotStatus


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_number: str
    status: SessionStatus
    entry_time: datetime
    parked_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    paid_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    amount_due: Optional[float] = None
    slot_id: Optional[int] = None


class PaymentResult(BaseModel):
    session_id: int
    status: SessionStatus
    amount_paid: float
    barrier_opened: bool = True


class SlotReleaseOut(BaseModel):
    detail: str
    slot: SlotOut
