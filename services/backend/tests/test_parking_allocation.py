"""Four shared spaces: staff and paying customers compete for the same capacity."""
import pytest

from tests.helpers import Lot, add_staff

SPACES = ["P1", "P2", "P3", "P4"]
STAFF = ["A001AA", "B777BB", "S003SS", "S004SS", "S005SS"]
CUSTOMERS = [f"C00{i}CC" for i in range(1, 7)]


@pytest.fixture()
def lot(client):
    add_staff(client, "S003SS", "S004SS", "S005SS")
    return Lot(client)


def fill(lot, n_staff, n_customers):
    """Park n_staff + n_customers vehicles, one per space."""
    plates = STAFF[:n_staff] + CUSTOMERS[:n_customers]
    for plate, space in zip(plates, SPACES):
        lot.park(plate, space)
    return plates


def test_exactly_four_shared_spaces_without_dedicated_types(lot):
    assert sorted(lot.slots) == SPACES
    assert {s["slot_type"] for s in lot.slots.values()} == {"PAID"}  # nothing staff-only


# 1-6: every mix of staff/customers fills the lot, then everybody else is denied
@pytest.mark.parametrize("n_staff", [0, 1, 2, 3, 4])
def test_any_mix_fills_four_spaces_and_then_denies_everyone(lot, n_staff):
    fill(lot, n_staff, 4 - n_staff)
    assert lot.occupied() == 4
    assert lot.entry("S005SS").status_code == 409  # a staff vehicle
    assert lot.entry("C006CC").status_code == 409  # a customer
    assert lot.occupied() == 4


def test_four_customers_fill_lot_and_staff_is_denied(lot):
    fill(lot, 0, 4)
    r = lot.entry("A001AA")
    assert r.status_code == 409 and r.json()["detail"] == "Нет свободных мест"


def test_customer_denial_keeps_original_message(lot):
    fill(lot, 4, 0)
    r = lot.entry("C001CC")
    assert r.status_code == 409 and r.json()["detail"] == "Нет свободных платных мест"


# 7: any vehicle type may take any physical space
@pytest.mark.parametrize("space", SPACES)
@pytest.mark.parametrize("plate", ["A001AA", "C001CC"])
def test_any_vehicle_can_take_any_space(lot, plate, space):
    lot.park(plate, space)
    assert lot.state()[space] == "PARKED"


def test_mixed_assignment_in_arbitrary_order(lot):
    lot.park("C001CC", "P4")
    lot.park("A001AA", "P1")
    lot.park("C002CC", "P3")
    lot.park("B777BB", "P2")
    assert set(lot.state().values()) == {"PARKED"}


def test_no_priority_for_staff_over_customers(lot):
    """Customers got the first three; the last unit goes to whoever asks first."""
    fill(lot, 0, 3)
    assert lot.entry("C004CC").status_code == 200
    assert lot.entry("A001AA").status_code == 409


def test_sensor_without_plate_binds_oldest_waiting_vehicle_whatever_its_type(lot):
    lot.entry("C001CC")
    lot.entry("A001AA")
    first = lot.sensor("P3").json()
    second = lot.sensor("P1").json()
    assert (first["plate_number"], first["slot_id"]) == ("C001CC", lot.sid("P3"))
    assert (second["plate_number"], second["slot_id"]) == ("A001AA", lot.sid("P1"))


def test_assigned_space_is_recorded_in_session(lot):
    lot.park("A001AA", "P2")
    lot.park("C001CC", "P4")
    by_plate = {s["plate_number"]: s for s in lot.c.get("/api/sim/sessions").json()}
    assert by_plate["A001AA"]["slot_id"] == lot.sid("P2")
    assert by_plate["C001CC"]["slot_id"] == lot.sid("P4")
    assert by_plate["A001AA"]["status"] == "EMPLOYEE_PASS"
    assert by_plate["C001CC"]["status"] == "PARKED"


def test_cannot_occupy_taken_space(lot):
    lot.park("C001CC", "P1")
    lot.entry("A001AA")
    r = lot.sensor("P1", "A001AA")
    assert r.status_code == 409 and r.json()["detail"] == "Слот уже занят"


# 8-10: reservations
def test_denied_when_spaces_are_occupied_or_reserved(lot):
    fill(lot, 1, 1)  # 2 parked
    assert lot.entry("C003CC").status_code == 200  # reserved
    assert lot.entry("S003SS").status_code == 200  # reserved
    assert lot.entry("C004CC").status_code == 409
    assert lot.entry("B777BB").status_code == 409


def test_admitted_when_exactly_one_unit_remains(lot):
    fill(lot, 1, 2)  # 3 parked
    assert lot.entry("C004CC").status_code == 200
    assert lot.entry("C005CC").status_code == 409


@pytest.mark.parametrize("newcomer", ["A001AA", "C004CC"])
def test_last_unit_can_go_to_staff_or_customer(lot, newcomer):
    fill(lot, 0, 3)
    assert lot.entry(newcomer).status_code == 200
    assert lot.sensor("P4", newcomer).status_code == 200
    assert lot.occupied() == 4


