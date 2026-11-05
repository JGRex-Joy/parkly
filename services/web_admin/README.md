# Parkly Web Admin (`services/web_admin`)

React 18 + Vite + Tailwind + Three.js + GSAP + Recharts.

```bash
cd services/web_admin
npm install
npm run dev      # http://localhost:5173
npm run build
```

`.env`: `VITE_WS_URL` (default `ws://localhost:8000/ws/parking`), `VITE_API_URL` (default `http://localhost:8000`),
`VITE_SERVICE_TOKEN` (only if the backend sets `PARKING_SERVICE_TOKEN`).

## Architecture: strictly event-driven
No seed data, no demo buttons. Everything is driven by `/ws/parking` (auto-reconnect with back-off):

| Event | 3D scene |
|---|---|
| `INITIAL_STATE` | clean/replay: parked cars, car waiting in the lane, car at the exit gate |
| `ENTRY_OCR {plate}` | car spawns far down the entry road, stops at the gate, gate opens 90°, car waits in the lane, gate closes |
| `SLOT_OCCUPIED {slot_id, plate}` | car reverses into the slot, boundary green→red, plate badge, entrance screen count |
| `EXIT_OCR {slot_id, plate, duration, fee}` | car leaves slot (green again, count updates), stops at exit gate, exit screen shows plate / duration / fee / QR |
| `PAYMENT_CONFIRMED {plate}` | “PAYMENT SUCCESS / GATE OPENING”, gate opens, car drives off-screen and despawns, gate closes, screen idles |

`/crm` shows real data only: history is loaded from `GET /api/v1/sessions` and refreshed whenever an event arrives.
