
from __future__ import annotations

from app.db.models import ParkingSession
from app.repositories import Repositories
from app.utils import format_duration_hms, generate_qr_base64


class DisplayPayloadBuilder:
    def __init__(self, repos: Repositories, base_url: str) -> None:
        self._repos = repos
        self._base_url = base_url

    def pay_url(self, session_id: int) -> str:
        return f"{self._base_url}/pay/{session_id}"

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
        }

    def exit_status(self) -> dict:
        pending = self._repos.sessions.find_latest_awaiting_payment()
        return self.exit_bill(pending) if pending else self.exit_cleared()

    @staticmethod
    def barrier_open(gate: str, plate_number: str) -> dict:
        return {"event": "barrier_open", "plate_number": plate_number, "gate": gate}

    @staticmethod
    def exit_cleared() -> dict:
        return {"event": "exit_clear"}
