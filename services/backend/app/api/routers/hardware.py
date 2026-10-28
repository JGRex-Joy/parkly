from __future__ import annotations

from fastapi import APIRouter, Depends

from app import schemas
from app.api.dependencies import get_hardware_service
from app.api.security import require_service_token
from app.services.hardware import HardwareService

router = APIRouter(
    prefix="/api/hardware",
    tags=["Оборудование (bridge)"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/authorizations", 
            summary="Разрешения на открытие шлагбаума, ещё не подтверждённые контроллером")
def pending_authorizations(gate: str, service: HardwareService = Depends(get_hardware_service)):
    return service.pending_authorizations(gate)


@router.post("/authorizations/{gate}/{session_id}/opened",
             summary="Контроллер подтвердил команду OPEN (ACK), идемпотентно")
def ack_open(
    gate: str,
    session_id: int,
    service: HardwareService = Depends(get_hardware_service),
):
    session = service.ack_barrier_command(gate, session_id)
    return {"session_id": session.id, "gate": gate, "acknowledged": True}


@router.post("/barrier-events", 
             summary="Наблюдение датчиков/шлагбаума (OPENED, CLOSED, VEHICLE_CLEARED)")
def barrier_event(
    body: schemas.BarrierEventIn, service: HardwareService = Depends(get_hardware_service)
):
    return service.report_barrier_event(body.event_id, body.gate, body.event, body.plate_number)
