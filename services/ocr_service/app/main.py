from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routers import debug, gate, health, recognition
from app.services.container import ServiceContainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = getattr(app.state, "container", None) or ServiceContainer.build(get_settings())
    app.state.container = container
    container.start()
    try:
        yield
    finally:
        container.stop()  


def create_app() -> FastAPI:
    application = FastAPI(
        title="Smart Parking - OCR Service (KG plates)",
        description="Распознавание кыргызских автомобильных номеров через OpenCV + EasyOCR.",
        version="0.2.0",
        lifespan=lifespan,
    )
    for module in (recognition, gate, debug, health):
        application.include_router(module.router)
    return application


app = create_app()
