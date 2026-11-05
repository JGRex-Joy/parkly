from __future__ import annotations

import time
from typing import Protocol

from app.logging_setup import get_logger

log = get_logger("transport")

_ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403}

# A line longer than this can only be garbage (protocol.MAX_FRAME_LEN is 96).
_LINE_LIMIT = 512


class TransportError(Exception):
    pass


class Transport(Protocol):
    # Incremented every time the transport had to throw away unread input (see readline()).
    flushed: int

    def open(self) -> None: ...
    def close(self) -> None: ...
    def readline(self) -> bytes:
        """One line (including b'\\n'), or b'' after the read timeout. Raises on a dead port."""

    def write(self, data: bytes) -> None: ...


def resolve_port(port: str) -> str:
    if port.lower() != "auto":
        return port
    from serial.tools import list_ports

    candidates = list(list_ports.comports())
    for info in candidates:
        if info.vid in _ARDUINO_VIDS:
            return info.device
    if len(candidates) == 1:
        return candidates[0].device
    raise TransportError(
        "BRIDGE_SERIAL_PORT=auto found no Arduino; set BRIDGE_SERIAL_PORT explicitly "
        f"(visible ports: {[c.device for c in candidates]})"
    )


class PySerialTransport:
    """Blocking pyserial wrapper. Only ever used from the SerialManager threads (one reader thread,
    one TX thread) - never from the asyncio loop - so a slow/stuck port cannot freeze the event loop."""

    def __init__(self, port: str, baud: int, boot_delay: float = 2.0, backlog_max: int = 1024) -> None:
        self._port = port
        self._baud = baud
        self._boot_delay = boot_delay
        self._backlog_max = backlog_max
        self._ser = None
        self._buf = bytearray()
        self._discarding = False      # True = skipping the rest of an oversized line
        self.flushed = 0

    def open(self) -> None:
        import serial

        device = resolve_port(self._port)       # 'auto' is re-resolved on EVERY reconnect (COM number may change)
        try:
            self._ser = serial.Serial(device, self._baud, timeout=0.25, write_timeout=1.0)
        except (serial.SerialException, OSError, ValueError) as exc:
            raise TransportError(str(exc)) from exc
        # Opening the port toggles DTR, which resets an Uno: wait out the bootloader, THEN drop whatever
        # accumulated (bootloader noise, half a frame, stale lines from a previous session).
        time.sleep(self._boot_delay)
        self._reset_buffers()
        self._buf.clear()
        self._discarding = False

    def _reset_buffers(self) -> None:
        ser = self._ser
        if ser is None:
            return
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception as exc:                       # a dead port surfaces on the next read/write
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def readline(self) -> bytes:
        ser = self._ser
        if ser is None:
            raise TransportError("port closed")
        try:
            while True:
                nl = self._buf.find(b"\n")
                if nl >= 0:
                    line = bytes(self._buf[: nl + 1])
                    del self._buf[: nl + 1]
                    if self._discarding:            # that was only the tail of an oversized line
                        self._discarding = False
                        continue
                    return line

                waiting = ser.in_waiting
                if waiting > self._backlog_max:
                    # The reader fell far behind (e.g. the process was suspended). Stale events are worse
                    # than none: every one of them describes the past. Drop them all; the manager asks the
                    # device for a fresh STATE afterwards, and STATE/HB carry the complete picture.
                    ser.reset_input_buffer()
                    self._buf.clear()
                    self._discarding = False
                    self.flushed += 1
                    log.warning("stale serial input flushed", extra={"bytes": waiting})
                    return b""

                chunk = ser.read(max(1, waiting))
                if not chunk:
                    return b""                      # read timeout: lets the caller check stop/link flags
                self._buf.extend(chunk)
                if len(self._buf) > _LINE_LIMIT and b"\n" not in self._buf:
                    self._buf.clear()               # garbage without a terminator: resync on the next '\n'
                    self._discarding = True
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(str(exc)) from exc

    def write(self, data: bytes) -> None:
        ser = self._ser
        if ser is None:
            raise TransportError("port closed")
        try:
            ser.write(data)      # frames are already '\n'-terminated by protocol.encode()
            ser.flush()
        except Exception as exc:
            raise TransportError(str(exc)) from exc
