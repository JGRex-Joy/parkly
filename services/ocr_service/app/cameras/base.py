from __future__ import annotations

import abc
import logging
import threading
import time
from typing import Callable, Optional, Protocol, Tuple

import numpy as np

from app.config import CameraReliability
from app.models import CapturedFrame, ConnectionState

logger = logging.getLogger("ocr_service.cameras")


class CameraError(RuntimeError):
    """Базовая ошибка камеры. Наследует RuntimeError, как и исходный код."""


class CameraConnectError(CameraError):
    """Не удалось открыть устройство или поток."""


class CameraUnavailableError(CameraError):
    """Камера не подключена (нет соединения / источник выключен)."""


class CameraTimeoutError(CameraError):
    """Камера подключена, но свежий кадр не пришёл вовремя."""


class VideoCaptureLike(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> Tuple[bool, Optional[np.ndarray]]: ...
    def release(self) -> None: ...


class CameraSource(abc.ABC):
    """Источник кадров с автоматическим переподключением."""

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

    @abc.abstractmethod
    def _open_capture(self) -> VideoCaptureLike:
        """Возвращает открытое устройство или бросает CameraConnectError."""

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

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
                last_ok = now
                with self._cond:
                    self._frame = CapturedFrame(image=image, captured_at=now, source=self.frame_source)
                    self._cond.notify_all()
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
        except Exception:  # noqa: BLE001
            logger.exception("camera %s: ошибка при освобождении устройства", self.name)
