from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.routers.dependencies import get_container
from app.schemas import RecognizeResponse
from app.services.container import ServiceContainer

router = APIRouter()


async def read_image(file: UploadFile) -> bytes:
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Ожидается изображение JPEG или PNG")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Пустой файл")
    return image_bytes


@router.post("/recognize", response_model=RecognizeResponse, summary="Распознать номер на фото (без форварда в backend)")
async def recognize(
    file: UploadFile = File(..., description="JPEG/PNG кадр с камеры"),
    container: ServiceContainer = Depends(get_container),
):
    image_bytes = await read_image(file)
    try:
        return await container.gate_service.recognize(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
