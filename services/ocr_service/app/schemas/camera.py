from pydantic import BaseModel


class CameraSnapshotResponse(BaseModel):
    source: str          # "webcam" (USB-камера), "ip_camera" (IP-камера), "fixture" (файл-заглушка)
    image_base64: str    # data:image/jpeg;base64,... — НЕ сохраняется на диск, только в ответе
