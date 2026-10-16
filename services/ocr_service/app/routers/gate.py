import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.routers.dependencies import get_container
from app.routers.recognition import read_image
from app.schemas import GateEventResponse
from app.services.container import ServiceContainer
from app.services.gate_service import BackendUnavailableError

router = APIRouter()


async def _process(container: ServiceContainer, gate: str, image_bytes: bytes, frame_source: str) -> GateEventResponse:
    try:
        return await container.gate_service.process_gate_event(gate, image_bytes, frame_source=frame_source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BackendUnavailableError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/gate-event/signal", response_model=GateEventResponse,
             summary="ЧИСТЫЙ сигнал с датчика (Arduino) — без файла, камера снимает сама")
async def gate_event_signal(
    gate: Literal["entry", "exit"] = Query(..., description="Какой шлагбаум сработал"),
    container: ServiceContainer = Depends(get_container),
):
    try:
        image_bytes, source = await asyncio.to_thread(container.camera_service.capture_frame_bytes, gate)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Камера недоступна: {e}")
    return await _process(container, gate, image_bytes, frame_source=source)


@router.post("/gate-event/with-photo", response_model=GateEventResponse,
             summary="То же самое, но кадр уже снят и прислан файлом")
async def gate_event_with_photo(
    gate: Literal["entry", "exit"] = Query(..., description="Какой шлагбаум сработал"),
    file: UploadFile = File(..., description="JPEG/PNG кадр, уже снятый внешней камерой-системой"),
    container: ServiceContainer = Depends(get_container),
):
    image_bytes = await read_image(file)
    return await _process(container, gate, image_bytes, frame_source="uploaded")
