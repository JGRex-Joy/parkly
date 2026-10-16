from fastapi import APIRouter

router = APIRouter()


@router.get("/health", summary="Проверка, что сервис жив")
def health():
    return {"status": "ok", "service": "ocr-service"}
