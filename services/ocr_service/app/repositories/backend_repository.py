from __future__ import annotations

from typing import Literal

import httpx

Gate = Literal["entry", "exit"]

ENDPOINT_BY_GATE = {
    "entry": "/api/sim/entry",
    "exit": "/api/sim/exit",
}


class BackendRepository:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def forward_plate(self, gate: Gate, plate_formatted: str) -> dict:
        url = f"{self._base_url}{ENDPOINT_BY_GATE[gate]}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json={"plate_number": plate_formatted})
            response.raise_for_status()
            return response.json() if response.content else {}
