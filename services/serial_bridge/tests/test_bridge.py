import asyncio, time
import pytest
from app import protocol
from app.commands import BarrierCommands
from app.config import Settings
from app.event_router import EventRouter
from app.mock_arduino import MockArduino
from app.serial_manager import SerialManager
from app.state import BridgeState
from app.transports import TransportError

FAST = dict(serial_port="mock://", slot_settle_s=0.05, slot_min_interval_s=0.2, slot_reconcile_interval=0.5,
            reconnect_min=0.05, reconnect_max=0.1, ack_timeout=0.2, link_timeout=2.0)


class FakeSerial:
    def __init__(self): self.sent = []
    async def send_command(self, name, *a, **k):
        self.sent.append((name,) + a)
        class A: detail = ""
        return A()


class FakeBackend:
    def __init__(self, delay=0.0): self.posts = []; self.delay = delay
    async def list_slots(self): await asyncio.sleep(self.delay); return []
    async def slot_id(self, n): return int(n[1:])
    async def staff_holds_slot(self, _): return False
    async def post_sensor(self, slot_id, occupied, cid=None):
        await asyncio.sleep(self.delay); self.posts.append((slot_id, occupied, time.monotonic()))
        class R: status_code = 200; text = ""
        return R()


def make_router(backend=None, serial=None, **kw):
    s = Settings(**{**FAST, **kw}); st = BridgeState(); serial = serial or FakeSerial()
    cmds = BarrierCommands(s, serial, st)
    r = EventRouter(s, serial, backend or FakeBackend(), None, cmds, st); r.start()
    return r, st, serial, cmds


def evt(seq, name, *a): return protocol.Event(seq, name, tuple(a))


def run(coro): return asyncio.run(coro)


# ---- slot de-duplication / rate limiting ------------------------------------------------------------
def test_flap_that_returns_is_never_sent():
    async def t():
        be = FakeBackend(); r, st, *_ = make_router(be)
        st.slot_forwarded[1] = False                     # backend state known from bring-up
        r._want_slot(1, True); await asyncio.sleep(0.01); r._want_slot(1, False)
        await asyncio.sleep(0.4); await r.stop()
        assert be.posts == [] and st.counters.slot_coalesced == 1
    run(t())


def test_repeated_same_state_posts_once():
    async def t():
        be = FakeBackend(); r, st, *_ = make_router(be)
        st.slot_forwarded[1] = False
        for _ in range(5): r._want_slot(1, True); await asyncio.sleep(0.01)
        await asyncio.sleep(0.4)
        for _ in range(3): r._want_slot(1, True)       # backend already has it
        await asyncio.sleep(0.1); await r.stop()
        assert [p[:2] for p in be.posts] == [(1, True)]
        assert st.counters.slot_dup_suppressed == 3
    run(t())


def test_rate_limit_and_latest_wins():
    async def t():
        be = FakeBackend(); r, st, *_ = make_router(be, slot_min_interval_s=0.5)
        st.slot_forwarded[1] = False
        r._want_slot(1, True); await asyncio.sleep(0.2)
        r._want_slot(1, False); await asyncio.sleep(0.1); r._want_slot(1, True)   # flaps right after 1st POST
        r._want_slot(1, False)
        await asyncio.sleep(1.2); await r.stop()
        assert [p[1] for p in be.posts] == [True, False]
        assert be.posts[1][2] - be.posts[0][2] >= 0.45
    run(t())


def test_slow_backend_for_one_slot_does_not_block_others():
    async def t():
        class Slow(FakeBackend):
            async def post_sensor(self, slot_id, occupied, cid=None):
                if slot_id == 1: await asyncio.sleep(1.0)
                return await super().post_sensor(slot_id, occupied, cid)
        be = Slow(); r, *_ = make_router(be)
        t0 = time.monotonic(); r._want_slot(1, True); r._want_slot(2, True)
        await asyncio.sleep(0.4)
        assert [p[0] for p in be.posts] == [2]          # old single worker: slot 2 waited behind slot 1
        await r.stop()
    run(t())


# ---- the defects found in the audit ---------------------------------------------------------------
def test_bringup_does_not_block_event_dispatch():
    async def t():
        r, st, *_ = make_router(FakeBackend(delay=1.0))
        handled = []
        orig = r._handle
        async def spy(e): handled.append((e.name, time.monotonic())); await orig(e)
        r._handle = spy
        t0 = time.monotonic(); r.on_event(evt(1, "BOOT", "1.1.0")); r.on_event(evt(2, "SLOT", "1", "1"))
        await asyncio.sleep(0.2)
        assert [n for n, _ in handled] == ["BOOT", "SLOT"] and handled[1][1] - t0 < 0.3   # was 3 s
        await r.stop()
    run(t())


