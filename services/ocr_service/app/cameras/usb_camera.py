from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import List, Optional, Sequence

import cv2

from app.cameras.base import CameraConnectError, CameraSource, VideoCaptureLike
from app.config import UsbCameraSettings

logger = logging.getLogger("ocr_service.cameras.usb")


def resolve_backend(name: str) -> Optional[int]:
    name = name.lower()
    if name == "auto":
        if platform.system() == "Windows":
            return cv2.CAP_DSHOW
        if platform.system() == "Linux":
            return cv2.CAP_V4L2
        return None
    mapping = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "v4l2": cv2.CAP_V4L2, "any": None}
    if name not in mapping:
        raise ValueError(f"Неизвестный бэкенд камеры: {name!r}")
    return mapping[name]


def _open_index(index: int, backend: Optional[int]) -> cv2.VideoCapture:
    return cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)


@dataclass(frozen=True)
class UsbCameraInfo:
    index: int
    width: int
    height: int


def discover_usb_cameras(
    backend_name: str = "auto", scan_limit: int = 8, ignore: Sequence[int] = ()
) -> List[UsbCameraInfo]:
    backend = resolve_backend(backend_name)
    found: List[UsbCameraInfo] = []
    for index in range(scan_limit):
        if index in ignore:
            continue
        capture = _open_index(index, backend)
        try:
            if not capture.isOpened():
                continue
            ok, frame = capture.read()
            if ok and frame is not None:
                found.append(UsbCameraInfo(index, int(frame.shape[1]), int(frame.shape[0])))
        finally:
            capture.release()
    return found


class UsbCameraSource(CameraSource):
    frame_source = "webcam"  

    def __init__(self, settings: UsbCameraSettings, name: str = "usb") -> None:
        super().__init__(name=name, reliability=settings.reliability)
        self._settings = settings
        self._backend = resolve_backend(settings.backend)
        self._last_index: Optional[int] = None

    def _candidate_indexes(self) -> List[int]:
        if self._settings.index is not None:
            return [self._settings.index]
        indexes = [i for i in range(self._settings.scan_limit) if i not in self._settings.ignore_indexes]
        if self._last_index in indexes:  
            indexes.remove(self._last_index)
            indexes.insert(0, self._last_index)
        return indexes

    def _configure(self, capture: cv2.VideoCapture) -> None:
        s = self._settings
        if s.fourcc:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*s.fourcc[:4].ljust(4)))
        if s.width > 0:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, s.width)
        if s.height > 0:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, s.height)

    def _open_capture(self) -> VideoCaptureLike:
        tried: List[int] = []
        for index in self._candidate_indexes():
            tried.append(index)
            capture = _open_index(index, self._backend)
            if not capture.isOpened():
                capture.release()
                continue
            self._configure(capture)
            ok, frame = capture.read() 
            if not ok or frame is None:
                capture.release()
                continue
            self._last_index = index
            logger.info("USB-камера подключена: индекс %d", index)
            return capture
        raise CameraConnectError(f"USB-камера не найдена (проверены индексы: {tried or 'нет'})")
