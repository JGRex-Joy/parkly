# OCR service (KG plates)

FastAPI service that reads plates of the form `DD LL DDD LLL` (e.g. `01KG111AAA`: region, country, serial, series),
takes frames from a phone camera and forwards trusted plates to the parking backend.
Run: `pip install -r requirements.txt && uvicorn app.main:app` (config: `.env.example`, all via environment variables).

## Layout
`app/main.py` entry · `config/` settings · `schemas/` API models · `models/` domain objects · `repositories/` backend HTTP,
EasyOCR model, fixture frames · `services/` recognition pipeline, gate rules, camera facade · `routers/` endpoints ·
`cameras/` camera sources · `utils/` · `scripts/` · `tests/`.

## API
Unchanged from 0.2.0: `POST /recognize`, `POST /gate-event/signal`, `POST /gate-event/with-photo`,
`GET /debug/camera-snapshot`, `GET /health` — same URLs, parameters, schemas, status codes and messages.
`tests/test_api_compat.py` compares the generated OpenAPI with a snapshot taken from the original code.
Only addition in values: `frame_source` is `"ip_camera"` for the IP source (USB still reports `"webcam"`).
`plate_number` stays without the country code (`01111AAA`); `formatted` stays `01 KG 111 AAA`.

## Cameras
Two independent sources, each with its own settings, bound to gates by `CAMERA_ENTRY_SOURCE` / `CAMERA_EXIT_SOURCE` (`usb`|`ip`).
- **IP (phone on the LAN):** `CAMERA_IP_URL` (e.g. Android IP Webcam `http://<ip>:8080/video`, or `rtsp://...`), open/read timeouts.
- **USB (phone seen as a camera):** `CAMERA_USB_INDEX` (number or `auto`), backend, resolution, FOURCC.
Find devices with `python scripts/find_cameras.py [--ip URL] [--save dir]`.

Each source runs a reader thread that keeps the stream drained (no stale buffered frames), reconnects with exponential backoff,
treats `*_STALL_TIMEOUT` seconds without frames as a dead stream, drops the cached frame on disconnect, and releases the device
from the same thread that reads it. A request gets a frame captured *after* it arrived. Shutdown stops all threads.
`CAMERA_FIXTURE_FALLBACK=true` (original behaviour) substitutes `fixtures/*.jpg` when a camera is down — disable it in production.

## Recognition pipeline
frame → plate candidates (gradient / bright / dark regions, polarity-independent) → normalisation (polarity, lighting,
scale) → **segmentation into exactly 10 slots** (dynamic programming over column ink; splits touching glyphs such as the
merged `AAA` in the sample; rejects lines with fewer or more than 10 characters) → per-slot reading by the existing EasyOCR
model with the alphabet restricted to the slot class (digit/letter) → format and country check. If no candidate segments,
the previous whole-line reading is used as fallback. `corrections_applied` counts characters the format constraint changed.
Slot confidence is the model's own confidence when it agrees with the constraint, and is discounted when the constraint overrode it.

## OCR quality assessment (does the model need fine-tuning?)
Synthetic benchmark, 180 images, fonts not used during development, same images for both pipelines:

| | old | new |
|---|---|---|
| exact plate | 69% | 81% |
| exact after trust gate | 69% | 78% |
| wrong plate accepted | 11% | 8% |

Better on full frames (63→93%, 47→73%) and clean crops (83→97%); **worse on heavily degraded crops (60→47%)**.
A small classifier trained from scratch on synthetic glyphs of other font families scored 66% exact vs 80% for EasyOCR on
unseen fonts (it confused `0→9` on a dotted zero it had never seen). Conclusion: do not retrain on synthetic data.
Fine-tune only if real frames from your phones, scored with `scripts/evaluate_ocr.py dataset ...`, show errors concentrated in
specific characters (the one weakness found is `G→C`). `OCR_MIN_SLOT_CONFIDENCE` trades coverage for fewer wrong accepts.
Caveat: all numbers are synthetic; nothing here was measured on real plates.

## Tests
`pytest -m "not ocr_model"` (no model needed) · `pytest` (also runs the tests that load EasyOCR; weights download on first run).
Not covered: real USB hardware (logic is tested with fake devices), real photographed plates.