@pytest.mark.parametrize("newcomer", ["B777BB", "C004CC"])
def test_two_customers_and_one_staff_leave_one_unit(lot, newcomer):
    fill(lot, 1, 2)
    assert lot.entry(newcomer).status_code == 200


def test_admitted_but_not_parked_counts_against_capacity(lot):
    fill(lot, 1, 2)  # three occupied
    assert lot.entry("C004CC").status_code == 200  # authorised, not parked yet
    assert lot.occupied() == 3
    for plate in ("A001AA", "B777BB", "C005CC"):  # includes staff
        assert lot.entry(plate).status_code == 409


def test_pending_staff_also_counts(lot):
    fill(lot, 0, 3)
    assert lot.entry("A001AA").status_code == 200
    assert lot.entry("C004CC").status_code == 409


# 11: exits release exactly the right space
def test_staff_exit_releases_only_its_space_and_restores_capacity(lot):
    fill(lot, 2, 2)  # A001AA:P1 B777BB:P2 C001CC:P3 C002CC:P4
    assert lot.exit("B777BB").status_code == 200
    assert lot.state() == {"P1": "PARKED", "P2": "FREE", "P3": "PARKED", "P4": "PARKED"}
    assert lot.entry("C003CC").status_code == 200
    assert lot.entry("C004CC").status_code == 409


def test_customer_exit_releases_only_its_space_after_payment(lot):
    fill(lot, 2, 2)
    bill = lot.exit("C001CC").json()
    assert lot.state()["P3"] == "PARKED"  # still held until paid (unchanged lifecycle)
    assert lot.entry("S003SS").status_code == 409
    assert lot.pay(bill["id"]).status_code == 200
    assert lot.state() == {"P1": "PARKED", "P2": "PARKED", "P3": "FREE", "P4": "PARKED"}
    assert lot.entry("S003SS").status_code == 200


def test_freed_space_can_be_reused_by_other_vehicle_type(lot):
    lot.park("A001AA", "P1")
    lot.exit("A001AA")
    lot.park("C001CC", "P1")
    assert lot.state()["P1"] == "PARKED"


def test_staff_exit_response_and_second_exit(lot):
    lot.park("A001AA", "P1")
    body = lot.exit("A001AA").json()
    assert body["status"] == "EMPLOYEE_PASS" and body["exit_time"] and body["slot_id"] == lot.sid("P1")
    assert lot.exit("A001AA").status_code == 404


def test_staff_entry_returns_null(lot):
    assert lot.entry("A001AA").json() is None


# 12: manual releases
def test_manual_release_does_not_detach_wrong_session(lot):
    fill(lot, 1, 2)  # A001AA:P1 C001CC:P2 C002CC:P3
    assert lot.sensor("P2", occupied=False).status_code == 200
    sessions = {s["plate_number"]: s for s in lot.c.get("/api/sim/sessions").json()}
    assert lot.state() == {"P1": "PARKED", "P2": "FREE", "P3": "PARKED", "P4": "FREE"}
    # neighbours are untouched: both still exit normally and still free their own space
    assert lot.exit("A001AA").status_code == 200
    assert lot.state()["P3"] == "PARKED"
    assert sessions["C002CC"]["slot_id"] == lot.sid("P3")


def test_stale_customer_paying_after_manual_release_does_not_free_new_occupant(lot):
    lot.park("C001CC", "P1")
    lot.sensor("P1", occupied=False)
    lot.park("A001AA", "P1")  # new occupant (staff) of the same space
    old = lot.exit("C001CC").json()
    assert lot.pay(old["id"]).status_code == 200
    assert lot.state()["P1"] == "PARKED"
    assert lot.exit("A001AA").status_code == 200
    assert lot.state()["P1"] == "FREE"


def test_manual_release_of_staff_closes_its_visit(lot):
    lot.park("A001AA", "P1")
    lot.sensor("P1", occupied=False)
    assert lot.exit("A001AA").status_code == 404
    assert lot.state()["P1"] == "FREE"


def test_manual_release_of_free_space_is_idempotent(lot):
    r = lot.sensor("P1", occupied=False)
    assert r.status_code == 200 and r.json()["detail"] == "Слот освобождён вручную"


def test_unknown_space(lot):
    assert lot.c.post("/api/sim/sensor/9999", json={"occupied": True}).status_code == 404
    assert lot.c.post("/api/sim/sensor/9999", json={"occupied": False}).status_code == 404


def test_total_parked_never_exceeds_four_in_any_order(lot):
    plates = STAFF + CUSTOMERS
    for plate in plates:
        lot.entry(plate)
    for plate in plates:
        for space in SPACES:
            lot.sensor(space, plate)
        assert lot.occupied() <= 4


# displays
def test_entry_display_payload(client):
    lot = Lot(client)
    with client.websocket_connect("/ws/entry-display") as ws:
        first = ws.receive_json()
    assert (first["free_paid_slots"], first["total_paid_slots"]) == (4, 4)
    assert (first["free_slots"], first["total_slots"]) == (4, 4)
    assert (first["free_employee_slots"], first["total_employee_slots"]) == (0, 0)
    lot.park("A001AA", "P1")  # staff consume the same capacity customers see
    with client.websocket_connect("/ws/entry-display") as ws:
        assert ws.receive_json()["free_paid_slots"] == 3
