from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

VALID_REGION_CODES = frozenset(f"{i:02d}" for i in range(1, 12))  # 01..11


@dataclass(frozen=True)
class PlateCandidate:
    region: str      
    country: str     
    serial: str      
    letters: str     
    corrections: int  

    @property
    def plate_number(self) -> str:          
        return f"{self.region}{self.serial}{self.letters}"

    @property
    def formatted(self) -> str:             
        return f"{self.region} {self.country} {self.serial} {self.letters}"

    @property
    def is_valid_region(self) -> bool:
        return self.region in VALID_REGION_CODES


@dataclass
class Detection:
    text: str
    confidence: float
    x: float = 0.0


@dataclass
class PlateCrop:
    image: np.ndarray
    method: str
    score: float
    box: Optional[np.ndarray] = None


@dataclass
class RecognitionResult:
    candidate: Optional[PlateCandidate]
    confidence: float
    detections: List[Detection] = field(default_factory=list)
    crop: Optional[PlateCrop] = None
