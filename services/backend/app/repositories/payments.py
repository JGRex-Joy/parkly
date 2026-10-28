from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, payment: Payment) -> Payment:
        self._db.add(payment)
        self._db.flush()
        return payment

    def by_reference(self, reference: str) -> Optional[Payment]:
        return self._db.scalars(select(Payment).where(Payment.reference == reference)).first()

    def by_txn(self, txn_id: str) -> Optional[Payment]:
        return self._db.scalars(select(Payment).where(Payment.provider_txn_id == txn_id)).first()

    def pending_for(self, session_id: int) -> Optional[Payment]:
        return self._db.scalars(
            select(Payment).where(
                Payment.session_id == session_id, Payment.status == PaymentStatus.PENDING
            )
        ).first()

    def succeeded_for(self, session_id: int) -> Optional[Payment]:
        return self._db.scalars(
            select(Payment).where(
                Payment.session_id == session_id, Payment.status == PaymentStatus.SUCCEEDED
            )
        ).first()

    def list_for(self, session_id: int) -> list[Payment]:
        return list(
            self._db.scalars(select(Payment).where(Payment.session_id == session_id).order_by(Payment.id))
        )
