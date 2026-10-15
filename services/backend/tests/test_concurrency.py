"""Concurrent requests must never double-book a space or admit more than four vehicles.

HTTP requests are served by worker threads (sync endpoints), each with its own
DB connection to a real SQLite file, so these tests exercise genuine
parallelism across the whole stack (and also hit the service layer directly).
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.api.exceptions import ConflictError
from tests.helpers import Lot, add_staff

SPACES = ["P1", "P2", "P3", "P4"]
STAFF = ["A001AA", "B777BB", "S003SS", "S004SS", "S005SS", "S006SS", "S007SS", "S008SS"]
CUSTOMERS = [f"C{i:03d}CC" for i in range(8)]


def run_parallel(fn, args):
    barrier = Barrier(len(args))

    def task(a):
        barrier.wait()
        return fn(a)

    with ThreadPoolExecutor(max_workers=len(args)) as pool:
        return list(pool.map(task, args))


@pytest.fixture()
def lot(client):
    add_staff(client, *STAFF[2:])
    return Lot(client)


def admitted(lot, plates):
    return sum(c == 200 for c in run_parallel(lambda p: lot.entry(p).status_code, plates))


def test_concurrent_customer_entries_cannot_exceed_capacity(lot):
    assert admitted(lot, [f"C{i:03d}CC" for i in range(16)]) == 4


def test_concurrent_staff_entries_cannot_exceed_capacity(lot):
    assert admitted(lot, STAFF) == 4


def test_concurrent_mixed_entries_cannot_exceed_capacity(lot):
    assert admitted(lot, STAFF + CUSTOMERS) == 4


def test_concurrent_entries_with_one_unit_left_admit_exactly_one(lot):
    for plate, space in zip(["A001AA", "C000CC", "C001CC"], SPACES):
        lot.park(plate, space)
    assert admitted(lot, STAFF[1:] + CUSTOMERS[2:]) == 1


def test_concurrent_entries_with_one_pending_reservation_admit_exactly_the_remainder(lot):
    for plate, space in zip(["A001AA", "C000CC"], SPACES):
        lot.park(plate, space)
    assert lot.entry("C001CC").status_code == 200  # reserved, not parked
    assert admitted(lot, STAFF[1:] + CUSTOMERS[2:]) == 1


def test_concurrent_entries_when_full_admit_nobody(lot):
    for plate, space in zip(["A001AA", "C000CC", "C001CC", "B777BB"], SPACES):
        lot.park(plate, space)
    assert admitted(lot, STAFF[2:] + CUSTOMERS[2:]) == 0


def test_concurrent_sensors_for_same_space_only_one_wins(lot):
    plates = ["C000CC", "A001AA"]
    for p in plates:
        assert lot.entry(p).status_code == 200
    codes = run_parallel(lambda p: lot.sensor("P1", p).status_code, plates)
    assert sorted(codes) == [200, 409]
    assert lot.occupied() == 1


def test_concurrent_sensors_on_different_spaces_never_share_a_space(lot):
    plates = ["A001AA", "C000CC", "B777BB", "C001CC"]
    for p in plates:
        assert lot.entry(p).status_code == 200

    def park(arg):
        plate, space = arg
        return lot.sensor(space, plate).status_code

    assert run_parallel(park, list(zip(plates, SPACES))) == [200] * 4
    sessions = lot.c.get("/api/sim/sessions").json()
    assert sorted(s["slot_id"] for s in sessions) == sorted(lot.sid(n) for n in SPACES)


def test_concurrent_payments_succeed_exactly_once(lot):
    lot.park("C000CC", "P1")
    sid = lot.exit("C000CC").json()["id"]
    codes = run_parallel(lambda _: lot.pay(sid).status_code, list(range(8)))
    assert sorted(codes) == [200] + [409] * 7
    assert lot.state()["P1"] == "FREE"


def test_concurrent_exit_bills_once(lot):
    lot.park("C000CC", "P1")
    codes = run_parallel(lambda _: lot.exit("C000CC").status_code, list(range(6)))
    assert sorted(codes) == [200] + [404] * 5


def test_concurrent_staff_exit_releases_once(lot):
    lot.park("A001AA", "P1")
    codes = run_parallel(lambda _: lot.exit("A001AA").status_code, list(range(6)))
    assert sorted(codes) == [200] + [404] * 5
    assert lot.state()["P1"] == "FREE"


def test_concurrent_exit_and_entry_never_exceed_capacity(lot):
    for plate, space in zip(["A001AA", "C000CC", "C001CC", "B777BB"], SPACES):
        lot.park(plate, space)

    def act(arg):
        kind, plate = arg
        return (lot.exit(plate) if kind == "exit" else lot.entry(plate)).status_code

    jobs = [("exit", "A001AA"), ("exit", "B777BB")] + [("entry", p) for p in CUSTOMERS[2:] + STAFF[2:]]
    run_parallel(act, jobs)
    sessions = lot.c.get("/api/sim/sessions").json()
    waiting = [s for s in sessions if s["slot_id"] is None and s["exit_time"] is None]
    assert lot.occupied() + len(waiting) <= 4


def test_full_cycle_under_load_keeps_invariants(lot):
    plates = STAFF + CUSTOMERS
    run_parallel(lambda p: lot.entry(p).status_code, plates)

    def try_park(p):
        return [lot.sensor(s, p).status_code for s in SPACES]

    run_parallel(try_park, plates)
    assert lot.occupied() <= 4
    held = [s["slot_id"] for s in lot.c.get("/api/sim/sessions").json() if s["slot_id"] is not None]
    assert len(held) == len(set(held)), "a space was assigned to two sessions"
    assert len(held) == lot.occupied()


# ---- service layer, many DB sessions at once ------------------------------
def test_services_serialise_admission_across_sessions(make_scope):
    scopes = [make_scope() for _ in range(12)]

    def admit(i):
        try:
            scopes[i].parking.register_entry(f"A{i:03d}XX" if i % 2 else f"C{i:03d}CC")
            return True
        except ConflictError:
            return False

    assert sum(run_parallel(admit, list(range(12)))) == 4


def test_database_rejects_double_booking_even_if_application_checks_are_bypassed(make_scope):
    """The partial unique index is the last line of defence."""
    from sqlalchemy.exc import IntegrityError

    from app.db.models import ParkingSession, SessionStatus

    scope = make_scope()
    slot = scope.repos.slots.list_active()[0]
    for i in range(2):
        scope.db.add(ParkingSession(plate_number=f"X{i}", status=SessionStatus.PARKED, slot_id=slot.id))
    with pytest.raises(IntegrityError):
        scope.db.flush()
    scope.db.rollback()


def test_slot_compare_and_set_refuses_second_claim(make_scope):
    from app.api.exceptions import SlotOccupiedError

    scope = make_scope()
    slot = scope.repos.slots.list_active()[0]
    scope.repos.slots.mark_parked(slot)
    with pytest.raises(SlotOccupiedError):
        scope.repos.slots.mark_parked(slot)
    scope.db.rollback()
