import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import OcrSettings
from app.main import app
from app.models import Detection, PlateCandidate, PlateCrop, RecognitionResult
from app.repositories import OcrModelRepository
from app.routers.dependencies import get_container
from app.services.gate_service import GateService
from app.services.recognition_service import RecognitionService

FIXTURES = Path(__file__).parent / "fixtures"


def png_bytes(w=40, h=20) -> bytes:
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), 128, np.uint8))
    return buf.tobytes()


def result_for(candidate, confidence=0.9, method="already_cropped", score=0.9):
    crop = PlateCrop(np.zeros((4, 4, 3), np.uint8), method, score)
    return RecognitionResult(candidate, confidence, [Detection("01", 0.5, 0.0)], crop)


class FakeRecognition:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def recognize(self, image_bytes):
        self.calls += 1
        return self.result


class FakeBackend:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response if response is not None else {"ok": True}, error, []

    async def forward_plate(self, gate, plate, correlation_id=None):
        self.calls.append((gate, plate))
        if self.error:
            raise self.error
        return self.response


class FakeCameraService:
    def __init__(self, source="webcam", error=None):
        self.source, self.error, self.gates = source, error, []

    def capture_frame_bytes(self, gate):
        self.gates.append(gate)
        if self.error:
            raise self.error
        return png_bytes(), self.source


def make_client(result=None, backend=None, camera=None, recognition=None):
    recognition = recognition or FakeRecognition(result)
    backend = backend or FakeBackend()
    camera = camera or FakeCameraService()
    container = SimpleNamespace(gate_service=GateService(recognition, backend, max_corrections=2), camera_service=camera)
    app.dependency_overrides[get_container] = lambda: container
    return TestClient(app), backend, camera


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


GOOD = PlateCandidate("01", "KG", "111", "AAA", 0)


def test_openapi_is_identical_to_pre_refactor_snapshot():
    snapshot = json.loads((FIXTURES / "openapi_v0.2.0.json").read_text(encoding="utf-8"))
    assert json.dumps(app.openapi(), sort_keys=True) == json.dumps(snapshot, sort_keys=True)


def test_all_original_routes_and_methods_exist():
    routes = {(m, r.path) for r in app.routes if hasattr(r, "methods") for m in r.methods if m not in ("HEAD", "OPTIONS")}
    assert routes >= {("POST", "/recognize"), ("POST", "/gate-event/signal"), ("POST", "/gate-event/with-photo"),
                      ("GET", "/debug/camera-snapshot"), ("GET", "/health")}


def test_app_entrypoint_and_metadata_unchanged():
    assert app.title == "Smart Parking - OCR Service (KG plates)" and app.version == "0.2.0"


def test_health():
    client, *_ = make_client(result_for(GOOD))
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "service": "ocr-service"}


