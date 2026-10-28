from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text, true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.utils import utcnow


class SlotType(str, enum.Enum):
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
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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
    __table_args__ = (
        Index(
            "uq_parking_sessions_active_slot",
            "slot_id",
            unique=True,
            sqlite_where=text("slot_id IS NOT NULL AND slot_released_at IS NULL"),
            postgresql_where=text("slot_id IS NOT NULL AND slot_released_at IS NULL"),
        ),
    )

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

    slot_assignment: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    entry_open_acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_open_acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exception_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("uq_payments_one_pending", "session_id", unique=True,
              sqlite_where=text("status = 'PENDING'"),
              postgresql_where=text("status = 'PENDING'")),
        Index("uq_payments_one_success", "session_id", unique=True,
              sqlite_where=text("status = 'SUCCEEDED'"),
              postgresql_where=text("status = 'SUCCEEDED'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("parking_sessions.id"), index=True)
    reference: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_txn_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    slot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plate_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    event_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
