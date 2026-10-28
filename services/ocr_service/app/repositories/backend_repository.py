from __future__ import annotations

from typing import Literal, Optional

import httpx

Gate = Literal["entry", "exit"]

ENDPOINT_BY_GATE = {
    "entry": "/api/sim/entry",
    "exit": "/api/sim/exit",
}


class BackendRepository:
    def __init__(self, base_url: str, timeout: float = 5.0, service_token: str = "") -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._service_token = service_token

    async def forward_plate(self, gate: Gate, plate_formatted: str, correlation_id: Optional[str] = None) -> dict:
        url = f"{self._base_url}{ENDPOINT_BY_GATE[gate]}"
        headers = {}
        if self._service_token:
            headers["X-Service-Token"] = self._service_token
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id  
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json={"plate_number": plate_formatted}, headers=headers)
            response.raise_for_status()
            return response.json() if response.content else {}
