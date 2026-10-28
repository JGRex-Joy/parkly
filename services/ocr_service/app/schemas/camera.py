from pydantic import BaseModel


class CameraSnapshotResponse(BaseModel):
    source: str          
    image_base64: str    
