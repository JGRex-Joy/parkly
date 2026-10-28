from __future__ import annotations

from app.api.exceptions import ConflictError
from app.db.models import ParkingSession, SessionStatus as S

ALLOWED: dict[S, frozenset[S]] = {
    S.ENTERED: frozenset({S.PARKED, S.EXCEPTION}),
    S.PARKED: frozenset({S.AWAITING_PAYMENT, S.EXCEPTION}),
    S.AWAITING_PAYMENT: frozenset({S.PAID, S.EXCEPTION}),
    S.PAID: frozenset({S.COMPLETED, S.EXCEPTION}),
    S.EXCEPTION: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.EMPLOYEE_PASS: frozenset(),
}


class IllegalTransitionError(ConflictError):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"Недопустимый переход статуса сессии: {current.value} -> {target.value}")
        self.current, self.target = current, target


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED.get(current, frozenset())


def transition(session: ParkingSession, target: S) -> None:
    if not can_transition(session.status, target):
        raise IllegalTransitionError(session.status, target)
    session.status = target
