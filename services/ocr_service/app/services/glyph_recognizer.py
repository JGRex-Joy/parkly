from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np

from app.models import Segmentation, SlotReading
from app.repositories import OcrModelRepository
from app.services.plate_format import DIGITS, LETTERS, SLOT_CLASSES

PAD_RATIO = 0.25          
MIN_ASPECT = 0.9          
STRIP_GAP = 10
ALL_CHARS = DIGITS + LETTERS


def glyph_canvases(seg: Segmentation) -> List[np.ndarray]:
    first = seg.slots[0]
    height = first.y1 - first.y0
    pad = int(round(height * PAD_RATIO))
    canvas_h = height + 2 * pad
    canvases = []
    for slot in seg.slots:
        glyph = seg.gray[slot.y0:slot.y1, slot.x0:slot.x1]
        width = max(glyph.shape[1] + 2 * pad, int(canvas_h * MIN_ASPECT))
        canvas = np.full((canvas_h, width), 255, np.uint8)
        offset = (width - glyph.shape[1]) // 2
        canvas[pad:pad + glyph.shape[0], offset:offset + glyph.shape[1]] = glyph
        canvases.append(canvas)
    return canvases


def _strip(canvases: Sequence[np.ndarray]) -> Tuple[np.ndarray, List[List[int]]]:
    height = max(c.shape[0] for c in canvases)
    total = STRIP_GAP + sum(c.shape[1] + STRIP_GAP for c in canvases)
    strip = np.full((height, total), 255, np.uint8)
    boxes, x = [], STRIP_GAP
    for canvas in canvases:
        strip[:canvas.shape[0], x:x + canvas.shape[1]] = canvas
        boxes.append([x, x + canvas.shape[1], 0, canvas.shape[0]])
        x += canvas.shape[1] + STRIP_GAP
    return strip, boxes


def combine_confidence(raw_char: str, raw_conf: float, char: str, constrained_conf: float) -> float:
    if raw_char == char:
        return float(raw_conf)
    return float(constrained_conf) * (1.0 - float(raw_conf))


class GlyphRecognizer:
    def __init__(self, model: OcrModelRepository) -> None:
        self._model = model

    def _recognize(self, canvases: Sequence[np.ndarray], allowlist: str) -> List[Tuple[str, float]]:
        strip, boxes = _strip(canvases)
        reader = self._model.get_reader()
        with self._model.inference_lock:
            results = reader.recognize(
                strip, horizontal_list=boxes, free_list=[], allowlist=allowlist,
                decoder="greedy", batch_size=len(boxes),
            )
        by_x: Dict[int, Tuple[str, float]] = {
            int(min(p[0] for p in box)): (text, float(conf)) for box, text, conf in results
        }
        return [by_x.get(box[0], ("", 0.0)) for box in boxes]

    def read(self, seg: Segmentation) -> List[SlotReading]:
        canvases = glyph_canvases(seg)
        digits = self._recognize(canvases, DIGITS)
        letters = self._recognize(canvases, LETTERS)
        free = self._recognize(canvases, ALL_CHARS)

        readings: List[SlotReading] = []
        for i, slot_class in enumerate(SLOT_CLASSES):
            constrained_text, constrained_conf = digits[i] if slot_class == "D" else letters[i]
            raw_text, raw_conf = free[i]
            char = constrained_text[:1]
            raw_char = raw_text[:1]
            if not char:  
                readings.append(SlotReading(i, "", 0.0, raw_char, corrected=False))
                continue
            conf = combine_confidence(raw_char, raw_conf, char, constrained_conf)
            readings.append(SlotReading(i, char, conf, raw_char, corrected=bool(raw_char) and raw_char != char))
        return readings
