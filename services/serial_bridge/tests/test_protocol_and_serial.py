import asyncio

import pytest

from app import protocol
from app.config import Settings
from app.mock_arduino import MockArduino
from app.serial_manager import CommandRejected, CommandTimeout, SerialDisconnected, SerialManager


def test_roundtrip_and_known_checksum():
    frame = protocol.encode(("CMD", 7, "OPEN", "entry", 8000))
    assert frame == b"$CMD,7,OPEN,entry,8000*" + frame[-3:]
    assert protocol.decode(frame) == ["CMD", "7", "OPEN", "entry", "8000"]
    assert protocol.checksum("PING") == 0x50 ^ 0x49 ^ 0x4E ^ 0x47


def test_corruption_is_detected():
    frame = bytearray(protocol.encode(("EVT", 1, "SLOT", 2, 1)))
    frame[6] ^= 0x01
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(bytes(frame))


@pytest.mark.parametrize("bad", [b"", b"EVT,1*00\n", b"$EVT,1\n", b"$EVT,1*ZZ\n", b"\xff\xfe\n"])
def test_malformed_frames_rejected(bad):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(bad)


def test_encode_rejects_separators_in_fields():
    for field in ("a,b", "a*b", "a$b", "a\nb", ""):
        with pytest.raises(protocol.ProtocolError):
            protocol.encode(("CMD", 1, field))


def test_parse_messages():
    assert protocol.parse_message(protocol.encode(("ACK", 5, "OK"))) == protocol.Ack(5, True, "")
    assert protocol.parse_message(protocol.encode(("ACK", 5, "OK", "DUP"))).duplicate
    assert protocol.parse_message(protocol.encode(("NAK", 5, "BAD_GATE"))) == protocol.Ack(5, False, "BAD_GATE")
    event = protocol.parse_message(protocol.encode(("EVT", 9, "SLOT", 3, 1)))
    assert event == protocol.Event(9, "SLOT", ("3", "1"))
    assert protocol.parse_slot_event(event.args) == (3, True)
    state = protocol.parse_state(["1010", "1", "0", "0", "1"])
    assert state.slots == (True, False, True, False) and state.entry_present and state.exit_open


def test_semantic_validation():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_slot_event(["9", "1"])
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_gate_event(["side", "1"])
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_state(["10", "2", "0", "0", "0"])


FAST = Settings(serial_port="mock://", ack_timeout=0.15, ack_retries=2, reconnect_min=0.1,
                reconnect_max=0.2, link_timeout=2.0, log_level="WARNING")


class Harness:
    def __init__(self, device: MockArduino) -> None:
        self.device = device
        self.events: list[protocol.Event] = []
        self.connects = 0
        self.manager = SerialManager(
            FAST, lambda: device, on_event=self.events.append,
            on_connect=self._connected)

    def _connected(self):
        self.connects += 1

    async def wait(self, predicate, timeout=3.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.02)
        raise AssertionError("timeout")


@pytest.fixture
async def harness(anyio_backend):
    h = Harness(MockArduino(heartbeat_s=0.2))
    await h.manager.start()
    await h.wait(lambda: h.manager.connected)
    yield h
    await h.manager.stop()


@pytest.mark.anyio
async def test_command_ack_and_events(harness):
    ack = await harness.manager.send_command("PING")
    assert ack.ok
    await harness.wait(lambda: any(e.name == "BOOT" for e in harness.events))
    harness.device.set_slot(2, True)
    await harness.wait(lambda: any(e.name == "SLOT" and e.args == ("2", "1") for e in harness.events))


@pytest.mark.anyio
async def test_nak_raises_rejected(harness):
    with pytest.raises(CommandRejected) as err:
        await harness.manager.send_command("OPEN", "garage")
    assert err.value.reason == "BAD_GATE"


@pytest.mark.anyio
async def test_lost_ack_is_retransmitted_but_executed_once(harness):
    harness.device.drop_acks = 1
    ack = await harness.manager.send_command("OPEN", "exit")
    assert ack.ok and ack.duplicate
    assert harness.device.open_count["exit"] == 1
    assert harness.manager.stats.command_retries == 1


@pytest.mark.anyio
async def test_silent_device_times_out_after_retries(harness):
    harness.device.drop_acks = 99
    with pytest.raises(CommandTimeout):
        await harness.manager.send_command("OPEN", "entry")
    assert harness.device.open_count["entry"] == 1  
    assert harness.manager.stats.command_timeouts == 1


@pytest.mark.anyio
async def test_events_after_boot_are_in_order_and_sequenced(harness):
    for i in (1, 2, 3):
        harness.device.set_slot(i, True)
    await harness.wait(lambda: sum(e.name == "SLOT" for e in harness.events) == 3)
    seqs = [e.seq for e in harness.events if e.name != "BOOT"]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


@pytest.mark.anyio
async def test_disconnect_fails_waiters_and_reconnects(harness):
    first_connects = harness.connects
    harness.device.drop_acks = 99
    pending = asyncio.create_task(harness.manager.send_command("OPEN", "exit", timeout=2.0))
    await asyncio.sleep(0.05)
    harness.device.unplug(0.5)
    with pytest.raises(SerialDisconnected):
        await pending
    await harness.wait(lambda: not harness.manager.connected)
    with pytest.raises(SerialDisconnected):
        await harness.manager.send_command("PING")
    harness.device.drop_acks = 0  
    await harness.wait(lambda: harness.manager.connected, timeout=5)
    assert harness.connects == first_connects + 1
    assert harness.device.boots == 2
    assert (await harness.manager.send_command("PING")).ok
