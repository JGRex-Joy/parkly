# Parkly Smart Parking System: API and Protocol Specification

| Attribute | Value |
| :--- | :--- |
| Backend | `services/backend`, FastAPI, application version `0.3`, OpenAPI at `/docs` and `/openapi.json` |
| OCR service | `services/ocr_service`, FastAPI, version `0.4.0` (OpenAPI schema unchanged from the `0.2.0` snapshot) |
| Serial bridge | `services/serial_bridge`, FastAPI, version `0.1.0`, firmware `1.1.0` |
| Companion document | [`architecture.md`](architecture.md) (hardware, firmware, gateway) |

All routes, schemas and payload fields in this document are extracted from the service source code. Routes that do not exist in the code are not documented; Section 8 lists commonly expected interfaces that are not implemented.

## Table of Contents

1. [Software System Overview](#1-software-system-overview)
2. [Hardware Payload Specification (Serial Protocol)](#2-hardware-payload-specification-serial-protocol)
3. [Bridge Local HTTP API](#3-bridge-local-http-api)
4. [Backend REST API: Global Configuration and Conventions](#4-backend-rest-api-global-configuration-and-conventions)
5. [Backend REST API: Data Models](#5-backend-rest-api-data-models)
6. [Backend REST API: Endpoints by Resource](#6-backend-rest-api-endpoints-by-resource)
7. [Backend WebSocket Channels](#7-backend-websocket-channels)
8. [OCR Service API](#8-ocr-service-api)
9. [Interfaces Not Implemented](#9-interfaces-not-implemented)

---

## 1. Software System Overview

### 1.1 Components and default endpoints

| Component | Default address | Protocol | Role |
| :--- | :--- | :--- | :--- |
| Backend | `http://<host>:8000` | HTTP/1.1 REST, WebSocket | Parking rules, sessions, billing, mock payment, SQLite persistence, display channels |
| OCR service | `http://127.0.0.1:8001` | HTTP/1.1 REST | Camera capture, plate recognition, forwarding to the backend |
| Serial bridge | `http://127.0.0.1:8100` | HTTP/1.1 REST; serial port to the Arduino | Sole owner of the serial port; hardware I/O only |
| Arduino firmware | USB serial port | ASCII frames, 115200 8N1 | Sensors, LEDs, barriers |
| Display applications | Browser pages `/display/entry`, `/display/exit`; React Native app | WebSocket client | Entry and exit displays |

The ports 8001 and 8100 are the values used in the bridge documentation (`services/serial_bridge/README.md`); the OCR and bridge processes must be started on those ports to match the bridge defaults `BRIDGE_OCR_URL=http://localhost:8001`.

### 1.2 Interaction map

```
Arduino --(serial frames)--> Bridge --POST /gate-event/signal?gate=--> OCR --POST /api/sim/entry|exit--> Backend
   ^                           |  ^                                                                         |
   |                           |  +---------- WS /ws/entry-display, /ws/exit-display: barrier_open ---------+
   +----(CMD OPEN / CLOSE)-----+
                               +--POST /api/sim/sensor/{slot_id}, /api/hardware/*--------------------------> Backend
Display apps <--WS /ws/entry-display, /ws/exit-display--- Backend --WS /ws/parking--> dashboard clients
```

### 1.3 Access control principle

Recognition alone never opens a barrier. A barrier opens only when the backend publishes a `barrier_open` authorization (on entry admission, on successful payment, on staff exit, or on operator override) and the bridge converts it into an `OPEN` command. The additional bridge endpoint `POST /v1/barrier/{gate}/open` is a token-protected direct command path.

---

## 2. Hardware Payload Specification (Serial Protocol)

Source: `services/serial_bridge/docs/PROTOCOL.md`, `smart_parking.ino`, `services/serial_bridge/app/protocol.py`.

### 2.1 Frame format

```
$<field>,<field>,...*<CS>\n
```

| Element | Specification |
| :--- | :--- |
| Start | `$` |
| Fields | Comma-separated ASCII. Fields never contain `$ * , CR LF` |
| Checksum `CS` | XOR of every character between `$` and `*` (exclusive), two upper-case hexadecimal digits |
| Terminator | `\n` (`\r` is ignored) |
| Line settings | 115200 baud, 8N1 |
| Limits | Host-to-device line buffer 72 bytes; maximum frame 96 bytes |

Checksum helper (run from `services/serial_bridge`):

```bash
python -c "from app import protocol; print(protocol.encode(('CMD', 1, 'PING')))"
```

Frame types: `CMD` (host to device), `ACK` / `NAK` (device reply), `EVT` (device event).

### 2.2 Commands (host to device)

Grammar: `$CMD,<seq>,<NAME>[,args]*CS`. `seq` is an integer from 1 to 65535 chosen by the bridge.

| Command | Arguments | Behaviour | `ACK` detail | `NAK` reasons |
| :--- | :--- | :--- | :--- | :--- |
| `PING` | none | Liveness check | none | none |
| `SYNC` | none | `ACK`, then the device emits a full `STATE` event | none | none |
| `OPEN` | `<entry\|exit>[,<holdMs>]`; `holdMs` 500 to 60000, default `hold_ms` (8000) | Opens the barrier; auto-closes after the hold and after the gate sensor has been clear for `clear_ms` | `REFRESHED` when the barrier was already open (hold extended) | `BAD_ARGS`, `BAD_GATE`, `BAD_VALUE` |
| `CLOSE` | `<entry\|exit>` | Closes now | none | `BAD_ARGS`, `BAD_GATE`, `VEHICLE_PRESENT` (gate sensor reports a vehicle) |
| `CFG` | `<key>,<value>` | Sets a runtime parameter (keys in Section 2.5) | none | `BAD_ARGS`, `BAD_KEY`, `BAD_VALUE` |
| any other name | | | | `UNKNOWN_CMD` |

Examples (checksums computed with `protocol.encode`):

```
$CMD,1,PING*6B
$CMD,2,OPEN,entry,8000*10
$CMD,3,CLOSE,exit*03
$CMD,4,CFG,slot_thr,20*0B
$CMD,5,SYNC*78
```

### 2.3 Replies (device to host)

| Frame | Meaning |
| :--- | :--- |
| `$ACK,<seq>,OK*CS` | Command executed |
| `$ACK,<seq>,OK,<detail>*CS` | `detail` is `REFRESHED` or `DUP` |
| `$ACK,<seq>,OK,DUP*CS` | Byte-identical retransmission recognized (same `seq` and checksum); not executed again |
| `$NAK,<seq>,<REASON>*CS` | Command refused; `REASON` as in Section 2.2 |
| `$NAK,0,<REASON>*CS` | The frame itself was unusable: `CHECKSUM`, `BAD_FRAME`, `BAD_SEQ`, `TOO_LONG` |

Examples:

```
$ACK,1,OK*7C
$ACK,2,OK,DUP*12
$NAK,3,VEHICLE_PRESENT*3B
```

### 2.4 Events (device to host)

Grammar: `$EVT,<n>,<NAME>[,args]*CS`. `n` increments by 1 per event after boot and wraps from 65535 to 1.

| Event | Arguments | Emitted | Example |
| :--- | :--- | :--- | :--- |
| `BOOT` | `<firmware>` | At power-up or reset (opening the USB port resets an UNO) | `$EVT,1,BOOT,1.1.0*7C` |
| `STATE` | `<s1s2s3s4>,<entry>,<exit>,<entryOpen>,<exitOpen>` | After `BOOT` and after `SYNC` | `$EVT,2,STATE,0000,0,0,0,0*0E` |
| `HB` | `<uptimeS>,<s1s2s3s4>,<entry>,<exit>,<entryOpen>,<exitOpen>` | Every `hb_ms` (default 2000 ms) | `$EVT,6,HB,12,0100,1,0,0,0*78` |
| `SLOT` | `<1..4>,<0\|1>` | Debounced occupancy change of a slot | `$EVT,3,SLOT,1,1*70` |
| `GATE` | `<entry\|exit>,<0\|1>` | Debounced vehicle arrival (`1`) or departure (`0`) at a gate sensor | `$EVT,4,GATE,entry,1*21` |
| `BARRIER` | `<entry\|exit>,<OPENED\|CLOSED>` | Servo reached its end position | `$EVT,5,BARRIER,entry,OPENED*4E` |
| `DIST` | `<1..4\|entry\|exit>,<medianCm>,<rawCm>` | Only when `dbg=1`, about every fourth median per sensor; `65535` means no echo | none |

State vector fields: `s1s2s3s4` is four characters (`0` free, `1` occupied) for slots 1 to 4; `entry` and `exit` are gate sensor states (`1` vehicle present); `entryOpen` and `exitOpen` are the barrier open flags (`1` open requested or open).

### 2.5 Runtime configuration keys (`CFG`)

| Key | Default | Min | Max | Unit |
| :--- | ---: | ---: | ---: | :--- |
| `gate_thr` | 40 | 5 | 400 | cm |
| `slot_thr` | 25 | 5 | 400 | cm |
| `hyst` | 5 | 0 | 50 | cm |
| `debounce` | 3 | 1 | 20 | medians |
| `debounce_free` | 6 | 1 | 40 | medians |
| `median` | 5 | 1 | 5 | samples |
| `sample_ms` | 25 | 10 | 500 | ms |
| `hold_ms` | 8000 | 500 | 60000 | ms |
| `clear_ms` | 1500 | 0 | 60000 | ms |
| `open_deg` | 90 | 0 | 180 | degrees |
| `closed_deg` | 0 | 0 | 180 | degrees |
| `hb_ms` | 2000 | 500 | 60000 | ms |
| `dbg` | 0 | 0 | 1 | flag |

### 2.6 Reliability rules

| Rule | Specification |
| :--- | :--- |
| Corruption | A frame with a bad checksum is dropped; the device replies `NAK,0,CHECKSUM`. The bridge logs and counts bad frames |
| Command retry | No reply within `BRIDGE_ACK_TIMEOUT` (0.6 s) causes a resend with the same `seq`, up to `BRIDGE_ACK_RETRIES` (3) times |
| Device duplicate detection | The device remembers its last 4 `(seq, checksum)` pairs. A byte-identical repeat is answered `ACK,<seq>,OK,DUP` without execution |
| Sequence start | The bridge starts each connection at a random `seq` |
| Event de-duplication | The bridge drops `(epoch, n)` pairs it has already seen. The epoch increments on every link-up and on `BOOT` |
| Lost events | `STATE` and `HB` carry the complete state. The bridge compares them with its belief and repairs differences |
| Silent link | No byte for `BRIDGE_LINK_TIMEOUT` (8 s) is treated as a disconnect |
| Reconnect | Backoff 1 s doubling to 10 s; on reconnect the bridge runs bring-up (backend slot state, configured `CFG`, `SYNC`) |

### 2.7 Bridge-to-backend translation of device events

The bridge converts events into the following backend calls. These are ordinary REST calls documented in Section 6.

| Device event | Bridge action | Backend call |
| :--- | :--- | :--- |
| `SLOT,<n>,1` or `0` | After the value is stable for `BRIDGE_SLOT_SETTLE_S` (0.3 s), at most one request per slot per `BRIDGE_SLOT_MIN_INTERVAL_S` (1.0 s), only when it differs from the value the backend holds | `POST /api/sim/sensor/{slot_id}` with `{"occupied": <bool>}` |
| `GATE,<gate>,1` | Trigger OCR once per vehicle | `POST {OCR}/gate-event/signal?gate=<gate>` |
| `GATE,<gate>,0` | Report that the vehicle cleared the gate | `POST /api/hardware/barrier-events` with `{"event_id", "gate", "event": "VEHICLE_CLEARED", "plate_number"}` |
| `BARRIER,<gate>,OPENED` / `CLOSED` | Report barrier observation | `POST /api/hardware/barrier-events` with `event` `OPENED` or `CLOSED` |
| `ACK` to an authorized `OPEN` | Acknowledge the authorization | `POST /api/hardware/authorizations/{gate}/{session_id}/opened` |
| backend `barrier_open` message | Issue `OPEN` | Received on `WS /ws/entry-display` or `WS /ws/exit-display`; fallback `GET /api/hardware/authorizations?gate=` every 3.0 s |

---

## 3. Bridge Local HTTP API

Base URL: `http://127.0.0.1:8100` (bind to localhost). No version prefix on health endpoints; hardware commands use `/v1`.

**Authentication.** If `BRIDGE_API_TOKEN` is set, every `POST /v1/*` request requires the header `X-Bridge-Token: <token>`; otherwise the bridge returns `401 {"detail": "invalid or missing X-Bridge-Token"}`. When the variable is empty, no authentication is performed.

| Method | Path | Summary | Auth | Request | Success response | Error responses |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| GET | `/health` | Process liveness | none | none | `200 {"status": "ok", "uptime_s": 12.3}` | none |
| GET | `/ready` | Readiness; 503 while the Arduino link is down | none | none | `200 {"status": "ready"}` | `503 {"detail": "serial link down"}` |
| GET | `/status` | Full runtime status | none | Query `deep` (bool, default false): adds `backend_reachable` and `ocr_reachable` | `200` object with keys `serial`, `serial_port`, `mock`, `device`, `gates`, `distance_cm`, `slots_known_to_backend`, `backend_ws`, `counters`, `recent` (and, with `deep`, `backend_reachable`, `ocr_reachable`) | none |
| GET | `/v1/slots` | Slot occupancy as last reported by the Arduino | none | none | `200 [{"slot": "P1", "index": 1, "occupied": false}, ...]` | `503 {"detail": "no device report yet"}` |
| POST | `/v1/barrier/{gate}/open` | Open a barrier | `X-Bridge-Token` if configured | Path `gate` in `entry`, `exit`. Body below | `200 {"ok": true, "status": "...", "detail": "..."}` | `401` bad token; `422` invalid gate or body; `503` with `detail` object `{"ok", "status", "detail"}` when the open failed |
| POST | `/v1/barrier/{gate}/close` | Close a barrier now | `X-Bridge-Token` if configured | none | `200 {"ok": true, "status": "...", "detail": "..."}` | `401`; `409` with `detail` object (for example vehicle present) |
| POST | `/v1/device/sync` | Request a full device state report | `X-Bridge-Token` if configured | none | `200 {"status": "sync requested"}` | `401`; `503` serial disconnected; `504` command timeout or rejected |
| POST | `/v1/gates/{gate}/retrigger` | Run OCR again for the vehicle at a gate (operator action) | `X-Bridge-Token` if configured | none | `200 {"status": "started"}` | `401`; `409 {"detail": "busy"}` or `{"detail": "no_vehicle"}` |

`POST /v1/barrier/{gate}/open` request body:

| Field | Type | Required | Constraint | Description |
| :--- | :--- | :---: | :--- | :--- |
| `plate_number` | string | No | | Used for logging and de-duplication only |
| `request_id` | string | No | | Idempotency key; a repeated identifier opens the barrier only once |
| `hold_ms` | integer | No | 500 to 60000 | Open hold time; default `BRIDGE_OPEN_HOLD_MS` |

**Simulation endpoints.** Available only when `BRIDGE_SERIAL_PORT=mock://`; otherwise `404 {"detail": "simulation API exists only with BRIDGE_SERIAL_PORT=mock://"}`.

| Method | Path | Query | Response |
| :--- | :--- | :--- | :--- |
| POST | `/sim/slot/{index}` | `occupied` (bool, required); `index` 1 to 4, else `404 {"detail": "slot index 1..4"}` | `{"slot": 1, "occupied": true}` |
| POST | `/sim/gate/{gate}` | `present` (bool, required) | `{"gate": "entry", "present": true}` |
| POST | `/sim/unplug` | `seconds` (float, required) | `{"unplugged_for_s": 5.0}` |
| POST | `/sim/drop-acks` | `count` (int, required) | `{"dropping": 2}` |
| GET | `/sim/device` | none | Snapshot of the simulated device |

---

## 4. Backend REST API: Global Configuration and Conventions

### 4.1 Base URL and versioning

| Item | Value |
| :--- | :--- |
| Base URL | `http://<host>:8000` (the default port is `PORT = 8000` in `app/core/config.py`) |
| Versioning | There is no global version prefix. The route families are `/api/v1/*` (event-style interface), `/api/sim/*` (sensor and camera simulation interface used by the OCR service and the bridge), `/api/hardware/*`, `/api/admin/*`, `/api/pay/*`, `/api/system/*`, plus unversioned `/`, `/health`, `/pay/{id}`, `/display/{channel}` |
| Content type | Requests with a body: `Content-Type: application/json`. Responses: `application/json`, except HTML pages |
| Time format | ISO 8601 timestamps without a UTC offset (naive UTC, generated by `utcnow`) |
| Interactive documentation | `GET /docs` (Swagger UI), `GET /openapi.json` |

### 4.2 Headers

| Header | Direction | Description |
| :--- | :--- | :--- |
| `X-Correlation-ID` | Request (optional), response (always) | If the supplied value matches `^[A-Za-z0-9._:\-]{1,64}$` it is used; otherwise the server generates `srv-<12 hex>`. The value is returned in the response header and stored in audit events. CORS exposes this header |
| `Content-Type` | Request | `application/json` for bodies |

### 4.3 Authentication

The backend implements no authentication. There is no JWT, API key, or token check. Every endpoint, including `/api/admin/*` and `/api/hardware/*`, is open, and CORS allows every origin, method and header (`backend/README.md`: "Demo only"). The `401 Unauthorized` status is therefore never returned by the backend. The bridge (Section 3) is the only component with an optional token (`X-Bridge-Token`). The bridge and OCR service can send an `X-Service-Token` header to the backend when configured (`BRIDGE_SERVICE_TOKEN`, `BACKEND_SERVICE_TOKEN`); the backend ignores it.

### 4.4 Response envelopes

The backend does not wrap successful responses. A success response is the resource itself (JSON object, JSON array, or `null`).

**Domain errors** (raised as `ParkingError`) use a single-field envelope:

```json
{ "detail": "<human-readable message>" }
```

**Request validation errors** (FastAPI/Pydantic) use the framework envelope with status 422:

```json
{
  "detail": [
    { "type": "missing", "loc": ["body", "plate"], "msg": "Field required", "input": {} }
  ]
}
```

The message strings in domain errors are Russian literals in the source and are returned verbatim.

### 4.5 Status codes

| Code | Origin | Meaning |
| :---: | :--- | :--- |
| 200 | All successful requests | Success. No `201` or `204` is used |
| 400 | `ParkingError` base class default | Not raised by any documented route. Invalid input is reported as 422. (400 is used by the OCR service, Section 8) |
| 401 | Not emitted by the backend | See Section 4.3 |
| 403 | `ForbiddenError` | Defined, not used by documented routes |
| 404 | `NotFoundError` | Session, slot, bill, or vehicle not found |
| 409 | `ConflictError` and subclasses `NoFreeSpaceError`, `SlotOccupiedError`, `AmbiguousVehicleError`, `IllegalTransitionError` | State conflict (lot full, duplicate entry, slot already occupied, illegal session transition, payment not available) |
| 422 | `ValidationFailedError` and request validation | Invalid plate, invalid gate or event name, missing field, wrong type |
| 500 | Unhandled exception | Internal server error (framework default body `Internal Server Error`) |
| 503 | `ConfigurationError`; `GET /health` | No active tariff; database unavailable |

### 4.6 Session state machine

`app/services/state_machine.py` defines the permitted transitions of `SessionStatus`. An illegal transition raises `IllegalTransitionError` (HTTP 409, message `Недопустимый переход статуса сессии: <from> -> <to>`).

| From | Permitted targets |
| :--- | :--- |
| `ENTERED` | `PARKED`, `EXCEPTION` |
| `PARKED` | `AWAITING_PAYMENT`, `EXCEPTION` |
| `AWAITING_PAYMENT` | `PAID`, `EXCEPTION` |
| `PAID` | `COMPLETED`, `EXCEPTION` |
| `EXCEPTION` | `COMPLETED` |
| `COMPLETED` | none |
| `EMPLOYEE_PASS` | none |

---

## 5. Backend REST API: Data Models

### 5.1 Enumerations

| Enum | Values |
| :--- | :--- |
| `SessionStatus` | `ENTERED`, `PARKED`, `AWAITING_PAYMENT`, `PAID`, `EMPLOYEE_PASS`, `COMPLETED`, `EXCEPTION` |
| `SlotStatus` | `FREE`, `PARKED` |
| `SlotType` | `PAID`, `EMPLOYEE` |
| `PaymentStatus` | `PENDING`, `SUCCEEDED`, `FAILED`, `CANCELLED` |

### 5.2 `SessionOut`

| Field | Type | Nullable | Description |
| :--- | :--- | :---: | :--- |
| `id` | integer | No | Session identifier |
| `plate_number` | string | No | Normalized plate (separators removed, upper case) |
| `status` | `SessionStatus` | No | Current status |
| `entry_time` | datetime | No | Admission time |
| `parked_time` | datetime | Yes | Time the slot sensor reported the vehicle |
| `exit_time` | datetime | Yes | Time the exit camera read the plate |
| `paid_time` | datetime | Yes | Payment time |
| `duration_seconds` | integer | Yes | Billed duration |
| `amount_due` | number | Yes | Amount due |
| `slot_id` | integer | Yes | Occupied slot id |
| `slot_assignment` | string | Yes | Slot assignment method |
| `exit_authorized_at` | datetime | Yes | Time exit was authorized |
| `completed_time` | datetime | Yes | Completion time |
| `exception_reason` | string | Yes | Operator override reason |

Example:

```json
{
  "id": 7,
  "plate_number": "01KG111AAA",
  "status": "PARKED",
  "entry_time": "2026-11-06T09:14:02.511204",
  "parked_time": "2026-11-06T09:14:19.870031",
  "exit_time": null,
  "paid_time": null,
  "duration_seconds": null,
  "amount_due": null,
  "slot_id": 2,
  "slot_assignment": null,
  "exit_authorized_at": null,
  "completed_time": null,
  "exception_reason": null
}
```

### 5.3 `SlotOut` and `SlotReleaseOut`

`SlotOut`: `{"id": integer, "slot_number": string, "slot_type": SlotType, "status": SlotStatus}`.

`SlotReleaseOut`: `{"detail": string, "slot": SlotOut}`.

```json
{ "id": 2, "slot_number": "P2", "slot_type": "PAID", "status": "FREE" }
```

### 5.4 `PaymentStatusOut` and `PaymentResult`

| Model | Fields |
| :--- | :--- |
| `PaymentStatusOut` | `session_id` integer; `session_status` `SessionStatus`; `payment_status` string or null; `amount` number or null; `currency` string or null; `reference` string or null; `simulated` boolean (default false); `exit_authorized` boolean (default false) |
| `PaymentResult` | `session_id` integer; `status` `SessionStatus`; `amount_paid` number; `barrier_opened` boolean (default false); `exit_authorized` boolean (default true); `simulated` boolean (default false) |

### 5.5 Request models

| Model | Fields |
| :--- | :--- |
| `SimEntryRequest` | `plate_number` string, default `"01KG111AAA"` |
| `SimExitRequest` | `plate_number` string, default `"01KG111AAA"` |
| `SimSensorRequest` | `occupied` boolean, default `true`; `plate_number` string or null |
| `PlateIn` (v1) | `plate` string or null; `plate_number` string or null; at least one is required, else 422 (`plate (or plate_number) is required`) |
| `SlotUpdateIn` (v1) | `slot_id` integer (required); `occupied` boolean, default `true`; `plate` string or null; `plate_number` string or null |
| `PaymentConfirmIn` (v1) | `plate` string or null; `plate_number` string or null; `session_id` integer or null; `session_id` or a plate is required, else 422 |
| `BarrierEventIn` | `event_id` string (required); `gate` string (required); `event` string (required); `plate_number` string or null |
| `OverrideIn` | `reason` string (required) |

### 5.6 Tariff and billing

A tariff has `name`, `price_per_minute` and `free_minutes`. The amount is `max(ceil(duration_seconds / 60) - free_minutes, 0) * price_per_minute`, rounded to two decimals. The seeded default tariff is `price_per_minute` 5.0 and `free_minutes` 1. The currency is `KGS`. A zero amount settles automatically when `AUTO_SETTLE_FREE_STAYS` is true.

---

## 6. Backend REST API: Endpoints by Resource

Error responses use the envelope of Section 4.4. Unless stated, no request header is required beyond `Content-Type: application/json` for bodies. `X-Correlation-ID` is optional on every request.

### 6.1 System

#### `GET /`

| Item | Specification |
| :--- | :--- |
| Summary | Service liveness and entry points |
| Parameters / body | None |
| 200 | `{"service": "Parkly", "mode": "software-only (mock sensors via REST)", "docs": "/docs", "entry_display_ws": "/ws/entry-display", "exit_display_ws": "/ws/exit-display", "entry_display": "/display/entry", "exit_display": "/display/exit"}` |

#### `GET /health`

| Item | Specification |
| :--- | :--- |
| Summary | Liveness and database availability (`SELECT 1`) |
| Parameters / body | None |
| 200 | `{"status": "ok", "service": "backend", "database": "ok"}` |
| 503 | `{"detail": "database unavailable: <ExceptionClassName>"}` |

#### `GET /api/system/config`

| Item | Specification |
| :--- | :--- |
| Summary | Non-secret configuration |
| Parameters / body | None |
| 200 | `{"payment_mode": "mock", "payment_simulated": true, "currency": "KGS", "billing_start": "parked", "auth_ttl_seconds": 120, "ambiguous_slot_policy": "fifo", "base_url": "http://192.168.1.50:8000"}` (values reflect `app/core/config.py`; `base_url` is auto-detected from the LAN address unless `BASE_URL` is set) |

### 6.2 Parking events (v1)

#### `POST /api/v1/entry`

| Item | Specification |
| :--- | :--- |
| Summary | Entry camera read a plate (`ENTRY_OCR`). Creates a session, reserves capacity, authorizes the entry barrier |
| Request body | `PlateIn`: `{"plate": "01KG111AAA"}` (or `plate_number`) |
| 200 | `SessionOut`. Status `ENTERED`, or `EMPLOYEE_PASS` for a registered employee plate |
| 404 | not used |
| 409 | `{"detail": "Нет свободных платных мест"}` (customer) or `{"detail": "Нет свободных мест"}` (staff) when the lot is full; `{"detail": "Автомобиль с номером <plate> уже находится на парковке (сессия #<id>, статус <status>)"}` when an active session exists |
| 422 | Invalid plate (`Некорректный номер: ожидается 2-16 букв/цифр`) or missing field |
| 500 | Unhandled error |
| Side effects | Publishes `barrier_open` (gate `entry`) and `entry_display_update` on the entry channel; broadcasts `ENTRY_OCR` on the dashboard channel |

#### `POST /api/v1/exit`

| Item | Specification |
| :--- | :--- |
| Summary | Exit camera read a plate (`EXIT_OCR`). Issues a bill for a parked customer; completes a staff visit; re-shows an existing bill; re-authorizes a paid session |
| Request body | `PlateIn` |
| 200 | `SessionOut` (status `AWAITING_PAYMENT` after billing; `PAID` or staff statuses as applicable) |
| 404 | `{"detail": "Нет припаркованной (PARKED) сессии с таким номером"}` |
| 409 | `{"detail": "Автомобиль не занимал парковочное место: счёт не выставляется, выезд требует решения оператора"}` for a session that never parked |
| 422 | Invalid plate or missing field |
| 500 | Unhandled error |
| 503 | `{"detail": "Нет активного тарифа"}` when no active tariff exists |
| Side effects | Publishes `exit_bill` (QR and amount) on the exit channel; broadcasts `EXIT_OCR` |

#### `POST /api/v1/slots/update`

| Item | Specification |
| :--- | :--- |
| Summary | Slot sensor event. Occupied: binds a waiting vehicle to the slot (`SLOT_OCCUPIED`). Free: releases a slot only if no active session holds it (`SLOT_RELEASED`) |
| Request body | `SlotUpdateIn`: `{"slot_id": 2, "occupied": true, "plate": "01KG111AAA"}`; `plate` optional |
| 200 (occupied) | `SessionOut` |
| 200 (free) | `SlotReleaseOut`. `detail` is `"slot released"` or `"FREE ignored: slot locked by active session (exit only via EXIT_OCR)"` |
| 404 | `{"detail": "Слот не найден"}`, or no waiting session for an occupied report |
| 409 | `{"detail": "Слот уже занят"}`; ambiguous vehicle selection when `AMBIGUOUS_SLOT_POLICY` is `reject` |
| 422 | Missing `slot_id` or wrong type |
| 500 | Unhandled error |

#### `POST /api/v1/payment/confirm`

| Item | Specification |
| :--- | :--- |
| Summary | Confirm payment (`PAYMENT_CONFIRMED`; mock payment) |
| Request body | `PaymentConfirmIn`: `{"session_id": 7}` or `{"plate": "01KG111AAA"}` |
| 200 | `SessionOut` with status `PAID` |
| 404 | `{"detail": "No bill awaiting payment for this plate"}` (plate lookup); `{"detail": "Сессия не найдена"}` (unknown `session_id`) |
| 409 | `{"detail": "Сессия уже оплачена"}`; `{"detail": "Оплата недоступна: счёт ещё не выставлен выездной камерой"}`; `{"detail": "Нет открытого платёжного запроса для этой сессии"}` |
| 422 | Neither `session_id` nor a plate supplied |
| 500 | Unhandled error |
| Side effects | Publishes `barrier_open` (gate `exit`) and `exit_clear`; broadcasts `PAYMENT_CONFIRMED` |

#### `GET /api/v1/sessions`

| Item | Specification |
| :--- | :--- |
| Summary | Session history, newest first |
| Parameters / body | None |
| 200 | `[SessionOut, ...]` |
| 500 | Unhandled error |

### 6.3 Simulation interface (used by OCR service and bridge)

These routes implement the same use cases as Section 6.2 with a different request schema.

#### `POST /api/sim/entry`

| Item | Specification |
| :--- | :--- |
| Summary | Entry camera read a plate, or an employee presented a pass |
| Request body | `SimEntryRequest`: `{"plate_number": "01KG111AAA"}` |
| 200 | `SessionOut`, or `null` when the plate belongs to an employee (`EMPLOYEE_PASS`) |
| 409, 422, 500 | As `POST /api/v1/entry` |

#### `POST /api/sim/sensor/{slot_id}`

| Item | Specification |
| :--- | :--- |
| Summary | Slot sensor fired (vehicle parked or left) |
| Path parameter | `slot_id` integer, backend slot id (obtain from `GET /api/sim/slots`) |
| Request body | `SimSensorRequest`: `{"occupied": true, "plate_number": null}` |
| 200 | `SessionOut` (occupied) or `SlotReleaseOut` (free). Free detail: `"Слот освобождён"` or `"FREE проигнорирован: слот заблокирован активной сессией (выезд только через EXIT_OCR)"` |
| 404, 409, 422, 500 | As `POST /api/v1/slots/update` |

#### `POST /api/sim/exit`

| Item | Specification |
| :--- | :--- |
| Summary | Exit camera read a plate (bill and QR issued) |
| Request body | `SimExitRequest`: `{"plate_number": "01KG111AAA"}` |
| 200 | `SessionOut` |
| 404, 409, 422, 500, 503 | As `POST /api/v1/exit` |

#### `GET /api/sim/slots`

| Item | Specification |
| :--- | :--- |
| Summary | State of all slots (debug and bridge bring-up) |
| 200 | `[SlotOut, ...]` for `P1` to `P4` |
| 500 | Unhandled error |

#### `GET /api/sim/sessions`

| Item | Specification |
| :--- | :--- |
| Summary | All parking sessions (debug) |
| 200 | `[SessionOut, ...]` |
| 500 | Unhandled error |

### 6.4 Payment

#### `GET /pay/{session_id}`

| Item | Specification |
| :--- | :--- |
| Summary | HTML payment page opened by the QR code |
| Path parameter | `session_id` integer |
| 200 | `text/html` (template `pay.html`) |
| 404 | `{"detail": "Сессия не найдена"}` |

#### `GET /api/pay/{session_id}/status`

| Item | Specification |
| :--- | :--- |
| Summary | Payment status, polled by the payment page |
| Path parameter | `session_id` integer |
| 200 | `PaymentStatusOut` |
| 404 | `{"detail": "Сессия не найдена"}` |

```json
{
  "session_id": 7,
  "session_status": "AWAITING_PAYMENT",
  "payment_status": "PENDING",
  "amount": 15.0,
  "currency": "KGS",
  "reference": "<provider reference>",
  "simulated": true,
  "exit_authorized": false
}
```

#### `POST /api/pay/{session_id}`

| Item | Specification |
| :--- | :--- |
| Summary | Mock payment; succeeds immediately, no credentials required |
| Path parameter | `session_id` integer |
| Request body | None |
| 200 | `PaymentResult`: `{"session_id": 7, "status": "PAID", "amount_paid": 15.0, "barrier_opened": false, "exit_authorized": true, "simulated": true}` |
| 404 | `{"detail": "Сессия не найдена"}` |
| 409 | `{"detail": "Сессия уже оплачена"}`; `{"detail": "Оплата недоступна: счёт ещё не выставлен выездной камерой"}`; `{"detail": "Нет открытого платёжного запроса для этой сессии"}` |
| 500 | Unhandled error |

### 6.5 Hardware (bridge interface)

`gate` is `entry` or `exit`. An invalid value returns `422 {"detail": "gate must be one of ('entry', 'exit')"}`.

#### `GET /api/hardware/authorizations`

| Item | Specification |
| :--- | :--- |
| Summary | Barrier authorizations not yet acknowledged by the controller and still within `AUTH_TTL_SECONDS` (120 s) |
| Query parameter | `gate` (required) |
| 200 | List of authorizations |
| 422 | Missing or invalid `gate` |
| 500 | Unhandled error |

```json
[
  {
    "authorization_id": "entry-7",
    "gate": "entry",
    "session_id": 7,
    "plate_number": "01KG111AAA",
    "authorized_at": "2026-11-06T09:14:02.511204",
    "expires_at": "2026-11-06T09:16:02.511204"
  }
]
```

#### `POST /api/hardware/authorizations/{gate}/{session_id}/opened`

| Item | Specification |
| :--- | :--- |
| Summary | The controller acknowledged the `OPEN` command (command acknowledgement, not vehicle passage). Idempotent |
| Path parameters | `gate` (`entry` or `exit`), `session_id` integer |
| Request body | None |
| 200 | `{"session_id": 7, "gate": "entry", "acknowledged": true}` |
| 404 | `{"detail": "Сессия не найдена"}` |
| 409 | `{"detail": "Выезд для этой сессии не разрешён"}` (exit gate, exit not authorized) |
| 422 | Invalid `gate` |
| 500 | Unhandled error |

#### `POST /api/hardware/barrier-events`

| Item | Specification |
| :--- | :--- |
| Summary | Observation from sensors or the barrier. Idempotent by `event_id` |
| Request body | `BarrierEventIn` |
| `event` values | `OPENED`, `CLOSED`, `VEHICLE_CLEARED` |
| Behaviour | For gate `exit`, the event is matched to an unconfirmed exit session (by plate when supplied, otherwise only if exactly one candidate exists). `OPENED` records the open acknowledgement; `VEHICLE_CLEARED` completes the session (`COMPLETED`, or stays `EMPLOYEE_PASS` for staff) |

Request example:

```json
{ "event_id": "exit-3f2a9c01-cleared", "gate": "exit", "event": "VEHICLE_CLEARED", "plate_number": "01KG111AAA" }
```

| Status | Body |
| :---: | :--- |
| 200 (matched) | `{"duplicate": false, "matched": true, "session_id": 7, "status": "COMPLETED"}` |
| 200 (no match) | `{"duplicate": false, "matched": false}` |
| 200 (repeat) | `{"duplicate": true, "matched": false}` |
| 422 | `{"detail": "event must be one of ('OPENED', 'CLOSED', 'VEHICLE_CLEARED')"}`; `{"detail": "event_id is required"}`; invalid `gate`; missing field |
| 500 | Unhandled error |

### 6.6 Operator

#### `POST /api/admin/sessions/{session_id}/exit-override`

| Item | Specification |
| :--- | :--- |
| Summary | Manual exit authorization (unreadable plate, no payment, and similar). Audited. Cancels any pending payment, frees the slot, authorizes the exit barrier |
| Path parameter | `session_id` integer |
| Request body | `OverrideIn`: `{"reason": "plate unreadable"}`; `reason` must contain at least 3 characters after trimming |
| 200 | `SessionOut` with status `EXCEPTION` and `exception_reason` set |
| 404 | `{"detail": "Сессия не найдена"}` |
| 409 | `{"detail": "Сессия уже оплачена/завершена: ручное разрешение не требуется"}`; `{"detail": "Сотрудники выезжают по номеру: используйте выездную камеру"}`; `{"detail": "Недопустимое состояние сессии"}` |
| 422 | `{"detail": "Укажите причину ручного разрешения выезда"}` or missing field |
| 500 | Unhandled error |

#### `GET /api/admin/audit`

| Item | Specification |
| :--- | :--- |
| Summary | Audit event log |
| Query parameters | `session_id` integer, `correlation_id` string, `kind` string (all optional); `limit` integer, default 200, clamped to 1 to 1000 |
| 200 | List of events |
| 422 | Wrong parameter type |
| 500 | Unhandled error |

```json
[
  {
    "id": 41,
    "ts": "2026-11-06T09:14:02.600000",
    "kind": "entry_authorized",
    "correlation_id": "entry-3f2a9c01",
    "session_id": 7,
    "slot_id": null,
    "plate_number": "01KG111AAA",
    "detail": "{\"staff\": false}"
  }
]
```

`detail` is a JSON string or `null`. Audit `kind` values written by the source: `entry_authorized`, `entry_repeat_read`, `entry_expired`, `entry_rejected`, `slot_occupied`, `slot_vacated`, `slot_occupancy_rejected`, `exit_billed`, `exit_repeat_read`, `exit_authorized`, `exit_reauthorized`, `exit_assumed_on_reentry`, `exit_cleared_ambiguous`, `exit_rejected`, `payment_succeeded`, `payment_not_required`, `payment_rejected`, `payment_double_charge_suspected`, `barrier_command_acked`, `barrier_event`, `session_completed`, `operator_exit_override`.

---

### 6.7 Display pages

#### `GET /display/{channel}`

| Item | Specification |
| :--- | :--- |
| Summary | HTML display page for a gate (`display.html`) |
| Path parameter | `channel` in `entry`, `exit` |
| 200 | `text/html` |
| 422 | `channel` outside `entry`, `exit` |

`GET /static/*` serves static files from `app/static`.

---

## 7. Backend WebSocket Channels

Clients send no meaningful messages (the server reads and discards text frames to detect disconnection). All server messages are JSON objects with an `event` field.

### 7.1 `WS /ws/entry-display`

On connect the server sends one `entry_display_update` snapshot. Later messages are `entry_display_update` (after capacity changes) and `barrier_open` (gate `entry`).

```json
{
  "event": "entry_display_update",
  "free_paid_slots": 3,
  "free_employee_slots": 0,
  "total_paid_slots": 4,
  "total_employee_slots": 0,
  "free_slots": 3,
  "total_slots": 4,
  "tariff": { "name": "Стандартный (тест: считаем по минутам)", "price_per_minute": 5.0, "free_minutes": 1 }
}
```

`tariff` is `null` when no active tariff exists.

### 7.2 `WS /ws/exit-display`

On connect the server sends `exit_bill` if a session awaits payment, otherwise `exit_clear`. Later messages: `exit_bill`, `exit_clear`, `barrier_open` (gate `exit`).

```json
{
  "event": "exit_bill",
  "session_id": 7,
  "plate_number": "01KG111AAA",
  "duration": { "hours": 0, "minutes": 3, "seconds": 12 },
  "amount_due": 10.0,
  "pay_url": "http://192.168.1.50:8000/pay/7",
  "qr_code_base64": "<base64 PNG>",
  "status": "AWAITING_PAYMENT",
  "currency": "KGS",
  "payment_simulated": true
}
```

```json
{ "event": "exit_clear" }
```

### 7.3 `barrier_open` (both display channels)

```json
{
  "event": "barrier_open",
  "plate_number": "01KG111AAA",
  "gate": "entry",
  "session_id": 7,
  "authorization_id": "entry-7",
  "expires_in_s": 120
}
```

`session_id`, `authorization_id` and `expires_in_s` are present when a session is associated. The bridge executes only messages whose `gate` equals the channel. `authorization_id` is `<gate>-<session_id>` and serves as the idempotency key.

### 7.4 `WS /ws/parking` (dashboard)

On connect the server sends `INITIAL_STATE`; later messages are the parking events below.

```json
{
  "event": "INITIAL_STATE",
  "total_slots": 4,
  "free_slots": 3,
  "slots": [
    { "slot_id": 1, "status": "FREE", "plate": null },
    { "slot_id": 2, "status": "OCCUPIED", "plate": "01KG111AAA" }
  ],
  "sessions": [
    { "plate": "01KG111AAA", "phase": "PARKED", "slot_id": 2, "duration": null, "fee": null }
  ]
}
```

`phase` is `ENTERING`, `PARKED` or `EXITING`.

| Event | Fields | Trigger |
| :--- | :--- | :--- |
| `ENTRY_OCR` | `plate` | Entry admitted |
| `SLOT_OCCUPIED` | `slot_id`, `plate` | Vehicle bound to a slot |
| `EXIT_OCR` | `slot_id`, `plate`, `duration` (`HH:MM:SS`), `fee` | Bill issued (also on operator override) |
| `PAYMENT_CONFIRMED` | `plate` | Payment succeeded (also on override and free stays) |
| `SLOT_RELEASED` | `slot_id` | Orphan slot released; suppressed when the slot still has a plate |

---

## 8. OCR Service API

Base URL `http://127.0.0.1:8001`. No authentication. Source: `services/ocr_service/app/api.py`, `gate.py`, `schemas.py`. The routes, parameters, payloads and error messages are the public contract and are covered by `tests/test_api_contract.py` (OpenAPI snapshot `tests/fixtures/openapi_v0.2.0.json`).

| Method | Path | Summary | Request | 200 | Errors |
| :--- | :--- | :--- | :--- | :--- | :--- |
| GET | `/health` | Liveness | none | `{"status": "ok", "service": "ocr-service"}` | none |
| POST | `/recognize` | Recognize a plate in an uploaded image (no forwarding) | `multipart/form-data` field `file` (`image/jpeg`, `image/jpg` or `image/png`) | `RecognizeResponse` | `400` unsupported content type (`Ожидается изображение JPEG или PNG`), empty file (`Пустой файл`), or recognition `ValueError`; `422` missing field |
| POST | `/gate-event/signal` | Pure sensor signal: the service captures fresh frames from the camera bound to the gate, reads the plate, and forwards a trusted plate to the backend once | Query `gate` (`entry` or `exit`, required). No body. Optional header `X-Correlation-ID`, forwarded to the backend. Concurrent calls for the same gate share one in-flight task | `GateEventResponse` | `400` recognition `ValueError`; `422` invalid `gate`; `502` backend unreachable (`Backend недоступен: <error>`); `503` camera unavailable (`Камера недоступна: <detail>`) |
| POST | `/gate-event/with-photo` | Same processing for an already captured frame (single read, no burst) | Query `gate`; `multipart/form-data` field `file` (JPEG or PNG); optional `X-Correlation-ID` | `GateEventResponse` (`frame_source` is `"uploaded"`) | `400`, `422`, `502` |
| GET | `/debug/camera-snapshot` | Show what the gate camera sees (no recognition, no storage) | Query `gate` (required) | `CameraSnapshotResponse` | `422`, `503` |

`RecognizeResponse`:

| Field | Type |
| :--- | :--- |
| `plate_number` | string or null (without the country code, for example `01111AAA`) |
| `formatted` | string or null (for example `01 KG 111 AAA`) |
| `region_code` | string or null |
| `is_valid_region` | boolean (region code 01 to 11) |
| `corrections_applied` | integer |
| `confidence` | number |
| `plate_detection_method` | string (the localization method, or `fallback_full_frame`) |
| `plate_detection_score` | number |
| `raw_detections` | array of `{"text": string, "confidence": number}` |

`GateEventResponse`:

| Field | Type |
| :--- | :--- |
| `recognized` | `RecognizeResponse` |
| `forwarded_to_backend` | boolean |
| `backend_response` | object or null |
| `reject_reason` | string or null |
| `frame_source` | string: `webcam` (camera configured as a device index), `ip_camera` (camera configured as a stream URL), or `uploaded` |

`CameraSnapshotResponse`: `{"source": "webcam" | "ip_camera", "image_base64": "data:image/jpeg;base64,..."}`.

### 8.1 Burst processing of `POST /gate-event/signal`

| Parameter | Value | Location |
| :--- | :--- | :--- |
| Maximum frames per signal | 10 | `BURST_ATTEMPTS` |
| Interval between frames | 0.05 s | `BURST_INTERVAL` |
| Burst deadline | 4.0 s | `BURST_DEADLINE` |
| Single-frame acceptance | A read that passes the trust gate with `confidence` of at least 0.85 and no corrections | `CONFIDENT` |

Procedure: each frame is read in fast mode. A read that passes the trust gate is accepted immediately when it is confident and uncorrected; otherwise the same plate must be read on two frames. When the burst ends without agreement, the most frequent trusted plate is used; if none exists, one thorough read of the last frame is attempted; if that also fails, the best rejected read is returned with its `reject_reason`. A camera failure before any read raises `503`; a failure after at least one read ends the burst with the data collected so far.

### 8.2 Trust gate and rejection reasons

A plate is forwarded to the backend only when all of the following hold: a plate was recognized, the region code is in the range 01 to 11, and `corrections_applied` does not exceed `MAX_CORRECTIONS_TO_TRUST` (2). The recognized string must match `\d{2}KG\d{3}[A-Z]{3}`. A rejected plate returns `200` with `forwarded_to_backend: false` and one of the following `reject_reason` values (Russian literals in the source, returned verbatim):

| `reject_reason` | Condition |
| :--- | :--- |
| `Номер не распознан` | No plate recognized |
| `Код региона '<code>' вне диапазона 01-11` | Region code outside 01 to 11 |
| `Слишком много исправленных символов (<n>) - результату не доверяем` | More than 2 corrected characters |
| `Backend отклонил: <status> <body>` | The backend answered with an HTTP error status (for example 409 when the lot is full); returned with `200` |

A forwarded plate is posted as `{"plate_number": "<formatted>"}` to `/api/sim/entry` (gate `entry`) or `/api/sim/exit` (gate `exit`), with `X-Service-Token` when `BACKEND_SERVICE_TOKEN` is set and `X-Correlation-ID` when supplied. The bridge treats a reason starting with `Backend отклонил` as final and any other rejection as retryable.

---

## 9. Interfaces Not Implemented

The following interfaces are commonly expected in parking systems and are **not** present in the source. They are listed to prevent integration against non-existent routes.

| Expected interface | Status |
| :--- | :--- |
| `/api/v1/hardware/telemetry` | Not implemented. Device state is held by the bridge (`GET /status`, `GET /v1/slots`); only slot occupancy and barrier observations are forwarded to the backend |
| `/api/v1/slots` (resource collection) | Not implemented. Slot state is exposed by `GET /api/sim/slots`; slot events are submitted to `POST /api/v1/slots/update` |
| `/api/v1/gates` | Not implemented. Gate control is exposed by the bridge (`POST /v1/barrier/{gate}/open`, `close`) and by the `/api/hardware/*` routes |
| `/api/v1/reservations` | Not implemented. A reservation is implicit: capacity is reserved from admission at the gate until exit |
| JWT or API-key authentication | Not implemented in the backend |
| Binary serial payloads, MQTT, ESP-NOW, RS485 | Not used. The only device protocol is the ASCII serial protocol in Section 2 |
