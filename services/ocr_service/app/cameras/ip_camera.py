from __future__ import annotations

import logging
import os
import threading
from urllib.parse import urlsplit

import cv2

from app.cameras.base import CameraConnectError, CameraSource, VideoCaptureLike
from app.config import IpCameraSettings
from app.utils.urls import mask_url_credentials

logger = logging.getLogger("ocr_service.cameras.ip")

SUPPORTED_SCHEMES = ("http", "https", "rtsp", "rtsps", "rtmp")

_ffmpeg_env_lock = threading.Lock()


def validate_stream_url(url: str) -> str:
    if not url:
        raise ValueError("CAMERA_IP_URL не задан")
    parts = urlsplit(url)
    if parts.scheme.lower() not in SUPPORTED_SCHEMES:
        raise ValueError(
            f"Неподдерживаемая схема {parts.scheme!r} в CAMERA_IP_URL; допустимо: {', '.join(SUPPORTED_SCHEMES)}"
        )
    if not parts.hostname:
        raise ValueError("В CAMERA_IP_URL не указан адрес хоста")
    return url


class IpCameraSource(CameraSource):
    frame_source = "ip_camera"

    def __init__(self, settings: IpCameraSettings, name: str = "ip") -> None:
        super().__init__(name=name, reliability=settings.reliability)
        self._settings = settings
        self._safe_url = mask_url_credentials(settings.url)

    def _open_capture(self) -> VideoCaptureLike:
        url = validate_stream_url(self._settings.url)
        is_rtsp = urlsplit(url).scheme.lower() in ("rtsp", "rtsps")

        params = [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(self._settings.open_timeout_ms),
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(self._settings.read_timeout_ms),
        ]
        with _ffmpeg_env_lock:
            if is_rtsp and "OPENCV_FFMPEG_CAPTURE_OPTIONS" not in os.environ:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{self._settings.rtsp_transport}"
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)

        if not capture.isOpened():
            capture.release()
            raise CameraConnectError(f"не удалось подключиться к IP-камере {self._safe_url}")
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  
        except Exception:  
            pass
        logger.info("IP-камера подключена: %s", self._safe_url)
        return capture
