"""End-to-end scenarios: real backend + scripted OCR stand-in + bridge (mock serial)."""
import time

import httpx
import pytest

from tests.conftest import stays_false, wait_until


def test_entry_opens_barrier_once_and_creates_one_session(stack):
    stack.arrive("entry", "X100XX")
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1, what="entry barrier open")
    session = stack.session_of("X100XX")
    assert session["status"] == "ENTERED"

    stack.gate("entry", True)
    stack.bridge.post("/v1/device/sync")
    time.sleep(0.8)
    assert stack.ocr.state.calls == ["entry"]
    assert len([s for s in stack.sessions() if s["plate_number"] == "X100XX"]) == 1
    assert stack.device()["open_count"]["entry"] == 1


def test_gate_rearms_after_vehicle_leaves(stack):
    stack.arrive("entry", "X100XX")
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1)
    stack.gate("entry", False)
    wait_until(lambda: stack.status()["gates"]["entry"]["phase"] == "IDLE", what="gate re-armed")
    stack.arrive("entry", "Y200YY")
    wait_until(lambda: stack.device()["open_count"]["entry"] == 2, what="second vehicle admitted")
    assert stack.session_of("Y200YY")["status"] == "ENTERED"


def test_ocr_retries_until_plate_is_read(stack):
    stack.ocr.state.script[:] = [None, None]  
    stack.arrive("entry", "X100XX")           
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1, what="barrier after retries")
    assert stack.ocr.state.calls == ["entry"] * 3
    assert len([s for s in stack.sessions() if s["plate_number"] == "X100XX"]) == 1


def test_unreadable_plate_never_opens_barrier(stack):
    stack.ocr.state.script[:] = [None, None]
    stack.gate("entry", True)  
    wait_until(lambda: stack.status()["gates"]["entry"]["phase"] == "DONE", what="attempts exhausted")
    assert stack.ocr.state.calls == ["entry"] * 3
    assert stack.sessions() == []
    assert stack.device()["open_count"]["entry"] == 0
    stack.ocr.state.script[:] = ["X100XX"]
    stack.bridge.post("/v1/gates/entry/retrigger").raise_for_status()
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1, what="barrier after manual retrigger")


def test_full_lot_is_rejected_by_backend_and_not_retried(stack):
    for plate in ("A1", "A2", "A3", "A4"): 
        stack.backend.post("/api/sim/entry", json={"plate_number": plate}).raise_for_status()
    wait_until(lambda: stack.device()["open_count"]["entry"] == 4, what="four authorised entries")
    stack.arrive("entry", "LATE01")
    wait_until(lambda: stack.status()["gates"]["entry"]["phase"] == "DONE", what="flow finished")
    outcome = stack.status()["gates"]["entry"]["last_outcome"]
    assert outcome["kind"] == "final" and "409" in outcome["detail"]
    assert stack.ocr.state.calls == ["entry"]  
    time.sleep(0.5)
    assert stack.device()["open_count"]["entry"] == 4  


def test_slot_occupancy_and_vacancy_reach_backend(stack):
    stack.enter_and_park("X100XX", slot_index=3)
    assert stack.slots()["P3"]["status"] == "PARKED"
    assert stack.session_of("X100XX")["status"] == "PARKED"
    stack.slot(3, False)
    wait_until(lambda: stack.slots()["P3"]["status"] == "FREE", what="P3 released")


def test_slot_event_without_waiting_session_is_reported_not_crashing(stack):
    stack.slot(2, True)  
    wait_until(lambda: stack.status()["counters"]["slot_unmatched"] >= 1, what="unmatched counted")
    assert stack.slots()["P2"]["status"] == "FREE"
    assert stack.bridge.get("/health").status_code == 200


def test_exit_barrier_opens_only_after_payment(stack):
    session = stack.enter_and_park("X100XX")
    sid = session["id"]

    assert stack.backend.post(f"/api/pay/{sid}").status_code == 409
    stays_false(lambda: stack.device()["open_count"]["exit"] > 0, 0.6, what="exit barrier open")

    stack.arrive("exit", "X100XX")
    wait_until(lambda: stack.session_of("X100XX")["status"] == "AWAITING_PAYMENT", what="bill issued")
    stays_false(lambda: stack.device()["open_count"]["exit"] > 0, 1.0, what="exit barrier open before payment")

    assert stack.backend.post(f"/api/pay/{sid}").status_code == 200
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="exit barrier after payment")
    assert stack.session_of("X100XX")["status"] == "PAID"
    assert stack.slots()["P1"]["status"] == "FREE"

    stack.gate("exit", False)
    wait_until(lambda: not stack.device()["barrier_open"]["exit"], timeout=6, what="exit barrier closes")


def test_failed_payment_keeps_barrier_closed(stack):
    stack.enter_and_park("X100XX")
    stack.arrive("exit", "X100XX")
    wait_until(lambda: stack.session_of("X100XX")["status"] == "AWAITING_PAYMENT")
    assert stack.backend.post("/api/pay/99999").status_code == 404  
    stays_false(lambda: stack.device()["open_count"]["exit"] > 0, 1.0, what="exit barrier open")
    assert stack.session_of("X100XX")["status"] == "AWAITING_PAYMENT"


