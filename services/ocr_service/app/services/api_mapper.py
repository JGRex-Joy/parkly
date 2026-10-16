from __future__ import annotations

from app.models import RecognitionResult
from app.schemas import DetectionOut, RecognizeResponse


def to_recognize_response(result: RecognitionResult) -> RecognizeResponse:
    candidate = result.candidate
    crop = result.crop
    return RecognizeResponse(
        plate_number=candidate.plate_number if candidate else None,
        formatted=candidate.formatted if candidate else None,
        region_code=candidate.region if candidate else None,
        is_valid_region=candidate.is_valid_region if candidate else False,
        corrections_applied=candidate.corrections if candidate else 0,
        confidence=round(result.confidence, 3),
        plate_detection_method=crop.method if crop else "fallback_full_frame",
        plate_detection_score=round(crop.score, 3) if crop else 0.0,
        raw_detections=[DetectionOut(text=d.text, confidence=d.confidence) for d in result.detections],
    )
