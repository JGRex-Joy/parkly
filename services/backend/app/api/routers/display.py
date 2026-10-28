from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import get_templates

router = APIRouter(tags=["Дисплеи"])


@router.get("/display/{channel}", response_class=HTMLResponse, summary="Страница дисплея въезда/выезда")
def display_page(
    request: Request,
    channel: Literal["entry", "exit"],
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(request, "display.html", {"channel": channel})
