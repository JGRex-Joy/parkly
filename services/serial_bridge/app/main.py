from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from typing import Callable, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.authorizations import AuthorizationDispatcher
from app.backend_ws import BackendListener
from app.clients import BackendClient, OcrClient
from app.commands import BarrierCommands
from app.config import Settings
from app.event_router import EventRouter
from app.logging_setup import configure_logging, get_logger
from app.mock_arduino import MockArduino
from app.serial_manager import CommandRejected, CommandTimeout, SerialDisconnected, SerialManager
from app.state import BridgeState
from app.transports import PySerialTransport, Transport

log = get_logger("main")
Gate = Literal["entry", "exit"]


class OpenRequest(BaseModel):
    plate_number: Optional[str] = Field(None, description="Only used for logging and de-duplication")
    request_id: Optional[str] = Field(None, description="Idempotency key; repeated ids open only once")
    hold_ms: Optional[int] = Field(None, ge=500, le=60000)


def create_app(
    settings: Optional[Settings] = None,
    transport_factory: Optional[Callable[[], Transport]] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level, settings.log_format)
        state = BridgeState()
        backend = BackendClient(settings)
        ocr = OcrClient(settings)

        mock: Optional[MockArduino] = None
        factory = transport_factory
        if factory is None:
            if settings.mock:
                mock = MockArduino(
                    hold_ms=settings.mock_hold_ms,
                    clear_ms=settings.mock_clear_ms,
                    heartbeat_s=settings.mock_heartbeat_s,
                )
                factory = lambda: mock  # the same simulated device across reconnects
                log.warning("MOCK SERIAL MODE: no hardware is used")
            else:
                factory = lambda: PySerialTransport(
                    settings.serial_port, settings.serial_baud, settings.serial_boot_delay,
                    settings.rx_backlog_max)

        router: Optional[EventRouter] = None
        serial = SerialManager(
            settings, factory,
            on_event=lambda e: router.on_event(e),
            on_connect=lambda: router.on_link_up(),
            on_disconnect=lambda: router.on_link_down(),
            on_resync=lambda: router.on_resync(),
        )
        commands = BarrierCommands(settings, serial, state)
        router = EventRouter(settings, serial, backend, ocr, commands, state)
        dispatcher = AuthorizationDispatcher(settings, commands, backend, state)
        listener = BackendListener(settings, commands, state, dispatcher)

        app.state.settings = settings
        app.state.bridge = state
        app.state.serial = serial
        app.state.router = router
        app.state.commands = commands
        app.state.backend = backend
        app.state.ocr = ocr
        app.state.mock = mock
        app.state.dispatcher = dispatcher

        router.start()
        listener.start()
        dispatcher.start()
        await serial.start()
        log.info("bridge started", extra={"serial_port": settings.serial_port,
                                          "backend": settings.backend_url, "ocr": settings.ocr_url})
        try:
            yield
        finally:
            log.info("bridge shutting down")
            await listener.stop()
            await dispatcher.stop()
            await serial.stop()
            await router.stop()
            await backend.aclose()
            await ocr.aclose()
            log.info("bridge stopped")

    app = FastAPI(
        title="Smart Parking - PySerial Bridge",
        description="Sole owner of the Arduino serial port. Hardware I/O only; no parking rules.",
        version="0.1.0",
        lifespan=lifespan,
    )

    def require_token(request: Request, x_bridge_token: Optional[str] = Header(None)) -> None:
        expected = request.app.state.settings.api_token
        if expected and not hmac.compare_digest(x_bridge_token or "", expected):
            raise HTTPException(status_code=401, detail="invalid or missing X-Bridge-Token")

    @app.get("/health", summary="Liveness: the process is up")
    def health(request: Request):
        return {"status": "ok", "uptime_s": round(time.time() - request.app.state.bridge.started_at, 1)}

    @app.get("/ready", summary="Readiness: 503 while the Arduino link is down")
    def ready(request: Request):
        connected = request.app.state.serial.connected
        if not connected:
            raise HTTPException(status_code=503, detail="serial link down")
        return {"status": "ready"}

    @app.get("/status", summary="Full runtime status")
    async def status(request: Request, deep: bool = False):
        st: BridgeState = request.app.state.bridge
        device = st.device
        body = {
            "serial": request.app.state.serial.snapshot(),
            "serial_port": request.app.state.settings.serial_port,
            "mock": request.app.state.mock is not None,
            "device": {
                "firmware": st.device_firmware,
                "epoch": st.epoch,
                "last_message_age_s": None if st.last_device_message is None
                else round(time.time() - st.last_device_message, 2),
                "slots": None if device is None else list(device.slots),
                "barrier_open": None if device is None
                else {"entry": device.entry_open, "exit": device.exit_open},
            },
            "gates": {g: rt.public() for g, rt in st.gates.items()},
            "distance_cm": dict(st.dist),     # filtered distances; only populated with device cfg dbg=1
            "slots_known_to_backend": {str(k): v for k, v in sorted(st.slot_forwarded.items())},
            "backend_ws": dict(st.ws_connected),
            "counters": st.counters.__dict__,
            "recent": list(st.recent)[-20:],
        }
        if deep:
            body["backend_reachable"] = await request.app.state.backend.ping()
            body["ocr_reachable"] = await request.app.state.ocr.ping()
        return body

    @app.get("/v1/slots", summary="Slot occupancy as last reported by the Arduino")
    def slots(request: Request):
        device = request.app.state.bridge.device
        names = dict(request.app.state.settings.slot_map)
        if device is None:
            raise HTTPException(status_code=503, detail="no device report yet")
        return [{"slot": names.get(i + 1, str(i + 1)), "index": i + 1, "occupied": occ}
                for i, occ in enumerate(device.slots)]

    @app.post("/v1/barrier/{gate}/open", dependencies=[Depends(require_token)],
              summary="Open a barrier. Called by the backend AFTER it authorised the vehicle")
    async def open_barrier(gate: Gate, body: OpenRequest, request: Request):
        result = await request.app.state.commands.open(
            gate, plate=body.plate_number, request_id=body.request_id,
            hold_ms=body.hold_ms, source="http")
        if not result.ok:
            raise HTTPException(status_code=503, detail=result.public())
        return result.public()

    @app.post("/v1/barrier/{gate}/close", dependencies=[Depends(require_token)])
    async def close_barrier(gate: Gate, request: Request):
        result = await request.app.state.commands.close(gate)
        if not result.ok:
            raise HTTPException(status_code=409, detail=result.public())
        return result.public()

    @app.post("/v1/device/sync", dependencies=[Depends(require_token)],
              summary="Ask the Arduino for a full state report")
    async def sync(request: Request):
        try:
            await request.app.state.serial.send_command("SYNC")
        except SerialDisconnected as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except (CommandTimeout, CommandRejected) as exc:
            raise HTTPException(status_code=504, detail=str(exc))
        return {"status": "sync requested"}

    @app.post("/v1/gates/{gate}/retrigger", dependencies=[Depends(require_token)],
              summary="Run OCR again for the vehicle waiting at a gate (operator action)")
    async def retrigger(gate: Gate, request: Request):  # async: it spawns a task on the event loop
        outcome = request.app.state.router.retrigger(gate)
        if outcome != "started":
            raise HTTPException(status_code=409, detail=outcome)
        return {"status": outcome}

    def _mock(request: Request) -> MockArduino:
        mock = request.app.state.mock
        if mock is None:
            raise HTTPException(status_code=404, detail="simulation API exists only with BRIDGE_SERIAL_PORT=mock://")
        return mock

    @app.post("/sim/slot/{index}", tags=["simulation"], summary="Put a car into / take it out of a slot")
    def sim_slot(index: int, occupied: bool, request: Request):
        if not 1 <= index <= 4:
            raise HTTPException(status_code=404, detail="slot index 1..4")
        _mock(request).set_slot(index, occupied)
        return {"slot": index, "occupied": occupied}

    @app.post("/sim/gate/{gate}", tags=["simulation"], summary="A car arrives at / leaves a gate sensor")
    def sim_gate(gate: Gate, present: bool, request: Request):
        _mock(request).set_gate(gate, present)
        return {"gate": gate, "present": present}

    @app.post("/sim/unplug", tags=["simulation"], summary="Pull the USB cable for N seconds")
    def sim_unplug(seconds: float, request: Request):
        _mock(request).unplug(seconds)
        return {"unplugged_for_s": seconds}

    @app.post("/sim/drop-acks", tags=["simulation"], summary="Swallow the next N command ACKs")
    def sim_drop(count: int, request: Request):
        _mock(request).drop_acks = count
        return {"dropping": count}

    @app.get("/sim/device", tags=["simulation"], summary="Inspect the simulated device")
    def sim_device(request: Request):
        return _mock(request).snapshot()

    return app


app = create_app()
