import asyncio
import base64
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.dependencies import get_container
from app.schemas import CameraSnapshotResponse
from app.services.container import ServiceContainer

router = APIRouter()


@router.get("/debug/camera-snapshot", response_model=CameraSnapshotResponse,
            summary="DEBUG: посмотреть, что именно видит камера (без распознавания, без сохранения на диск)")
async def camera_snapshot(
    gate: Literal["entry", "exit"] = Query(...),
    container: ServiceContainer = Depends(get_container),
):
    try:
        image_bytes, source = await asyncio.to_thread(container.camera_service.capture_frame_bytes, gate)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Камера недоступна: {e}")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    return CameraSnapshotResponse(source=source, image_base64=f"data:image/jpeg;base64,{b64}")
