# Audit: Hot Wheels prototype instability (firmware 1.1.0 / bridge 0.1.0)

Every defect below was **reproduced on the original code first** (host-compiled firmware + Python
repro scripts), then fixed, then pinned by a test in `tests/`. Items marked *hypothesis* cannot be
proven without the physical rig.

## Where things actually live (differs from the brief)
* Raw HC-SR04 distances never reach Python: sampling, filtering and debouncing happen **in the
  firmware**. The median filter therefore had to be implemented in `smart_parking.ino`; the Python
  layer receives only debounced `SLOT`/`GATE` events and adds a second verification stage.
* The serial protocol is checksummed frames (`$CMD,<seq>,OPEN,entry,8000*CS\n`), not `OPEN_GATE_1`.
  Kept: it is explicit, `\n`-terminated, ACKed and retried. The backend call is
  `POST /api/sim/sensor/{slot_id}` (not `/api/v1/slots/update`).
* The bridge was already async (one reader thread -> asyncio, `httpx.AsyncClient`) with reconnect
  and ACK/retry. It was not a blocking design; the bottlenecks were more specific (below).

## 1. Sensor flicker (firmware)
| Original behaviour | Measured (car parked the whole time) |
|---|---|
| single reading = one vote; lost echo reset the "occupied" streak | echo loss 1 in 3: **0 detections** |
| lost echo counted as "far" = vote for FREE | bursts of 3 lost echoes: **15 false transitions in 12 s** |

Fix (v1.1): glitch reject (<2 cm) -> sliding **median of 5** -> hysteresis dead band
(`thr`..`thr+hyst`) -> **asymmetric debounce** (3 consecutive medians to OCCUPIED, 6 to FREE).
Same inputs now: 1 detection / 1 transition. Cost: ~0.85 s to occupy, ~1.5 s to free (slots).
A lost echo is still treated as "far": an empty slot usually also returns no echo, so the two
cannot be told apart; the median + the longer FREE debounce are what protect against it.

## 2. Servo "every other time"
| # | Cause | Status |
|---|---|---|
| a | Device cached the last 4 command **seq** numbers and answered `ACK,OK,DUP` *without executing*. The bridge restarts counting at 1; if the port re-open does not reset the board, the first commands collide. Repro: `OPEN seq=2` -> `DUP`, servo stays at 0. | fixed: DUP needs seq **and** frame checksum; bridge starts each connection at a random seq |
| b | `gate:plate` dedupe window (15 s) swallowed a repeat open of the same plate even after the barrier had closed. Repro: 2 requests -> 1 `OPEN` frame. Typical when re-testing with the same toy car/fixture image. | fixed: heuristic keys are dropped on the `BARRIER CLOSED` event; explicit `request_id`s still dedupe |
| c | Reset in the hold window (brown-out etc.): ACK already delivered, board reboots, barrier is closed, nobody re-sends OPEN. | fixed: `BOOT` inside an authorised hold -> OPEN re-sent with the remaining time |
| d | Flaky gate sensor -> barrier auto-closes (clear for `clear_ms`) onto a car it "lost". | mitigated by section 1 (same filter on gate sensors) |
| e | **Hypothesis:** SG90 stall/inrush on the Uno's 5 V pin resets or glitches the board. The bridge now logs `Arduino RESET while the USB link was up` and counts `unexpected_resets` in `/status`; if that counter moves when a gate moves, it is power. See HARDWARE.md. | diagnosed, not fixable in software |

## 3. Bridge bottlenecks
| Defect | Repro on original | Fix |
|---|---|---|
| `BOOT` bring-up ran **inside** the event-dispatch loop (backend HTTP, 5 s timeout) | GATE event handled 3.0 s late | spawned as a task: 0.02 s |
| One shared slot worker, 5 retries x 5 s, `staff_holds_slot` GET per vacant | slot 2 waits behind slot 1 | one sender task per slot |
| One report worker for both gates | entry backlog delays exit report | one per gate |
| Event dedupe `(epoch, seq)`: epoch only bumped on `BOOT`, which `reset_input_buffer()` usually flushed | after re-plug **every** device event dropped as duplicate until the counter passed its old value (`HB` every 2 s: minutes) | epoch bumps on every link-up |
| Writes used the shared default executor | - | dedicated single TX thread (ordered, isolated) |

## 4. Dedupe / rate limiting (`event_router.py`)
`_want_slot()` is O(1), no I/O. Per-slot sender: value must be stable `slot_settle_s` (0.3 s), at most
one POST per `slot_min_interval_s` (1 s), only if different from what the backend holds, newest value
wins over retries. Counters: `slot_coalesced`, `slot_dup_suppressed`.

## 5. Fault tolerance
Reconnect/backoff already existed; added: stale-input flush (`reset_input_buffer()` on open and when
> `rx_backlog_max` bytes wait, followed by an automatic `SYNC`), oversized-line resync, malformed
frames of any kind counted and logged at most once per second (the reader cannot crash on parsing),
`auto` port re-resolved on each reconnect, bring-up retried when the device is alive but an earlier
bring-up timed out.

## Tuning for 7x4 cm cars (do this on the rig)
1. `BRIDGE_DEVICE_CFG=dbg=1`, open `GET /status` -> `distance_cm` (median and last raw per sensor).
2. Measure empty vs. parked for each slot; set `slot_thr` about midway and `hyst` >= the spread of the
   parked median (e.g. `slot_thr=20,hyst=6`). Keep `slot_thr + hyst` below the empty-slot distance.
3. If a parked median still jumps to "no echo" for seconds, it is geometry, not filtering: aim the
   sensor at the car's flattest face (side/rear), mount at body height (~1.5-2 cm), keep the beam
   (~15 deg cone) off the floor and neighbours, 5+ cm minimum distance. Cheap acoustic fix: a small flat
   card behind/above the target. Robust fix: a VL53L0X/VL53L1X time-of-flight sensor, which does not
   suffer from specular reflection on small curved bodies.
4. `dbg=0` afterwards.
