from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.websocket import ENTERING, EXITING, PARKED, ConnectionManager
from app.db.database import Database
from app.db.models import ParkingSession, SessionStatus
from app.repositories.slots import SlotRepository
from app.services.parking_events import _hms, _number
from app.utils import utcnow


def hydrate_dashboard_state(manager: ConnectionManager, database: Database, *, pending_ttl_seconds: int) -> None:
    manager.reset_state()
    cutoff = utcnow() - timedelta(seconds=pending_ttl_seconds)
    with database.session() as db:
        manager.configure_slots(s.id for s in SlotRepository(db).list_active())
        rows = db.scalars(
            select(ParkingSession)
            .where(ParkingSession.status.in_((
                SessionStatus.ENTERED, SessionStatus.PARKED,
                SessionStatus.AWAITING_PAYMENT, SessionStatus.EMPLOYEE_PASS,
            )))
            .order_by(ParkingSession.id)
        ).all()
        for s in rows:
            plate = s.plate_number
            if s.status == SessionStatus.AWAITING_PAYMENT:
                manager.sessions[plate] = {
                    "plate": plate, "phase": EXITING, "slot_id": s.slot_id,
                    "duration": _hms(s.duration_seconds), "fee": _number(s.amount_due),
                }
            elif s.exit_time is not None:
                continue
            elif s.holds_slot and s.slot_id in manager.slot_plates:
                manager.slot_plates[s.slot_id] = plate
                manager.sessions[plate] = {"plate": plate, "phase": PARKED, "slot_id": s.slot_id,
                                           "duration": None, "fee": None}
            elif s.slot_id is None and s.entry_time and s.entry_time >= cutoff:
                manager.sessions[plate] = {"plate": plate, "phase": ENTERING, "slot_id": None,
                                           "duration": None, "fee": None}
