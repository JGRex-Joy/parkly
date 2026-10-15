from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app import schemas
from app.api.dependencies import get_parking_service
from app.services.parking import ParkingService

router = APIRouter(prefix="/api/sim", tags=["Симуляция датчиков и камер"])


@router.post("/entry", response_model=Optional[schemas.SessionOut],
             summary="Въездная камера считала номер / сотрудник поднёс пропуск")
def sim_entry(
    payload: schemas.SimEntryRequest, service: ParkingService = Depends(get_parking_service)
):
    session = service.register_entry(payload.plate_number)
    # Public contract: staff entries are answered with ``null`` (they are not billed).
    return None if session.is_staff else session


@router.post("/sensor/{slot_id}",
             summary="Датчик слота сработал (машина встала/уехала с конкретного места)")
def sim_sensor(
    slot_id: int,
    payload: schemas.SimSensorRequest,
    service: ParkingService = Depends(get_parking_service),
):
    if payload.occupied:
        session = service.occupy_slot(slot_id, payload.plate_number)
        return schemas.SessionOut.model_validate(session)
    slot = service.release_slot(slot_id)
    return schemas.SlotReleaseOut(
        detail="Слот освобождён вручную", slot=schemas.SlotOut.model_validate(slot)
    )


@router.post("/exit", response_model=schemas.SessionOut,
             summary="Выездная камера считала номер (выставляем счёт и QR)")
def sim_exit(
    payload: schemas.SimExitRequest, service: ParkingService = Depends(get_parking_service)
):
    return service.register_exit(payload.plate_number)


@router.get("/slots", response_model=list[schemas.SlotOut],
            summary="Текущее состояние всех слотов (debug)")
def list_slots(service: ParkingService = Depends(get_parking_service)):
    return service.list_slots()


@router.get("/sessions", response_model=list[schemas.SessionOut],
            summary="Все сессии парковки (debug)")
def list_sessions(service: ParkingService = Depends(get_parking_service)):
    return service.list_sessions()
