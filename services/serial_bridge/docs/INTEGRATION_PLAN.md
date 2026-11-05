# Integration plan and reused endpoints

## What was inspected
* **backend** (FastAPI + SQLAlchemy): `ParkingService`, `PaymentService`, routers, WebSocket display channels.
* **ocr_service** (FastAPI + EasyOCR): `/gate-event/signal`, backend client, camera module.

## Decision: no changes to either existing service
Both already expose what the hardware needs, so the bridge plugs into existing contracts:

| Need | Existing mechanism reused |
|---|---|
| Trigger OCR when a car reaches a gate | `POST {OCR}/gate-event/signal?gate=entry\|exit` (written for an Arduino signal; captures, reads the plate, forwards it to the backend) |
| Plate -> session / bill | OCR -> `POST {BACKEND}/api/sim/entry` / `/api/sim/exit` (unchanged) |
| Slot occupied / vacant | `POST {BACKEND}/api/sim/sensor/{slot_id}` `{"occupied": bool}`; slot ids from `GET /api/sim/slots` (P1..P4) |
| Authorisation to open a barrier | backend WebSocket `/ws/entry-display`, `/ws/exit-display`: `{"event":"barrier_open","gate":...,"plate_number":...}` - published **after commit** on entry admission, on `confirm_payment`, and on staff exit |
| Payment | untouched: QR page `/pay/{id}`, `POST /api/pay/{id}` |

```
Arduino --USB--> pyserial_bridge --POST /gate-event/signal--> OCR --/api/sim/entry|exit--> backend
                      |  ^                                                                    |
                      |  +---------- WS barrier_open (authorisation) --------------------------+
                      +--- POST /api/sim/sensor/{id} (slot changes) ---------------------------> backend
```
Access control stays in the backend: OCR never talks to the bridge, so recognition alone cannot open
a barrier. Exit opens only on the backend's `barrier_open`, which `PaymentService.confirm_payment`
emits after a successful payment. `POST /v1/barrier/{gate}/open` is an additional, token-protected way
for the backend to command hardware explicitly (same de-duplication).

## Findings in the existing code that you should know about
1. **Staff + "slot vacant" conflict.** `release_slot` (what a vacant sensor event calls) ends a staff
   visit (`exit_time` set); the later exit then returns 404 and the barrier never opens. The bridge's
   default `BRIDGE_SLOT_VACANT_POLICY=skip_staff` does not forward vacant events for a slot currently held by a
   staff session (the exit frees it, as the backend README intends). `forward` = always forward
   (staff exit breaks); `ignore` = never forward vacancy. A backend-side fix would be cleaner; none was made.
2. **Entry is not idempotent**: every `/api/sim/entry` creates a session. The bridge therefore triggers OCR
   once per vehicle (gate state machine, re-armed only when the sensor reports the vehicle gone) and
   retries only when nothing reached the backend (unreadable plate, camera/OCR/backend unreachable).
   A timeout is *not* retried automatically (outcome unknown); use `POST /v1/gates/{gate}/retrigger`.
3. `occupy_slot` needs a waiting session (admitted, not yet parked). A car that appears in a slot without
   being admitted gets 404; the bridge counts it (`slot_unmatched`), retries on heartbeats (every 10 s, max 30 times).
4. Customers' slots are freed by the backend at payment; a vacant event frees them earlier (billing still works,
   it uses `entry_time`).
5. `PARKING_BASE_URL` defaults to `10.46.227.79:8000` without `http://`, so QR/pay links lack a scheme. Unrelated
   to the bridge; set `PARKING_BASE_URL=http://<ip>:8000` for a scannable QR.
6. The OCR camera indexes (`entry`=3, `exit`=2) and the `fixtures/` fallback images are unchanged.
