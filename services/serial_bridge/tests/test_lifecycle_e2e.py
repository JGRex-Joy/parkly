from __future__ import annotations

import httpx

from tests.conftest import stays_false, wait_until

ADMIN = {"X-Admin-Token": "adm"}


def trace(stack, session_id):
    return [e["kind"] for e in reversed(stack.backend.get(
        "/api/admin/audit", params={"session_id": session_id, "limit": 100}, headers=ADMIN).json())]


def test_complete_lifecycle_entry_to_hardware_confirmed_exit(make_stack):
    stack = make_stack(backend_env={"PARKING_ADMIN_TOKEN": "adm"})
    plate = "C123CC"

    stack.arrive("entry", plate)
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1, what="entry barrier")
    entered = stack.session_of(plate)
    assert entered["status"] == "ENTERED" and entered["parked_time"] is None   
    stack.gate("entry", False)
    stack.slot(1, True)
    wait_until(lambda: stack.session_of(plate).get("status") == "PARKED", what="parked")
    assert stack.session_of(plate)["parked_time"] and stack.slots()["P1"]["status"] == "PARKED"
    stack.slot(1, False)
    wait_until(lambda: stack.slots()["P1"]["status"] == "FREE", what="slot freed")
    kept = stack.session_of(plate)
    assert kept["status"] == "PARKED" and kept["parked_time"] == stack.session_of(plate)["parked_time"]
    stack.arrive("exit", plate)
    wait_until(lambda: stack.session_of(plate).get("status") == "AWAITING_PAYMENT", what="billed")
    billed = stack.session_of(plate)
    assert billed["amount_due"] is not None and billed["exit_time"]
    stays_false(lambda: stack.device()["open_count"]["exit"] > 0, 1.0, what="exit barrier before payment")

    assert stack.backend.post(f"/api/pay/{billed['id']}").json()["barrier_opened"] is False  # honest
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="exit barrier after payment")
    assert stack.session_of(plate)["status"] == "PAID"
    assert stack.session_of(plate)["completed_time"] is None       
    stack.gate("exit", False)                                      
    wait_until(lambda: stack.session_of(plate).get("status") == "COMPLETED", what="hardware-confirmed completion")
    assert stack.session_of(plate)["completed_time"]

    assert stack.device()["open_count"] == {"entry": 1, "exit": 1}
    assert len(stack.sessions()) == 1
    assert all(s["status"] == "FREE" for s in stack.slots().values())

    kinds = trace(stack, billed["id"])
    for step in ("entry_authorized", "slot_occupied", "slot_vacated", "exit_billed", "payment_succeeded",
                 "exit_authorized", "barrier_command_acked", "barrier_event", "session_completed"):
        assert step in kinds, f"{step} missing from {kinds}"
    cid = stack.ocr.state.correlation_ids[0]
    assert cid.startswith("entry-")
    by_cid = stack.backend.get("/api/admin/audit", params={"correlation_id": cid}, headers=ADMIN).json()
    assert "entry_authorized" in [e["kind"] for e in by_cid]


def test_authorisation_is_recovered_by_polling_when_the_websocket_is_unavailable(make_stack):
    stack = make_stack(backend_ws_enabled=False, auth_poll_interval=0.3)
    stack.enter_and_park("C123CC")
    wait_until(lambda: stack.device()["open_count"]["entry"] == 1, what="entry opened via poll")
    stack.arrive("exit", "C123CC")
    wait_until(lambda: stack.session_of("C123CC").get("status") == "AWAITING_PAYMENT", what="billed")
    sid = stack.session_of("C123CC")["id"]
    stack.backend.post(f"/api/pay/{sid}")
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="exit opened via poll")
    wait_until(lambda: stack.backend.get("/api/hardware/authorizations", params={"gate": "exit"}).json() == [],
               what="controller ACK reported to the backend")
    stays_false(lambda: stack.device()["open_count"]["exit"] > 1, 1.5, what="second opening")
    stack.gate("exit", False)
    wait_until(lambda: stack.session_of("C123CC").get("status") == "COMPLETED", what="completed")


def test_push_and_poll_together_open_the_barrier_once(make_stack):
    stack = make_stack(auth_poll_interval=0.2)          
    stack.enter_and_park("C123CC")
    stack.pay_exit("C123CC")
    wait_until(lambda: stack.device()["open_count"]["exit"] >= 1, what="exit opened")
    stays_false(lambda: stack.device()["open_count"]["exit"] > 1, 2.0, what="duplicate opening")
    assert stack.status()["counters"]["auth_executed"] == 2   


