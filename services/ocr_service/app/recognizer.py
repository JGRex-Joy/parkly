from __future__ import annotations

import logging
import threading
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np

from app.models import Detection, PlateCrop, RecognitionResult
from app.plate_format import ALLOWLIST, DIGITS, LETTERS, from_groups, parse_text
from app.plate_locator import LINE_HEIGHT, Line, extract_line, find_candidates, slot_groups

logger = logging.getLogger("ocr_service.recognizer")

SURE_CONFIDENCE = 0.7    
MIN_CONFIDENCE = 0.5     
SINGLE_READER_CAP = 0.8  
CLEAN_STRIP = 0.85       
MAX_TRIES = 3            
FALLBACK_SIDE = 960      


class OcrEngine:
    def __init__(self, gpu: Optional[bool] = None) -> None:      
        self._gpu = gpu
        self._reader = None
        self._load_lock = threading.Lock()
        self._lock = threading.Lock()

    @property
    def reader(self):
        if self._reader is None:
            with self._load_lock:
                if self._reader is None:
                    import easyocr
                    import torch
                    use_gpu = torch.cuda.is_available() if self._gpu is None else self._gpu
                    logger.info("Loading EasyOCR model (gpu=%s)...", use_gpu)
                    self._reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
        return self._reader

    def warm_up(self) -> None:
        blank = np.full((LINE_HEIGHT, 256), 255, np.uint8)
        self.read_lines([blank])
        with self._lock:
            self.reader.readtext(np.full((96, 320), 255, np.uint8), allowlist=ALLOWLIST)

    def read_lines(self, lines: List[np.ndarray], allowlist: str = ALLOWLIST) -> List[Tuple[str, float]]:
        gap = 4
        width = max(l.shape[1] for l in lines)
        canvas = np.full((len(lines) * (LINE_HEIGHT + gap), width), 255, np.uint8)
        boxes = []
        for i, l in enumerate(lines):
            y = i * (LINE_HEIGHT + gap)
            canvas[y:y + l.shape[0], :l.shape[1]] = l
            boxes.append([0, l.shape[1], y, y + l.shape[0]])
        reader = self.reader
        with self._lock:
            raw = reader.recognize(canvas, horizontal_list=boxes, free_list=[], allowlist=allowlist,
                                   decoder="greedy", batch_size=len(boxes), adjust_contrast=0.0)
        by_y = {int(min(p[1] for p in box)): (text, float(conf)) for box, text, conf in raw}
        return [by_y.get(b[2], ("", 0.0)) for b in boxes]

    def read_groups(self, groups: List[Tuple[str, np.ndarray]]) -> List[Tuple[str, float]]:
        words: List[Tuple[str, float]] = [("", 0.0)] * len(groups)
        for cls, alphabet in (("D", DIGITS), ("L", LETTERS)):
            idx = [i for i, (c, _) in enumerate(groups) if c == cls]
            if idx:
                for i, word in zip(idx, self.read_lines([groups[i][1] for i in idx], allowlist=alphabet)):
                    words[i] = word
        return words

    def read_scene(self, frame_bgr: np.ndarray) -> List[Detection]:
        h, w = frame_bgr.shape[:2]
        s = min(1.0, FALLBACK_SIDE / max(h, w))
        img = cv2.resize(frame_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1.0 else frame_bgr
        reader = self.reader
        with self._lock:
            raw = reader.readtext(img, allowlist=ALLOWLIST, mag_ratio=1.5, text_threshold=0.6, low_text=0.3)
        return sorted((Detection(t, float(c), float(min(p[0] for p in b))) for b, t, c in raw), key=lambda d: d.x)


class RecognitionService:
    def __init__(self, engine: OcrEngine) -> None:
        self._engine = engine

    def recognize(self, image: Union[bytes, np.ndarray], thorough: bool = True) -> RecognitionResult:
        frame = _to_frame(image)

        best_failed: Optional[RecognitionResult] = None
        pending: List[Tuple[float, PlateCrop, Line]] = []
        tries = 0

        def attempt(crop: PlateCrop, line: Line) -> Optional[RecognitionResult]:
            nonlocal best_failed, tries
            tries += 1
            result = self._read(crop, line)
            if result.candidate is not None:
                return result
            if best_failed is None or result.confidence > best_failed.confidence:
                best_failed = result
            return None

        for crop in find_candidates(frame):               
            line = extract_line(crop.image)
            if line is None:
                continue
            if line.glyphs == 10 and line.quality >= CLEAN_STRIP:      
                hit = attempt(crop, line)
                if hit is not None:
                    return hit
            else:
                pending.append((0.35 * crop.score + 0.65 * line.quality, crop, line))
        for _, crop, line in sorted(pending, key=lambda t: -t[0]):
            if tries >= MAX_TRIES:
                break
            hit = attempt(crop, line)
            if hit is not None:
                return hit

        if thorough:
            detections = self._engine.read_scene(frame)
            candidate = parse_text("".join(d.text for d in detections))
            if candidate is not None:
                conf = float(np.mean([d.confidence for d in detections]))
                return RecognitionResult(candidate, conf, detections, PlateCrop(frame, "fallback_full_frame", 0.0))

        return best_failed or RecognitionResult(None, 0.0, [], None)

    def _read(self, crop: PlateCrop, line: Line) -> RecognitionResult:
        shown = PlateCrop(crop.image, crop.method, crop.score, crop.box)
        candidate, confidence, detections, sure = None, 0.0, [], False

        groups = slot_groups(line)
        if groups:
            words = self._engine.read_groups(groups)
            candidate = from_groups([w for w, _ in words])
            detections = [Detection(w, c) for w, c in words if w]
            confs = [c for _, c in words]
            confidence = float(np.mean(confs)) if confs else 0.0
            sure = candidate is not None and min(confs) >= SURE_CONFIDENCE

        if not sure:
            (text, conf), = self._engine.read_lines([line.image])
            second = parse_text(text)
            if candidate is not None:                       
                if second is not None and second.plate_number == candidate.plate_number:
                    confidence = max(confidence, conf)
                else:
                    candidate = None
            elif second is not None and conf >= MIN_CONFIDENCE:
                candidate, confidence, detections = second, min(conf, SINGLE_READER_CAP), [Detection(text, conf)]
        return RecognitionResult(candidate, confidence, detections, shown)


def _to_frame(image: Union[bytes, np.ndarray]) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    frame = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Не удалось декодировать изображение")
    return frame
