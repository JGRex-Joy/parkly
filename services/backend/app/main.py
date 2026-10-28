from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routers import admin, display, hardware, payment, simulation, system
from app.context import reset_correlation_id, set_correlation_id
from app.services.payment_providers import build_provider
from app.db.bootstrap import initialize_database
from app.core.config import Settings
from app.core.websocket import ConnectionManager as DashboardConnectionManager
from app.db.database import Database
from app.api.exceptions import ParkingError
from app.api.routers import websockets as ws_router
from app.api.v1.endpoints import parking as v1_parking, ws as dashboard_ws
from app.services.dashboard_state import hydrate_dashboard_state
from app.services.publishing import WebSocketPublisher
from app.websocket_manager import ConnectionManager


logger = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = (settings or Settings.from_env()).validated()
    database = Database(settings.database_url)
    manager = ConnectionManager()
    dashboard_manager = DashboardConnectionManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(database, settings)
        hydrate_dashboard_state(
            dashboard_manager, database, pending_ttl_seconds=settings.pending_entry_ttl_seconds
        )
        yield
        database.dispose()

    app = FastAPI(
        title="Smart Parking Management System",
        description="Макет умной парковки. Все датчики/камеры эмулируются",
        version="0.3",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.connection_manager = manager
    app.state.dashboard_manager = dashboard_manager
    app.state.publisher = WebSocketPublisher(manager, dashboard_manager)
    app.state.payment_provider = build_provider(settings)
    if app.state.payment_provider.is_simulated:
        logger.warning("PAYMENT SIMULATION ENABLED (PARKING_ENV=%s): payments are NOT real", settings.environment)
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))

    # CORS for REST calls from the web admin dashboard. (Browsers do not enforce CORS on
    # WebSocket handshakes, so /ws/parking is reachable from any dev origin regardless.)
    #   PARKING_CORS_ORIGINS="*"            -> any origin
    #   PARKING_CORS_ORIGINS="http://a,b"   -> exactly those origins
    #   unset (non-production)              -> localhost / 127.0.0.1 on any dev port
    origins = list(settings.cors_origins)
    wildcard = "*" in origins
    local_dev = settings.environment != "production"
    if origins or local_dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"] if wildcard else origins,
            allow_origin_regex=(
                r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
                if local_dev and not wildcard else None
            ),
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Correlation-ID"],
        )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        supplied = request.headers.get("x-correlation-id", "")
        cid = supplied if _SAFE_ID.match(supplied) else f"srv-{uuid.uuid4().hex[:12]}"
        token = set_correlation_id(cid)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers["X-Correlation-ID"] = cid
        return response

    @app.exception_handler(ParkingError)
    async def parking_error_handler(_: Request, exc: ParkingError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    settings.static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    app.include_router(system.router)
    app.include_router(simulation.router)
    app.include_router(payment.router)
    app.include_router(hardware.router)
    app.include_router(admin.router)
    app.include_router(display.router)
    app.include_router(ws_router.router)
    app.include_router(v1_parking.router)
    app.include_router(dashboard_ws.router)
    return app


app = create_app()
