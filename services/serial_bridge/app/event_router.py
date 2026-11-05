from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from typing import Optional

import httpx

from app import protocol
from app.clients import FORWARDED, RETRYABLE, BackendClient, OcrClient
from app.commands import BarrierCommands
from app.config import Settings
from app.logging_setup import get_logger
from app.serial_manager import CommandRejected, CommandTimeout, SerialDisconnected, SerialManager
from app.state import BridgeState

log = get_logger("router")


class EventRouter:
    def __init__(
        self,
        settings: Settings,
        serial: SerialManager,
        backend: BackendClient,
        ocr: OcrClient,
        commands: BarrierCommands,
        state: BridgeState,
    ) -> None:
        self._s = settings
        self._serial = serial
        self._backend = backend
        self._ocr = ocr
        self._commands = commands
        self.state = state

        self._slot_names = dict(settings.slot_map)       
        self._events: "asyncio.Queue[protocol.Event]" = asyncio.Queue()
        self._seen: "OrderedDict[tuple[int, int], None]" = OrderedDict()
        self._tasks: set[asyncio.Task] = set()
        self._closing = False

        # --- slot publishing: ONE sender task per slot (see _slot_worker) ---------------------------
        # desired[i]  = latest debounced occupancy the device reported (what the backend SHOULD hold)
        # state.slot_forwarded[i] = what the backend is known to hold
        # A sender only ever transmits `desired` when it differs from `forwarded`.
        self._desired: dict[int, bool] = {}
        self._slot_wake = {i: asyncio.Event() for i in self._slot_names}
        self._slot_busy: set[int] = set()
        self._slot_last_post: dict[int, float] = {}
        self._slot_failed_at: dict[int, float] = {}
        self._slot_unmatched: dict[int, int] = {}

        # one report queue + worker per gate: a slow/failing report for one gate can't delay the other
        self._report_qs: "dict[str, asyncio.Queue]" = {g: asyncio.Queue() for g in protocol.GATES}

        self._bringup_lock = asyncio.Lock()
        self._brought_up_epoch = -1
        self._link_up_at: Optional[float] = None

    def start(self) -> None:
        self._spawn(self._dispatch_loop())
        for index in self._slot_names:
            self._spawn(self._slot_worker(index))
        for gate in protocol.GATES:
            self._spawn(self._report_worker(gate))

    async def stop(self) -> None:
        self._closing = True
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def on_link_up(self) -> None:
        # A (re)connected port is a new device session whether or not we manage to see its BOOT frame
        # (the transport flushes input after the boot delay, so BOOT is usually gone). The device's event
        # counter restarts at 1: without this, every new event looked like an old (epoch, seq) pair and
        # was dropped as a "duplicate" until the counter passed its previous value (minutes of deafness).
        self.state.epoch += 1
        self._seen.clear()
        self._link_up_at = time.monotonic()
        self._spawn(self.bring_up("link_up"))

    def on_resync(self) -> None:
        """The transport discarded stale input; ask the device for a fresh complete STATE."""
        self._spawn(self._resync())

    async def _resync(self) -> None:
        try:
            await self._serial.send_command("SYNC")
            log.info("resync requested after stale input flush")
        except (SerialDisconnected, CommandTimeout, CommandRejected) as exc:
            log.warning("resync failed", extra={"error": str(exc)})

    def on_link_down(self) -> None:
        self.state.note("link_down")

    def on_event(self, event: protocol.Event) -> None:
        self.state.last_device_message = time.time()
        if event.name == "BOOT":
            self.state.epoch += 1
            self._seen.clear()
        key = (self.state.epoch, event.seq)
        if key in self._seen:
            self.state.counters.events_duplicate += 1
            log.info("duplicate device event dropped", extra={"evt": event.name, "seq": event.seq})
            return
        self._seen[key] = None
        while len(self._seen) > 256:
            self._seen.popitem(last=False)
        self._events.put_nowait(event)

    async def _dispatch_loop(self) -> None:
        while True:
            event = await self._events.get()
            try:
                await self._handle(event)
            except asyncio.CancelledError:
                raise
            except (protocol.ProtocolError, ValueError) as exc:
                self.state.counters.events_invalid += 1
                log.warning("invalid device event", extra={"evt": event.name, "error": str(exc)})
            except Exception:
                log.exception("event handling failed", extra={"evt": event.name})

    async def _handle(self, event: protocol.Event) -> None:
        name = event.name
        if name == "BOOT":
            self.state.device_firmware = event.args[0] if event.args else ""
            log.info("device booted", extra={"firmware": self.state.device_firmware,
                                             "epoch": self.state.epoch})
            self.state.note("boot", firmware=self.state.device_firmware)
            since_up = None if self._link_up_at is None else time.monotonic() - self._link_up_at
            if since_up is not None and since_up > self._s.unexpected_boot_window_s:
                self.state.counters.unexpected_resets += 1
                log.error("Arduino RESET while the USB link was up - suspect servo/5V supply brown-out "
                          "(see docs/HARDWARE.md, power)", extra={"since_link_up_s": round(since_up, 1)})
                self.state.note("unexpected_reset", since_link_up_s=round(since_up, 1))
            # bring-up talks to the backend and the device (seconds when the backend is slow). It must NOT
            # run inside the dispatch loop, or GATE/SLOT events queue up behind it.
            self._spawn(self._after_boot())
        elif name == "GATE":
            gate, present = protocol.parse_gate_event(event.args)
            log.info("gate event", extra={"gate": gate, "present": present, "seq": event.seq})
            self._on_gate(gate, present)
        elif name == "SLOT":
            index, occupied = protocol.parse_slot_event(event.args, len(self._slot_names))
            log.info("slot event", extra={"slot": index, "occupied": occupied, "seq": event.seq})
            self._want_slot(index, occupied)
        elif name == "STATE":
            self._on_state(protocol.parse_state(event.args))
        elif name == "HB":
            if not event.args:
                raise protocol.ProtocolError("empty HB")
            self._on_state(protocol.parse_state(event.args[1:]))
        elif name == "DIST":
            if len(event.args) != 3:
                raise protocol.ProtocolError("bad DIST event")
            median_cm, raw_cm = (int(event.args[1]), int(event.args[2]))   # ValueError -> handled below
            self.state.dist[event.args[0]] = {"median_cm": median_cm, "raw_cm": raw_cm,
                                              "age_s_at": round(time.time(), 1)}
        elif name == "BARRIER":
            if len(event.args) == 2 and event.args[0] in protocol.GATES:
                gate, barrier = event.args
                self.state.gates[gate].barrier = barrier
                log.info("barrier moved", extra={"gate": gate, "state": barrier})
                self.state.note("barrier", gate=gate, state=barrier)
                if barrier == "CLOSED":
                    self._commands.on_barrier_closed(gate)
                self._report_barrier(gate, barrier)
        else:
            log.warning("unknown device event", extra={"evt": name})

    async def _after_boot(self) -> None:
        try:
            await self.bring_up("boot")
            await self._commands.reassert_open()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("post-boot handling failed")

    async def bring_up(self, reason: str) -> None:
        async with self._bringup_lock:
            if self._brought_up_epoch == self.state.epoch:
                return   # this device session is already configured (epoch changes on link-up and BOOT)
            epoch = self.state.epoch
            await self._load_backend_slot_state()
            try:
                for key, value in self._s.device_cfg:
                    await self._serial.send_command("CFG", key, value)
                await self._serial.send_command("SYNC")
            except CommandRejected as exc:
                log.error("device rejected configuration", extra={"reason": exc.reason})
            except (SerialDisconnected, CommandTimeout) as exc:
                log.warning("bring-up incomplete", extra={"reason": reason, "error": str(exc)})
                return
            self._brought_up_epoch = epoch
            log.info("device synchronised", extra={"reason": reason})

    async def _load_backend_slot_state(self) -> None:
        try:
            slots = await self._backend.list_slots()
        except httpx.HTTPError as exc:
            log.warning("backend slot state unavailable", extra={"error": str(exc)})
            return
        occupied = {s["slot_number"]: s["status"] == "PARKED" for s in slots}
        for index, number in self._slot_names.items():
            if number in occupied:
                self.state.slot_forwarded[index] = occupied[number]

    def _on_state(self, device: protocol.DeviceState) -> None:
        self.state.device = device
        now = time.monotonic()
        if self._brought_up_epoch != self.state.epoch and not self._bringup_lock.locked():
            self._spawn(self.bring_up("device_alive"))   # an earlier bring-up timed out; try again
        for gate in protocol.GATES:
            present = device.present(gate)
            if present != self.state.gates[gate].present:
                log.info("gate state repaired from device report", extra={"gate": gate, "present": present})
                self._on_gate(gate, present)
        for position, occupied in enumerate(device.slots):
            index = position + 1
            if index not in self._slot_names:
                continue
            known = self.state.slot_forwarded.get(index)
            if known is None and not occupied:
                self.state.slot_forwarded[index] = False
            elif known != occupied:
                if now - self._slot_failed_at.get(index, 0.0) < self._s.slot_reconcile_interval:
                    continue
                if self._slot_unmatched.get(index, 0) >= self._s.slot_unmatched_max:
                    continue
                self._want_slot(index, occupied)

    def _on_gate(self, gate: str, present: bool) -> None:
        g = self.state.gates[gate]
        if g.present == present:
            return
        g.present = present
        if not present:
            self._report_cleared(gate)
            if g.phase == "DONE":
                g.phase = "IDLE"
            return
        g.generation += 1
        self.state.counters.gate_triggers += 1
        if g.phase == "IDLE":
            self._start_flow(gate)
        else:
            self.state.counters.gate_triggers_suppressed += 1
            log.info("gate trigger suppressed", extra={"gate": gate, "phase": g.phase})

    def _start_flow(self, gate: str) -> None:
        g = self.state.gates[gate]
        g.phase = "PROCESSING"
        g.attempts = 0
        self._spawn(self._gate_flow(gate, g.generation))

    def retrigger(self, gate: str) -> str:
        g = self.state.gates[gate]
        if g.phase == "PROCESSING":
            return "busy"
        if not g.present:
            return "no_vehicle"
        g.generation += 1
        self._start_flow(gate)
        return "started"

    async def _gate_flow(self, gate: str, generation: int) -> None:
        g = self.state.gates[gate]
        try:
            cid = f"{gate}-{uuid.uuid4().hex[:10]}"  
            g.last_cid = cid
            for attempt in range(1, self._s.ocr_max_attempts + 1):
                if not g.present or g.generation != generation:
                    break
                g.attempts = attempt
                self.state.counters.ocr_calls += 1
                outcome = await self._ocr.trigger(gate, cid)
                g.last_outcome = outcome.public()
                log.info("ocr outcome", extra={"gate": gate, "attempt": attempt, "cid": cid, **outcome.public()})
                self.state.note("ocr", gate=gate, attempt=attempt, result=outcome.kind,
                                detail=outcome.detail, plate=outcome.plate)
                if outcome.kind == FORWARDED:
                    self.state.counters.ocr_forwarded += 1
                    break
                if outcome.kind != RETRYABLE:
                    break
                if attempt < self._s.ocr_max_attempts:
                    await asyncio.sleep(self._s.ocr_retry_delay)
                else:
                    log.warning("ocr attempts exhausted; barrier stays closed", extra={"gate": gate})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("gate flow failed", extra={"gate": gate})
            g.last_outcome = {"kind": "error", "detail": str(exc), "plate": None}
        finally:
            if not self._closing:
                if g.present and g.generation != generation:
                    self._start_flow(gate)  
                else:
                    g.phase = "DONE" if g.present else "IDLE"

    # ------------------------------------------------------------------------------------------------
    # Slot publishing: event de-duplication, flap absorption, rate limiting
    #
    # The device already debounces (median + hysteresis, see firmware). This layer guarantees that the
    # backend only ever sees VERIFIED TRANSITIONS and that a slow backend cannot hold anything up:
    #
    #   * _want_slot() is O(1), never awaits, never does I/O - it just records the latest desired value
    #     (so the serial reader / event dispatcher are never held up by HTTP).
    #   * one sender task per slot: a slow request for slot 1 can no longer delay slot 2 (the previous
    #     single shared worker did, for up to 5 retries x 5 s).
    #   * a value is POSTed only after it stayed unchanged for `slot_settle_s` (flaps are absorbed) and
    #     only if it differs from what the backend already holds (no duplicate POSTs).
    #   * at most one POST per slot per `slot_min_interval_s`.
    #   * "latest wins": if the value changed while a request was retrying, the stale value is dropped.
    # ------------------------------------------------------------------------------------------------
    def _want_slot(self, index: int, occupied: bool) -> None:
        if index not in self._slot_wake:
            return
        changed = self._desired.get(index) != occupied
        self._desired[index] = occupied
        if self.state.slot_forwarded.get(index) == occupied:
            if index in self._slot_busy:
                self._slot_wake[index].set()          # reverts a pending flap -> sender will absorb it
            else:
                self.state.counters.slot_dup_suppressed += 1   # backend already has this: no HTTP at all
            return
        if changed or index not in self._slot_busy:
            self._slot_wake[index].set()

    async def _slot_worker(self, index: int) -> None:
        wake = self._slot_wake[index]
        while True:
            await wake.wait()
            self._slot_busy.add(index)
            try:
                # 1) settle: the value must stay unchanged for slot_settle_s (bounded, so continuous
                #    flapping cannot starve the slot forever)
                for _ in range(10):
                    wake.clear()
                    await asyncio.sleep(self._s.slot_settle_s)
                    if not wake.is_set():
                        break
                # 2) rate limit
                wait = self._slot_last_post.get(index, 0.0) + self._s.slot_min_interval_s - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                wake.clear()    # anything newer than this read sets it again; the value is read AFTER the clear
                occupied = self._desired.get(index)
                if occupied is None:
                    continue
                if self.state.slot_forwarded.get(index) == occupied:
                    self.state.counters.slot_coalesced += 1   # flapped and came back: nothing to tell
                    continue
                try:
                    await self._forward_with_retry(index, occupied)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("slot forwarding crashed", extra={"slot": index})
                self._slot_last_post[index] = time.monotonic()
            finally:
                self._slot_busy.discard(index)
                # a newer value may have arrived while we were sending
                latest = self._desired.get(index)
                if latest is not None and self.state.slot_forwarded.get(index) != latest and not wake.is_set():
                    if time.monotonic() - self._slot_failed_at.get(index, 0.0) >= self._s.slot_reconcile_interval \
                            and self._slot_unmatched.get(index, 0) < self._s.slot_unmatched_max:
                        wake.set()

    async def _forward_with_retry(self, index: int, occupied: bool) -> None:
        if self.state.slot_forwarded.get(index) == occupied:
            return
        delay = 0.5
        for attempt in range(1, self._s.slot_retry_attempts + 1):
            if self._desired.get(index) != occupied:
                return   # superseded while retrying: the sender loop will pick up the newest value
            try:
                result = await self._forward_once(index, occupied)
            except (httpx.HTTPError, LookupError) as exc:
                log.warning("slot forward failed", extra={"slot": index, "attempt": attempt, "error": str(exc)})
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)
                continue
            if result in ("ok", "skipped"):
                self.state.slot_forwarded[index] = occupied
                self._slot_failed_at.pop(index, None)
                self._slot_unmatched.pop(index, None)
                if result == "skipped":
                    self.state.counters.slot_skipped += 1
                else:
                    self.state.counters.slot_forwarded += 1
                self.state.note("slot", slot=index, occupied=occupied, result=result)
                return
            self.state.counters.slot_unmatched += 1
            self._slot_unmatched[index] = self._slot_unmatched.get(index, 0) + 1
            self._slot_failed_at[index] = time.monotonic()
            self.state.note("slot", slot=index, occupied=occupied, result="rejected")
            return
        self.state.counters.slot_failed += 1
        self._slot_failed_at[index] = time.monotonic()
        log.error("slot update not delivered; will retry on a later heartbeat", extra={"slot": index})

    async def _forward_once(self, index: int, occupied: bool) -> str:
        slot_id = await self._backend.slot_id(self._slot_names[index])
        if not occupied:
            policy = self._s.slot_vacant_policy
            if policy == "ignore":
                return "skipped"
            if policy == "skip_staff" and await self._backend.staff_holds_slot(slot_id):
                log.info("vacant event skipped for staff vehicle", extra={"slot": index})
                return "skipped"
        response = await self._backend.post_sensor(
            slot_id, occupied, cid=f"slot-{self._slot_names[index]}-{uuid.uuid4().hex[:8]}")
        code = response.status_code
        if code == 200:
            log.info("slot forwarded", extra={"slot": index, "occupied": occupied})
            return "ok"
        if code == 409 and occupied:
            return "ok"  
        if code >= 500:
            response.raise_for_status()
        log.warning("backend rejected slot update", extra={
            "slot": index, "occupied": occupied, "status": code, "body": response.text[:200]})
        return "rejected"

    def _report_barrier(self, gate: str, barrier: str) -> None:
        if barrier != "OPENED":
            return
        lo = self.state.gates[gate].last_open
        if lo and time.monotonic() - lo["opened_at"] <= self._s.clear_report_window:
            self._report_qs[gate].put_nowait(
                (f"opened-{lo['authorization_id']}", gate, "OPENED", lo["plate"], self.state.gates[gate].last_cid))

    def _report_cleared(self, gate: str) -> None:
        lo = self.state.gates[gate].last_open
        if not lo or lo["cleared_reported"] or not lo["saw_vehicle"]:
            return
        if time.monotonic() - lo["opened_at"] > self._s.clear_report_window:
            return
        lo["cleared_reported"] = True
        self._report_qs[gate].put_nowait(
            (f"cleared-{lo['authorization_id']}", gate, "VEHICLE_CLEARED", lo["plate"], self.state.gates[gate].last_cid))

    async def _report_worker(self, queue_gate: str) -> None:
        queue = self._report_qs[queue_gate]
        while True:
            event_id, gate, event, plate, cid = await queue.get()
            delay = 0.5
            for attempt in range(1, self._s.report_attempts + 1):
                try:
                    await self._backend.post_barrier_event(event_id, gate, event, plate, cid)
                except asyncio.CancelledError:
                    raise
                except Exception as exc: 
                    log.warning("barrier report not delivered", extra={
                        "report": event_id, "attempt": attempt, "error": exc.__class__.__name__})
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue
                self.state.counters.reports_sent += 1
                self.state.note("report", event=event, gate=gate, plate=plate)
                break
            else:
                self.state.counters.reports_failed += 1
                log.error("barrier report dropped after retries", extra={"report": event_id})
