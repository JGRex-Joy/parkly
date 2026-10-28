from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import schemas
from app.api.dependencies import get_payment_service, get_templates
from app.db.models import PaymentStatus, SessionStatus
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
            "payment": view.payment,
            "simulated_mode": view.simulated_mode,
            "currency": view.currency,
            "awaiting_payment": view.session.status == SessionStatus.AWAITING_PAYMENT,
        },
    )


@router.get("/api/pay/{session_id}/status", response_model=schemas.PaymentStatusOut,
            summary="Статус оплаты (опрашивается страницей оплаты)")
def payment_status(session_id: int, service: PaymentService = Depends(get_payment_service)):
    view = service.get_payment_view(session_id)
    payment = view.payment
    return schemas.PaymentStatusOut(
        session_id=view.session.id,
        session_status=view.session.status,
        payment_status=payment.status.value if payment else None,
        amount=payment.amount if payment else None,
        currency=payment.currency if payment else None,
        reference=payment.reference if payment else None,
        simulated=bool(payment and payment.is_simulated),
        exit_authorized=view.session.exit_authorized_at is not None,
    )


@router.post("/api/pay/{session_id}", response_model=schemas.PaymentResult,
             summary="DEV/TEST: имитировать оплату (только при PARKING_PAYMENT_MODE=simulated)")
def confirm_payment(
    session_id: int, service: PaymentService = Depends(get_payment_service)
):
    session = service.confirm_simulated_payment(session_id)
    return schemas.PaymentResult(
        session_id=session.id,
        status=session.status,
        amount_paid=session.amount_due or 0.0,
        barrier_opened=False,
        exit_authorized=True,
        simulated=True,
    )


@router.post("/api/payments/webhook", 
             summary="Уведомление платёжного провайдера (подпись HMAC)")
async def payment_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None),
    service: PaymentService = Depends(get_payment_service),
):
    raw = await request.body()
    result = await run_in_threadpool(service.handle_provider_callback, raw, x_signature)
    if result.already_processed:
        outcome = "duplicate"
    elif result.payment.status == PaymentStatus.SUCCEEDED:
        outcome = "processed"
    else:
        outcome = "ignored"
    return {
        "status": outcome,
        "session_id": result.session.id,
        "session_status": result.session.status.value,
    }