def test_events_after_reconnect_without_boot_are_not_dropped():
    async def t():
        r, st, *_ = make_router()
        for i in range(1, 6): r.on_event(evt(i, "HB", "10", "0000", "0", "0", "0", "0"))
        r.on_link_up()                                   # new session, BOOT frame was flushed
        r.on_event(evt(1, "SLOT", "1", "1")); r.on_event(evt(2, "SLOT", "2", "1"))
        assert st.counters.events_duplicate == 0
        await r.stop()
    run(t())


def test_same_plate_reopen_after_physical_close_is_executed():
    async def t():
        s = Settings(**FAST); st = BridgeState(); ser = FakeSerial(); c = BarrierCommands(s, ser, st)
        assert (await c.open("entry", plate="A1")).status == "opened"
        assert (await c.open("entry", plate="A1")).status == "duplicate_suppressed"   # barrier still open
        c.on_barrier_closed("entry")
        assert (await c.open("entry", plate="A1")).status == "opened"
        assert (await c.open("entry", request_id="auth-9")).status == "opened"
        c.on_barrier_closed("entry")                                                  # explicit ids survive
        assert (await c.open("entry", request_id="auth-9")).status == "duplicate_suppressed"
        assert len(ser.sent) == 3
    run(t())


def test_reopen_after_unexpected_reset_inside_hold_window():
    async def t():
        r, st, ser, cmds = make_router()
        await cmds.open("entry", plate="A1", hold_ms=5000)
        r.on_link_up(); await asyncio.sleep(0.05)
        r._link_up_at -= 60                                         # long-running link
        r.on_event(evt(1, "BOOT", "1.1.0")); await asyncio.sleep(0.3)
        assert st.counters.unexpected_resets == 1 and st.counters.open_reasserted == 1
        opens = [c for c in ser.sent if c[0] == "OPEN"]
        assert len(opens) == 2 and 3000 < opens[1][2] <= 5000
        await r.stop()
    run(t())


# ---- serial layer ----------------------------------------------------------------------------------
class Harness:
    def __init__(self, transport):
        self.events = []; self.connects = 0
        self.s = Settings(**FAST)
        self.m = SerialManager(self.s, lambda: transport, self.events.append,
                               on_connect=lambda: setattr(self, "connects", self.connects + 1))


def test_malformed_lines_never_kill_reader_and_commands_use_newline_frames():
    async def t():
        dev = MockArduino(heartbeat_s=0.2); h = Harness(dev); await h.m.start()
        await asyncio.sleep(0.3)
        for junk in (b"\xff\xfe\x00garbage\n", b"$EVT,1*00\n", b"$\n", b"$EVT,x,y*ZZ\n", b"\n"):
            dev._out.put(junk)
        await asyncio.sleep(0.3)
        ack = await h.m.send_command("PING")
        assert ack.ok and h.m.stats.bad_frames >= 4 and h.m.connected
        frame = protocol.encode_command(5, "OPEN", "entry", 8000)
        assert frame.endswith(b"\n") and frame.count(b"\n") == 1
        await h.m.stop()
    run(t())


def test_reconnect_after_unplug_and_new_seq_space():
    async def t():
        dev = MockArduino(heartbeat_s=0.2); h = Harness(dev); await h.m.start()
        await asyncio.sleep(0.3); seq_before = h.m._seq
        dev.unplug(0.4); await asyncio.sleep(0.2)
        assert not h.m.connected
        await asyncio.sleep(1.2)
        assert h.m.connected and h.connects >= 2 and h.m.stats.disconnects >= 1
        assert (await h.m.send_command("PING")).ok
        await h.m.stop()
    run(t())


def test_device_never_confuses_new_command_with_old_seq():
    dev = MockArduino(); dev.open()
    for seq in (1, 2, 3, 4): dev.write(protocol.encode_command(seq, "PING"))
    dev.write(protocol.encode_command(2, "OPEN", "entry", 8000))
    assert dev.open_count["entry"] == 1
    dev.write(protocol.encode_command(2, "OPEN", "entry", 8000))      # true retransmit
    assert dev.open_count["entry"] == 1


def test_slow_http_does_not_stop_serial_reading():
    async def t():
        dev = MockArduino(heartbeat_s=0.1); h = Harness(dev)
        be = FakeBackend(delay=2.0); r, st, *_ = make_router(be)
        m = SerialManager(Settings(**FAST), lambda: dev, r.on_event, on_connect=r.on_link_up)
        await m.start(); await asyncio.sleep(0.3)
        dev.set_slot(1, True)
        await asyncio.sleep(1.0)       # backend still "answering" (2 s) but frames keep arriving
        rx0 = m.stats.frames_rx; await asyncio.sleep(0.6)
        assert m.stats.frames_rx > rx0 + 3
        await m.stop(); await r.stop()
    run(t())
