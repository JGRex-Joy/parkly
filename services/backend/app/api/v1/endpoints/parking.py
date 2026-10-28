from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator

from app import schemas
from app.api.dependencies import get_parking_service, get_payment_service, get_repositories
from app.api.exceptions import NotFoundError
from app.api.security import require_service_token
from app.db.models import SessionStatus
from app.repositories import Repositories
from app.services.parking import ParkingService
from app.services.payment import PaymentService
from app.utils import normalize_plate

router = APIRouter(
    prefix="/api/v1",
    tags=["v1: parking events"],
    dependencies=[Depends(require_service_token)],
)


class PlateIn(BaseModel):
    plate: Optional[str] = None
    plate_number: Optional[str] = None

    @model_validator(mode="after")
    def _need_plate(self):
        if not (self.plate or self.plate_number):
            raise ValueError("plate (or plate_number) is required")
        return self

    @property
    def value(self) -> str:
        return (self.plate or self.plate_number or "").strip()


class SlotUpdateIn(BaseModel):
    slot_id: int
    occupied: bool = True
    plate: Optional[str] = None
    plate_number: Optional[str] = None

    @property
    def value(self) -> Optional[str]:
        return (self.plate or self.plate_number or "").strip() or None


class PaymentConfirmIn(BaseModel):
    plate: Optional[str] = None
    plate_number: Optional[str] = None
    session_id: Optional[int] = None

    @model_validator(mode="after")
    def _need_target(self):
        if self.session_id is None and not (self.plate or self.plate_number):
            raise ValueError("session_id or plate is required")
        return self


@router.post("/entry", response_model=schemas.SessionOut, summary="Entry camera read a plate -> ENTRY_OCR")
def entry(body: PlateIn, service: ParkingService = Depends(get_parking_service)):
    return service.register_entry(body.value)


@router.post("/exit", response_model=schemas.SessionOut, summary="Exit camera read a plate -> EXIT_OCR")
def exit_(body: PlateIn, service: ParkingService = Depends(get_parking_service)):
    return service.register_exit(body.value)


@router.post("/slots/update", summary="Slot sensor -> SLOT_OCCUPIED / SLOT_RELEASED")
def slots_update(body: SlotUpdateIn, service: ParkingService = Depends(get_parking_service)):
    if body.occupied:
        return schemas.SessionOut.model_validate(service.occupy_slot(body.slot_id, body.value))
    slot = service.release_slot(body.slot_id)
    return schemas.SlotReleaseOut(detail="slot released", slot=schemas.SlotOut.model_validate(slot))


@router.post("/payment/confirm", response_model=schemas.SessionOut,
             summary="Confirm payment -> PAYMENT_CONFIRMED (PARKING_PAYMENT_MODE=simulated only)")
def payment_confirm(
    body: PaymentConfirmIn,
    payments: PaymentService = Depends(get_payment_service),
    repos: Repositories = Depends(get_repositories),
):
    session_id = body.session_id
    if session_id is None:
        plate = normalize_plate(body.plate or body.plate_number or "")
        session = repos.sessions.find_customer_for_exit(plate)
        if session is None or session.status != SessionStatus.AWAITING_PAYMENT:
            raise NotFoundError("No bill awaiting payment for this plate")
        session_id = session.id
    return payments.confirm_simulated_payment(session_id)


@router.get("/sessions", response_model=list[schemas.SessionOut], summary="Session history (newest first)")
def sessions(service: ParkingService = Depends(get_parking_service)):
    return service.list_sessions()
