from __future__ import annotations

import abc
import logging
import threading
import time
from typing import Callable, Optional, Protocol, Tuple

import numpy as np

from app.config import CameraReliability
from app.models import CapturedFrame, ConnectionState
from app.utils.image import frame_problem

logger = logging.getLogger("ocr_service.cameras")


class CameraError(RuntimeError):
    pass

class CameraConnectError(CameraError):
    pass

class CameraUnavailableError(CameraError):
    pass

class CameraTimeoutError(CameraError):
    pass

class CameraBlackFrameError(CameraTimeoutError):
    pass

class VideoCaptureLike(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> Tuple[bool, Optional[np.ndarray]]: ...
    def release(self) -> None: ...


class CameraSource(abc.ABC):
    frame_source: str = "camera"

    def __init__(
        self,
        name: str,
        reliability: CameraReliability,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._rel = reliability
        self._clock = clock
        self._cond = threading.Condition()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame: Optional[CapturedFrame] = None
        self._state = ConnectionState.STOPPED
        self._last_error: Optional[str] = None
        self._closed = False
        self._last_rejection: Optional[Tuple[float, str]] = None  
        self._rejected_total = 0
        self._rejected_since_ok = 0
        self._last_reject_log = float("-inf")

    @abc.abstractmethod
    def _open_capture(self) -> VideoCaptureLike:
        pass
    
    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _frame_problem(self, image) -> Optional[str]:
        if image is None or getattr(image, "size", 0) == 0:
            return "пустой кадр"
        if not self._rel.reject_black_frames:
            return None
        return frame_problem(image, self._rel.black_mean_threshold, self._rel.black_peak_threshold)

    def _note_rejection(self, reason: str) -> None:
        now = self._clock()
        self._last_rejection = (now, reason)
        self._rejected_total += 1
        self._rejected_since_ok += 1
        if now - self._last_reject_log >= 5.0:
            self._last_reject_log = now
            logger.warning("camera %s: кадр отброшен: %s (отброшено подряд: %d)", self.name, reason, self._rejected_since_ok)

    def _note_valid_frame(self) -> None:
        if self._last_rejection is not None:
            logger.info("camera %s: снова приходят нормальные кадры (отброшено перед этим: %d)", self.name, self._rejected_since_ok)
        self._last_rejection = None
        self._rejected_since_ok = 0

    def _recent_rejection(self, window: float) -> Optional[str]:
        rejection = self._last_rejection
        if rejection is not None and self._clock() - rejection[0] <= window:
            return rejection[1]
        return None

    def _set_state(self, state: ConnectionState) -> None:
        with self._cond:
            if state is not ConnectionState.CONNECTED:
                self._frame = None  
            if state is not self._state:
                logger.info("camera %s: %s -> %s", self.name, self._state.value, state.value)
            self._state = state
            self._cond.notify_all()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.is_running:
                return
            self._closed = False
            self._stop_event.clear()
            self._set_state(ConnectionState.CONNECTING)
            self._thread = threading.Thread(
                target=self._run, name=f"camera-{self.name}", daemon=True
            )
            self._thread.start()

    def stop(self, join_timeout: float = 10.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            self._closed = True
            self._stop_event.set()
            if thread is not None and thread is not threading.current_thread():
                thread.join(join_timeout)
                if thread.is_alive():
                    logger.warning("camera %s: поток чтения не завершился за %.1f с", self.name, join_timeout)
            self._thread = None
            self._set_state(ConnectionState.STOPPED)

    def get_frame(self, newer_than: Optional[float] = None, timeout: Optional[float] = None) -> CapturedFrame:
        if not self.is_running:
            if self._closed:
                raise CameraUnavailableError(f"источник '{self.name}' остановлен")
            self.start()
        timeout = self._rel.frame_timeout if timeout is None else timeout
        deadline = self._clock() + timeout
        with self._cond:
            while True:
                frame = self._frame
                if frame is not None and (newer_than is None or frame.captured_at >= newer_than):
                    return frame
                if self._state is ConnectionState.STOPPED:
                    raise CameraUnavailableError(f"источник '{self.name}' остановлен")
                remaining = deadline - self._clock()
                if remaining <= 0:
                    black = self._recent_rejection(2 * max(timeout, self._rel.stall_timeout))
                    if black is not None:
                        logger.error("camera %s: съёмка не удалась, камера отдаёт непригодные кадры: %s", self.name, black)
                        raise CameraBlackFrameError(
                            f"камера '{self.name}' отдаёт только чёрные/пустые кадры за {timeout:.1f} с ({black}); "
                            "проверьте, что приложение Iriun на телефоне запущено, экран не заблокирован, "
                            "и что индекс устройства указан верно"
                        )
                    if self._state is ConnectionState.CONNECTED:
                        raise CameraTimeoutError(f"нет свежего кадра от '{self.name}' за {timeout:.1f} с")
                    detail = f": {self._last_error}" if self._last_error else ""
                    raise CameraUnavailableError(f"'{self.name}' не подключена{detail}")
                self._cond.wait(min(remaining, 0.25))

    def _run(self) -> None:
        delay = self._rel.reconnect_min_delay
        first_attempt = True
        while not self._stop_event.is_set():
            capture: Optional[VideoCaptureLike] = None
            try:
                self._set_state(ConnectionState.CONNECTING if first_attempt else ConnectionState.RECONNECTING)
                capture = self._open_capture()
                self._discard_warmup(capture)
                self._last_error = None
                delay = self._rel.reconnect_min_delay
                self._set_state(ConnectionState.CONNECTED)
                self._read_loop(capture)
            except Exception as exc:  
                self._last_error = str(exc)
                logger.warning("camera %s: %s", self.name, exc)
            finally:
                self._safe_release(capture)
            first_attempt = False
            if self._stop_event.is_set():
                break
            self._set_state(ConnectionState.RECONNECTING)
            if self._stop_event.wait(delay):
                break
            delay = min(delay * 2, self._rel.reconnect_max_delay)
        self._set_state(ConnectionState.STOPPED)

    def _discard_warmup(self, capture: VideoCaptureLike) -> None:
        for _ in range(max(self._rel.warmup_frames, 0)):
            if self._stop_event.is_set():
                return
            capture.read()

    def _read_loop(self, capture: VideoCaptureLike) -> None:
        last_ok = self._clock()
        while not self._stop_event.is_set():
            ok, image = capture.read()
            now = self._clock()
            if ok and image is not None and image.size > 0:
                problem = self._frame_problem(image)
                if problem is None:
                    last_ok = now
                    self._note_valid_frame()
                    with self._cond:
                        self._frame = CapturedFrame(image=image, captured_at=now, source=self.frame_source)
                        self._cond.notify_all()
                    continue
                self._note_rejection(problem)
                if now - last_ok > self._rel.stall_timeout:
                    raise CameraConnectError(
                        f"'{self.name}': только непригодные кадры более {self._rel.stall_timeout:.1f} с ({problem}), переподключаюсь"
                    )
                continue
            if now - last_ok > self._rel.stall_timeout:
                raise CameraConnectError(
                    f"'{self.name}': нет кадров более {self._rel.stall_timeout:.1f} с, переподключаюсь"
                )
            self._stop_event.wait(0.05)

    def _safe_release(self, capture: Optional[VideoCaptureLike]) -> None:
        if capture is None:
            return
        try:
            capture.release()
        except Exception:  
            logger.exception("camera %s: ошибка при освобождении устройства", self.name)
