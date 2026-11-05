from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Union

MAX_FRAME_LEN = 96 
_FORBIDDEN = set("$*,\r\n")

GATES = ("entry", "exit")


class ProtocolError(ValueError):
    pass


def checksum(payload: str) -> int:
    value = 0
    for byte in payload.encode("ascii"):
        value ^= byte
    return value


def encode(fields: Sequence[object]) -> bytes:
    parts = []
    for field in fields:
        text = str(field)
        if not text or not text.isascii() or any(c in _FORBIDDEN for c in text):
            raise ProtocolError(f"invalid field {text!r}")
        parts.append(text)
    payload = ",".join(parts)
    frame = f"${payload}*{checksum(payload):02X}\n"
    if len(frame) > MAX_FRAME_LEN:
        raise ProtocolError("frame too long")
    return frame.encode("ascii")


def decode(line: Union[bytes, str]) -> list[str]:
    try:
        text = line.decode("ascii") if isinstance(line, (bytes, bytearray)) else line
    except UnicodeDecodeError as exc:
        raise ProtocolError("non-ascii data") from exc
    text = text.rstrip("\r\n")
    if len(text) + 1 > MAX_FRAME_LEN:
        raise ProtocolError("frame too long")
    if not text.startswith("$"):
        raise ProtocolError("missing '$'")
    body, star, cs = text[1:].rpartition("*")
    if not star or len(cs) != 2:
        raise ProtocolError("missing checksum")
    try:
        expected = int(cs, 16)
    except ValueError as exc:
        raise ProtocolError("bad checksum field") from exc
    if checksum(body) != expected:
        raise ProtocolError("checksum mismatch")
    return body.split(",")


def encode_command(seq: int, name: str, *args: object) -> bytes:
    if not 1 <= seq <= 65535:
        raise ProtocolError("seq out of range")
    return encode(("CMD", seq, name, *args))


@dataclass(frozen=True)
class Ack:
    seq: int
    ok: bool
    detail: str = ""

    @property
    def duplicate(self) -> bool:
        return self.detail == "DUP"


@dataclass(frozen=True)
class Event:
    seq: int
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class DeviceState:
    slots: tuple[bool, ...]
    entry_present: bool
    exit_present: bool
    entry_open: bool
    exit_open: bool

    def present(self, gate: str) -> bool:
        return self.entry_present if gate == "entry" else self.exit_present


def _int(text: str, what: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise ProtocolError(f"bad {what}: {text!r}") from exc


def parse_message(line: Union[bytes, str]) -> Union[Ack, Event]:
    fields = decode(line)
    kind = fields[0]
    if kind in ("ACK", "NAK"):
        if len(fields) < 3:
            raise ProtocolError(f"short {kind}")
        seq = _int(fields[1], "seq")
        if kind == "NAK":
            return Ack(seq, False, fields[2])
        if fields[2] != "OK":
            raise ProtocolError(f"bad ACK status {fields[2]!r}")
        return Ack(seq, True, fields[3] if len(fields) > 3 else "")
    if kind == "EVT":
        if len(fields) < 3:
            raise ProtocolError("short EVT")
        return Event(_int(fields[1], "seq"), fields[2], tuple(fields[3:]))
    raise ProtocolError(f"unknown frame type {kind!r}")


def _flag(text: str) -> bool:
    if text not in ("0", "1"):
        raise ProtocolError(f"bad flag {text!r}")
    return text == "1"


def parse_state(args: Sequence[str]) -> DeviceState:
    if len(args) != 5:
        raise ProtocolError("bad state arity")
    return DeviceState(
        slots=tuple(_flag(c) for c in args[0]),
        entry_present=_flag(args[1]),
        exit_present=_flag(args[2]),
        entry_open=_flag(args[3]),
        exit_open=_flag(args[4]),
    )


def parse_gate_event(args: Sequence[str]) -> tuple[str, bool]:
    if len(args) != 2 or args[0] not in GATES:
        raise ProtocolError("bad GATE event")
    return args[0], _flag(args[1])


def parse_slot_event(args: Sequence[str], num_slots: int = 4) -> tuple[int, bool]:
    if len(args) != 2:
        raise ProtocolError("bad SLOT event")
    index = _int(args[0], "slot")
    if not 1 <= index <= num_slots:
        raise ProtocolError(f"slot {index} out of range")
    return index, _flag(args[1])
