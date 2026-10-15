from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Employee


class EmployeeRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def is_staff_plate(self, plate_number: str) -> bool:
        return (
            self._db.scalars(
                select(Employee.id).where(Employee.plate_number == plate_number)
            ).first()
            is not None
        )
