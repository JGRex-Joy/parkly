import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import protocol

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not available")


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    out = tmp_path_factory.mktemp("fw") / "fw_host"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "tools/hostsim"),
                    "-o", str(out), str(ROOT / "tools/hostsim/harness.cpp")], check=True)
    return out


def run(binary, *script):
    result = subprocess.run([str(binary)], input="\n".join(script) + "\n", capture_output=True,
                            text=True, timeout=30, check=True)
    lines = []
    for raw in result.stdout.splitlines():
        t, _, text = raw.partition("] ")
        lines.append((int(t[1:]), text))
    return lines


def msgs(lines):
    out = []
    for t, text in lines:
        if text.startswith("$"):
            out.append((t, protocol.parse_message(text)))
    return out


def events(lines, name):
    return [(t, m) for t, m in msgs(lines) if isinstance(m, protocol.Event) and m.name == name]


def cmd(seq, name, *args):
    return "L " + protocol.encode_command(seq, name, *args).decode().strip()


def acks(lines):
    return [m for _, m in msgs(lines) if isinstance(m, protocol.Ack)]


def test_boot_and_every_frame_has_valid_checksum(binary):
    lines = run(binary, "T 2500")
    kinds = [m.name for _, m in msgs(lines)]
    assert kinds[:2] == ["BOOT", "STATE"] and "HB" in kinds
    seqs = [m.seq for _, m in msgs(lines)]
    assert seqs == list(range(1, len(seqs) + 1))
    assert events(lines, "BOOT")[0][1].args == ("1.0.0",)


def test_slot_debounce_event_and_led(binary):
    lines = run(binary, "D 0 10", "T 1500", "P")
    slot = events(lines, "SLOT")
    assert [m.args for _, m in slot] == [("1", "1")]           
    assert "leds=1000" in lines[-1][1]
    t = slot[0][0]
    assert 300 <= t <= 1000                                      


def test_single_noisy_reading_is_ignored(binary):
    lines = run(binary, "D 0 10", "T 250", "D 0 200", "T 3000", "P")
    assert events(lines, "SLOT") == []
    assert "leds=0000" in lines[-1][1]


def test_hysteresis_keeps_slot_occupied_until_clearly_free(binary):
    lines = run(binary, "D 1 10", "T 1500",
                "D 1 28", "T 2000",        
                "D 1 40", "T 2000")        
    assert [m.args for _, m in events(lines, "SLOT")] == [("2", "1"), ("2", "0")]


def test_gate_detection_is_faster_than_slot_detection(binary):
    lines = run(binary, "D 4 20", "D 5 20", "T 1000")
    gates = {m.args: t for t, m in events(lines, "GATE")}
    assert set(gates) == {("entry", "1"), ("exit", "1")}


def test_ping_ack_duplicate_and_bad_frames(binary):
    good = cmd(5, "PING")
    corrupted = good[:-2] + "00"
    lines = run(binary, good, good, corrupted, "L garbage", "R 150", "T 5")
    replies = [(a.seq, a.ok, a.detail) for a in acks(lines)]
    assert replies == [(5, True, ""), (5, True, "DUP"), (0, False, "CHECKSUM"), (0, False, "TOO_LONG")]


def test_open_is_non_blocking_holds_then_closes_when_clear(binary):
    lines = run(binary,
                cmd(1, "OPEN", "entry", 600), "T 400", "P",     
                "T 300", "P",                                   
                "D 4 20", "T 1200", "P",                        
                "D 4 300", "T 3500", "P")                       
    stats = [text for _, text in lines if text.startswith("STAT ")]
    assert "entry_servo=90" in stats[1]
    assert "entry_servo=90" in stats[2]                         
    assert "entry_servo=0" in stats[3]
    assert [m.args for _, m in events(lines, "BARRIER")] == [("entry", "OPENED"), ("entry", "CLOSED")]
    assert acks(lines)[0].ok
    assert events(lines, "GATE")


def test_open_again_refreshes_and_unknown_inputs_are_nak(binary):
    lines = run(binary, cmd(1, "OPEN", "exit"), cmd(2, "OPEN", "exit"), cmd(3, "OPEN", "garage"),
                cmd(4, "OPEN", "exit", 99), cmd(6, "FLY"), cmd(7, "CFG", "nope", 1),
                cmd(8, "CFG", "debounce", 0), "T 5")
    assert [(a.seq, a.ok, a.detail) for a in acks(lines)] == [
        (1, True, ""), (2, True, "REFRESHED"), (3, False, "BAD_GATE"), (4, False, "BAD_VALUE"),
        (6, False, "UNKNOWN_CMD"), (7, False, "BAD_KEY"), (8, False, "BAD_VALUE")]


def test_cfg_changes_threshold_at_runtime(binary):
    lines = run(binary, "D 2 40", "T 1500", cmd(1, "CFG", "slot_thr", 60), "T 1500")
    assert [m.args for _, m in events(lines, "SLOT")] == [("3", "1")]


def test_sync_reports_full_state(binary):
    lines = run(binary, "D 3 10", "D 4 20", "T 1500", cmd(1, "SYNC"), "T 5")
    state = events(lines, "STATE")[-1][1]
    parsed = protocol.parse_state(state.args)
    assert parsed.slots == (False, False, False, True) and parsed.entry_present


def test_close_refused_while_vehicle_present(binary):
    lines = run(binary, cmd(1, "OPEN", "exit"), "D 5 20", "T 600", cmd(2, "CLOSE", "exit"), "T 5")
    assert [(a.seq, a.ok, a.detail) for a in acks(lines)][-1] == (2, False, "VEHICLE_PRESENT")
