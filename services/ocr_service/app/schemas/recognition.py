from typing import List, Optional

from pydantic import BaseModel


class DetectionOut(BaseModel):
    text: str
    confidence: float


class RecognizeResponse(BaseModel):
    plate_number: Optional[str]
    formatted: Optional[str]
    region_code: Optional[str]
    is_valid_region: bool
    corrections_applied: int
    confidence: float
    plate_detection_method: str
    plate_detection_score: float
    raw_detections: List[DetectionOut]