def test_failed_open_is_retried_while_authorisation_is_fresh_and_acked_only_when_executed(make_stack):
    stack = make_stack(backend_env={"PARKING_AUTH_TTL_SECONDS": "60"},
                       auth_poll_interval=0.4, open_deadline=0.8)
    stack.enter_and_park("C123CC")
    stack.arrive("exit", "C123CC")
    wait_until(lambda: stack.session_of("C123CC").get("status") == "AWAITING_PAYMENT", what="billed")
    stack.bridge.post("/sim/unplug", params={"seconds": 3.0}).raise_for_status()
    sid = stack.session_of("C123CC")["id"]
    stack.backend.post(f"/api/pay/{sid}")
    wait_until(lambda: stack.status()["counters"]["open_failed"] >= 1, what="barrier command failed")
    assert [a["session_id"] for a in stack.backend.get(
        "/api/hardware/authorizations", params={"gate": "exit"}).json()] == [sid]
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, 15, what="opened after the link returned")
    wait_until(lambda: stack.backend.get("/api/hardware/authorizations", params={"gate": "exit"}).json() == [],
               what="acknowledged after execution")


def test_unreachable_ocr_keeps_barrier_closed_and_is_reported(make_stack):
    stack = make_stack(ocr_url="http://127.0.0.1:1", ocr_max_attempts=2)
    stack.gate("entry", True)
    wait_until(lambda: stack.status()["counters"]["ocr_calls"] >= 2, what="OCR attempts")
    stays_false(lambda: stack.device()["open_count"]["entry"] > 0, 1.0, what="barrier without a plate")
    assert stack.session_of("C123CC") == {} and stack.sessions() == []
    assert stack.bridge.get("/status", params={"deep": True}).json()["ocr_reachable"] is False
    assert stack.bridge.get("/ready").status_code == 200      


def test_backend_outage_is_survived_and_slot_events_are_delivered_after_restart(make_stack):
    stack = make_stack(slot_reconcile_interval=0.5)
    stack.enter_and_park("C123CC", slot_index=1)
    stack.stop_backend()
    wait_until(lambda: not _alive(stack.backend_url), what="backend down")
    stack.slot(1, False)                                       
    wait_until(lambda: stack.status()["counters"]["slot_failed"] >= 1
               or stack.status()["counters"]["slot_unmatched"] >= 1, 15, what="bridge noticed the outage")
    assert stack.bridge.get("/health").status_code == 200        
    stack.start_backend()
    wait_until(lambda: _alive(stack.backend_url), 20, what="backend back")
    wait_until(lambda: stack.slots()["P1"]["status"] == "FREE", 30, what="vacancy delivered after restart")
    assert stack.session_of("C123CC")["status"] == "PARKED"     
    assert len(stack.sessions()) == 1


def _alive(url):
    try:
        return httpx.get(url + "/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def test_service_token_is_sent_on_every_bridge_and_ocr_call(make_stack):
    stack = make_stack(backend_env={"PARKING_SERVICE_TOKEN": "tok"}, service_token="tok", auth_poll_interval=0.3)
    assert stack.backend.get("/api/sim/slots").status_code == 401            
    stack.backend.headers["X-Service-Token"] = "tok"                         
    stack.enter_and_park("C123CC")                                           
    stack.arrive("exit", "C123CC")
    wait_until(lambda: stack.session_of("C123CC").get("status") == "AWAITING_PAYMENT", what="billed")
    stack.backend.post(f"/api/pay/{stack.session_of('C123CC')['id']}")
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="authorisation polled with the token")
    assert stack.status()["counters"]["slot_failed"] == 0


def test_free_stay_needs_no_payment_and_still_completes_on_hardware_confirmation(make_stack):
    stack = make_stack(backend_env={"PARKING_AUTO_SETTLE_FREE_STAYS": "true", "PARKING_PAYMENT_MODE": "webhook",
                                    "PARKING_PAYMENT_WEBHOOK_SECRET": "s", "PARKING_ENV": "production"})
    stack.enter_and_park("C123CC")
    stack.arrive("exit", "C123CC")                    
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="barrier opens without a payment")
    assert stack.session_of("C123CC")["amount_due"] == 0
    stack.gate("exit", False)
    wait_until(lambda: stack.session_of("C123CC").get("status") == "COMPLETED", what="completed")


def test_vehicle_that_never_stood_at_the_gate_is_not_reported_as_cleared(make_stack):
    stack = make_stack(auth_poll_interval=0.3)
    stack.enter_and_park("C123CC")
    stack.arrive("exit", "C123CC")
    wait_until(lambda: stack.session_of("C123CC").get("status") == "AWAITING_PAYMENT", what="billed")
    stack.gate("exit", False)                        
    sid = stack.session_of("C123CC")["id"]
    stack.backend.post(f"/api/pay/{sid}")
    wait_until(lambda: stack.device()["open_count"]["exit"] == 1, what="barrier opened for the paid session")
    stack.gate("exit", True); stack.gate("exit", False)   
    stays_false(lambda: stack.session_of("C123CC").get("status") == "COMPLETED", 1.5,
                what="completion attributed to a vehicle that was not there")
