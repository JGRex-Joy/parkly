"""The HTTP contract of the service. These tests use fakes (no camera, no model, no backend) and must keep passing
unchanged across refactors: other services depend on these routes, payloads and messages."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import api
from app.camera import CameraError
from app.config import load_settings
from app.gate import BackendClient, GateService
from app.main import create_app
from app.models import Detection, PlateCandidate, PlateCrop, RecognitionResult
from app.services import get_services

FIXTURES = Path(__file__).parent / "fixtures"
GOOD = PlateCandidate("01", "KG", "111", "AAA", 0)


def result(candidate=GOOD, confidence=0.96, method="already_cropped", score=0.9):
    return RecognitionResult(candidate, confidence, [Detection("01", 0.5)] if candidate else [],
                             PlateCrop(np.zeros((8, 8, 3), np.uint8), method, score))


class FakeRecognition:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def recognize(self, image, thorough=True):
        self.calls.append(thorough)
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class FakeBackend:
    def __init__(self, error=None):
        self.error, self.sent = error, []

    async def forward_plate(self, gate, formatted, correlation_id=None):
        if self.error:
            raise self.error
        self.sent.append((gate, formatted, correlation_id))
        return {"ok": True}


class FakeCameras:
    def __init__(self, error=None, delay=0.0):
        self.error, self.delay, self.captured = error, delay, []

    def capture(self, gate):
        import time
        time.sleep(self.delay)
        if self.error:
            raise self.error
        self.captured.append(gate)
        return np.full((12, 16, 3), 90, np.uint8), "webcam"


def make_client(recognition, backend=None, cameras=None, max_corrections=2):
    backend = backend or FakeBackend()
    cameras = cameras or FakeCameras()
    services = SimpleNamespace(settings=load_settings({}), cameras=cameras,
                               gate_service=GateService(recognition, backend, max_corrections))
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app), backend, cameras, recognition


PNG = cv2.imencode(".png", np.zeros((10, 10, 3), np.uint8))[1].tobytes()
FILES = {"file": ("x.png", PNG, "image/png")}


@pytest.fixture(autouse=True)
def fast_burst(monkeypatch):
    monkeypatch.setattr(api, "BURST_ATTEMPTS", 4)
    monkeypatch.setattr(api, "BURST_INTERVAL", 0.0)


# ── the contract itself ────────────────────────────────────────────────────────────────────────────────────────────
def test_openapi_is_identical_to_the_pre_refactor_snapshot():
    snapshot = json.loads((FIXTURES / "openapi_v0.2.0.json").read_text(encoding="utf-8"))
    assert json.dumps(create_app().openapi(), sort_keys=True) == json.dumps(snapshot, sort_keys=True)


def test_health():
    client, *_ = make_client(FakeRecognition(result()))
    assert client.get("/health").json() == {"status": "ok", "service": "ocr-service"}


def test_recognize_payload():
    client, *_ = make_client(FakeRecognition(result(confidence=0.9123, score=0.5678)))
    body = client.post("/recognize", files=FILES).json()
    assert body == {"plate_number": "01111AAA", "formatted": "01 KG 111 AAA", "region_code": "01",
                    "is_valid_region": True, "corrections_applied": 0, "confidence": 0.912,
                    "plate_detection_method": "already_cropped", "plate_detection_score": 0.568,
                    "raw_detections": [{"text": "01", "confidence": 0.5}]}


def test_recognize_nothing_found():
    client, *_ = make_client(FakeRecognition(result(None, 0.0)))
    body = client.post("/recognize", files=FILES).json()
    assert body["plate_number"] is None and body["formatted"] is None and body["is_valid_region"] is False


def test_upload_validation_messages():
    client, *_ = make_client(FakeRecognition(result()))
    r = client.post("/recognize", files={"file": ("x.txt", b"hi", "text/plain")})
    assert (r.status_code, r.json()["detail"]) == (400, "Ожидается изображение JPEG или PNG")
    r = client.post("/recognize", files={"file": ("x.png", b"", "image/png")})
    assert (r.status_code, r.json()["detail"]) == (400, "Пустой файл")


def test_undecodable_image_is_400():
    class Broken:
        def recognize(self, image, thorough=True):
            raise ValueError("Не удалось декодировать изображение")
    client, *_ = make_client(Broken())
    assert client.post("/recognize", files=FILES).status_code == 400


# ── with-photo ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_with_photo_forwards_formatted_plate_and_correlation_id():
    client, backend, *_ = make_client(FakeRecognition(result()))
    r = client.post("/gate-event/with-photo?gate=entry", files=FILES, headers={"X-Correlation-ID": "abc"})
    body = r.json()
    assert r.status_code == 200 and body["forwarded_to_backend"] is True and body["frame_source"] == "uploaded"
    assert body["backend_response"] == {"ok": True} and body["reject_reason"] is None
    assert backend.sent == [("entry", "01 KG 111 AAA", "abc")]


@pytest.mark.parametrize("candidate,reason", [
    (None, "Номер не распознан"),
    (PlateCandidate("12", "KG", "111", "AAA", 0), "Код региона '12' вне диапазона 01-11"),
    (PlateCandidate("01", "KG", "111", "AAA", 3), "Слишком много исправленных символов (3) - результату не доверяем"),
])
def test_rejected_reads_are_not_forwarded(candidate, reason):
    client, backend, *_ = make_client(FakeRecognition(result(candidate)))
    body = client.post("/gate-event/with-photo?gate=exit", files=FILES).json()
    assert body["forwarded_to_backend"] is False and body["reject_reason"] == reason and backend.sent == []


def test_backend_errors():
    request = httpx.Request("POST", "http://b")
    rejected = httpx.HTTPStatusError("x", request=request, response=httpx.Response(409, text="occupied", request=request))
    client, *_ = make_client(FakeRecognition(result()), FakeBackend(rejected))
    body = client.post("/gate-event/with-photo?gate=entry", files=FILES).json()
    assert body["forwarded_to_backend"] is False and body["reject_reason"] == "Backend отклонил: 409 occupied"

    client, *_ = make_client(FakeRecognition(result()), FakeBackend(httpx.ConnectError("down", request=request)))
    r = client.post("/gate-event/with-photo?gate=entry", files=FILES)
    assert r.status_code == 502 and r.json()["detail"].startswith("Backend недоступен")


def test_gate_must_be_entry_or_exit():
    client, *_ = make_client(FakeRecognition(result()))
    assert client.post("/gate-event/signal?gate=side").status_code == 422
    assert client.post("/gate-event/signal").status_code == 422


# ── signal (camera captures by itself) ─────────────────────────────────────────────────────────────────────────────
def test_signal_confident_read_is_forwarded_once_from_one_frame():
    client, backend, cameras, rec = make_client(FakeRecognition(result(confidence=0.97)))
    r = client.post("/gate-event/signal?gate=entry", headers={"X-Correlation-ID": "c1"})
    body = r.json()
    assert r.status_code == 200 and body["forwarded_to_backend"] and body["frame_source"] == "webcam"
    assert len(rec.calls) == 1 and rec.calls == [False]            # fast path only inside the burst
    assert backend.sent == [("entry", "01 KG 111 AAA", "c1")]


def test_signal_unsure_read_needs_two_agreeing_frames_and_forwards_once():
    client, backend, _, rec = make_client(FakeRecognition(result(confidence=0.6)))
    assert client.post("/gate-event/signal?gate=exit").json()["forwarded_to_backend"] is True
    assert len(rec.calls) == 2 and len(backend.sent) == 1


def test_signal_disagreeing_unsure_reads_never_double_forward():
    other = PlateCandidate("02", "KG", "222", "BBB", 0)
    client, backend, _, rec = make_client(FakeRecognition(result(confidence=0.6), result(other, 0.7), result(confidence=0.6)))
    body = client.post("/gate-event/signal?gate=entry").json()
    assert body["forwarded_to_backend"] is True and len(backend.sent) == 1
    assert backend.sent[0][1] == "01 KG 111 AAA"                     # seen twice beats seen once


def test_signal_retries_until_a_plate_appears():
    client, backend, _, rec = make_client(FakeRecognition(result(None, 0.0), result(None, 0.0), result(confidence=0.95)))
    body = client.post("/gate-event/signal?gate=entry").json()
    assert body["forwarded_to_backend"] and len(rec.calls) == 3


def test_signal_nothing_readable_ends_with_one_slow_pass_and_a_reject():
    client, backend, _, rec = make_client(FakeRecognition(result(None, 0.0)))
    body = client.post("/gate-event/signal?gate=entry").json()
    assert body["forwarded_to_backend"] is False and body["reject_reason"] == "Номер не распознан"
    assert rec.calls == [False] * 4 + [True] and backend.sent == []


def test_signal_camera_failure_is_503():
    client, *_ = make_client(FakeRecognition(result()), cameras=FakeCameras(CameraError("Камера для 'entry' недоступна: x")))
    r = client.post("/gate-event/signal?gate=entry")
    assert r.status_code == 503 and r.json()["detail"].startswith("Камера недоступна:")


def test_signal_backend_down_is_502():
    request = httpx.Request("POST", "http://b")
    client, *_ = make_client(FakeRecognition(result()), FakeBackend(httpx.ConnectError("down", request=request)))
    assert client.post("/gate-event/signal?gate=entry").status_code == 502


def test_simultaneous_pulses_for_one_gate_share_one_burst():
    async def scenario():
        rec = FakeRecognition(result(confidence=0.97))
        backend, cameras = FakeBackend(), FakeCameras(delay=0.15)
        services = SimpleNamespace(settings=load_settings({}), cameras=cameras, gate_service=GateService(rec, backend))
        app = create_app()
        app.dependency_overrides[get_services] = lambda: services
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            responses = await asyncio.gather(*[client.post("/gate-event/signal?gate=entry") for _ in range(3)])
        return responses, backend
    responses, backend = asyncio.run(scenario())
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert len(backend.sent) == 1                                      # one plate, forwarded once


def test_debug_snapshot():
    client, *_ = make_client(FakeRecognition(result()))
    body = client.get("/debug/camera-snapshot?gate=entry").json()
    assert body["source"] == "webcam" and body["image_base64"].startswith("data:image/jpeg;base64,")
    client, *_ = make_client(FakeRecognition(result()), cameras=FakeCameras(CameraError("x")))
    assert client.get("/debug/camera-snapshot?gate=entry").status_code == 503


# ── backend client + config ────────────────────────────────────────────────────────────────────────────────────────
def test_backend_client_url_body_and_headers(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content), headers=request.headers)
        return httpx.Response(200, json={"gate": "open"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = asyncio.run(BackendClient("http://backend:8000", service_token="tok").forward_plate("exit", "01 KG 111 AAA", "cid"))
    assert out == {"gate": "open"}
    assert seen["url"] == "http://backend:8000/api/sim/exit" and seen["body"] == {"plate_number": "01 KG 111 AAA"}
    assert seen["headers"]["x-service-token"] == "tok" and seen["headers"]["x-correlation-id"] == "cid"


def test_settings_defaults_and_overrides():
    s = load_settings({})
    assert (s.backend_base_url, s.entry_camera_source, s.exit_camera_source) == ("http://localhost:8000", "2", "3")
    s = load_settings({"BACKEND_BASE_URL": "http://x:1/", "ENTRY_CAMERA_SOURCE": " rtsp://cam/1 ", "BACKEND_SERVICE_TOKEN": "t"})
    assert (s.backend_base_url, s.entry_camera_source, s.backend_service_token) == ("http://x:1", "rtsp://cam/1", "t")
