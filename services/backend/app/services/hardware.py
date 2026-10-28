from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from app.api.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.db.models import ParkingSession, PaymentStatus, SessionStatus
from app.repositories import Repositories
from app.services import parking_events as ev
from app.services.display import DisplayPayloadBuilder
from app.services.parking import ServicePolicy
from app.services.state_machine import can_transition, transition
from app.services.unit_of_work import UnitOfWork
from app.utils import normalize_plate, utcnow

GATES = ("entry", "exit")
BARRIER_EVENTS = ("OPENED", "CLOSED", "VEHICLE_CLEARED")


class HardwareService:
    def __init__(
        self,
        repos: Repositories,
        uow: UnitOfWork,
        displays: DisplayPayloadBuilder,
        *,
        policy: Optional[ServicePolicy] = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repos = repos
        self._uow = uow
        self._displays = displays
        self._policy = policy or ServicePolicy()
        self._clock = clock

    def pending_authorizations(self, gate: str) -> list[dict]:
        self._check_gate(gate)
        ttl = timedelta(seconds=self._policy.auth_ttl_seconds)
        since = self._clock() - ttl
        if gate == "entry":
            sessions = self._repos.sessions.list_entry_authorizations(since=since)
            stamp = lambda s: s.entry_time  
        else:
            sessions = self._repos.sessions.list_exit_authorizations(since=since)
            stamp = lambda s: s.exit_authorized_at  
        return [
            {
                "authorization_id": f"{gate}-{s.id}",
                "gate": gate,
                "session_id": s.id,
                "plate_number": s.plate_number,
                "authorized_at": stamp(s).isoformat(),
                "expires_at": (stamp(s) + ttl).isoformat(),
            }
            for s in sessions
        ]

    def ack_barrier_command(self, gate: str, session_id: int) -> ParkingSession:
        self._check_gate(gate)
        with self._uow.transaction():
            session = self._repos.sessions.get(session_id)
            if session is None:
                raise NotFoundError("Сессия не найдена")
            now = self._clock()
            if gate == "entry":
                if session.entry_open_acked_at is None:
                    session.entry_open_acked_at = now
                    self._repos.audit.add("barrier_command_acked", session_id=session.id,
                                          plate_number=session.plate_number, gate=gate)
            else:
                if session.exit_authorized_at is None:
                    raise ConflictError("Выезд для этой сессии не разрешён")
                if session.exit_open_acked_at is None:
                    session.exit_open_acked_at = now
                    self._repos.audit.add("barrier_command_acked", session_id=session.id,
                                          plate_number=session.plate_number, gate=gate)
            self._repos.sessions.flush()
        return session

    def report_barrier_event(
        self, event_id: str, gate: str, event: str, plate_number: Optional[str] = None
    ) -> dict:
        self._check_gate(gate)
        if event not in BARRIER_EVENTS:
            raise ValidationFailedError(f"event must be one of {BARRIER_EVENTS}")
        if not event_id:
            raise ValidationFailedError("event_id is required")
        plate = normalize_plate(plate_number) if plate_number else None
        with self._uow.transaction():
            key = f"hw:{event_id}"
            if self._repos.audit.has_key(key):
                return {"duplicate": True, "matched": False}

            now = self._clock()
            session = self._match_exit_session(plate) if gate == "exit" else None
            ambiguous = gate == "exit" and session is None and plate is None and len(
                self._repos.sessions.list_unconfirmed_exits()
            ) > 1
            self._repos.audit.add(
                "barrier_event", event_key=key,
                session_id=session.id if session else None, plate_number=plate,
                gate=gate, event=event, matched=session is not None,
            )
            result: dict = {"duplicate": False, "matched": session is not None}

            if gate == "exit" and session is not None:
                if event == "OPENED" and session.exit_open_acked_at is None:
                    session.exit_open_acked_at = now
                elif event == "VEHICLE_CLEARED":
                    self._complete(session, now)
                result["session_id"] = session.id
                result["status"] = session.status.value
            elif gate == "exit" and event == "VEHICLE_CLEARED":
                self._repos.audit.add(
                    "exit_cleared_ambiguous" if ambiguous else "exit_cleared_unmatched",
                    plate_number=plate,
                )
            self._repos.sessions.flush()
        return result

    def _match_exit_session(self, plate: Optional[str]) -> Optional[ParkingSession]:
        candidates = self._repos.sessions.list_unconfirmed_exits(plate)
        if plate:
            return candidates[0] if candidates else None
        return candidates[0] if len(candidates) == 1 else None

    def _complete(self, session: ParkingSession, now: datetime) -> None:
        if session.completed_time is not None:
            return
        if session.status != SessionStatus.EMPLOYEE_PASS:
            transition(session, SessionStatus.COMPLETED)
        session.completed_time = now
        if session.exit_open_acked_at is None:
            session.exit_open_acked_at = now
        self._repos.audit.add("session_completed", session_id=session.id,
                              plate_number=session.plate_number)

    def operator_exit_override(self, session_id: int, reason: str) -> ParkingSession:
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise ValidationFailedError("Укажите причину ручного разрешения выезда")
        with self._uow.transaction() as outbox:
            session = self._repos.sessions.get(session_id)
            if session is None:
                raise NotFoundError("Сессия не найдена")
            if session.status in (SessionStatus.PAID, SessionStatus.COMPLETED):
                raise ConflictError("Сессия уже оплачена/завершена: ручное разрешение не требуется")
            if session.is_staff:
                raise ConflictError("Сотрудники выезжают по номеру: используйте выездную камеру")
            now = self._clock()
            if session.status != SessionStatus.EXCEPTION:
                if not can_transition(session.status, SessionStatus.EXCEPTION):
                    raise ConflictError("Недопустимое состояние сессии")
                transition(session, SessionStatus.EXCEPTION)
            session.exception_reason = reason
            if session.exit_time is None:
                session.exit_time = now
                session.duration_seconds = max(int((now - session.entry_time).total_seconds()), 0)
            pending = self._repos.payments.pending_for(session.id)
            if pending is not None:
                pending.status = PaymentStatus.CANCELLED
            if session.holds_slot:
                slot = self._repos.slots.get(session.slot_id)
                if slot is not None:
                    self._repos.slots.mark_free(slot)
                session.slot_released_at = now
            session.exit_authorized_at = now
            session.exit_open_acked_at = None
            self._repos.sessions.flush()
            self._repos.audit.add("operator_exit_override", session_id=session.id,
                                  plate_number=session.plate_number, reason=reason)
            outbox.add("exit", self._displays.barrier_open("exit", session.plate_number, session))
            outbox.add("exit", self._displays.exit_cleared())
            outbox.add("entry", self._displays.entry_status())
            outbox.add(ev.CHANNEL, ev.exit_ocr(session))
            outbox.add(ev.CHANNEL, ev.payment_confirmed(session.plate_number))
        return session

    @staticmethod
    def _check_gate(gate: str) -> None:
        if gate not in GATES:
            raise ValidationFailedError(f"gate must be one of {GATES}")
