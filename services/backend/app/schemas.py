from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import SessionStatus, SlotStatus, SlotType


class SimEntryRequest(BaseModel):
    plate_number: str = "01KG111AAA"


class SimSensorRequest(BaseModel):
    occupied: bool = True
    plate_number: Optional[str] = None


class SimExitRequest(BaseModel):
    plate_number: str = "01KG111AAA"


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
    # additive fields
    slot_assignment: Optional[str] = None
    exit_authorized_at: Optional[datetime] = None
    completed_time: Optional[datetime] = None
    exception_reason: Optional[str] = None


class BarrierEventIn(BaseModel):
    event_id: str
    gate: str
    event: str
    plate_number: Optional[str] = None


class BarrierAckIn(BaseModel):
    event_id: Optional[str] = None


class OverrideIn(BaseModel):
    reason: str


class PaymentStatusOut(BaseModel):
    session_id: int
    session_status: SessionStatus
    payment_status: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    reference: Optional[str] = None
    simulated: bool = False
    exit_authorized: bool = False


class PaymentResult(BaseModel):
    session_id: int
    status: SessionStatus
    amount_paid: float
    barrier_opened: bool = False
    exit_authorized: bool = True
    simulated: bool = False


class SlotReleaseOut(BaseModel):
    detail: str
    slot: SlotOut
