from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, and_, select
from sqlalchemy.orm import Session

from app.db.models import ParkingSession, SessionStatus


def _awaiting_slot():
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


def _roaming():
    return and_(
        ParkingSession.slot_id.is_not(None),
        ParkingSession.slot_released_at.is_not(None),
        or_(
            ParkingSession.status == SessionStatus.PARKED,
            and_(
                ParkingSession.status == SessionStatus.EMPLOYEE_PASS,
                ParkingSession.exit_time.is_(None),
            ),
        ),
    )


def _newest_first():
    return (ParkingSession.entry_time.desc(), ParkingSession.id.desc())


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

    def list_awaiting_slot(
        self, plate_number: Optional[str] = None, *, not_before: Optional[datetime] = None
    ) -> list[ParkingSession]:
        stmt = select(ParkingSession).where(_awaiting_slot())
        if plate_number:
            stmt = stmt.where(ParkingSession.plate_number == plate_number)
        if not_before is not None:
            stmt = stmt.where(ParkingSession.entry_time >= not_before)
        return list(
            self._db.scalars(stmt.order_by(ParkingSession.entry_time.asc(), ParkingSession.id.asc()))
        )

    def list_roaming(self, plate_number: Optional[str] = None) -> list[ParkingSession]:
        stmt = select(ParkingSession).where(_roaming())
        if plate_number:
            stmt = stmt.where(ParkingSession.plate_number == plate_number)
        return list(
            self._db.scalars(stmt.order_by(ParkingSession.slot_released_at.desc(), ParkingSession.id.desc()))
        )

    def count_awaiting_slot(self, *, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(ParkingSession)
            .where(_awaiting_slot(), ParkingSession.entry_time >= since)
        )
        return self._db.scalar(stmt) or 0

    def list_stale_awaiting(self, *, before: datetime) -> list[ParkingSession]:
        return list(
            self._db.scalars(
                select(ParkingSession).where(_awaiting_slot(), ParkingSession.entry_time < before)
            )
        )

    def find_active_for_plate(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                or_(
                    ParkingSession.status.in_(
                        (
                            SessionStatus.ENTERED,
                            SessionStatus.PARKED,
                            SessionStatus.AWAITING_PAYMENT,
                        )
                    ),
                    and_(
                        ParkingSession.status == SessionStatus.EMPLOYEE_PASS,
                        ParkingSession.exit_time.is_(None),
                    ),
                ),
            )
            .order_by(*_newest_first())
        ).first()

    def list_paid_unfinished(self, plate_number: str) -> list[ParkingSession]:
        return list(self._db.scalars(
            select(ParkingSession).where(
                ParkingSession.plate_number == plate_number,
                ParkingSession.status == SessionStatus.PAID,
                ParkingSession.completed_time.is_(None),
            )
        ))

    def find_customer_for_exit(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                or_(
                    ParkingSession.status.in_(
                        (
                            SessionStatus.ENTERED,
                            SessionStatus.PARKED,
                            SessionStatus.AWAITING_PAYMENT,
                        )
                    ),
                    and_(
                        ParkingSession.status == SessionStatus.PAID,
                        ParkingSession.completed_time.is_(None),
                    ),
                ),
            )
            .order_by(*_newest_first())
        ).first()

    def find_parked_customer(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                ParkingSession.status == SessionStatus.PARKED,
            )
            .order_by(*_newest_first())
        ).first()

    def find_open_staff(self, plate_number: str) -> Optional[ParkingSession]:
        return self._db.scalars(
            select(ParkingSession)
            .where(
                ParkingSession.plate_number == plate_number,
                ParkingSession.status == SessionStatus.EMPLOYEE_PASS,
                ParkingSession.exit_time.is_(None),
            )
            .order_by(*_newest_first())
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

    def list_entry_authorizations(self, *, since: datetime) -> list[ParkingSession]:
        return list(
            self._db.scalars(
                select(ParkingSession)
                .where(
                    _awaiting_slot(),
                    ParkingSession.entry_open_acked_at.is_(None),
                    ParkingSession.entry_time >= since,
                )
                .order_by(ParkingSession.id)
            )
        )

    def list_exit_authorizations(self, *, since: datetime) -> list[ParkingSession]:
        return list(
            self._db.scalars(
                select(ParkingSession)
                .where(
                    ParkingSession.exit_authorized_at.is_not(None),
                    ParkingSession.exit_authorized_at >= since,
                    ParkingSession.exit_open_acked_at.is_(None),
                    ParkingSession.completed_time.is_(None),
                    ParkingSession.status.in_(
                        (SessionStatus.PAID, SessionStatus.EXCEPTION, SessionStatus.EMPLOYEE_PASS)
                    ),
                )
                .order_by(ParkingSession.id)
            )
        )

    def list_unconfirmed_exits(self, plate_number: Optional[str] = None) -> list[ParkingSession]:
        stmt = select(ParkingSession).where(
            ParkingSession.exit_authorized_at.is_not(None),
            ParkingSession.completed_time.is_(None),
            ParkingSession.status.in_(
                (SessionStatus.PAID, SessionStatus.EXCEPTION, SessionStatus.EMPLOYEE_PASS)
            ),
        )
        if plate_number:
            stmt = stmt.where(ParkingSession.plate_number == plate_number)
        return list(self._db.scalars(stmt.order_by(ParkingSession.exit_authorized_at.desc())))

    def flush(self) -> None:
        self._db.flush()
