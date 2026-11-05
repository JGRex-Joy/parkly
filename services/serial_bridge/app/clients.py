from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings

FORWARDED = "forwarded"       
RETRYABLE = "retryable"        
FINAL = "final"                
AMBIGUOUS = "ambiguous"        


@dataclass(frozen=True)
class OcrOutcome:
    kind: str
    detail: str = ""
    plate: Optional[str] = None

    def public(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "plate": self.plate}


class BackendClient:
    def __init__(self, settings: Settings) -> None:
        headers = {"X-Service-Token": settings.service_token} if settings.service_token else {}
        self._http = httpx.AsyncClient(
            base_url=settings.backend_url, timeout=settings.http_timeout, headers=headers)
        self._slot_ids: dict[str, int] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ping(self) -> bool:
        try:
            return (await self._http.get("/")).status_code == 200
        except httpx.HTTPError:
            return False

    async def list_slots(self) -> list[dict]:
        response = await self._http.get("/api/sim/slots")
        response.raise_for_status()
        slots = response.json()
        self._slot_ids = {s["slot_number"]: s["id"] for s in slots}
        return slots

    async def slot_id(self, slot_number: str) -> int:
        if slot_number not in self._slot_ids:
            await self.list_slots()
        try:
            return self._slot_ids[slot_number]
        except KeyError:
            raise LookupError(f"backend has no active slot {slot_number!r}") from None

    async def staff_holds_slot(self, slot_id: int) -> bool:
        response = await self._http.get("/api/sim/sessions")
        response.raise_for_status()
        return any(
            s.get("slot_id") == slot_id and s.get("status") == "EMPLOYEE_PASS" and not s.get("exit_time")
            for s in response.json()
        )

    async def post_sensor(self, slot_id: int, occupied: bool, cid: Optional[str] = None) -> httpx.Response:
        return await self._http.post(
            f"/api/sim/sensor/{slot_id}", json={"occupied": occupied}, headers=_cid(cid))

    async def pending_authorizations(self, gate: str) -> list[dict]:
        """Fresh, not-yet-acknowledged barrier authorisations (poll fallback for the WebSocket)."""
        response = await self._http.get("/api/hardware/authorizations", params={"gate": gate})
        response.raise_for_status()
        return response.json()

    async def ack_open(self, gate: str, session_id: int) -> None:
        """The controller acknowledged OPEN for this session (a command ACK, not a passage)."""
        response = await self._http.post(f"/api/hardware/authorizations/{gate}/{session_id}/opened")
        response.raise_for_status()

    async def post_barrier_event(
        self, event_id: str, gate: str, event: str, plate: Optional[str], cid: Optional[str] = None
    ) -> dict:
        response = await self._http.post(
            "/api/hardware/barrier-events",
            json={"event_id": event_id, "gate": gate, "event": event, "plate_number": plate},
            headers=_cid(cid),
        )
        response.raise_for_status()
        return response.json()


class OcrClient:
    def __init__(self, settings: Settings) -> None:
        self._http = httpx.AsyncClient(
            base_url=settings.ocr_url,
            timeout=httpx.Timeout(settings.ocr_timeout, connect=3.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def ping(self) -> bool:
        try:
            return (await self._http.get("/health", timeout=3.0)).status_code == 200
        except httpx.HTTPError:
            return False

    async def trigger(self, gate: str, cid: Optional[str] = None) -> OcrOutcome:
        try:
            response = await self._http.post(
                "/gate-event/signal", params={"gate": gate}, headers=_cid(cid))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return OcrOutcome(RETRYABLE, f"ocr unreachable: {exc.__class__.__name__}")
        except httpx.HTTPError as exc:
            return OcrOutcome(AMBIGUOUS, f"ocr call failed: {exc.__class__.__name__}")

        if response.status_code in (502, 503):
            return OcrOutcome(RETRYABLE, f"ocr {response.status_code}: {_detail(response)}")
        if response.status_code != 200:
            return OcrOutcome(FINAL, f"ocr {response.status_code}: {_detail(response)}")

        data = response.json()
        recognized = data.get("recognized") or {}
        plate = recognized.get("formatted")
        if data.get("forwarded_to_backend"):
            return OcrOutcome(FORWARDED, "plate forwarded to backend", plate)
        reason = data.get("reject_reason") or "rejected"
        if reason.startswith("Backend отклонил"):
            return OcrOutcome(FINAL, reason, plate)
        return OcrOutcome(RETRYABLE, reason, plate)


def _cid(cid: Optional[str]) -> dict:
    return {"X-Correlation-ID": cid} if cid else {}


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))[:200]
    except ValueError:
        return response.text[:200]
