from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol

from app.api.exceptions import (
    AmbiguousVehicleError,
    ConfigurationError,
    ConflictError,
    NoFreeSpaceError,
    NotFoundError,
    ParkingError,
    SlotOccupiedError,
    ValidationFailedError,
)
from app.core.config import Settings
from app.db.models import ParkingSession, Payment, PaymentStatus, SessionStatus, Slot, SlotStatus
from app.repositories import Repositories
from app.services.allocation import LotOccupancy
from app.services.billing import BillingCalculator
from app.services.display import DisplayPayloadBuilder
from app.services import parking_events as ev
from app.services.payment_providers import PaymentProvider, SimulatedProvider
from app.services.state_machine import transition
from app.services.unit_of_work import Outbox, UnitOfWork
from app.utils import is_plausible_plate, normalize_plate, utcnow

logger = logging.getLogger(__name__)

NO_PENDING_SESSION = (
    "Нет сессии со статусом ENTERED без назначенного слота "
    "(сначала вызовите /api/sim/entry)"
)
NO_PARKED_SESSION = "Нет припаркованной (PARKED) сессии с таким номером"


@dataclass(frozen=True)
class ServicePolicy:
    currency: str = "KGS"
    billing_start: str = "parked"            # parked | entry
    auth_ttl_seconds: int = 120
    entry_stale_seconds: int = 6 * 3600
    ambiguous_slot_policy: str = "fifo"      # fifo | reject
    auto_settle_free_stays: bool = True

    @classmethod
    def from_settings(cls, s: Settings) -> "ServicePolicy":
        return cls(
            currency=s.currency,
            billing_start=s.billing_start,
            auth_ttl_seconds=s.auth_ttl_seconds,
            entry_stale_seconds=s.entry_stale_seconds,
            ambiguous_slot_policy=s.ambiguous_slot_policy,
            auto_settle_free_stays=s.auto_settle_free_stays,
        )


