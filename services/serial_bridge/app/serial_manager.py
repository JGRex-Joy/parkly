from __future__ import annotations

import asyncio
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from app import protocol
from app.config import Settings
from app.logging_setup import get_logger
from app.transports import Transport

log = get_logger("serial")


class SerialDisconnected(Exception):
    pass


class CommandTimeout(Exception):
    pass


class CommandRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class LinkStats:
    connected: bool = False
    connects: int = 0
    disconnects: int = 0
    last_error: str = ""
    last_rx_age_s: Optional[float] = None
    frames_rx: int = 0
    bad_frames: int = 0
    commands_sent: int = 0
    command_retries: int = 0
    command_timeouts: int = 0
    command_rejects: int = 0
    duplicate_acks: int = 0
    unmatched_acks: int = 0
    events_rx: int = 0
    stale_flushes: int = 0
    bad_frames_unlogged: int = 0


class SerialManager:
    def __init__(
        self,
        settings: Settings,
        transport_factory: Callable[[], Transport],
        on_event: Callable[[protocol.Event], None],
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_resync: Optional[Callable[[], None]] = None,
    ) -> None:
        self._s = settings
        self._factory = transport_factory
        self._on_event = on_event
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_resync = on_resync
        # ALL serial writes go through this one dedicated thread: commands keep their order, and a slow
        # write (blocked USB, write_timeout) can neither starve nor be starved by the default executor
        # that httpx / DNS / websockets also use.
        self._tx = ThreadPoolExecutor(max_workers=1, thread_name_prefix="serial-tx")
        self._flushed_seen = 0
        self._bad_logged_at = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._transport: Optional[Transport] = None
        self._link_broken = threading.Event()
        self._connected = False
        self._last_rx = 0.0
        self._seq = random.randrange(1, 65536)   # see _run(): never restart at 1
        self._seq_lock = threading.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self.stats = LinkStats()

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run, name="serial-reader", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            await asyncio.get_running_loop().run_in_executor(None, thread.join, 5.0)
        self._fail_pending(SerialDisconnected("shutting down"))
        self._tx.shutdown(wait=False, cancel_futures=True)

    def snapshot(self) -> dict:
        data = {k: v for k, v in self.stats.__dict__.items()}
        data["connected"] = self._connected
        if self._connected:
            data["last_rx_age_s"] = round(time.monotonic() - self._last_rx, 2)
        return data

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq = self._seq % 65535 + 1
            return self._seq

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            transport = self._transport
            if transport is None or not self._connected:
                raise SerialDisconnected("not connected")
            try:
                transport.write(data)
            except Exception as exc:
                self._link_broken.set()
                self.stats.last_error = str(exc)
                raise SerialDisconnected(str(exc)) from exc

    async def send_command(
        self,
        name: str,
        *args: object,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ) -> protocol.Ack:
        if not self._connected:
            raise SerialDisconnected("not connected")
        loop = asyncio.get_running_loop()
        timeout = self._s.ack_timeout if timeout is None else timeout
        retries = self._s.ack_retries if retries is None else retries
        seq = self._next_seq()
        frame = protocol.encode_command(seq, name, *args)
        future: asyncio.Future = loop.create_future()
        self._pending[seq] = future
        try:
            for attempt in range(retries + 1):
                if attempt:
                    self.stats.command_retries += 1
                    log.warning("command retransmit", extra={"cmd": name, "seq": seq, "attempt": attempt})
                await loop.run_in_executor(self._tx, self._write, frame)
                if attempt == 0:
                    self.stats.commands_sent += 1
                try:
                    ack = await asyncio.wait_for(asyncio.shield(future), timeout)
                except asyncio.TimeoutError:
                    continue
                if ack.duplicate:
                    self.stats.duplicate_acks += 1
                if not ack.ok:
                    self.stats.command_rejects += 1
                    raise CommandRejected(ack.detail)
                return ack
            self.stats.command_timeouts += 1
            raise CommandTimeout(f"{name} seq={seq}: no ACK after {retries + 1} attempts")
        finally:
            self._pending.pop(seq, None)

    def _run(self) -> None:
        backoff = self._s.reconnect_min
        while not self._stop.is_set():
            transport = self._factory()
            try:
                transport.open()
            except Exception as exc:
                self.stats.last_error = str(exc)
                log.warning("serial open failed", extra={"error": str(exc), "retry_in_s": backoff})
                transport.close()
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, self._s.reconnect_max)
                continue

            backoff = self._s.reconnect_min
            # New connection => new sequence space. The Arduino remembers its last 4 command seqs to
            # recognise retransmits; if the board was NOT reset by the re-open and we restarted at 1,
            # our first commands collided with remembered ones. (Firmware 1.1 also compares the frame
            # checksum, this makes a collision practically impossible even with older firmware.)
            with self._seq_lock:
                self._seq = random.randrange(1, 65536)
            self._flushed_seen = getattr(transport, "flushed", 0)
            self._transport = transport
            self._link_broken.clear()
            self._last_rx = time.monotonic()
            self._connected = True
            self.stats.connected = True
            self.stats.connects += 1
            log.info("serial connected", extra={"connects": self.stats.connects})
            self._call_soon(self._on_connect)
            try:
                self._read_loop(transport)
            except Exception as exc:
                self.stats.last_error = str(exc)
                log.warning("serial link lost", extra={"error": str(exc)})
            finally:
                with self._write_lock:
                    self._connected = False
                    self._transport = None
                self.stats.connected = False
                self.stats.disconnects += 1
                transport.close()
                self._fail_pending(SerialDisconnected("link lost"))
                self._call_soon(self._on_disconnect)
        log.info("serial reader stopped")

    def _read_loop(self, transport: Transport) -> None:
        while not self._stop.is_set() and not self._link_broken.is_set():
            line = transport.readline()
            now = time.monotonic()

            flushed = getattr(transport, "flushed", 0)
            if flushed != self._flushed_seen:
                # The transport dropped a stale backlog. Events in it are lost, so ask for a full STATE.
                self._flushed_seen = flushed
                self.stats.stale_flushes += 1
                self._call_soon(self._on_resync)

            if not line:
                limit = self._s.link_timeout
                if limit and now - self._last_rx > limit:
                    raise TimeoutError(f"no data from device for {limit:.0f}s")
                continue
            self._last_rx = now
            try:
                message = protocol.parse_message(line)
            except Exception as exc:
                # A malformed line (noise, baud mismatch, half frame after a reset) must NEVER take the
                # reader down: count it, log it (rate limited), carry on with the next line.
                self._note_bad_frame(exc, line, now)
                continue
            self.stats.frames_rx += 1
            self._call_soon(self._dispatch, message)

    def _note_bad_frame(self, exc: Exception, line: bytes, now: float) -> None:
        self.stats.bad_frames += 1
        self.stats.bad_frames_unlogged += 1
        if now - self._bad_logged_at >= self._s.bad_frame_log_interval:
            log.warning("bad frame from device", extra={
                "error": str(exc), "raw": repr(bytes(line[:80])),
                "also_since_last_log": self.stats.bad_frames_unlogged - 1})
            self._bad_logged_at = now
            self.stats.bad_frames_unlogged = 0

    def _call_soon(self, fn: Optional[Callable], *args) -> None:
        if fn is None or self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass  

    def _dispatch(self, message) -> None:  
        if isinstance(message, protocol.Ack):
            future = self._pending.get(message.seq)
            if future is None or future.done():
                if message.seq != 0 or message.ok:
                    self.stats.unmatched_acks += 1
                else:
                    log.warning("device rejected a frame", extra={"reason": message.detail})
                return
            future.set_result(message)
        else:
            self.stats.events_rx += 1
            try:
                self._on_event(message)
            except Exception:
                log.exception("event handler failed", extra={"evt": message.name})

    def _fail_pending(self, exc: Exception) -> None:
        def _fail() -> None:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(exc)

        self._call_soon(_fail)
