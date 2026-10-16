from __future__ import annotations

import asyncio

import httpx

from app.repositories import BackendRepository, Gate
from app.schemas import GateEventResponse, RecognizeResponse
from app.services.api_mapper import to_recognize_response
from app.services.recognition_service import RecognitionService


class BackendUnavailableError(RuntimeError):
    """Backend парковки недоступен (сеть/таймаут). Роутер превращает это в HTTP 502."""


class GateService:
    def __init__(self, recognition: RecognitionService, backend: BackendRepository, max_corrections: int) -> None:
        self._recognition = recognition
        self._backend = backend
        self._max_corrections = max_corrections

    async def recognize(self, image_bytes: bytes) -> RecognizeResponse:
        result = await asyncio.to_thread(self._recognition.recognize, image_bytes)
        return to_recognize_response(result)

    async def process_gate_event(self, gate: Gate, image_bytes: bytes, frame_source: str) -> GateEventResponse:
        recognized = await self.recognize(image_bytes)

        if not recognized.plate_number:
            return GateEventResponse(recognized=recognized, forwarded_to_backend=False,
                                     reject_reason="Номер не распознан", frame_source=frame_source)
        if not recognized.is_valid_region:
            return GateEventResponse(recognized=recognized, forwarded_to_backend=False,
                                     reject_reason=f"Код региона '{recognized.region_code}' вне диапазона 01-11",
                                     frame_source=frame_source)
        if recognized.corrections_applied > self._max_corrections:
            return GateEventResponse(recognized=recognized, forwarded_to_backend=False,
                                     reject_reason=f"Слишком много исправленных символов "
                                                   f"({recognized.corrections_applied}) - результату не доверяем",
                                     frame_source=frame_source)

        try:
            backend_response = await self._backend.forward_plate(gate, recognized.formatted)
        except httpx.HTTPStatusError as e:
            return GateEventResponse(
                recognized=recognized, forwarded_to_backend=False,
                reject_reason=f"Backend отклонил: {e.response.status_code} {e.response.text}",
                frame_source=frame_source,
            )
        except httpx.RequestError as e:
            raise BackendUnavailableError(f"Backend недоступен: {e}") from e

        return GateEventResponse(recognized=recognized, forwarded_to_backend=True,
                                 backend_response=backend_response, frame_source=frame_source)
