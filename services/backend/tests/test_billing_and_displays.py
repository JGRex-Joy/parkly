from datetime import datetime, timedelta

from app.db.models import Tariff
from app.services.billing import BillingCalculator
from tests.helpers import Lot

T0 = datetime(2026, 1, 1, 12, 0, 0)
TARIFF = Tariff(name="t", price_per_minute=5.0, free_minutes=1)


def test_billing_rounds_up_and_applies_free_minutes():
    calc = BillingCalculator()
    assert calc.calculate(T0, T0, TARIFF).amount == 0.0
    assert calc.calculate(T0, T0 + timedelta(seconds=60), TARIFF).amount == 0.0   # 1 min free
    assert calc.calculate(T0, T0 + timedelta(seconds=61), TARIFF).amount == 5.0   # 2nd minute started
    bill = calc.calculate(T0, T0 + timedelta(minutes=10), TARIFF)
    assert (bill.duration_seconds, bill.amount) == (600, 45.0)


def test_billing_never_negative_for_clock_skew():
    assert BillingCalculator().calculate(T0, T0 - timedelta(seconds=30), TARIFF).duration_seconds == 0


def test_exit_uses_injected_clock_and_publishes_bill(make_scope, publisher):
    now = {"t": T0}
    scope = make_scope(clock=lambda: now["t"])
    scope.parking.register_entry("C001CC")
    scope.parking.occupy_slot(scope.repos.slots.list_active()[0].id, "C001CC")
    now["t"] = T0 + timedelta(minutes=11)
    session = scope.parking.register_exit("C001CC")
    assert (session.duration_seconds, session.amount_due) == (660, 50.0)

    channel, payload = publisher.messages[-1]
    assert channel == "exit" and payload["event"] == "exit_bill"
    assert payload["amount_due"] == 50.0
    assert payload["duration"] == {"hours": 0, "minutes": 11, "seconds": 0}
    assert payload["qr_code_base64"].startswith("data:image/png;base64,")
    assert payload["pay_url"].endswith(f"/pay/{session.id}")


def test_payment_publishes_in_original_order(make_scope, publisher):
    scope = make_scope()
    scope.parking.register_entry("C001CC")
    scope.parking.occupy_slot(scope.repos.slots.list_active()[0].id, "C001CC")
    session = scope.parking.register_exit("C001CC")
    publisher.messages.clear()
    scope.payment.confirm_payment(session.id)
    assert [(c, p["event"]) for c, p in publisher.messages] == [
        ("exit", "barrier_open"), ("exit", "exit_clear"), ("entry", "entry_display_update"),
    ]


def test_failed_operation_publishes_nothing_and_changes_nothing(make_scope, publisher):
    import pytest

    from app.api.exceptions import NotFoundError

    scope = make_scope()
    publisher.messages.clear()
    with pytest.raises(NotFoundError):
        scope.parking.register_exit("NOBODY")
    assert publisher.messages == []


def test_stale_pending_entries_stop_reserving_capacity(make_scope):
    now = {"t": T0}
    scope = make_scope(clock=lambda: now["t"])
    for plate in ("C001CC", "C002CC", "C003CC", "A001AA"):  # staff reserve like anyone else
        scope.parking.register_entry(plate)
    now["t"] = T0 + timedelta(seconds=10)
    from app.api.exceptions import NoFreeSpaceError
    import pytest

    with pytest.raises(NoFreeSpaceError):
        scope.parking.register_entry("C004CC")
    now["t"] = T0 + timedelta(hours=1)  # earlier arrivals never reached a space
    assert scope.parking.register_entry("C004CC").plate_number == "C004CC"


def test_exit_display_websocket_replays_pending_bill(client):
    lot = Lot(client)
    lot.park("C001CC", "P1")
    lot.exit("C001CC")
    with client.websocket_connect("/ws/exit-display") as ws:
        msg = ws.receive_json()
    assert msg["event"] == "exit_bill" and msg["plate_number"] == "C001CC"


def test_exit_display_websocket_clear_when_nothing_pending(client):
    with client.websocket_connect("/ws/exit-display") as ws:
        assert ws.receive_json() == {"event": "exit_clear"}


def test_live_broadcast_reaches_connected_displays(client):
    lot = Lot(client)
    with client.websocket_connect("/ws/entry-display") as ws:
        assert ws.receive_json()["event"] == "entry_display_update"
        lot.park("C001CC", "P1")
        events = [ws.receive_json() for _ in range(2)]  # barrier_open + display update
    assert [e["event"] for e in events] == ["barrier_open", "entry_display_update"]
    assert events[1]["free_paid_slots"] == 3
