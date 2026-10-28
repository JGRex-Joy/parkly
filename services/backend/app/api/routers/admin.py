from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app import schemas
from app.api.dependencies import get_hardware_service, get_repositories
from app.api.security import require_admin_token
from app.repositories import Repositories
from app.services.hardware import HardwareService

router = APIRouter(prefix="/api/admin", tags=["Оператор"], dependencies=[Depends(require_admin_token)])


@router.post("/sessions/{session_id}/exit-override", response_model=schemas.SessionOut,
             summary="Ручное разрешение выезда (нераспознанный номер, нет оплаты и т.п.). Аудируется.")
def exit_override(
    session_id: int, body: schemas.OverrideIn,
    service: HardwareService = Depends(get_hardware_service),
):
    return service.operator_exit_override(session_id, body.reason)


@router.get("/audit", summary="Журнал событий (по сессии или correlation id)")
def audit(
    session_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 200,
    repos: Repositories = Depends(get_repositories),
):
    rows = repos.audit.list(session_id=session_id, correlation_id=correlation_id, kind=kind,
                            limit=min(max(limit, 1), 1000))
    return [
        {"id": r.id, "ts": r.ts.isoformat(), "kind": r.kind, "correlation_id": r.correlation_id,
         "session_id": r.session_id, "slot_id": r.slot_id, "plate_number": r.plate_number,
         "detail": r.detail}
        for r in rows
    ]
