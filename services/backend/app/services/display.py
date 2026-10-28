from __future__ import annotations

from typing import Optional

from app.db.models import ParkingSession
from app.repositories import Repositories
from app.utils import format_duration_hms, generate_qr_base64


class DisplayPayloadBuilder:
    def __init__(
        self,
        repos: Repositories,
        base_url: str,
        *,
        currency: str = "KGS",
        payment_simulated: bool = False,
        auth_ttl_seconds: int = 120,
    ) -> None:
        self._repos = repos
        self._base_url = base_url
        self._currency = currency
        self._simulated = payment_simulated
        self._auth_ttl = auth_ttl_seconds

    def pay_url(self, session_id: int) -> str:
        base = self._base_url
        if "://" not in base:  
            base = f"http://{base}"
        return f"{base.rstrip('/')}/pay/{session_id}"

    def entry_status(self) -> dict:
        slots, tariff = self._repos.slots, self._repos.tariffs.get_active()
        free, total = slots.count_free(), slots.count_total()
        return {
            "event": "entry_display_update",
            "free_paid_slots": free,
            "free_employee_slots": 0,
            "total_paid_slots": total,
            "total_employee_slots": 0,
            "free_slots": free,
            "total_slots": total,
            "tariff": {
                "name": tariff.name,
                "price_per_minute": tariff.price_per_minute,
                "free_minutes": tariff.free_minutes,
            }
            if tariff
            else None,
        }

    def exit_bill(self, session: ParkingSession) -> dict:
        hours, minutes, seconds = format_duration_hms(session.duration_seconds)
        pay_url = self.pay_url(session.id)
        return {
            "event": "exit_bill",
            "session_id": session.id,
            "plate_number": session.plate_number,
            "duration": {"hours": hours, "minutes": minutes, "seconds": seconds},
            "amount_due": session.amount_due,
            "pay_url": pay_url,
            "qr_code_base64": generate_qr_base64(pay_url),
            "status": session.status.value,
            "currency": self._currency,
            "payment_simulated": self._simulated,
        }

    def exit_status(self) -> dict:
        pending = self._repos.sessions.find_latest_awaiting_payment()
        return self.exit_bill(pending) if pending else self.exit_cleared()

    def barrier_open(self, gate: str, plate_number: str, session: Optional[ParkingSession] = None) -> dict:
        payload = {"event": "barrier_open", "plate_number": plate_number, "gate": gate}
        if session is not None:
            payload.update(
                session_id=session.id,
                authorization_id=f"{gate}-{session.id}",
                expires_in_s=self._auth_ttl,
            )
        return payload

    @staticmethod
    def exit_cleared() -> dict:
        return {"event": "exit_clear"}
