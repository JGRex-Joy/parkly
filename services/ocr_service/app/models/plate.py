"""Доменные объекты распознавания номера."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

VALID_REGION_CODES = frozenset(f"{i:02d}" for i in range(1, 12))  # 01..11


@dataclass(frozen=True)
class PlateCandidate:
    region: str          # "01"
    country: str         # "KG"
    serial: str          # "111"
    letters: str         # "AAA"
    corrections: int     # сколько символов пришлось исправить по требованиям формата

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
    image: np.ndarray                  # BGR, выпрямленная пластина (ширина > высота)
    method: str                        # каким способом найдена
    score: float                       # уверенность локализации 0..1
    box: Optional[np.ndarray] = None   # 4 точки в координатах исходного кадра


@dataclass
class GlyphSlot:
    index: int
    x0: int
    x1: int          # исключая
    y0: int
    y1: int          # исключая


@dataclass
class Segmentation:
    gray: np.ndarray                   # нормализованное изображение: тёмный текст на светлом фоне, uint8
    slots: List[GlyphSlot]
    score: float                       # 0..1, насколько разбиение похоже на строку номера


@dataclass
class SlotReading:
    index: int
    char: str                # символ после ограничения по формату
    confidence: float
    raw_char: str            # что модель прочитала без ограничений
    corrected: bool          # ограничение формата изменило символ


@dataclass
class RecognitionResult:
    candidate: Optional[PlateCandidate]
    confidence: float
    detections: List[Detection] = field(default_factory=list)
    crop: Optional[PlateCrop] = None
    slot_readings: Tuple[SlotReading, ...] = ()
