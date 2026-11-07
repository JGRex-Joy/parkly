# OCR Service - Kyrgyz license plates (OpenCV + EasyOCR)

Reads `01KG111AAA`-style plates from a camera, validates them and forwards them to the parking backend.
**The HTTP API is unchanged**: same routes, parameters, payloads, error messages - the OpenAPI schema is byte-identical
to the pre-refactor snapshot (`tests/fixtures/openapi_v0.2.0.json`, enforced by a test).

## Run it

Python 3.10+ (developed and tested on 3.10).

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8001
```

The first start downloads the EasyOCR model (~100 MB, once). Startup takes ~10 s on a modest machine: the cameras open and the model
is loaded and warmed up **before** the service starts answering, so the first request of the demo is already fast.
Open `http://localhost:8001/docs` to try it.

### Configuration - 4 optional environment variables

| variable | default | meaning |
|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8000` | where plates are forwarded (`/api/sim/entry`, `/api/sim/exit`) |
| `BACKEND_SERVICE_TOKEN` | *(empty)* | sent as `X-Service-Token` when set |
| `ENTRY_CAMERA_SOURCE` | `2` | device index **or** stream URL (`rtsp://...`, `http://...`) |
| `EXIT_CAMERA_SOURCE` | `3` | same, for the exit camera |

Set them in the shell (PowerShell: `$env:ENTRY_CAMERA_SOURCE="0"`; bash: `export ENTRY_CAMERA_SOURCE=0`), or keep a
`.env` file (see `.env.example`) and start with `uvicorn app.main:app --env-file .env`. There is no custom `.env` parser any more.
Everything else (burst length, thresholds, timeouts) is a named constant at the top of the module that uses it.

Not sure which index is which phone? `python scripts/find_cameras.py` saves a snapshot per device (stop the service first).

## Endpoints (unchanged)

| | |
|---|---|
| `POST /recognize` | image in, plate out, nothing forwarded |
| `POST /gate-event/signal?gate=entry\|exit` | sensor pulse: the service grabs fresh frames itself, reads the plate, forwards it **once** |
| `POST /gate-event/with-photo?gate=entry\|exit` | same, with an uploaded frame |
| `GET /debug/camera-snapshot?gate=entry\|exit` | what the camera sees right now |
| `GET /health` | liveness |

## What was wrong, and what changed

I measured the original on synthetic 1280x720 scenes (Inter-style plate growing from 150 px to 460 px wide, tilt,
perspective, noise) and on the real `tests/fixtures/num.png`.

**Why it needed many attempts**

1. **Slow, spiky OCR.** Up to 3 EasyOCR passes *per glyph* plus a DP segmenter, and when that failed a fall-through to
   EasyOCR's text *detector* on the whole frame: 0.5 s median, **4-10 s worst case**. The burst has a 4 s budget, so one
   slow frame consumed most of it and the car had already moved on.
2. **Stale/slow frame capture.** Every frame was JPEG-encoded at q95 and decoded again (lossy and slow), with a long
   "flush" heuristic to guess whether a frame was fresh.
3. **Startup stall.** A camera probe scanned device indexes 0-10 under three backends at ~1.5 s each.
4. **Accepting the first read.** Nothing protected against a plausible-looking misread.

**What it does now**

```
frame -> 4 cheap OpenCV candidate generators -> perspective-straighten -> glyph check -> tight dark-on-light strip
      -> EasyOCR recognizer only (no detector network), digit/letter-restricted per plate group
      -> strict regex  \d{2}KG\d{3}[A-Z]{3}  -> burst confirms across frames -> forward once
```

* **Localisation** (`app/plate_locator.py`): rows of glyph-shaped blobs (adaptive threshold, either polarity, baseline
  chaining so tilt is followed), text-band morphology, bright plate bodies and edge quadrilaterals, filtered by aspect
  ratio and size. Every candidate is perspective-warped, then must *contain* a row of ~10 glyphs to be believed.
