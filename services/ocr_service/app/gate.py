from __future__ import annotations

import asyncio
from typing import Literal, Optional, Union

import httpx
import numpy as np

from app.config import BACKEND_TIMEOUT_SECONDS, MAX_CORRECTIONS_TO_TRUST
from app.models import RecognitionResult
from app.recognizer import RecognitionService
from app.schemas import DetectionOut, GateEventResponse, RecognizeResponse

Gate = Literal["entry", "exit"]
ENDPOINT_BY_GATE = {"entry": "/api/sim/entry", "exit": "/api/sim/exit"}


class BackendUnavailableError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str, timeout: float = BACKEND_TIMEOUT_SECONDS, service_token: str = "") -> None:
        self._base_url, self._timeout, self._token = base_url, timeout, service_token

    async def forward_plate(self, gate: Gate, plate_formatted: str, correlation_id: Optional[str] = None) -> dict:
        headers = {}
        if self._token:
            headers["X-Service-Token"] = self._token
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}{ENDPOINT_BY_GATE[gate]}",
                                         json={"plate_number": plate_formatted}, headers=headers)
            response.raise_for_status()
            return response.json() if response.content else {}


def to_recognize_response(result: RecognitionResult) -> RecognizeResponse:
    c, crop = result.candidate, result.crop
    return RecognizeResponse(
        plate_number=c.plate_number if c else None,
        formatted=c.formatted if c else None,
        region_code=c.region if c else None,
        is_valid_region=c.is_valid_region if c else False,
        corrections_applied=c.corrections if c else 0,
        confidence=round(result.confidence, 3),
        plate_detection_method=crop.method if crop else "fallback_full_frame",
        plate_detection_score=round(crop.score, 3) if crop else 0.0,
        raw_detections=[DetectionOut(text=d.text, confidence=d.confidence) for d in result.detections],
    )


class GateService:
    def __init__(self, recognition: RecognitionService, backend: BackendClient,
                 max_corrections: int = MAX_CORRECTIONS_TO_TRUST) -> None:
        self._recognition, self._backend, self._max_corrections = recognition, backend, max_corrections

    async def recognize(self, image: Union[bytes, np.ndarray], thorough: bool = True) -> RecognizeResponse:
        result = await asyncio.to_thread(self._recognition.recognize, image, thorough)
        return to_recognize_response(result)

    def reject_reason(self, rec: RecognizeResponse) -> Optional[str]:
        if not rec.plate_number:
            return "Номер не распознан"
        if not rec.is_valid_region:
            return f"Код региона '{rec.region_code}' вне диапазона 01-11"
        if rec.corrections_applied > self._max_corrections:
            return (f"Слишком много исправленных символов ({rec.corrections_applied}) - результату не доверяем")
        return None

    async def finish(self, gate: Gate, rec: RecognizeResponse, frame_source: str,
                     correlation_id: Optional[str] = None) -> GateEventResponse:
        reason = self.reject_reason(rec)
        if reason:
            return GateEventResponse(recognized=rec, forwarded_to_backend=False, reject_reason=reason,
                                     frame_source=frame_source)
        try:
            backend_response = await self._backend.forward_plate(gate, rec.formatted, correlation_id)
        except httpx.HTTPStatusError as e:
            return GateEventResponse(recognized=rec, forwarded_to_backend=False, frame_source=frame_source,
                                     reject_reason=f"Backend отклонил: {e.response.status_code} {e.response.text}")
        except httpx.RequestError as e:
            raise BackendUnavailableError(f"Backend недоступен: {e}") from e
        return GateEventResponse(recognized=rec, forwarded_to_backend=True, backend_response=backend_response,
                                 frame_source=frame_source)

    async def process_gate_event(self, gate: Gate, image: Union[bytes, np.ndarray], frame_source: str,
                                 correlation_id: Optional[str] = None) -> GateEventResponse:
        return await self.finish(gate, await self.recognize(image), frame_source, correlation_id)
