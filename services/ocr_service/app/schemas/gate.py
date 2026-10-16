from typing import Optional

from pydantic import BaseModel

from app.schemas.recognition import RecognizeResponse


class GateEventResponse(BaseModel):
    recognized: RecognizeResponse
    forwarded_to_backend: bool
    backend_response: Optional[dict] = None
    reject_reason: Optional[str] = None
    frame_source: str
