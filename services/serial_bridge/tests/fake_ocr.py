from __future__ import annotations

from typing import Literal

import httpx
from fastapi import FastAPI, Query, Request

ENDPOINT = {"entry": "/api/sim/entry", "exit": "/api/sim/exit"}


def _recognized(plate):
    return {
        "plate_number": plate, "formatted": plate, "region_code": None, "is_valid_region": plate is not None,
        "corrections_applied": 0, "confidence": 0.9 if plate else 0.0,
        "plate_detection_method": "fake", "plate_detection_score": 1.0, "raw_detections": [],
    }


def create_fake_ocr(backend_url: str, service_token: str = "") -> FastAPI:
    app = FastAPI()
    app.state.script = []
    app.state.calls = []
    app.state.correlation_ids = []

    @app.post("/gate-event/signal")
    async def signal(request: Request, gate: Literal["entry", "exit"] = Query(...)):
        app.state.calls.append(gate)
        cid = request.headers.get("x-correlation-id")
        app.state.correlation_ids.append(cid)
        plate = app.state.script.pop(0) if app.state.script else None
        if plate is None:
            return {"recognized": _recognized(None), "forwarded_to_backend": False,
                    "reject_reason": "Номер не распознан", "frame_source": "fake"}
        async with httpx.AsyncClient(timeout=5) as client:
            headers = {}
            if cid:
                headers["X-Correlation-ID"] = cid  
            if service_token:
                headers["X-Service-Token"] = service_token
            response = await client.post(backend_url + ENDPOINT[gate], json={"plate_number": plate}, headers=headers)
        if response.status_code >= 400:
            return {"recognized": _recognized(plate), "forwarded_to_backend": False,
                    "reject_reason": f"Backend отклонил: {response.status_code} {response.text}",
                    "frame_source": "fake"}
        return {"recognized": _recognized(plate), "forwarded_to_backend": True,
                "backend_response": response.json() if response.content else {}, "frame_source": "fake"}

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "fake-ocr"}

    return app
