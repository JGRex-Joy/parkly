from __future__ import annotations

from dataclasses import dataclass

from app.cameras import CameraManager
from app.config import Settings
from app.repositories import BackendRepository, FixtureRepository, OcrModelRepository
from app.services.camera_service import CameraService
from app.services.gate_service import GateService
from app.services.recognition_service import RecognitionService


@dataclass
class ServiceContainer:
    settings: Settings
    ocr_model: OcrModelRepository
    camera_manager: CameraManager
    camera_service: CameraService
    recognition_service: RecognitionService
    gate_service: GateService

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        ocr_model = OcrModelRepository(gpu=settings.ocr.gpu)
        manager = CameraManager(settings)
        camera_service = CameraService(settings, manager, FixtureRepository(settings.fixtures_dir))
        recognition = RecognitionService(ocr_model, settings.ocr)
        gate = GateService(recognition, BackendRepository(settings.backend_base_url), settings.max_corrections_to_trust)
        return cls(settings, ocr_model, manager, camera_service, recognition, gate)

    def start(self) -> None:
        self.camera_manager.start()
        if self.settings.ocr.preload:
            self.ocr_model.preload_in_background()

    def stop(self) -> None:
        self.camera_manager.stop()
