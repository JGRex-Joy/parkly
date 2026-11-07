from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Dict, Literal, Optional

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.camera import CameraError
from app.gate import BackendUnavailableError
from app.schemas import CameraSnapshotResponse, GateEventResponse, RecognizeResponse
from app.services import Services, get_services

router = APIRouter()
logger = logging.getLogger("ocr_service.api")

BURST_ATTEMPTS = 10
BURST_INTERVAL = 0.05          
BURST_DEADLINE = 4.0
CONFIDENT = 0.85               

_IN_FLIGHT: Dict[str, "asyncio.Future[GateEventResponse]"] = {}


async def read_image(file: UploadFile) -> bytes:
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Ожидается изображение JPEG или PNG")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Пустой файл")
    return image_bytes


async def _capture(services: Services, gate: str):
    try:
        return await asyncio.to_thread(services.cameras.capture, gate)
    except CameraError as e:
        raise HTTPException(status_code=503, detail=f"Камера недоступна: {e}")


async def _burst(services: Services, gate: str, correlation_id: Optional[str]) -> GateEventResponse:
    svc = services.gate_service
    deadline = time.monotonic() + BURST_DEADLINE
    seen: Dict[str, list] = {}                 
    best: Optional[tuple] = None               
    last = None

    for attempt in range(1, BURST_ATTEMPTS + 1):
        try:
            frame, source = await _capture(services, gate)
        except HTTPException:
            if best is not None or seen:
                break                          
            raise
        last = (frame, source)
        try:
            rec = await svc.recognize(frame, thorough=False)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        logger.info("gate=%s попытка %d/%d: номер=%s conf=%.2f", gate, attempt, BURST_ATTEMPTS,
                    rec.plate_number, rec.confidence)

        if svc.reject_reason(rec) is None:
            entry = seen.setdefault(rec.plate_number, [0, rec, source])
            entry[0] += 1
            if rec.confidence >= entry[1].confidence:
                entry[1], entry[2] = rec, source
            if entry[0] >= 2 or (rec.confidence >= CONFIDENT and rec.corrections_applied == 0):
                return await _finish(svc, gate, entry[1], entry[2], correlation_id)
        elif best is None or rec.confidence > best[0].confidence:
            best = (rec, source, frame)

        if time.monotonic() + BURST_INTERVAL >= deadline:
            break
        await asyncio.sleep(BURST_INTERVAL)

    if seen:                                   
        _, rec, source = max(seen.values(), key=lambda e: (e[0], e[1].confidence))
        return await _finish(svc, gate, rec, source, correlation_id)

    if last is not None:                       
        try:
            rec = await svc.recognize(last[0], thorough=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if svc.reject_reason(rec) is None or best is None or rec.confidence > best[0].confidence:
            return await _finish(svc, gate, rec, last[1], correlation_id)
    assert best is not None
    return await _finish(svc, gate, best[0], best[1], correlation_id)


async def _finish(svc, gate, rec, source, correlation_id) -> GateEventResponse:
    try:
        return await svc.finish(gate, rec, source, correlation_id)
    except BackendUnavailableError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/recognize", response_model=RecognizeResponse, summary="Распознать номер на фото (без форварда в backend)")
async def recognize(
    file: UploadFile = File(..., description="JPEG/PNG кадр с камеры"),
    services: Services = Depends(get_services),
):
    image_bytes = await read_image(file)
    try:
        return await services.gate_service.recognize(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/gate-event/signal", response_model=GateEventResponse,
             summary="ЧИСТЫЙ сигнал с датчика (Arduino) — без файла, камера снимает сама")
async def gate_event_signal(
    request: Request,
    gate: Literal["entry", "exit"] = Query(..., description="Какой шлагбаум сработал"),
    services: Services = Depends(get_services),
):
    x_correlation_id = request.headers.get("x-correlation-id")
    running = _IN_FLIGHT.get(gate)
    if running is not None and not running.done():       
        return await asyncio.shield(running)
    task = asyncio.ensure_future(_burst(services, gate, x_correlation_id))
    _IN_FLIGHT[gate] = task
    try:
        return await asyncio.shield(task)
    finally:
        if _IN_FLIGHT.get(gate) is task and task.done():
            _IN_FLIGHT.pop(gate, None)


@router.post("/gate-event/with-photo", response_model=GateEventResponse,
             summary="То же самое, но кадр уже снят и прислан файлом")
async def gate_event_with_photo(
    request: Request,
    gate: Literal["entry", "exit"] = Query(..., description="Какой шлагбаум сработал"),
    file: UploadFile = File(..., description="JPEG/PNG кадр, уже снятый внешней камерой-системой"),
    services: Services = Depends(get_services),
):
    x_correlation_id = request.headers.get("x-correlation-id")
    image_bytes = await read_image(file)
    try:
        return await services.gate_service.process_gate_event(gate, image_bytes, frame_source="uploaded",
                                                              correlation_id=x_correlation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BackendUnavailableError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/debug/camera-snapshot", response_model=CameraSnapshotResponse,
            summary="DEBUG: посмотреть, что именно видит камера (без распознавания, без сохранения на диск)")
async def camera_snapshot(
    gate: Literal["entry", "exit"] = Query(...),
    services: Services = Depends(get_services),
):
    frame, source = await _capture(services, gate)
    ok, jpeg = await asyncio.to_thread(cv2.imencode, ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    b64 = base64.b64encode(jpeg.tobytes()).decode("ascii")
    return CameraSnapshotResponse(source=source, image_base64=f"data:image/jpeg;base64,{b64}")


@router.get("/health", summary="Проверка, что сервис жив")
def health():
    return {"status": "ok", "service": "ocr-service"}
