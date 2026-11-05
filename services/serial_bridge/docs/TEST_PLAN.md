# Test plan

## A. Automated (no hardware) - `python -m pytest tests -q` (about 1 minute)
| Area | Tests |
|---|---|
| Protocol | round-trip, checksum, malformed/oversized/non-ASCII frames, field validation (`test_protocol_and_serial.py`) |
| Serial manager | ACK, NAK, lost ACK -> retransmit executed once, silent device -> timeout, event order/seq, unplug -> waiters fail -> reconnect + reboot (`test_protocol_and_serial.py`) |
| **Real firmware** on a PC shim | boot frames, checksum parity, debounce, noise rejection, hysteresis, LED, gate vs slot timing, DUP/NAK/TOO_LONG, non-blocking barrier, no close on a vehicle, CFG, SYNC (`test_firmware_host.py`) |
| Entry | single OCR + session per vehicle; sensor flapping suppressed; re-arm; OCR retry; unreadable plate keeps barrier closed; operator retrigger; full lot (backend 409) not retried |
| Slots | occupied/vacant forwarded; unmatched occupancy reported; repair after outage |
| Exit/payment | no open on OCR alone; pay-before-bill refused (409); unknown session (404); open only after successful payment; auto-close; unknown plate; staff flow with vacant event |
| Barrier safety | duplicate open suppressed; lost ACKs -> one physical open; open deferred across unplug; clean failure if link never returns |
| API | health/ready/status, deep status, token enforcement, bad gate 422 |

The integration tests start the **unmodified backend** as a subprocess, a scripted OCR stand-in (same
contract as the real one) and the bridge in mock mode.

## B. Manual - mock mode (`BRIDGE_SERIAL_PORT=mock://`, real backend and real OCR)
1. Start backend, OCR, bridge. `curl :8100/status?deep=true` -> serial connected, both websockets true.
2. `curl -X POST ":8100/sim/gate/entry?present=true"` -> OCR runs (fixture/webcam), session created, `/sim/device` shows `open_count.entry=1`.
3. `curl -X POST ":8100/sim/slot/1?occupied=true"` -> backend `/api/sim/slots` P1 PARKED.
4. `curl -X POST ":8100/sim/gate/exit?present=true"` -> bill; **barrier stays closed**; pay via QR page -> exit opens.
5. Failed payment: pay a non-billed/unknown session -> 409/404, barrier stays closed.
6. `curl -X POST ":8100/sim/unplug?seconds=5"` -> `/ready` 503, recovers, pending open executes once.
7. `curl -X POST ":8100/sim/drop-acks?count=2"` then open -> `command_retries` rises, `open_count` +1 only.

## C. Tinkercad (before touching the physical board)
1. Paste `smart_parking.ino`, start simulation, open the Serial Monitor at 115200.
2. Expect `$EVT,1,BOOT,1.0.0*7D` and `$EVT,2,STATE,0000,0,0,0,0*0E`.
3. Drag an object in front of each sensor (< 25 cm for slots, < 40 cm for gates): matching `SLOT`/`GATE` event, slot LED lights.
   This also **verifies the pin mapping**: entrance/exit, slot order, LED 2/LED 3 (see HARDWARE.md).
4. Type `$CMD,1,PING*<cs>` (checksum via `python -c "from app import protocol;print(protocol.encode(('CMD',1,'PING')))"`),
   then `OPEN,entry`: servo swings to 90 degrees, `BARRIER,entry,OPENED`; closes after hold with the sensor clear.
   Tinkercad's Serial Monitor cannot reach the PC bridge, so full-stack tests need the physical Uno.

## D. Physical hardware
1. Find the port (`python -m serial.tools.list_ports`), set `BRIDGE_SERIAL_PORT`, close the Arduino IDE serial monitor (only the bridge may own the port).
2. Walk through B with real sensors; measure and set `gate_thr`/`slot_thr` for your geometry.
3. Disconnect/reconnect the USB cable during a payment: barrier must open once after reconnect.
4. Kill the bridge (Ctrl+C): shutdown log shows `bridge stopped`; restart: slots are reconciled from the device.
5. Servo power: check the Uno does not brown-out when both servos move.