def test_unknown_vehicle_at_exit_is_rejected_by_backend(stack):
    stack.arrive("exit", "GHOST1")
    wait_until(lambda: stack.status()["gates"]["exit"]["phase"] == "DONE")
    assert stack.status()["gates"]["exit"]["last_outcome"]["kind"] == "final"
    assert stack.device()["open_count"]["exit"] == 0


def test_staff_vehicle_vacating_slot_can_still_leave(stack):
    stack.enter_and_park("A001AA", slot_index=2)       
    assert stack.session_of("A001AA")["status"] == "EMPLOYEE_PASS"
    stack.slot(2, False)                                
    wait_until(lambda: stack.slots()["P2"]["status"] == "FREE", what="space freed in the backend")
    assert stack.status()["counters"]["slot_skipped"] == 0
    assert not stack.session_of("A001AA").get("exit_time")   

    stack.arrive("exit", "A001AA")                     
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="staff exit barrier")
    assert stack.slots()["P2"]["status"] == "FREE"


def test_duplicate_open_requests_are_suppressed(stack):
    body = {"plate_number": "X100XX"}
    first = stack.bridge.post("/v1/barrier/exit/open", json=body).json()
    second = stack.bridge.post("/v1/barrier/exit/open", json=body).json()
    assert first["status"] == "opened" and second["status"] == "duplicate_suppressed"
    assert stack.device()["open_count"]["exit"] == 1
    other = stack.bridge.post("/v1/barrier/exit/open", json={"plate_number": "Z9"}).json()
    assert other["status"] in ("opened", "refreshed") and stack.device()["open_count"]["exit"] == 2


def test_lost_ack_does_not_open_twice(stack):
    stack.bridge.post("/sim/drop-acks", params={"count": 2})
    result = stack.bridge.post("/v1/barrier/entry/open", json={"request_id": "r-1"}).json()
    assert result["ok"]
    assert stack.device()["open_count"]["entry"] == 1
    assert stack.status()["serial"]["command_retries"] >= 2


def test_unplug_recovery_and_open_survives_reconnect(stack):
    session = stack.enter_and_park("X100XX")
    stack.arrive("exit", "X100XX")
    wait_until(lambda: stack.session_of("X100XX")["status"] == "AWAITING_PAYMENT")

    stack.bridge.post("/sim/unplug", params={"seconds": 1.0})
    wait_until(lambda: stack.bridge.get("/ready").status_code == 503, what="link reported down")
    assert stack.bridge.get("/health").status_code == 200  

    assert stack.backend.post(f"/api/pay/{session['id']}").status_code == 200
    wait_until(lambda: stack.bridge.get("/ready").status_code == 200, timeout=8, what="link restored")
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, timeout=8, what="deferred open executed")
    assert stack.device()["boots"] >= 2
    assert stack.status()["serial"]["disconnects"] >= 1


def test_open_fails_cleanly_when_link_never_returns(stack):
    stack.bridge.post("/sim/unplug", params={"seconds": 30})
    wait_until(lambda: stack.bridge.get("/ready").status_code == 503)
    response = stack.bridge.post("/v1/barrier/entry/open", json={"plate_number": "X1"}, timeout=15)
    assert response.status_code == 503
    assert stack.status()["counters"]["open_failed"] == 1


def test_slot_change_during_outage_is_repaired_after_reconnect(stack):
    stack.backend.post("/api/sim/entry", json={"plate_number": "X100XX"}).raise_for_status()
    stack.bridge.post("/sim/unplug", params={"seconds": 1.0})
    wait_until(lambda: stack.bridge.get("/ready").status_code == 503)
    stack.slot(1, True) 
    wait_until(lambda: stack.bridge.get("/ready").status_code == 200, timeout=8)
    wait_until(lambda: stack.slots()["P1"]["status"] == "PARKED", timeout=8, what="slot repaired after reconnect")


def test_status_and_simulation_endpoints(stack):
    status = stack.status()
    assert status["serial"]["connected"] and status["mock"]
    assert status["backend_ws"] == {"entry": True, "exit": True}
    deep = stack.bridge.get("/status", params={"deep": True}).json()
    assert deep["backend_reachable"] and deep["ocr_reachable"]
    assert stack.bridge.post("/v1/barrier/garage/open", json={}).status_code == 422


def test_api_token_is_enforced(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from tests.conftest import TEST_SETTINGS

    settings = Settings(api_token="s3cret", backend_url="http://127.0.0.1:9", ocr_url="http://127.0.0.1:9",
                        **TEST_SETTINGS)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200 
        assert client.post("/v1/barrier/exit/open", json={}).status_code == 401
        assert client.post("/v1/barrier/exit/open", json={}, headers={"X-Bridge-Token": "no"}).status_code == 401
        ok = client.post("/v1/barrier/exit/open", json={}, headers={"X-Bridge-Token": "s3cret"})
        assert ok.status_code in (200, 503)  
