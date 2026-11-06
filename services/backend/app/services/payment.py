from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)
from app.db.models import ParkingSession, Payment, PaymentStatus, SessionStatus
from app.repositories import Repositories
from app.services import parking_events as ev
from app.services.display import DisplayPayloadBuilder
from app.services.mock_payment import MockPaymentProvider
from app.services.state_machine import transition
from app.services.unit_of_work import Outbox, UnitOfWork
from app.utils import format_duration_hms, utcnow

AMOUNT_TOLERANCE = 0.005


@dataclass(frozen=True)
class PaymentView:
    session: ParkingSession
    hours: int
    minutes: int
    seconds: int
    already_paid: bool
    payment: Optional[Payment] = None
    simulated_mode: bool = False
    currency: str = "KGS"


@dataclass(frozen=True)
class SettlementResult:
    session: ParkingSession
    payment: Payment
    already_processed: bool


class PaymentService:
    def __init__(
        self,
        repos: Repositories,
        uow: UnitOfWork,
        displays: DisplayPayloadBuilder,
        *,
        clock: Callable[[], datetime] = utcnow,
        provider: Optional[MockPaymentProvider] = None,
        currency: str = "KGS",
        rejections=None,
    ) -> None:
        self._repos = repos
        self._uow = uow
        self._displays = displays
        self._clock = clock
        self._provider = provider or MockPaymentProvider()
        self._currency = currency
        self._rejections = rejections

    def get_payment_view(self, session_id: int) -> PaymentView:
        session = self._repos.sessions.get(session_id)
        if session is None:
            raise NotFoundError("Сессия не найдена")
        hours, minutes, seconds = format_duration_hms(session.duration_seconds)
        payments = self._repos.payments.list_for(session.id)
        payment = next((p for p in reversed(payments) if p.status == PaymentStatus.SUCCEEDED), None) \
            or (payments[-1] if payments else None)
        return PaymentView(
            session=session,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            already_paid=session.status in (SessionStatus.PAID, SessionStatus.COMPLETED),
            payment=payment,
            simulated_mode=self._provider.is_simulated,
            currency=self._currency,
        )

    def pay(self, session_id: int) -> ParkingSession:
        try:
            with self._uow.transaction() as outbox:
                session = self._require_session(session_id)
                payment = self._open_payment(session)
                result = self._provider.charge(payment.reference, payment.amount, payment.currency)
                settled = self._settle(
                    session, payment, transaction_id=result["transaction_id"],
                    amount=result["amount"], currency=result["currency"], outbox=outbox,
                )
            return settled.session
        except (ConflictError, NotFoundError) as exc:
            self._audit_rejection("payment_rejected", session_id=session_id, reason=exc.detail)
            raise

    confirm_simulated_payment = pay
    confirm_payment = pay

    def _require_session(self, session_id: int) -> ParkingSession:
        session = self._repos.sessions.get(session_id)
        if session is None:
            raise NotFoundError("Сессия не найдена")
        return session

    def _open_payment(self, session: ParkingSession) -> Payment:
        if session.status in (SessionStatus.PAID, SessionStatus.COMPLETED):
            raise ConflictError("Сессия уже оплачена")
        if session.status != SessionStatus.AWAITING_PAYMENT:
            raise ConflictError("Оплата недоступна: счёт ещё не выставлен выездной камерой")
        payment = self._repos.payments.pending_for(session.id)
        if payment is None:
            raise ConflictError("Нет открытого платёжного запроса для этой сессии")
        return payment

    def _settle(
        self,
        session: ParkingSession,
        payment: Payment,
        *,
        transaction_id: str,
        amount: float,
        currency: str,
        outbox: Outbox,
    ) -> SettlementResult:
        if payment.session_id != session.id:
            raise ConflictError("Платёж относится к другой сессии")
        if payment.status == PaymentStatus.SUCCEEDED:
            if payment.provider_txn_id != transaction_id:
                self._repos.audit.add(
                    "payment_double_charge_suspected", session_id=session.id,
                    first_transaction=payment.provider_txn_id, second_transaction=transaction_id,
                )
            return SettlementResult(session, payment, already_processed=True)
        if session.status != SessionStatus.AWAITING_PAYMENT:
            raise ConflictError(
                "Оплата недоступна: счёт ещё не выставлен выездной камерой"
                if session.status != SessionStatus.PAID else "Сессия уже оплачена"
            )
        if currency != payment.currency:
            raise ValidationFailedError(f"Валюта платежа {currency} не совпадает с {payment.currency}")
        if abs(amount - payment.amount) > AMOUNT_TOLERANCE:
            raise ValidationFailedError(
                f"Сумма платежа {amount:.2f} не совпадает с выставленной {payment.amount:.2f}"
            )

        now = self._clock()
        payment.status = PaymentStatus.SUCCEEDED
        payment.provider_txn_id = transaction_id
        payment.confirmed_at = now
        transition(session, SessionStatus.PAID)
        session.paid_time = now
        if session.holds_slot:
            slot = self._repos.slots.get(session.slot_id)
            if slot is not None:
                self._repos.slots.mark_free(slot)
            session.slot_released_at = now
        session.exit_authorized_at = now
        self._repos.sessions.flush()

        self._repos.audit.add(
            "payment_succeeded", session_id=session.id, plate_number=session.plate_number,
            amount=payment.amount, currency=payment.currency, provider=payment.provider,
            simulated=payment.is_simulated, transaction_id=transaction_id,
        )
        self._repos.audit.add("exit_authorized", session_id=session.id, plate_number=session.plate_number)

        outbox.add("exit", self._displays.barrier_open("exit", session.plate_number, session))
        outbox.add("exit", self._displays.exit_cleared())
        outbox.add("entry", self._displays.entry_status())
        outbox.add(ev.CHANNEL, ev.payment_confirmed(session.plate_number))
        return SettlementResult(session, payment, already_processed=False)

    def _audit_rejection(self, kind: str, **detail) -> None:
        if self._rejections is not None:
            self._rejections.record(kind, **detail)
