from __future__ import annotations

from typing import Optional

CHANNEL = "parking"


def _hms(seconds: Optional[int]) -> str:
    s = max(int(seconds or 0), 0)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _number(value: Optional[float]):
    v = float(value or 0)
    return int(v) if v.is_integer() else round(v, 2)


def entry_ocr(plate: str) -> dict:
    return {"event": "ENTRY_OCR", "plate": plate}


def slot_occupied(slot_id: int, plate: str) -> dict:
    return {"event": "SLOT_OCCUPIED", "slot_id": slot_id, "plate": plate}


def exit_ocr(session) -> dict:
    return {
        "event": "EXIT_OCR",
        "slot_id": session.slot_id,
        "plate": session.plate_number,
        "duration": _hms(session.duration_seconds),
        "fee": _number(session.amount_due),
    }


def payment_confirmed(plate: str) -> dict:
    return {"event": "PAYMENT_CONFIRMED", "plate": plate}


def slot_released(slot_id: int) -> dict:
    return {"event": "SLOT_RELEASED", "slot_id": slot_id}
