from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import schemas
from app.api.dependencies import get_payment_service, get_templates
from app.services.payment import PaymentService

router = APIRouter(tags=["Оплата"])


@router.get("/pay/{session_id}", response_class=HTMLResponse,
            summary="Страница оплаты (открывается по QR)")
def pay_page(
    request: Request,
    session_id: int,
    service: PaymentService = Depends(get_payment_service),
    templates: Jinja2Templates = Depends(get_templates),
):
    view = service.get_payment_view(session_id)
    return templates.TemplateResponse(
        request,
        "pay.html",
        {
            "session": view.session,
            "hours": view.hours,
            "minutes": view.minutes,
            "seconds": view.seconds,
            "already_paid": view.already_paid,
        },
    )


@router.post("/api/pay/{session_id}", response_model=schemas.PaymentResult,
             summary="Подтвердить оплату")
def confirm_payment(session_id: int, service: PaymentService = Depends(get_payment_service)):
    session = service.confirm_payment(session_id)
    return schemas.PaymentResult(
        session_id=session.id,
        status=session.status,
        amount_paid=session.amount_due or 0.0,
    )
