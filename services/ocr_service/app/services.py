from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import Request

from app.camera import CameraHub
from app.config import Settings, load_settings
from app.gate import BackendClient, GateService
from app.recognizer import OcrEngine, RecognitionService


@dataclass
class Services:
    settings: Settings
    engine: OcrEngine
    cameras: CameraHub
    gate_service: GateService

    @classmethod
    def build(cls, settings: Settings) -> "Services":
        engine = OcrEngine()
        backend = BackendClient(settings.backend_base_url, service_token=settings.backend_service_token)
        return cls(settings, engine, CameraHub(settings), GateService(RecognitionService(engine), backend))

    def start(self) -> None:
        self.cameras.start()      
        self.engine.warm_up()     

    def stop(self) -> None:
        self.cameras.stop()


_build_lock = threading.Lock()


def get_services(request: Request) -> Services:
    app = request.app
    services = getattr(app.state, "services", None)
    if services is None:
        with _build_lock:
            services = getattr(app.state, "services", None)
            if services is None:
                services = app.state.services = Services.build(load_settings())
    return services
