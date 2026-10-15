
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from app.api.exceptions import (
    ConfigurationError,
    NoFreeSpaceError,
    NotFoundError,
    SlotOccupiedError,
)
from app.db.models import ParkingSession, SessionStatus, Slot, SlotStatus
from app.repositories import Repositories
from app.services.allocation import LotOccupancy
from app.services.billing import BillingCalculator
from app.services.display import DisplayPayloadBuilder
from app.services.unit_of_work import Outbox, UnitOfWork
from app.utils import normalize_plate, utcnow

NO_PENDING_SESSION = (
    "Нет сессии со статусом ENTERED без назначенного слота "
    "(сначала вызовите /api/sim/entry)"
)


class ParkingService:
    def __init__(
        self,
        repos: Repositories,
        uow: UnitOfWork,
        displays: DisplayPayloadBuilder,
        *,
        pending_entry_ttl_seconds: int,
        billing: Optional[BillingCalculator] = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repos = repos
        self._uow = uow
        self._displays = displays
        self._pending_ttl = timedelta(seconds=pending_entry_ttl_seconds)
        self._billing = billing or BillingCalculator()
        self._clock = clock

    # ------------------------------------------------------------------ reads
    def list_slots(self) -> list[Slot]:
        return self._repos.slots.list_active()

    def list_sessions(self) -> list[ParkingSession]:
        return self._repos.sessions.list_recent_first()

    # ------------------------------------------------------------------ entry
    def register_entry(self, plate_number: str) -> ParkingSession:
 
        plate = normalize_plate(plate_number)
        with self._uow.transaction() as outbox:
            is_staff = self._repos.employees.is_staff_plate(plate)
            if self._occupancy().available <= 0:
                raise NoFreeSpaceError(is_staff=is_staff)

            session = self._repos.sessions.add(
                ParkingSession(
                    plate_number=plate,
                    status=SessionStatus.EMPLOYEE_PASS if is_staff else SessionStatus.ENTERED,
                    entry_time=self._clock(),
                )
            )
            outbox.add("entry", self._displays.barrier_open("entry", plate))
        return session

    # -------------------------------------------------------------- occupancy
    def occupy_slot(self, slot_id: int, plate_number: Optional[str] = None) -> ParkingSession:
        """A space sensor reports a vehicle: bind the waiting session to it."""
        with self._uow.transaction() as outbox:
            slot = self._require_slot(slot_id)
            if slot.status == SlotStatus.PARKED:
                raise SlotOccupiedError()

            session = self._select_session_for(plate_number)
            self._repos.slots.mark_parked(slot)
            session.slot_id = slot.id
            session.slot_released_at = None
            session.parked_time = self._clock()
            if not session.is_staff:
                session.status = SessionStatus.PARKED
            self._repos.sessions.flush()
            outbox.add("entry", self._displays.entry_status())
        return session

    def release_slot(self, slot_id: int) -> Slot:

        with self._uow.transaction() as outbox:
            slot = self._repos.slots.get(slot_id)
            if slot is None:
                raise NotFoundError("Слот не найден")
            holder = self._repos.sessions.find_slot_holder(slot.id)
            self._repos.slots.mark_free(slot)
            if holder:
                now = self._clock()
                holder.slot_released_at = now
                if holder.is_staff:
                    self._close_staff_visit(holder, now)
                self._repos.sessions.flush()
            outbox.add("entry", self._displays.entry_status())
        return slot

    # ------------------------------------------------------------------- exit
    def register_exit(self, plate_number: str) -> ParkingSession:
        plate = normalize_plate(plate_number)
        with self._uow.transaction() as outbox:
            staff = self._repos.sessions.find_open_staff(plate)
            if staff:
                self._staff_departure(staff, outbox)
                return staff

            session = self._repos.sessions.find_parked_customer(plate)
            if not session:
                raise NotFoundError("Нет припаркованной (PARKED) сессии с таким номером")
            self._issue_bill(session)
            outbox.add("exit", self._displays.exit_bill(session))
        return session

    # ---------------------------------------------------------------- helpers
    def _occupancy(self) -> LotOccupancy:
        since = self._clock() - self._pending_ttl
        return LotOccupancy(
            free_slots=self._repos.slots.count_free(),
            pending=self._repos.sessions.count_awaiting_slot(since=since),
            legacy_occupied=self._repos.slots.count_occupied_outside_layout(),
        )

    def _require_slot(self, slot_id: int) -> Slot:
        slot = self._repos.slots.get_active(slot_id)
        if slot is None:
            raise NotFoundError("Слот не найден")
        return slot

    def _select_session_for(self, plate_number: Optional[str]) -> ParkingSession:
        """The oldest waiting vehicle (of this plate, if one is given).

        The type of vehicle never limits which space it may take."""
        plate = normalize_plate(plate_number) if plate_number else None
        waiting = self._repos.sessions.list_awaiting_slot(plate)
        if not waiting:
            raise NotFoundError(NO_PENDING_SESSION)
        return waiting[0]

    def _issue_bill(self, session: ParkingSession) -> None:
        tariff = self._repos.tariffs.get_active()
        if tariff is None:
            raise ConfigurationError("Нет активного тарифа")
        now = self._clock()
        bill = self._billing.calculate(session.entry_time, now, tariff)
        session.exit_time = now
        session.duration_seconds = bill.duration_seconds
        session.amount_due = bill.amount
        session.tariff_id = tariff.id
        session.status = SessionStatus.AWAITING_PAYMENT
        self._repos.sessions.flush()

    def _staff_departure(self, session: ParkingSession, outbox: Outbox) -> None:
        now = self._clock()
        if session.holds_slot:
            slot = self._repos.slots.get(session.slot_id)
            if slot is not None:
                self._repos.slots.mark_free(slot)
            session.slot_released_at = now
        self._close_staff_visit(session, now)
        self._repos.sessions.flush()
        outbox.add("exit", self._displays.barrier_open("exit", session.plate_number))
        outbox.add("entry", self._displays.entry_status())

    def _close_staff_visit(self, session: ParkingSession, now: datetime) -> None:
        session.exit_time = now
        session.duration_seconds = max(int((now - session.entry_time).total_seconds()), 0)
