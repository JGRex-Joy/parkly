from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
    x: float


@dataclass
class PlateCrop:
    image: np.ndarray                  
    method: str                        
    score: float                       
    box: Optional[np.ndarray] = None   


@dataclass
class GlyphSlot:
    index: int
    x0: int
    x1: int          
    y0: int
    y1: int          


@dataclass
class Segmentation:
    gray: np.ndarray                   
    slots: List[GlyphSlot]
    score: float                       


@dataclass
class SlotReading:
    index: int
    char: str                
    confidence: float
    raw_char: str            
    corrected: bool          


@dataclass
class RecognitionResult:
    candidate: Optional[PlateCandidate]
    confidence: float
    detections: List[Detection] = field(default_factory=list)
    crop: Optional[PlateCrop] = None
    slot_readings: Tuple[SlotReading, ...] = ()
