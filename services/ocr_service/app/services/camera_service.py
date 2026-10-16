from __future__ import annotations

import logging
import time
from typing import Callable, Tuple

from app.cameras import CameraManager, CameraUnavailableError
from app.config import Settings
from app.repositories import FixtureRepository
from app.utils.image import encode_jpeg

logger = logging.getLogger("ocr_service.camera_service")


class CameraService:

    def __init__(
        self,
        settings: Settings,
        manager: CameraManager,
        fixtures: FixtureRepository,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._manager = manager
        self._fixtures = fixtures
        self._sleep = sleep
        self._clock = clock

    def capture_frame_bytes(self, gate: str) -> Tuple[bytes, str]:
        if self._settings.capture_delay_seconds > 0:
            self._sleep(self._settings.capture_delay_seconds)

        requested_at = self._clock()  
        try:
            frame = self._manager.capture(gate, newer_than=requested_at)
            image, source = frame.image, frame.source
        except CameraUnavailableError as exc:
            fixture = self._fixtures.load_frame(gate) if self._settings.fixture_fallback else None
            if fixture is None:
                raise
            logger.warning("Камера для '%s' недоступна (%s); использую файл-заглушку", gate, exc)
            image, source = fixture, "fixture"

        return encode_jpeg(image), source
