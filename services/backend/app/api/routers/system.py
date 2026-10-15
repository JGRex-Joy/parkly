from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/", tags=["Служебное"], summary="Проверка, что сервис жив")
def root():
    return {
        "service": "Smart Parking Management System",
        "mode": "software-only (mock sensors via REST)",
        "docs": "/docs",
        "entry_display_ws": "/ws/entry-display",
        "exit_display_ws": "/ws/exit-display",
    }
