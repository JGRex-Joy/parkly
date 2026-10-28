from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.dependencies import get_database, get_provider, get_settings
from app.core.config import Settings
from app.db.database import Database
from app.services.payment_providers import PaymentProvider

router = APIRouter()


@router.get("/", tags=["Служебное"], summary="Проверка, что сервис жив")
def root():
    return {
        "service": "Parkly",
        "mode": "software-only (mock sensors via REST)",
        "docs": "/docs",
        "entry_display_ws": "/ws/entry-display",
        "exit_display_ws": "/ws/exit-display",
        "entry_display": "/display/entry",
        "exit_display": "/display/exit",
    }


@router.get("/health", tags=["Служебное"], 
            summary="Liveness + доступность БД")
def health(database: Database = Depends(get_database)):
    try:
        with database.session() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:  
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc.__class__.__name__}")
    return {"status": "ok", "service": "backend", "database": "ok"}


@router.get("/api/system/config", tags=["Служебное"], 
            summary="Безопасная часть конфигурации (без секретов)")
def public_config(
    settings: Settings = Depends(get_settings), provider: PaymentProvider = Depends(get_provider)
):
    return {
        "environment": settings.environment,
        "payment_mode": settings.payment_mode,
        "payment_simulated": provider.is_simulated,
        "currency": settings.currency,
        "billing_start": settings.billing_start,
        "auth_ttl_seconds": settings.auth_ttl_seconds,
        "ambiguous_slot_policy": settings.ambiguous_slot_policy,
        "service_token_required": bool(settings.service_token),
        "admin_endpoints_enabled": bool(settings.admin_token),
        "webhook_secret_configured": bool(settings.payment_webhook_secret),
    }
