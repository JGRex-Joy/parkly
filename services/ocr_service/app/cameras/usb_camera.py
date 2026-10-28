from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.cameras.base import CameraConnectError, CameraSource, VideoCaptureLike
from app.config import UsbCameraSettings
from app.utils.image import frame_problem

logger = logging.getLogger("ocr_service.cameras.usb")

BackendSpec = Tuple[str, Optional[int]]  

_OPEN_LOCK = threading.Lock()
_CLAIMS_LOCK = threading.Lock()
_CLAIMS: Dict[int, str] = {}


def _backend_table() -> Dict[str, Optional[int]]:
    return {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "v4l2": cv2.CAP_V4L2, "any": None}


def resolve_backend(name: str) -> Optional[int]:
    name = name.lower()
    if name == "auto":
        return resolve_backends("auto")[0][1]
    table = _backend_table()
    if name not in table:
        raise ValueError(f"Неизвестный бэкенд камеры: {name!r}")
    return table[name]


def resolve_backends(spec: str) -> List[BackendSpec]:
    table = _backend_table()
    names: List[str] = []
    for part in spec.lower().replace(" ", "").split(","):
        if part == "auto":
            system = platform.system()
            names += ["dshow", "msmf", "any"] if system == "Windows" else ["v4l2", "any"] if system == "Linux" else ["any"]
        elif part in table:
            names.append(part)
        else:
            raise ValueError(f"Неизвестный бэкенд камеры: {part!r}")
    result: List[BackendSpec] = []
    for name in dict.fromkeys(names):
        result.append((name, table[name]))
    if not result:
        raise ValueError("Пустой список бэкендов камеры")
    return result


def _open_index(index: int, backend: Optional[int]) -> cv2.VideoCapture:
    return cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)


@dataclass(frozen=True)
class UsbCameraInfo:
    index: int
    width: int
    height: int
    backend: str = ""
    black: bool = False  


def _read_good_frame(capture, seconds: float) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
    deadline = time.monotonic() + max(seconds, 0.0)
    black: Optional[np.ndarray] = None
    reason = "read() не вернул ни одного кадра"
    while True:
        ok, frame = capture.read()
        if ok and frame is not None and getattr(frame, "size", 0) > 0:
            problem = frame_problem(frame)
            if problem is None:
                return frame, black, ""
            black, reason = frame, problem
        else:
            time.sleep(0.03)
        if time.monotonic() >= deadline:
            return None, black, reason


def discover_usb_cameras(
    backend_name: str = "auto", scan_limit: int = 8, ignore: Sequence[int] = (), probe_seconds: float = 3.0
) -> List[UsbCameraInfo]:
    found: List[UsbCameraInfo] = []
    for index in range(scan_limit):
        if index in ignore:
            continue
        for bname, backend in resolve_backends(backend_name)[:1]:
            with _OPEN_LOCK:
                capture = _open_index(index, backend)
            try:
                if not capture.isOpened():
                    continue
                good, black, _ = _read_good_frame(capture, probe_seconds)
                frame = good if good is not None else black
                if frame is not None:
                    found.append(UsbCameraInfo(index, int(frame.shape[1]), int(frame.shape[0]), bname, good is None))
            finally:
                capture.release()
    return found


class UsbCameraSource(CameraSource):
    frame_source = "webcam"  

    def __init__(self, settings: UsbCameraSettings, name: str = "usb") -> None:
        super().__init__(name=name, reliability=settings.reliability)
        self._settings = settings
        self._backends = resolve_backends(settings.backend)
        self._last_good: Optional[Tuple[int, str]] = None  
        self._last_index: Optional[int] = None
        self._claimed: Optional[int] = None

    def _candidate_indexes(self) -> List[int]:
        if self._settings.index is not None:
            return [self._settings.index]
        indexes = [i for i in range(self._settings.scan_limit) if i not in self._settings.ignore_indexes]
        with _CLAIMS_LOCK:
            indexes = [i for i in indexes if _CLAIMS.get(i, self.name) == self.name]
        if self._last_index in indexes:
            indexes.remove(self._last_index)
            indexes.insert(0, self._last_index)
        return indexes

    def _candidates(self) -> List[Tuple[int, BackendSpec]]:
        combos = [(i, b) for i in self._candidate_indexes() for b in self._backends]
        if self._last_good is not None:
            preferred = [c for c in combos if (c[0], c[1][0]) == self._last_good]
            combos = preferred + [c for c in combos if c not in preferred]
        return combos

    def _configure(self, capture: cv2.VideoCapture) -> None:
        s = self._settings
        if s.fourcc:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*s.fourcc[:4].ljust(4)))
        if s.width > 0:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, s.width)
        if s.height > 0:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, s.height)
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  
        except Exception:  
            pass

    def _wait_for_good_frame(self, capture: VideoCaptureLike) -> Tuple[bool, str]:
        deadline = self._clock() + max(self._settings.open_timeout, 0.0)
        reason = "read() не вернул ни одного кадра"
        while not self._stop_event.is_set():
            ok, frame = capture.read()
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                problem = self._frame_problem(frame)
                if problem is None:
                    return True, ""
                reason = problem
                self._note_rejection(problem)
            else:
                self._stop_event.wait(0.03)
            if self._clock() >= deadline:
                break
        return False, reason

    def _try_open(self, index: int, bname: str, backend: Optional[int]) -> Tuple[Optional[cv2.VideoCapture], str]:
        label = f"индекс {index}/{bname}"
        with _OPEN_LOCK:
            capture = _open_index(index, backend)
        try:
            if not capture.isOpened():
                capture.release()
                return None, f"{label}: устройство не открывается"
            self._configure(capture)
            good, reason = self._wait_for_good_frame(capture)
            if not good:
                capture.release()
                return None, f"{label}: {reason} за {self._settings.open_timeout:.1f} с"
            return capture, ""
        except BaseException:
            try:
                capture.release()
            finally:
                raise

    def _open_capture(self) -> VideoCaptureLike:
        failures: List[str] = []
        tried: List[int] = []
        for index, (bname, backend) in self._candidates():
            if index not in tried:
                tried.append(index)
            if self._stop_event.is_set():
                raise CameraConnectError(f"'{self.name}': остановка во время подключения")
            capture, failure = self._try_open(index, bname, backend)
            if capture is None:
                failures.append(failure)
                logger.warning("камера %s: %s", self.name, failure)
                continue
            self._last_good, self._last_index = (index, bname), index
            self._claim(index)
            logger.info("камера %s подключена: индекс %d, бэкенд %s, кадры нормальные", self.name, index, bname)
            return capture
        raise CameraConnectError(
            f"локальная камера не найдена или отдаёт чёрные кадры (проверены индексы: {tried or 'нет'}; "
            f"{'; '.join(failures) or 'нет кандидатов'})"
        )

    def _claim(self, index: int) -> None:
        with _CLAIMS_LOCK:
            _CLAIMS[index] = self.name
            self._claimed = index

    def _unclaim(self) -> None:
        with _CLAIMS_LOCK:
            if self._claimed is not None and _CLAIMS.get(self._claimed) == self.name:
                del _CLAIMS[self._claimed]
            self._claimed = None

    def _safe_release(self, capture: Optional[VideoCaptureLike]) -> None:
        try:
            super()._safe_release(capture)
        finally:
            self._unclaim()
