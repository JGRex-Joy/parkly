"""Median filter / hysteresis / debounce / DUP semantics of the REAL firmware (host-compiled)."""
from app import protocol


def events(lines, kind):
    return [l for l in lines if f",{kind}," in l]


def drive(readings, sensor=0, tick=200, cfg=()):
    """One reading per sampling of `sensor` (slot sensors are sampled every 200 ms)."""
    c = [f"L {protocol.encode_command(i + 1, 'CFG', k, v).decode().strip()}" for i, (k, v) in enumerate(cfg)]
    c.append("T 5")
    for v in readings:
        c += [f"D {sensor} {v}", f"T {tick}"]
    return "\n".join(c) + "\n"


def test_parked_car_with_one_in_three_echo_loss_is_detected(firmware):
    # v1.0: 0 events (every loss reset the streak). v1.1: exactly one OCCUPIED, never FREE.
    ev = events(firmware(drive([10, 10, 999] * 14)), "SLOT")
    assert len(ev) == 1 and ",SLOT,1,1" in ev[0]


def test_bursts_of_three_lost_echoes_do_not_flap(firmware):
    # v1.0 produced 15 transitions on this input
    ev = events(firmware(drive(([10] * 4 + [999] * 3 + [10]) * 8)), "SLOT")
    assert len(ev) == 1


def test_glitch_below_2cm_is_discarded(firmware):
    ev = events(firmware(drive([10, 1, 10, 10, 1, 10, 10, 10, 1, 10] * 3)), "SLOT")
    assert len(ev) == 1


def test_single_outlier_cannot_free_a_slot(firmware):
    ev = events(firmware(drive([10] * 8 + [999] + [10] * 8)), "SLOT")
    assert len(ev) == 1


def test_free_needs_more_evidence_than_occupied(firmware):
    # window already full of far readings, car arrives at sample 10; later it leaves at sample 30
    ev = events(firmware(drive([80] * 10 + [10] * 20 + [80] * 20)), "SLOT")
    assert len(ev) == 2
    t = [int(e.split("]")[0][1:]) for e in ev]
    occupy_latency = t[0] - 10 * 200
    free_latency = t[1] - 30 * 200
    assert free_latency > occupy_latency + 300   # 6 agreeing medians vs 3


def test_dead_band_holds_state(firmware):
    # thr 25, hyst 5: readings 27 (inside 25..30) keep an occupied slot occupied
    ev = events(firmware(drive([10] * 8 + [27] * 30)), "SLOT")
    assert len(ev) == 1
    ev = events(firmware(drive([10] * 8 + [31] * 30)), "SLOT")
    assert len(ev) == 2


def test_filter_off_plus_symmetric_debounce_reproduces_v1_0_flapping(firmware):
    cfg = [("median", 1), ("debounce_free", 3)]
    ev = events(firmware(drive(([10] * 4 + [999] * 3 + [10]) * 8, cfg=cfg)), "SLOT")
    assert len(ev) > 5


def test_dist_diagnostics_only_when_enabled(firmware):
    assert not events(firmware(drive([10] * 20)), "DIST")
    ev = [e for e in events(firmware(drive([10] * 20, cfg=[("dbg", 1)])), "DIST") if ",DIST,1," in e]
    assert ev and ",DIST,1,10,10" in ev[0]


def test_reused_seq_with_different_command_is_executed_not_dup(firmware):
    f = lambda seq, *a: "L " + protocol.encode_command(seq, *a).decode().strip()
    lines = firmware("\n".join([f(1, "PING"), f(2, "PING"), f(3, "SYNC"), f(4, "PING"), "T 5",
                                f(2, "OPEN", "entry", "8000"), "T 800", "P"]) + "\n")
    acks = [l for l in lines if "ACK,2," in l]
    assert len(acks) == 2 and acks[0].endswith("*7F") and "DUP" not in acks[1]
    assert "entry_servo=90" in lines[-1]


def test_true_retransmit_is_dup_and_not_executed_twice(firmware):
    f = "L " + protocol.encode_command(7, "OPEN", "entry", "8000").decode().strip()
    lines = firmware("\n".join([f, "T 5", f, "T 5"]) + "\n")
    assert sum("DUP" in l for l in lines) == 1
    assert sum(",BARRIER,entry,OPENED" in l for l in lines) <= 1
