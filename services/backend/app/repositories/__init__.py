from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.audit import AuditRepository
from app.repositories.employees import EmployeeRepository
from app.repositories.payments import PaymentRepository
from app.repositories.sessions import SessionRepository
from app.repositories.slots import SlotRepository
from app.repositories.tariffs import TariffRepository


@dataclass(frozen=True)
class Repositories:
    slots: SlotRepository
    sessions: SessionRepository
    tariffs: TariffRepository
    employees: EmployeeRepository
    payments: PaymentRepository
    audit: AuditRepository

    @classmethod
    def for_session(cls, db: Session) -> "Repositories":
        return cls(
            slots=SlotRepository(db),
            sessions=SessionRepository(db),
            tariffs=TariffRepository(db),
            employees=EmployeeRepository(db),
            payments=PaymentRepository(db),
            audit=AuditRepository(db),
        )


__all__ = [
    "AuditRepository",
    "EmployeeRepository",
    "PaymentRepository",
    "Repositories",
    "SessionRepository",
    "SlotRepository",
    "TariffRepository",
]