class RejectionAudit(Protocol):
    def record(self, kind: str, **detail) -> None: ...


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
        policy: Optional[ServicePolicy] = None,
        provider: Optional[PaymentProvider] = None,
        rejections: Optional[RejectionAudit] = None,
    ) -> None:
        self._repos = repos
        self._uow = uow
        self._displays = displays
        self._pending_ttl = timedelta(seconds=pending_entry_ttl_seconds)
        self._billing = billing or BillingCalculator()
        self._clock = clock
        self._policy = policy or ServicePolicy()
        self._provider = provider or SimulatedProvider()
        self._rejections = rejections

    def list_slots(self) -> list[Slot]:
        return self._repos.slots.list_active()

    def list_sessions(self) -> list[ParkingSession]:
        return self._repos.sessions.list_recent_first()

    def register_entry(self, plate_number: str) -> ParkingSession:
        try:
            plate = self._valid_plate(plate_number)
            self._sweep_stale()
            with self._uow.transaction() as outbox:
                now = self._clock()
                is_staff = self._repos.employees.is_staff_plate(plate)

                # 409 fix: a PAID session is a finished visit (the car left after paying). It must never
                # block the plate, so close it here and let the vehicle enter again.
                self._complete_paid_leftovers(plate, now)
                existing = self._repos.sessions.find_active_for_plate(plate)
                if existing is not None:
                    return self._repeat_entry(existing, now, is_staff, outbox)

                if self._occupancy().available <= 0:
                    raise NoFreeSpaceError(is_staff=is_staff)

                session = self._repos.sessions.add(
                    ParkingSession(
                        plate_number=plate,
                        status=SessionStatus.EMPLOYEE_PASS if is_staff else SessionStatus.ENTERED,
                        entry_time=now,
                    )
                )
                self._repos.audit.add(
                    "entry_authorized", session_id=session.id, plate_number=plate, staff=is_staff
                )
                outbox.add("entry", self._displays.barrier_open("entry", plate, session))
                outbox.add(ev.CHANNEL, ev.entry_ocr(plate))
            return session
        except ParkingError as exc:
            self._reject("entry_rejected", exc, plate=normalize_plate(plate_number or ""))
            raise

    def _complete_paid_leftovers(self, plate: str, now: datetime) -> None:
        for old in self._repos.sessions.list_paid_unfinished(plate):
            transition(old, SessionStatus.COMPLETED)
            old.completed_time = now
            self._repos.audit.add(
                "exit_assumed_on_reentry", session_id=old.id, plate_number=old.plate_number
            )
        self._repos.sessions.flush()

    def _repeat_entry(
        self, existing: ParkingSession, now: datetime, is_staff: bool, outbox: Outbox
    ) -> ParkingSession:
        waiting = existing.slot_id is None and (
            existing.status == SessionStatus.ENTERED
            or (existing.status == SessionStatus.EMPLOYEE_PASS and existing.exit_time is None)
        )
        if not waiting:
            raise ConflictError(
                f"Автомобиль с номером {existing.plate_number} уже находится на парковке "
                f"(сессия #{existing.id}, статус {existing.status.value})"
            )
        if now - existing.entry_time > self._pending_ttl:
            if self._occupancy().available <= 0:
                raise NoFreeSpaceError(is_staff=is_staff)
            existing.entry_time = now
        if existing.entry_open_acked_at is None:
            outbox.add("entry", self._displays.barrier_open("entry", existing.plate_number, existing))
        self._repos.audit.add(
            "entry_repeat_read",
            session_id=existing.id,
            plate_number=existing.plate_number,
            reauthorized=existing.entry_open_acked_at is None,
        )
        return existing

    def occupy_slot(self, slot_id: int, plate_number: Optional[str] = None) -> ParkingSession:
        try:
            self._sweep_stale()
            with self._uow.transaction() as outbox:
                now = self._clock()
                slot = self._require_slot(slot_id)
                if slot.status == SlotStatus.PARKED:
                    raise SlotOccupiedError()

                session, method = self._select_vehicle(slot, plate_number, now)
                self._repos.slots.mark_parked(slot)
                session.slot_id = slot.id
                session.slot_released_at = None
                session.slot_assignment = method
                if session.parked_time is None:
                    session.parked_time = now
                if session.status == SessionStatus.ENTERED:
                    transition(session, SessionStatus.PARKED)
                self._repos.sessions.flush()
                self._repos.audit.add(
                    "slot_occupied",
                    session_id=session.id,
                    slot_id=slot.id,
                    plate_number=session.plate_number,
                    assignment=method,
                    slot=slot.slot_number,
                )
                if method.startswith("INFERRED"):
                    logger.warning(
                        "slot %s: vehicle %s assigned by inference (no plate, several candidates)",
                        slot.slot_number, session.plate_number,
                    )
                outbox.add("entry", self._displays.entry_status())
                outbox.add(ev.CHANNEL, ev.slot_occupied(slot.id, session.plate_number))
            return session
        except ParkingError as exc:
            self._reject("slot_occupancy_rejected", exc, slot_id=slot_id,
                         plate=normalize_plate(plate_number) if plate_number else None)
            raise

    def release_slot(self, slot_id: int) -> Slot:
        with self._uow.transaction() as outbox:
            slot = self._repos.slots.get(slot_id)
            if slot is None:
                raise NotFoundError("Слот не найден")
            holder = self._repos.sessions.find_slot_holder(slot.id)
            was_occupied = slot.status == SlotStatus.PARKED
            self._repos.slots.mark_free(slot)
            if holder:
                holder.slot_released_at = self._clock()
                self._repos.sessions.flush()
            self._repos.audit.add(
                "slot_vacated",
                slot_id=slot.id,
                session_id=holder.id if holder else None,
                plate_number=holder.plate_number if holder else None,
                slot=slot.slot_number,
                was_occupied=was_occupied,
                had_holder=holder is not None,
            )
            outbox.add("entry", self._displays.entry_status())
            outbox.add(ev.CHANNEL, ev.slot_released(slot.id))
        return slot

    def register_exit(self, plate_number: str) -> ParkingSession:
        try:
            plate = self._valid_plate(plate_number)
            with self._uow.transaction() as outbox:
                now = self._clock()
                staff = self._repos.sessions.find_open_staff(plate)
                if staff:
                    self._staff_departure(staff, now, outbox)
                    return staff

                session = self._repos.sessions.find_customer_for_exit(plate)
                if session is None:
                    raise NotFoundError(NO_PARKED_SESSION)
                if session.status == SessionStatus.PARKED:
                    self._issue_bill(session, now, outbox)
                elif session.status == SessionStatus.AWAITING_PAYMENT:
                    self._reshow_bill(session, outbox)
                elif session.status == SessionStatus.PAID:
                    self._reauthorize_exit(session, now, outbox)
                else:  
                    raise ConflictError(
                        "Автомобиль не занимал парковочное место: счёт не выставляется, "
                        "выезд требует решения оператора"
                    )
            return session
        except ParkingError as exc:
            self._reject("exit_rejected", exc, plate=normalize_plate(plate_number or ""))
            raise

    def _valid_plate(self, plate_number: str) -> str:
        if not is_plausible_plate(plate_number or ""):
            raise ValidationFailedError("Некорректный номер: ожидается 2-16 букв/цифр")
        return normalize_plate(plate_number)

    def _reject(self, kind: str, exc: ParkingError, **detail) -> None:
        if self._rejections is not None:
            self._rejections.record(kind, reason=exc.detail, status=exc.status_code, **detail)

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

    def _sweep_stale(self) -> None:
        with self._uow.transaction() as outbox:
            self._expire_stale(self._clock(), outbox)

    def _expire_stale(self, now: datetime, outbox: Outbox) -> None:
        cutoff = now - timedelta(seconds=self._policy.entry_stale_seconds)
        for stale in self._repos.sessions.list_stale_awaiting(before=cutoff):
            reason = "entry authorisation expired without parking"
            if stale.is_staff:
                stale.exit_time = now
                stale.duration_seconds = 0
                stale.exception_reason = reason
            else:
                transition(stale, SessionStatus.EXCEPTION)
                stale.exception_reason = reason
            self._repos.audit.add("entry_expired", session_id=stale.id, plate_number=stale.plate_number)

    def _select_vehicle(
        self, slot: Slot, plate_number: Optional[str], now: datetime
    ) -> tuple[ParkingSession, str]:
        stale_cutoff = now - timedelta(seconds=self._policy.entry_stale_seconds)
        plate = normalize_plate(plate_number) if plate_number else None
        pending = self._repos.sessions.list_awaiting_slot(plate, not_before=stale_cutoff)
        roaming = self._repos.sessions.list_roaming(plate)
        candidates = pending + roaming
        if not candidates:
            raise NotFoundError(NO_PENDING_SESSION)
        if plate:
            return candidates[0], "PLATE"
        if len(candidates) == 1:
            return candidates[0], "SOLE_CANDIDATE"
        if self._policy.ambiguous_slot_policy == "reject":
            raise AmbiguousVehicleError(
                f"Несколько возможных автомобилей ({len(candidates)}), номер не передан: "
                "укажите plate_number в запросе датчика"
            )
        if pending:  
            return pending[0], "INFERRED_FIFO"
        returning = [s for s in roaming if s.slot_id == slot.id]
        return (returning or roaming)[0], "INFERRED_FIFO"

    def _bill_start(self, session: ParkingSession) -> datetime:
        if self._policy.billing_start == "parked" and session.parked_time is not None:
            return session.parked_time
        return session.entry_time

    def _issue_bill(self, session: ParkingSession, now: datetime, outbox: Outbox) -> None:
        tariff = self._repos.tariffs.get_active()
        if tariff is None:
            raise ConfigurationError("Нет активного тарифа")
        bill = self._billing.calculate(self._bill_start(session), now, tariff)
        session.exit_time = now
        session.duration_seconds = bill.duration_seconds
        session.amount_due = bill.amount
        session.tariff_id = tariff.id
        transition(session, SessionStatus.AWAITING_PAYMENT)
        payment = self._repos.payments.add(
            Payment(
                session_id=session.id,
                reference=self._provider.new_reference(),
                amount=bill.amount,
                currency=self._policy.currency,
                status=PaymentStatus.PENDING,
                provider=self._provider.name,
                is_simulated=self._provider.is_simulated,
            )
        )
        self._repos.sessions.flush()
        self._repos.audit.add(
            "exit_billed",
            session_id=session.id,
            plate_number=session.plate_number,
            amount=bill.amount,
            duration_seconds=bill.duration_seconds,
            billing_start=self._policy.billing_start,
            payment_reference=payment.reference,
        )
        outbox.add(ev.CHANNEL, ev.exit_ocr(session))
        if bill.amount == 0 and self._policy.auto_settle_free_stays:
            self._settle_free_stay(session, payment, now, outbox)
            return
        outbox.add("exit", self._displays.exit_bill(session))

    def _settle_free_stay(
        self, session: ParkingSession, payment: Payment, now: datetime, outbox: Outbox
    ) -> None:
        payment.provider = "free"
        payment.is_simulated = False
        payment.status = PaymentStatus.SUCCEEDED
        payment.confirmed_at = now
        transition(session, SessionStatus.PAID)
        session.paid_time = now
        self._release_held_slot(session, now)
        session.exit_authorized_at = now
        self._repos.sessions.flush()
        self._repos.audit.add("payment_not_required", session_id=session.id, plate_number=session.plate_number)
        self._repos.audit.add("exit_authorized", session_id=session.id, plate_number=session.plate_number)
        outbox.add("exit", self._displays.barrier_open("exit", session.plate_number, session))
        outbox.add("exit", self._displays.exit_cleared())
        outbox.add("entry", self._displays.entry_status())
        outbox.add(ev.CHANNEL, ev.payment_confirmed(session.plate_number))

    def _reshow_bill(self, session: ParkingSession, outbox: Outbox) -> None:
        if self._repos.payments.pending_for(session.id) is None:  
            self._repos.payments.add(
                Payment(
                    session_id=session.id,
                    reference=self._provider.new_reference(),
                    amount=session.amount_due or 0.0,
                    currency=self._policy.currency,
                    status=PaymentStatus.PENDING,
                    provider=self._provider.name,
                    is_simulated=self._provider.is_simulated,
                )
            )
        self._repos.audit.add(
            "exit_repeat_read", session_id=session.id, plate_number=session.plate_number,
            state="awaiting_payment",
        )
        outbox.add("exit", self._displays.exit_bill(session))
        outbox.add(ev.CHANNEL, ev.exit_ocr(session))

    def _reauthorize_exit(self, session: ParkingSession, now: datetime, outbox: Outbox) -> None:
        session.exit_authorized_at = now
        session.exit_open_acked_at = None
        self._repos.audit.add(
            "exit_reauthorized", session_id=session.id, plate_number=session.plate_number
        )
        outbox.add("exit", self._displays.barrier_open("exit", session.plate_number, session))

    def _release_held_slot(self, session: ParkingSession, now: datetime) -> None:
        if session.holds_slot:
            slot = self._repos.slots.get(session.slot_id)
            if slot is not None:
                self._repos.slots.mark_free(slot)
            session.slot_released_at = now

    def _staff_departure(self, session: ParkingSession, now: datetime, outbox: Outbox) -> None:
        self._release_held_slot(session, now)
        session.exit_time = now
        session.duration_seconds = max(int((now - session.entry_time).total_seconds()), 0)
        session.exit_authorized_at = now
        self._repos.sessions.flush()
        self._repos.audit.add("exit_authorized", session_id=session.id,
                              plate_number=session.plate_number, staff=True)
        outbox.add(ev.CHANNEL, ev.exit_ocr(session))
        outbox.add(ev.CHANNEL, ev.payment_confirmed(session.plate_number))
        outbox.add("exit", self._displays.barrier_open("exit", session.plate_number, session))
        outbox.add("entry", self._displays.entry_status())