* **Clean strip for EasyOCR**: CLAHE, background flattening, polarity normalised to dark-on-light, deskew, touching glyphs
  (`AAA`) split at ink valleys, cropped tight and scaled so characters fill 62 % of EasyOCR's 64 px input height (swept 0.45-0.82;
  0.62 was best for Inter-style fonts).
* **Reading**: `allowlist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'` everywhere. The plate is read as four short
  groups (`DD` `KG` `DDD` `LLL`) with a **digit-only** alphabet for the digit groups and a **letter-only** one for the letter
  groups (2 batched calls), which resolves O/0, I/1, Z/2, G/6 by position. A group the model is unsure of must be confirmed
  by an independent free line read, otherwise it is rejected. Text of the wrong length is never "repaired".
* **Regex gate** (`app/plate_format.py`): the final string must match `\d{2}KG\d{3}[A-Z]{3}`; region must be 01-11. The API
  still returns `plate_number` without `KG` (`01111AAA`) and `formatted` as `01 KG 111 AAA`, exactly as before.
* **Burst** (`app/api.py`): a clean, confident read is accepted from one frame; otherwise two frames must agree. The slow
  full-frame fallback never runs inside the loop, only once at the very end if nothing was read.
* **Cameras** (`app/camera.py`): one reader thread per camera keeps draining the driver, so a fresh frame is ~50 ms away,
  frames read while a backlog drains are never called "fresh", and dead cameras reconnect on their own. No JPEG round trip.

### Measured (same frames, same machine: 1 CPU core, no GPU)

| benchmark | | original | new |
|---|---|---|---|
| approaching car, 48 frames | exact reads | 46 | 45 |
| | wrong reads | 0 | 1 |
| | mean / median / worst | 919 / 515 / **10 381 ms** | 151 / 134 / **281 ms** |
| stress matrix, 60 frames (other fonts, light-on-dark, touching glyphs, heavy noise, tilt+perspective) | exact reads | 53 | 57 |
| | wrong reads | **4** | **0** |
| | mean / worst | 840 / 4 190 ms | 137 / 275 ms |
| real fixture `num.png` | | - | `01 KG 111 AAA`, conf 1.00, 78 ms |

Be realistic about what this shows: it is *synthetic* data plus one real crop. The misses that remain are the two
farthest plates (150-156 px wide, ~11 px glyphs - the burst re-reads as the car comes closer) and one Q/O look-alike.
Expect a faster laptop to be 2-4x quicker than these numbers. **Rehearse with your real camera and plates before the demo**:
`python scripts/evaluate.py photos/` prints plate, confidence and time for a folder of your own shots.

End-to-end check performed: real `uvicorn` process, live MJPEG stream of a "car" approaching, stub backend: 8/8 cars read
correctly, each forwarded exactly once with the token and correlation id.

## Tests

```bash
pytest                      # 60 tests, ~20 s (uses EasyOCR; weights download on first run)
pytest -m "not ocr_model"   # contract/unit tests only, ~5 s
python scripts/evaluate.py  # synthetic benchmark
```

`tests/test_api_contract.py` is the safety net for other services: OpenAPI snapshot, payloads, error messages, status
codes, single-flight per gate, backend headers. Keep it green and callers will not notice any refactor.

## Layout

```
app/
  main.py          app + startup (cameras open while the model warms up)
  api.py           routes + burst logic
  schemas.py       response models (public contract)
  gate.py          validate -> forward to backend
  recognizer.py    EasyOCR wrapper + recognition pipeline
  plate_locator.py OpenCV: candidates, straightening, character strip
  plate_format.py  regex + position-aware fixes
  camera.py        camera reader threads
  config.py        4 env vars
  models.py  services.py
scripts/  find_cameras.py  evaluate.py
tests/
```

## Tuning notes

* Plate not read while the car is far: that is physics (glyphs under ~9 px). Raise camera resolution / zoom, or mount the camera
  nearer; the burst already keeps trying for 4 s (`BURST_DEADLINE`, `BURST_ATTEMPTS` in `app/api.py`).
* Plate read but the gate refuses it with "too many corrected characters": the model was unsure about several glyphs;
  check lighting / focus (`/debug/camera-snapshot`).
* GPU is used automatically if PyTorch sees one.
