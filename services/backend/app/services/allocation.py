from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LotOccupancy:
    free_slots: int
    pending: int
    legacy_occupied: int = 0

    @property
    def available(self) -> int:
        return max(self.free_slots - self.pending - self.legacy_occupied, 0)
