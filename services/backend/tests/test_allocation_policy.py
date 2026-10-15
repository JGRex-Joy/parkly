"""Pure capacity arithmetic - no database."""
from app.services.allocation import LotOccupancy


def test_empty_lot_has_four_units():
    assert LotOccupancy(free_slots=4, pending=0).available == 4


def test_each_occupied_space_consumes_one_unit():
    assert [LotOccupancy(free_slots=f, pending=0).available for f in (4, 3, 2, 1, 0)] == [4, 3, 2, 1, 0]


def test_pending_admission_consumes_one_unit():
    assert LotOccupancy(free_slots=1, pending=1).available == 0
    assert LotOccupancy(free_slots=4, pending=3).available == 1


def test_vehicles_in_legacy_spaces_still_count():
    assert LotOccupancy(free_slots=4, pending=0, legacy_occupied=1).available == 3
    assert LotOccupancy(free_slots=3, pending=1, legacy_occupied=1).available == 1


def test_never_negative():
    assert LotOccupancy(free_slots=0, pending=3, legacy_occupied=2).available == 0
