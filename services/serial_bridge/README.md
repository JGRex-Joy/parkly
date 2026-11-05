# pyserial_bridge

> v0.1.0 / firmware 1.1.0: median filter, hysteresis, per-slot rate-limited publishing, reset-safe gate commands. **Read `docs/AUDIT.md` first.**

The only process that opens the Arduino serial port. It turns hardware events into calls to the
**existing** OCR service and backend, and turns the backend's access decisions into barrier commands.
It contains no parking, pricing or payment logic. See `docs/` for details:

* `docs/INTEGRATION_PLAN.md` - endpoints reused, findings in existing code
* `docs/HARDWARE.md` - confirmed pin map + what to verify in Tinkercad / on the board
* `docs/PROTOCOL.md` - serial protocol
* `docs/TEST_PLAN.md` - automated, mock, Tinkercad and hardware tests

```
app/main.py           service start-up, local HTTP API, health/status, simulation API
app/serial_manager.py single reader thread, locked writes, ACK/retry, reconnect
app/protocol.py       frame encode/decode/validation (pure)
app/event_router.py   gate state machine -> OCR; slot events -> backend; reconciliation
app/backend_ws.py     backend "barrier_open" -> OPEN command
app/commands.py       idempotent barrier commands
app/clients.py        HTTP clients for existing services
app/mock_arduino.py   software Arduino for mock mode
app/transports.py     real pyserial transport
app/config.py         BRIDGE_* environment variables
arduino/smart_parking/smart_parking.ino   firmware
```

## Setup (Windows/Linux, all services on one PC)
1. **Firmware:** open `arduino/smart_parking/smart_parking.ino` in the Arduino IDE (board *Arduino Uno*), upload.
   Verify the pin assumptions in `docs/HARDWARE.md` first. Close the IDE's Serial Monitor afterwards.
2. **Bridge:**
   ```bash
   cd pyserial_bridge
   python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Start everything** (three terminals; ports are an assumption - the OCR service needs a port different from the backend's 8000):
   ```bash
   cd backend      && uvicorn app.main:app --host 0.0.0.0 --port 8000    # PARKING_BASE_URL=http://<pc-ip>:8000 for QR links
   cd ocr_service  && uvicorn app.main:app --host 127.0.0.1 --port 8001
   cd pyserial_bridge && BRIDGE_SERIAL_PORT=COM3 uvicorn app.main:app --host 127.0.0.1 --port 8100
   ```
   (Windows cmd: `set BRIDGE_SERIAL_PORT=COM3` first. Run the bridge with a single worker.)
4. Check: `curl localhost:8100/status?deep=true`.

**No hardware?** `BRIDGE_SERIAL_PORT=mock://` starts a simulated Arduino and the `/sim/*` endpoints
(see `docs/TEST_PLAN.md` section B). It is the same code path as with hardware.

## Environment variables
| Variable | Default | Meaning |
|---|---|---|
| `BRIDGE_SERIAL_PORT` | `auto` | `COM3`, `/dev/ttyACM0`, `auto` (find an Arduino) or `mock://` |
| `BRIDGE_SERIAL_BAUD` | `115200` | must match firmware |
| `BRIDGE_SERIAL_BOOT_DELAY` | `2.0` | seconds to wait after opening (Uno resets) |
| `BRIDGE_RECONNECT_MIN` / `_MAX` | `1` / `10` | reconnect backoff (s) |
| `BRIDGE_LINK_TIMEOUT` | `8` | seconds without any byte before the link is declared dead (0 = off) |
| `BRIDGE_ACK_TIMEOUT` / `_RETRIES` | `0.6` / `3` | command acknowledgement |
| `BRIDGE_BACKEND_URL` | `http://localhost:8000` | existing backend |
| `BRIDGE_OCR_URL` | `http://localhost:8001` | existing OCR service |
| `BRIDGE_HTTP_TIMEOUT` | `5` | backend calls (s) |
| `BRIDGE_OCR_TIMEOUT` | `30` | one OCR trigger (capture+OCR+forward) |
| `BRIDGE_OCR_MAX_ATTEMPTS` / `_RETRY_DELAY` | `3` / `2.0` | re-read attempts while the vehicle waits |
| `BRIDGE_SLOT_MAP` | `1:P1,2:P2,3:P3,4:P4` | device slot index -> backend `slot_number` |
| `BRIDGE_SLOT_VACANT_POLICY` | `skip_staff` | `forward`, `skip_staff`, `ignore` (see integration plan, finding 1) |
| `BRIDGE_SLOT_RETRY_ATTEMPTS` | `5` | per update, with backoff |
| `BRIDGE_SLOT_RECONCILE_INTERVAL` | `10` | s between repair attempts of an undelivered slot update |
| `BRIDGE_SLOT_UNMATCHED_MAX` | `30` | stop re-sending an occupancy the backend keeps rejecting |
| `BRIDGE_OPEN_HOLD_MS` | `8000` | minimum open time sent with `OPEN` |
| `BRIDGE_OPEN_DEADLINE` | `10` | give up opening after this many s (waits for reconnect meanwhile) |
| `BRIDGE_OPEN_DEDUPE_SECONDS` | `15` | repeat of the same gate+plate / request_id is suppressed |
| `BRIDGE_SLOT_SETTLE_S` / `_SLOT_MIN_INTERVAL_S` | `0.3` / `1.0` | a slot value must be stable this long before POST / max one POST per slot per interval |
| `BRIDGE_RX_BACKLOG_MAX` | `1024` | bytes waiting in the OS buffer before stale input is flushed (then auto-SYNC) |
| `BRIDGE_BAD_FRAME_LOG_INTERVAL` | `1.0` | max one malformed-frame log line per interval |
| `BRIDGE_UNEXPECTED_BOOT_WINDOW_S` | `6.0` | BOOT later than this after link-up = board reset by itself (brown-out) |
| `BRIDGE_API_TOKEN` | empty | if set, `POST /v1/*` requires header `X-Bridge-Token` |
| `BRIDGE_DEVICE_CFG` | empty | pushed to the Arduino on every (re)connect, e.g. `slot_thr=20,hyst=6,debounce_free=8,dbg=1` |
| `BRIDGE_LOG_LEVEL` / `_FORMAT` | `INFO` / `json` | `json` or `text` |
| `BRIDGE_MOCK_HOLD_MS` / `_CLEAR_MS` / `_HEARTBEAT_S` | `3000` / `300` / `1.0` | mock device only |

## HTTP API (bind to 127.0.0.1)
`GET /health` (liveness) - `GET /ready` (503 while the Arduino link is down) - `GET /status[?deep=true]` -
`GET /v1/slots` - `POST /v1/barrier/{entry|exit}/open` `{plate_number?, request_id?, hold_ms?}` -
`POST /v1/barrier/{gate}/close` - `POST /v1/device/sync` - `POST /v1/gates/{gate}/retrigger`.
Mock only: `POST /sim/slot/{1-4}?occupied=`, `/sim/gate/{gate}?present=`, `/sim/unplug?seconds=`, `/sim/drop-acks?count=`, `GET /sim/device`.
Anyone who can reach `/v1/barrier/*/open` can lift a barrier: keep the bind on localhost and set `BRIDGE_API_TOKEN`.

## Tests
```bash
pip install -r requirements.txt
python -m pytest tests -q      # 22 tests; firmware tests need g++ (skipped without)
```
