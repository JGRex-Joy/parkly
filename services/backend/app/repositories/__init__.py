
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.employees import EmployeeRepository
from app.repositories.sessions import SessionRepository
from app.repositories.slots import SlotRepository
from app.repositories.tariffs import TariffRepository


@dataclass(frozen=True)
class Repositories:
    """All repositories bound to one database session."""

    slots: SlotRepository
    sessions: SessionRepository
    tariffs: TariffRepository
    employees: EmployeeRepository

    @classmethod
    def for_session(cls, db: Session) -> "Repositories":
        return cls(
            slots=SlotRepository(db),
            sessions=SessionRepository(db),
            tariffs=TariffRepository(db),
            employees=EmployeeRepository(db),
        )


__all__ = [
    "EmployeeRepository",
    "Repositories",
    "SessionRepository",
    "SlotRepository",
    "TariffRepository",
]
