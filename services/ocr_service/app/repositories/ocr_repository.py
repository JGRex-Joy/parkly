from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("ocr_service.ocr")


class OcrModelRepository:
    def __init__(self, gpu: bool = False) -> None:
        self._gpu = gpu
        self._reader: Optional[Any] = None
        self._load_lock = threading.Lock()
        self.inference_lock = threading.RLock()

    def get_reader(self) -> Any:
        if self._reader is None:
            with self._load_lock:
                if self._reader is None:
                    import easyocr 

                    logger.info("Загрузка модели EasyOCR (gpu=%s)", self._gpu)
                    self._reader = easyocr.Reader(["en"], gpu=self._gpu, verbose=False)
        return self._reader

    def preload_in_background(self) -> threading.Thread:
        """Греет модель, чтобы первый запрос с ворот не ждал загрузку. Ошибка не валит сервис."""

        def _load() -> None:
            try:
                self.get_reader()
                logger.info("Модель EasyOCR готова")
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось заранее загрузить модель EasyOCR; будет загружена при первом запросе")

        thread = threading.Thread(target=_load, name="ocr-preload", daemon=True)
        thread.start()
        return thread
