from __future__ import annotations

import logging
from typing import Dict, Optional

from app.cameras.base import CameraBlackFrameError, CameraSource, CameraTimeoutError, CameraUnavailableError
from app.cameras.ip_camera import IpCameraSource
from app.cameras.usb_camera import UsbCameraSource
from app.config import Settings
from app.models import CapturedFrame

logger = logging.getLogger("ocr_service.cameras")


def build_sources(settings: Settings) -> Dict[str, CameraSource]:
    sources: Dict[str, CameraSource] = {}
    if settings.usb_camera.enabled:
        sources["usb"] = UsbCameraSource(settings.usb_camera, name="usb")
    if settings.wifi_camera.enabled:
        # Iriun по Wi-Fi тоже виден системе как локальная камера (виртуальное устройство) — открываем по индексу.
        sources["wifi"] = UsbCameraSource(settings.wifi_camera, name="wifi")
    if settings.ip_camera.enabled:
        sources["ip"] = IpCameraSource(settings.ip_camera)
    return sources


class CameraManager:
    def __init__(self, settings: Settings, sources: Optional[Dict[str, CameraSource]] = None) -> None:
        self._settings = settings
        self._sources = build_sources(settings) if sources is None else sources

    @property
    def sources(self) -> Dict[str, CameraSource]:
        return self._sources

    def start(self) -> None:
        for name in {src for _, src in self._settings.gate_sources}:
            source = self._sources.get(name)
            if source is not None:
                source.start()

    def stop(self) -> None:
        for source in self._sources.values():
            source.stop()

    def capture(self, gate: str, newer_than: Optional[float] = None) -> CapturedFrame:
        source_name = self._settings.source_for_gate(gate)
        source = self._sources.get(source_name) if source_name else None
        if source is None:
            raise CameraUnavailableError(f"Камера для '{gate}' недоступна")
        try:
            return source.get_frame(newer_than=newer_than)
        except CameraUnavailableError as exc:
            raise CameraUnavailableError(f"Камера для '{gate}' недоступна: {exc}") from exc
        except CameraBlackFrameError as exc:
            raise CameraBlackFrameError(f"Не удалось получить кадр с камеры '{gate}': {exc}") from exc
        except CameraTimeoutError as exc:
            raise CameraTimeoutError(f"Не удалось получить кадр с камеры '{gate}': {exc}") from exc
