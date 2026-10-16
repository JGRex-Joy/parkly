from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.config import OcrSettings
from app.models import Detection, PlateCandidate, PlateCrop, RecognitionResult, Segmentation, SlotReading
from app.repositories import OcrModelRepository
from app.services.glyph_recognizer import GlyphRecognizer
from app.services.plate_format import (
    COUNTRY, REGION, SERIAL, SERIES, SLOT_COUNT, build_candidate, parse_text,
)
from app.services.plate_locator import find_plate_candidates
from app.services.preprocessing import normalize_line
from app.services.segmentation import segment_line
from app.utils.image import decode_image

logger = logging.getLogger("ocr_service.recognition")

MAX_READ_ATTEMPTS = 2        # сколько лучших кандидатов читаем, прежде чем сдаться
MIN_OCR_WIDTH = 440
PLATE_ALLOWLIST = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _prep_for_line_ocr(plate_img: np.ndarray) -> np.ndarray:
    """Подготовка для чтения строки целиком (запасной путь), как в прежней версии."""
    h, w = plate_img.shape[:2]
    if w < MIN_OCR_WIDTH:
        scale = MIN_OCR_WIDTH / w
        plate_img = cv2.resize(plate_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    gray = plate_img if plate_img.ndim == 2 else cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.2)
    return cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)


def slot_detections(readings: List[SlotReading]) -> List[Detection]:
    """«Сырые» чтения модели (без ограничений формата) по полям: регион, страна, серийник, серия."""
    detections: List[Detection] = []
    for start, end in (REGION, COUNTRY, SERIAL, SERIES):
        group = readings[start:end]
        text = "".join(r.raw_char for r in group)
        if text:
            detections.append(Detection(text=text, confidence=float(np.mean([r.confidence for r in group])), x=float(start)))
    return detections


class RecognitionService:
    def __init__(self, model: OcrModelRepository, settings: OcrSettings) -> None:
        self._model = model
        self._settings = settings
        self._glyphs = GlyphRecognizer(model)

    # ------------------------------------------------------------------ публичный API
    def recognize(self, image_bytes: bytes) -> RecognitionResult:
        frame = decode_image(image_bytes)
        crops = find_plate_candidates(frame)

        segmented = self._segment_candidates(crops)
        best_failed: Optional[RecognitionResult] = None
        for crop, seg in segmented[:MAX_READ_ATTEMPTS]:
            result = self._read_segmentation(crop, seg)
            if result.candidate is not None:
                return result
            if best_failed is None or result.confidence > best_failed.confidence:
                best_failed = result

        fallback = self._read_whole_line(crops[0] if crops else PlateCrop(frame, "fallback_full_frame", 0.0))
        if fallback.candidate is not None or best_failed is None:
            return fallback
        return best_failed

    # ------------------------------------------------------------------ внутренние шаги
    def _segment_candidates(self, crops: List[PlateCrop]) -> List[Tuple[PlateCrop, Segmentation]]:
        scored: List[Tuple[PlateCrop, Segmentation]] = []
        for crop in crops:
            line = normalize_line(crop.image)
            seg = segment_line(line) if line is not None else None
            if seg is not None and seg.score >= self._settings.min_segmentation_score:
                scored.append((crop, seg))
        scored.sort(key=lambda item: (item[1].score, item[0].score), reverse=True)
        return scored

    def _read_segmentation(self, crop: PlateCrop, seg: Segmentation) -> RecognitionResult:
        readings = self._glyphs.read(seg)
        detections = slot_detections(readings)
        reported = PlateCrop(crop.image, crop.method, seg.score, crop.box)
        confidence = float(np.mean([r.confidence for r in readings])) if readings else 0.0

        unreadable = any(not r.char for r in readings)
        too_weak = min((r.confidence for r in readings), default=0.0) < self._settings.min_slot_confidence
        candidate: Optional[PlateCandidate] = None
        if len(readings) == SLOT_COUNT and not unreadable and not too_weak:
            candidate = build_candidate(
                [r.char for r in readings], sum(1 for r in readings if r.corrected), self._settings.country_code
            )
        return RecognitionResult(candidate, confidence, detections, reported, tuple(readings))

    def _read_whole_line(self, crop: PlateCrop) -> RecognitionResult:
        """Запасной путь: EasyOCR читает строку целиком, формат применяется к тексту."""
        line = normalize_line(crop.image)
        prepared = _prep_for_line_ocr(line.gray if line is not None else crop.image)
        reader = self._model.get_reader()
        with self._model.inference_lock:
            raw = reader.readtext(
                prepared, allowlist=PLATE_ALLOWLIST, mag_ratio=2.0, text_threshold=0.6,
                low_text=0.3, contrast_ths=0.2, adjust_contrast=0.7,
            )
        detections = sorted(
            (Detection(text=t, confidence=float(c), x=float(min(p[0] for p in b))) for b, t, c in raw),
            key=lambda d: d.x,
        )
        candidate = parse_text("".join(d.text for d in detections), self._settings.country_code)
        confidence = float(np.mean([d.confidence for d in detections])) if detections else 0.0
        if candidate is not None and self._settings.min_slot_confidence > 0 and confidence < self._settings.min_slot_confidence:
            candidate = None
        return RecognitionResult(candidate, confidence, detections, crop)
