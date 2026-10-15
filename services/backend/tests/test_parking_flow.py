from fastapi.testclient import TestClient

from app.main import app


EXPECTED_ROUTES = {
    ("GET", "/"),
    ("POST", "/api/sim/entry"),
    ("POST", "/api/sim/sensor/{slot_id}"),
    ("POST", "/api/sim/exit"),
    ("GET", "/api/sim/slots"),
    ("GET", "/api/sim/sessions"),
    ("GET", "/pay/{session_id}"),
    ("POST", "/api/pay/{session_id}"),
}


def test_registered_routes():
    registered = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            registered.add((method, path))

    assert EXPECTED_ROUTES.issubset(registered)


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Smart Parking Management System"
    assert data["docs"] == "/docs"
    assert data["entry_display_ws"] == "/ws/entry-display"
    assert data["exit_display_ws"] == "/ws/exit-display"


def test_employee_entry_returns_null(client: TestClient):
    response = client.post("/api/sim/entry", json={"plate_number": "A001AA"})
    assert response.status_code == 200
    assert response.json() is None


def test_paid_entry_creates_session(client: TestClient):
    response = client.post("/api/sim/entry", json={"plate_number": "C123CC"})
    assert response.status_code == 200
    data = response.json()
    assert data["plate_number"] == "C123CC"
    assert data["status"] == "ENTERED"
    assert data["slot_id"] is None


def test_entry_when_no_free_paid_slots(client: TestClient):
    slots = client.get("/api/sim/slots").json()
    paid_slots = [s for s in slots if s["slot_type"] == "PAID"]

    for i, slot in enumerate(paid_slots):
        plate = f"T{i:03d}TT"
        entry = client.post("/api/sim/entry", json={"plate_number": plate})
        assert entry.status_code == 200
        sensor = client.post(
            f"/api/sim/sensor/{slot['id']}",
            json={"occupied": True, "plate_number": plate},
        )
        assert sensor.status_code == 200

    response = client.post("/api/sim/entry", json={"plate_number": "Z999ZZ"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Нет свободных платных мест"


def test_full_parking_flow(client: TestClient):
    entry = client.post("/api/sim/entry", json={"plate_number": "c123cc"})
    assert entry.status_code == 200
    session = entry.json()
    assert session["status"] == "ENTERED"

    slots = client.get("/api/sim/slots").json()
    free_paid = next(s for s in slots if s["slot_type"] == "PAID" and s["status"] == "FREE")

    sensor = client.post(
        f"/api/sim/sensor/{free_paid['id']}",
        json={"occupied": True, "plate_number": "C123CC"},
    )
    assert sensor.status_code == 200
    parked = sensor.json()
    assert parked["status"] == "PARKED"
    assert parked["slot_id"] == free_paid["id"]

    exit_resp = client.post("/api/sim/exit", json={"plate_number": "C123CC"})
    assert exit_resp.status_code == 200
    billed = exit_resp.json()
    assert billed["status"] == "AWAITING_PAYMENT"
    assert billed["amount_due"] is not None
    assert billed["duration_seconds"] is not None

    pay_page = client.get(f"/pay/{billed['id']}")
    assert pay_page.status_code == 200
    assert "text/html" in pay_page.headers["content-type"]
    assert "C123CC" in pay_page.text

    pay = client.post(f"/api/pay/{billed['id']}")
    assert pay.status_code == 200
    result = pay.json()
    assert result["session_id"] == billed["id"]
    assert result["status"] == "PAID"
    assert result["barrier_opened"] is True

    double_pay = client.post(f"/api/pay/{billed['id']}")
    assert double_pay.status_code == 409
    assert double_pay.json()["detail"] == "Сессия уже оплачена"


def test_sensor_unknown_slot(client: TestClient):
    response = client.post("/api/sim/sensor/9999", json={"occupied": True})
    assert response.status_code == 404
    assert response.json()["detail"] == "Слот не найден"


def test_sensor_without_entry_session(client: TestClient):
    slots = client.get("/api/sim/slots").json()
    free_paid = next(s for s in slots if s["slot_type"] == "PAID" and s["status"] == "FREE")
    response = client.post(f"/api/sim/sensor/{free_paid['id']}", json={"occupied": True})
    assert response.status_code == 404
    assert "ENTERED" in response.json()["detail"]


def test_exit_without_parked_session(client: TestClient):
    response = client.post("/api/sim/exit", json={"plate_number": "NOTEXIST"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Нет припаркованной (PARKED) сессии с таким номером"


def test_pay_before_bill(client: TestClient):
    entry = client.post("/api/sim/entry", json={"plate_number": "D456DD"})
    session_id = entry.json()["id"]
    response = client.post(f"/api/pay/{session_id}")
    assert response.status_code == 409
    assert response.json()["detail"] == "Оплата недоступна: счёт ещё не выставлен выездной камерой"


def test_list_slots_and_sessions(client: TestClient):
    client.post("/api/sim/entry", json={"plate_number": "E111EE"})
    slots = client.get("/api/sim/slots")
    sessions = client.get("/api/sim/sessions")
    assert slots.status_code == 200
    assert sessions.status_code == 200
    assert len(slots.json()) == 4
    assert len(sessions.json()) >= 1


def test_manual_free_slot(client: TestClient):
    slots = client.get("/api/sim/slots").json()
    free_paid = next(s for s in slots if s["slot_type"] == "PAID" and s["status"] == "FREE")
    response = client.post(
        f"/api/sim/sensor/{free_paid['id']}",
        json={"occupied": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["detail"] == "Слот освобождён вручную"
    assert data["slot"]["status"] == "FREE"
