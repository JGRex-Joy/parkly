# Smart Parking backend (demo build)

## Run (no .env, no keys, no auth)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000/docs. Tests: `pytest`.

* **Payments are mocked** (`app/services/mock_payment.py`): `POST /api/pay/{session_id}` (or the
  "Pay now" button on the QR page `/pay/{id}`) marks the bill paid immediately. No gateway, webhook or secret.
* **No authentication**: `X-Service-Token` / `X-Admin-Token` checks are removed; every endpoint,
  including `/api/admin/*` and `/api/hardware/*`, is open. CORS allows any origin. Demo only.
* **QR links** use the machine's LAN IP automatically (phones on the same Wi-Fi can open them).
  Set `BASE_URL` in `app/core/config.py` if detection picks the wrong interface.

## Настройки
Переменные окружения и `.env` не используются. Все настройки (порт, адрес для QR, валюта, БД, места)
лежат вверху файла `app/core/config.py` - правьте значения прямо там.
Если QR ведёт не на тот адрес, впишите `BASE_URL = "http://<ваш-IP>:8000"`.

## Parking rules: four shared spaces (P1-P4)
* No dedicated staff or customer spaces. Any vehicle may take any free space; the vehicle
  class (staff / customer) only affects authorisation, billing and reporting.
* Every vehicle uses exactly one unit of the same capacity from the moment it is admitted
  at the gate (reservation) until it leaves. Availability =
  `free active spaces - admitted-but-not-parked vehicles - vehicles still standing in retired spaces`.
* The space a vehicle occupies is the one its sensor reports (`POST /api/sim/sensor/{id}`);
  it is recorded in the session (`slot_id`) and exactly that space is released on exit.
* Staff leave via `POST /api/sim/exit` (space freed at once); customers free their space
  when the bill is paid (unchanged). Manual sensor release detaches only the session that
  holds that space.

## Migration (automatic, at startup, idempotent, non-destructive)
1. Adds `slots.is_active` and `parking_sessions.slot_released_at` if missing and backfills
   space ownership (finished sessions released; of several sessions linked to one space only the
   newest holds it).
2. Creates the unique index `uq_parking_sessions_active_slot` (one holder per space).
3. Makes P1-P4 the active spaces and deactivates every other space (legacy E1/E2) - rows are
   kept so history stays valid. Works from the original six-space DB and from the previous
   2 regular + 2 staff version.
4. Repairs spaces flagged occupied that no session holds.

Vehicles still in a retired space keep their session: they can exit/pay normally (which frees
the space), they count against capacity until then, and `sensor occupied=false` on the retired
space id clears them manually. Nothing depends on slot ids being sequential.

## Concurrency
Every write use case runs in one transaction under a single lock over the spaces
(`BEGIN IMMEDIATE` on SQLite, `SELECT ... FOR UPDATE` elsewhere); a compare-and-set on the
space and the partial unique index guard against double-booking at the database level.

## Dashboard WebSocket: `WS /ws/parking`
On connect: `INITIAL_STATE` (`slots[]`, `sessions[]` with phase ENTERING/PARKED/EXITING). The manager keeps this
active-session state in memory (rebuilt from the DB on startup), so late joiners can replay the scene.

| REST (`/api/v1`, `X-Service-Token` if configured) | Broadcast |
|---|---|
| `POST /entry {plate}` | `{"event":"ENTRY_OCR","plate"}` |
| `POST /slots/update {slot_id, occupied, plate}` | `SLOT_OCCUPIED {slot_id, plate}` / `SLOT_RELEASED {slot_id}` (only for an orphan slot with no session; see State locking) |
| `POST /exit {plate}` | `EXIT_OCR {slot_id, plate, duration "HH:MM:SS", fee}` (+ `PAYMENT_CONFIRMED` for free stays / staff) |
| `POST /payment/confirm {plate}` | `PAYMENT_CONFIRMED {plate}` (simulated payment mode only; real providers confirm via webhook, which broadcasts too) |
| `GET /sessions` | session history for the CRM |

The legacy `/api/sim/*`, hardware and webhook flows emit the same events from the service layer.

## Fix: 409 on re-entry
A plate whose previous visit is finished (`PAID`/`COMPLETED`) can enter again. Only unfinished sessions
(`ENTERED`, `PARKED`, `AWAITING_PAYMENT`, open `EMPLOYEE_PASS`) block entry. A `PAID` session whose barrier
confirmation never arrived is closed (`COMPLETED`, audit `exit_assumed_on_reentry`) when the plate enters again.


## Slot state locking (sensor jitter protection)

* While a session holds a slot (`slot_id` set, `slot_released_at IS NULL`, i.e. PARKED / AWAITING_PAYMENT / staff),
  sensor `FREE` readings are dropped: no DB change, no `SLOT_RELEASED` broadcast. The API answers
  `200` with `detail: "FREE ignored ..."`.
* Repeated sensor `OCCUPIED` readings for the already-locked slot are idempotent (no 409, no duplicate `SLOT_OCCUPIED`).
* The slot is released only by the formal exit workflow: `EXIT_OCR` -> `PAYMENT_CONFIRMED`
  (or staff departure / operator override).
* The dashboard `ConnectionManager` additionally refuses to apply/broadcast a `SLOT_RELEASED` for a slot that still has a plate.
