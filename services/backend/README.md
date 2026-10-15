# Smart Parking backend

Run: `uvicorn app.main:app` · Tests: `pytest`

## Environment variables (all optional)
| Variable | Default |
|---|---|
| `PARKING_BASE_URL` | `10.46.227.79:8000` (host used in QR/pay links) |
| `PARKING_DATABASE_URL` | `sqlite:///./smart_parking.db` |
| `PARKING_PENDING_ENTRY_TTL_SECONDS` | `900` - how long an admitted-but-not-parked vehicle reserves capacity |
| `PARKING_CORS_ORIGINS` | empty = no CORS middleware; comma-separated origins to enable |

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

