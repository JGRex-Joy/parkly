from __future__ import annotations

from fastapi.testclient import TestClient

STAFF_PLATES = ["A001AA", "B777BB"]  # seeded employees


class Lot:
    """Tiny driver around the public API."""

    def __init__(self, client: TestClient) -> None:
        self.c = client
        self.slots = {s["slot_number"]: s for s in client.get("/api/sim/slots").json()}

    def sid(self, number: str) -> int:
        return self.slots[number]["id"]

    def entry(self, plate: str):
        return self.c.post("/api/sim/entry", json={"plate_number": plate})

    def sensor(self, number: str, plate: str | None = None, occupied: bool = True):
        return self.c.post(
            f"/api/sim/sensor/{self.sid(number)}",
            json={"occupied": occupied, "plate_number": plate},
        )

    def park(self, plate: str, number: str):
        """entry + sensor, asserting both succeed."""
        assert self.entry(plate).status_code == 200
        r = self.sensor(number, plate)
        assert r.status_code == 200, r.text
        return r.json()

    def exit(self, plate: str):
        return self.c.post("/api/sim/exit", json={"plate_number": plate})

    def pay(self, session_id: int):
        return self.c.post(f"/api/pay/{session_id}")

    def state(self) -> dict[str, str]:
        return {s["slot_number"]: s["status"] for s in self.c.get("/api/sim/slots").json()}

    def occupied(self) -> int:
        return sum(1 for v in self.state().values() if v == "PARKED")


def add_staff(client: TestClient, *plates: str) -> None:
    """Register extra employee plates (the seed has only two)."""
    from app.db.models import Employee

    with client.app.state.database.session() as db:
        db.add_all(Employee(plate_number=p, full_name="Тест") for p in plates)
        db.commit()
