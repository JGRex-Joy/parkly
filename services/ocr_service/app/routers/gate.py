import asyncio
from typing import Literal

from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.routers.dependencies import get_container
from app.routers.recognition import read_image
from app.schemas import GateEventResponse
from app.services.container import ServiceContainer
from app.services.gate_service import BackendUnavailableError

router = APIRouter()

_IN_FLIGHT: Dict[str, "asyncio.Future[GateEventResponse]"] = {}


async def _capture_and_process(container: ServiceContainer, gate: str, correlation_id: Optional[str]) -> GateEventResponse:
    try:
        image_bytes, source = await asyncio.to_thread(container.camera_service.capture_frame_bytes, gate)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Камера недоступна: {e}")
    return await _process(container, gate, image_bytes, frame_source=source, correlation_id=correlation_id)


async def _process(container: ServiceContainer, gate: str, image_bytes: bytes, frame_source: str,
                   correlation_id: Optional[str] = None) -> GateEventResponse:
    try:
        return await container.gate_service.process_gate_event(
            gate, image_bytes, frame_source=frame_source, correlation_id=correlation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BackendUnavailableError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/gate-event/signal", response_model=GateEventResponse,
             summary="ЧИСТЫЙ сигнал с датчика (Arduino) — без файла, камера снимает сама")
async def gate_event_signal(
    request: Request,
    gate: Literal["entry", "exit"] = Query(..., description="Какой шлагбаум сработал"),
    container: ServiceContainer = Depends(get_container),
):
    x_correlation_id = request.headers.get("x-correlation-id")
    running = _IN_FLIGHT.get(gate)
    if running is not None and not running.done():
        return await asyncio.shield(running)
    task = asyncio.ensure_future(_capture_and_process(container, gate, x_correlation_id))
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
    container: ServiceContainer = Depends(get_container),
):
    x_correlation_id = request.headers.get("x-correlation-id")
    image_bytes = await read_image(file)
    return await _process(container, gate, image_bytes, frame_source="uploaded", correlation_id=x_correlation_id)
