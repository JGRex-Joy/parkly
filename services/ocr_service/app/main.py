from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import load_settings
from app.services import Services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = getattr(app.state, "services", None) or Services.build(load_settings())
    app.state.services = services
    await asyncio.to_thread(services.start)
    try:
        yield
    finally:
        await asyncio.to_thread(services.stop)


def create_app() -> FastAPI:
    application = FastAPI(
        title="Smart Parking - OCR Service (KG plates)",
        description="Распознавание кыргызских автомобильных номеров через OpenCV + EasyOCR.",
        version="0.4.0",
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()