def test_recognize_success_response_shape_and_values():
    client, *_ = make_client(result_for(GOOD, confidence=0.96149, score=0.96929))
    r = client.post("/recognize", files={"file": ("p.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json() == {
        "plate_number": "01111AAA", "formatted": "01 KG 111 AAA", "region_code": "01", "is_valid_region": True,
        "corrections_applied": 0, "confidence": 0.961, "plate_detection_method": "already_cropped",
        "plate_detection_score": 0.969, "raw_detections": [{"text": "01", "confidence": 0.5}],
    }


def test_recognize_when_nothing_found():
    client, *_ = make_client(result_for(None, confidence=0.0))
    body = client.post("/recognize", files={"file": ("p.jpg", png_bytes(), "image/jpeg")}).json()
    assert body["plate_number"] is None and body["formatted"] is None and body["region_code"] is None
    assert body["is_valid_region"] is False and body["corrections_applied"] == 0


@pytest.mark.parametrize("content_type", ["image/jpeg", "image/png", "image/jpg"])
def test_recognize_accepts_original_content_types(content_type):
    client, *_ = make_client(result_for(GOOD))
    assert client.post("/recognize", files={"file": ("f", png_bytes(), content_type)}).status_code == 200


def test_recognize_rejects_other_content_type_empty_file_and_missing_file():
    client, *_ = make_client(result_for(GOOD))
    r = client.post("/recognize", files={"file": ("a.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 400 and r.json() == {"detail": "Ожидается изображение JPEG или PNG"}
    r = client.post("/recognize", files={"file": ("a.png", b"", "image/png")})
    assert r.status_code == 400 and r.json() == {"detail": "Пустой файл"}
    assert client.post("/recognize").status_code == 422


def test_recognize_undecodable_image_is_400_with_original_message():
    real = RecognitionService(OcrModelRepository(), OcrSettings())   # декодирование падает до обращения к модели
    client, *_ = make_client(recognition=real)
    r = client.post("/recognize", files={"file": ("a.png", b"definitely not an image", "image/png")})
    assert r.status_code == 400 and r.json() == {"detail": "Не удалось декодировать изображение"}


def post_photo(client, gate="entry"):
    return client.post(f"/gate-event/with-photo?gate={gate}", files={"file": ("p.png", png_bytes(), "image/png")})


def test_gate_not_recognized():
    client, backend, _ = make_client(result_for(None, 0.0))
    body = post_photo(client).json()
    assert body["forwarded_to_backend"] is False and body["reject_reason"] == "Номер не распознан"
    assert body["frame_source"] == "uploaded" and body["backend_response"] is None and backend.calls == []


def test_gate_region_out_of_range():
    client, backend, _ = make_client(result_for(PlateCandidate("12", "KG", "111", "AAA", 0)))
    body = post_photo(client).json()
    assert body["reject_reason"] == "Код региона '12' вне диапазона 01-11" and backend.calls == []


def test_gate_too_many_corrections():
    client, backend, _ = make_client(result_for(PlateCandidate("01", "KG", "111", "AAA", 3)))
    body = post_photo(client).json()
    assert body["reject_reason"] == "Слишком много исправленных символов (3) - результату не доверяем"
    assert backend.calls == []


def test_gate_two_corrections_is_still_trusted():
    client, backend, _ = make_client(result_for(PlateCandidate("01", "KG", "111", "AAA", 2)))
    assert post_photo(client).json()["forwarded_to_backend"] is True


@pytest.mark.parametrize("gate", ["entry", "exit"])
def test_gate_forwards_formatted_plate_to_backend(gate):
    client, backend, _ = make_client(result_for(GOOD), backend=FakeBackend({"session_id": 7}))
    body = post_photo(client, gate).json()
    assert backend.calls == [(gate, "01 KG 111 AAA")]
    assert body["forwarded_to_backend"] is True and body["backend_response"] == {"session_id": 7}
    assert body["reject_reason"] is None and body["recognized"]["formatted"] == "01 KG 111 AAA"


def test_gate_backend_http_error_is_reported_not_raised():
    request = httpx.Request("POST", "http://backend/api/sim/entry")
    error = httpx.HTTPStatusError("x", request=request, response=httpx.Response(409, text="already inside", request=request))
    client, *_ = make_client(result_for(GOOD), backend=FakeBackend(error=error))
    body = post_photo(client).json()
    assert body["forwarded_to_backend"] is False and body["reject_reason"] == "Backend отклонил: 409 already inside"


def test_gate_backend_unreachable_is_502():
    client, *_ = make_client(result_for(GOOD), backend=FakeBackend(error=httpx.ConnectError("refused")))
    r = post_photo(client)
    assert r.status_code == 502 and r.json()["detail"].startswith("Backend недоступен:")


def test_gate_rejects_invalid_gate_value():
    client, *_ = make_client(result_for(GOOD))
    assert post_photo(client, "side").status_code == 422
    assert client.post("/gate-event/signal?gate=side").status_code == 422
    assert client.post("/gate-event/signal").status_code == 422


@pytest.mark.parametrize("source", ["webcam", "ip_camera", "fixture"])
def test_signal_uses_camera_and_reports_frame_source(source):
    client, backend, camera = make_client(result_for(GOOD), camera=FakeCameraService(source))
    body = client.post("/gate-event/signal?gate=exit").json()
    assert camera.gates == ["exit"] and body["frame_source"] == source and body["forwarded_to_backend"] is True


def test_signal_camera_failure_is_503_with_original_prefix():
    client, *_ = make_client(result_for(GOOD), camera=FakeCameraService(error=RuntimeError("Камера для 'entry' недоступна")))
    r = client.post("/gate-event/signal?gate=entry")
    assert r.status_code == 503 and r.json() == {"detail": "Камера недоступна: Камера для 'entry' недоступна"}


def test_debug_snapshot_shape_and_failure():
    client, *_ = make_client(result_for(GOOD), camera=FakeCameraService("ip_camera"))
    body = client.get("/debug/camera-snapshot?gate=entry").json()
    assert set(body) == {"source", "image_base64"} and body["source"] == "ip_camera"
    assert body["image_base64"].startswith("data:image/jpeg;base64,")
    client, *_ = make_client(result_for(GOOD), camera=FakeCameraService(error=RuntimeError("нет кадра")))
    r = client.get("/debug/camera-snapshot?gate=entry")
    assert r.status_code == 503 and r.json() == {"detail": "Камера недоступна: нет кадра"}


def test_lifespan_starts_and_stops_container(monkeypatch):
    events = []
    from app.services import container as container_module

    class Spy:
        def start(self): events.append("start")
        def stop(self): events.append("stop")

    monkeypatch.setattr(container_module.ServiceContainer, "build", classmethod(lambda cls, settings: Spy()))
    app.state.container = None
    with TestClient(app):
        assert events == ["start"]
    assert events == ["start", "stop"]
    app.state.container = None
