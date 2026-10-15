"""Database entities."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, true
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.utils import utcnow


class SlotType(str, enum.Enum):
    # PAID = regular customer space, EMPLOYEE = staff-designated space.
    # (A comment, not a docstring: docstrings leak into the OpenAPI schema.
    # The names are part of the public API and must not change.)

    PAID = "PAID"
    EMPLOYEE = "EMPLOYEE"


class SlotStatus(str, enum.Enum):
    FREE = "FREE"
    PARKED = "PARKED"


class SessionStatus(str, enum.Enum):
    ENTERED = "ENTERED"
    PARKED = "PARKED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    EMPLOYEE_PASS = "EMPLOYEE_PASS"


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    price_per_minute: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    free_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    slot_type: Mapped[SlotType] = mapped_column(SAEnum(SlotType), nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        SAEnum(SlotStatus), nullable=False, default=SlotStatus.FREE
    )
    # Spaces removed from the layout are kept (history keeps pointing at them)
    # but are never listed or allocated.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_number: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String, nullable=False)


class ParkingSession(Base):


    __tablename__ = "parking_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus), nullable=False, default=SessionStatus.ENTERED
    )

    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utcnow)
    parked_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    paid_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    slot_released_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount_due: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    slot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("slots.id"), nullable=True)
    slot: Mapped[Optional[Slot]] = relationship("Slot")

    tariff_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tariffs.id"), nullable=True
    )
    tariff: Mapped[Optional[Tariff]] = relationship("Tariff")

    @property
    def is_staff(self) -> bool:
        return self.status == SessionStatus.EMPLOYEE_PASS

    @property
    def holds_slot(self) -> bool:
        return self.slot_id is not None and self.slot_released_at is None
