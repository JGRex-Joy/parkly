
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, and_, select
from sqlalchemy.orm import Session

from app.db.models import ParkingSession, SessionStatus


def _awaiting_slot():
    """Admitted at the gate but not yet standing on a space."""
    return and_(
        ParkingSession.slot_id.is_(None),
        or_(
            ParkingSession.status == SessionStatus.ENTERED,
            and_(
                ParkingSession.status == SessionStatus.EMPLOYEE_PASS,
                ParkingSession.exit_time.is_(None),
            ),
        ),
    )


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, session: ParkingSession) -> ParkingSession:
        self._db.add(session)
        self._db.flush()
        return session

    def get(self, session_id: int) -> Optional[ParkingSession]:
        return self._db.get(ParkingSession, session_id)

    def list_recent_first(self) -> list[ParkingSession]:
        return list(self._db.scalars(select(ParkingSession).order_by(ParkingSession.id.desc())))

    def list_awaiting_slot(self, plate_number: Optional[str] = None) -> list[ParkingSession]:
        """Oldest first; customers and staff together."""
        stmt = select(ParkingSession).where(_awaiting_slot())
        if plate_number:
            stmt = stmt.where(ParkingSession.plate_number == plate_number)
        return list(
            self._db.scalars(stmt.order_by(ParkingSession.entry_time.asc(), ParkingSession.id.asc()))
        )

    def count_awaiting_slot(self, *, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(ParkingSession)
            .where(_awaiting_slot(), ParkingSession.entry_time >= since)
        )
        return self._db.scalar(stmt) or 0

    def find_parked_customer(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                ParkingSession.status == SessionStatus.PARKED,
            )
            .order_by(ParkingSession.entry_time.desc(), ParkingSession.id.desc())
        ).first()

    def find_open_staff(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                ParkingSession.status == SessionStatus.EMPLOYEE_PASS,
                ParkingSession.exit_time.is_(None),
            )
            .order_by(ParkingSession.entry_time.desc(), ParkingSession.id.desc())
        ).first()

    def find_slot_holder(self, slot_id: int) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession).where(
                ParkingSession.slot_id == slot_id,
                ParkingSession.slot_released_at.is_(None),
            )
        ).first()

    def find_latest_awaiting_payment(self) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(ParkingSession.status == SessionStatus.AWAITING_PAYMENT)
            .order_by(ParkingSession.exit_time.desc(), ParkingSession.id.desc())
        ).first()

    def flush(self) -> None:
        self._db.flush()
