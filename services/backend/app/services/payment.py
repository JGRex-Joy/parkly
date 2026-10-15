
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.api.exceptions import ConflictError, NotFoundError
from app.db.models import ParkingSession, SessionStatus
from app.repositories import Repositories
from app.services.display import DisplayPayloadBuilder
from app.services.unit_of_work import UnitOfWork
from app.utils import format_duration_hms, utcnow


@dataclass(frozen=True)
class PaymentView:
    session: ParkingSession
    hours: int
    minutes: int
    seconds: int
    already_paid: bool


class PaymentService:
    def __init__(
        self,
        repos: Repositories,
        uow: UnitOfWork,
        displays: DisplayPayloadBuilder,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repos = repos
        self._uow = uow
        self._displays = displays
        self._clock = clock

    def get_payment_view(self, session_id: int) -> PaymentView:
        session = self._repos.sessions.get(session_id)
        if session is None:
            raise NotFoundError("Сессия не найдена")
        hours, minutes, seconds = format_duration_hms(session.duration_seconds)
        return PaymentView(
            session=session,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            already_paid=session.status == SessionStatus.PAID,
        )

    def confirm_payment(self, session_id: int) -> ParkingSession:
        with self._uow.transaction() as outbox:
            session = self._repos.sessions.get(session_id)
            if session is None:
                raise NotFoundError("Сессия не найдена")
            if session.status == SessionStatus.PAID:
                raise ConflictError("Сессия уже оплачена")
            if session.status != SessionStatus.AWAITING_PAYMENT:
                raise ConflictError(
                    "Оплата недоступна: счёт ещё не выставлен выездной камерой"
                )

            now = self._clock()
            session.status = SessionStatus.PAID
            session.paid_time = now
            if session.holds_slot:
                slot = self._repos.slots.get(session.slot_id)
                if slot is not None:
                    self._repos.slots.mark_free(slot)
                session.slot_released_at = now
            self._repos.sessions.flush()

            outbox.add("exit", self._displays.barrier_open("exit", session.plate_number))
            outbox.add("exit", self._displays.exit_cleared())
            outbox.add("entry", self._displays.entry_status())
        return session
