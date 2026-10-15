
from __future__ import annotations

import base64
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, Tuple

import qrcode


def utcnow() -> datetime:
    """Naive UTC timestamp (the format already stored in the database)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_plate(plate_number: str) -> str:
    return plate_number.upper()


def generate_qr_base64(data: str) -> str:
    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def format_duration_hms(duration_seconds: Optional[int]) -> Tuple[int, int, int]:
    hours, remainder = divmod(duration_seconds or 0, 3600)
    minutes, seconds = divmod(remainder, 60)
    return hours, minutes, seconds
