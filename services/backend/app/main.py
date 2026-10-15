
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routers import payment, simulation, system
from app.db.bootstrap import initialize_database
from app.core.config import Settings
from app.db.database import Database
from app.api.exceptions import ParkingError
from app.api.routers import websockets as ws_router
from app.services.publishing import WebSocketPublisher
from app.websocket_manager import ConnectionManager


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    manager = ConnectionManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database, settings)
        yield
        database.dispose()

    app = FastAPI(
        title="Smart Parking Management System",
        description="Макет умной парковки. Все датчики/камеры эмулируются",
        version="0.2",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.connection_manager = manager
    app.state.publisher = WebSocketPublisher(manager)
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(ParkingError)
    async def parking_error_handler(_: Request, exc: ParkingError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    settings.static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    app.include_router(system.router)
    app.include_router(simulation.router)
    app.include_router(payment.router)
    app.include_router(ws_router.router)
    return app


app = create_app()
