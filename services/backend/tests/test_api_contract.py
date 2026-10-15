"""The public contract must stay byte-compatible with the pre-refactor API."""
import json
from pathlib import Path

from app.main import create_app

BASELINE = Path(__file__).parent / "fixtures" / "openapi_original.json"


def test_openapi_is_identical_to_pre_refactor_contract():
    current = json.loads(json.dumps(create_app().openapi(), sort_keys=True))
    assert current == json.loads(BASELINE.read_text())


def test_validation_errors_unchanged(client):
    r = client.post("/api/sim/sensor/1", json={"occupied": "not-a-bool"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "occupied"]


def test_unknown_session_responses(client):
    assert client.get("/pay/9999").status_code == 404
    assert client.get("/pay/9999").json() == {"detail": "Сессия не найдена"}
    assert client.post("/api/pay/9999").status_code == 404


def test_static_mount_exists(client):
    assert client.get("/static/does-not-exist").status_code == 404
