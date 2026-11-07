from __future__ import annotations

import logging
import os
import platform
import threading
import time
from typing import List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np

from app.config import Settings

logger = logging.getLogger("ocr_service.camera")

FRAME_GAP = 0.04          
LIVE_GRAB = 0.004         
STALE_PATIENCE = 1.0      
FRAME_TIMEOUT = 3.0       
FIRST_FRAME_TIMEOUT = 5.0
_OPEN_LOCK = threading.Lock()   


class CameraError(RuntimeError):
    pass


def _is_black(img: np.ndarray) -> bool:
    return float(img.mean()) < 1.0 and float(np.percentile(img[::8, ::8], 99.5)) < 8.0


def _mask(url: str) -> str:
    try:
        p = urlsplit(url)
        return urlunsplit(p._replace(netloc=p.netloc.rsplit("@", 1)[-1])) if "@" in p.netloc else url
    except ValueError:
        return url


def _backends() -> List[Optional[int]]:
    system = platform.system()
    if system == "Windows":
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
    if system == "Linux":
        return [cv2.CAP_V4L2, None]
    return [None]


class Camera:
    def __init__(self, name: str, source: str) -> None:
        self.name = name
        self.source = source.strip()
        self._index: Optional[int] = int(self.source) if self.source.lstrip("-").isdigit() else None
        if self._index is None and "://" not in self.source:
            raise ValueError(f"{name}: camera source must be a device index or a stream URL, got {source!r}")
        self.label = "webcam" if self._index is not None else "ip_camera"
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._stamp = 0.0
        self._problem = "камера ещё подключается"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"camera-{name}", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def get(self, newer_than: float, timeout: float = FRAME_TIMEOUT) -> np.ndarray:
        deadline = time.monotonic() + timeout
        with self._cond:
            while not (self._frame is not None and self._stamp >= newer_than):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CameraError(self._problem if self._frame is None else "нет свежего кадра")
                self._cond.wait(left)
            return self._frame

    def _publish(self, img: np.ndarray, stamp: float) -> None:
        with self._cond:
            self._frame, self._stamp = img, stamp
            self._cond.notify_all()

    def _run(self) -> None:
        delay = 0.5
        while not self._stop.is_set():
            cap = self._open()
            if cap is None:
                logger.warning("[%s] камера %s недоступна, повтор через %.1f с", self.name, _mask(self.source), delay)
                self._stop.wait(delay)
                delay = min(delay * 2, 5.0)
                continue
            logger.info("[%s] камера %s подключена", self.name, _mask(self.source))
            delay, misses, last = 0.5, 0, 0.0
            last_live = time.monotonic()
            while not self._stop.is_set():
                waited = time.monotonic()
                if not cap.grab():
                    misses += 1
                    if misses > 40:
                        break
                    time.sleep(0.05)
                    continue
                misses = 0
                now = time.monotonic()
                if now - waited >= LIVE_GRAB:
                    last_live = now                     
                elif now - last_live < STALE_PATIENCE:
                    continue                            
                                                        
                if now - last < FRAME_GAP:
                    continue
                ok, img = cap.retrieve()
                if ok and img is not None and img.size and not _is_black(img):
                    last = now
                    self._publish(img, now)
            cap.release()
            self._problem = "поток прервался, переподключение"
            logger.warning("[%s] %s", self.name, self._problem)

    def _open(self) -> Optional[cv2.VideoCapture]:
        with _OPEN_LOCK:
            if self._index is not None:
                for backend in _backends():
                    cap = cv2.VideoCapture(self._index) if backend is None else cv2.VideoCapture(self._index, backend)
                    if cap.isOpened():
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        if self._settle(cap):
                            return cap
                    cap.release()
                self._problem = f"устройство {self._index} не отдаёт кадры"
                return None
            if self.source.lower().startswith("rtsp"):
                os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if self._settle(cap):
                    return cap
            cap.release()
            self._problem = "поток недоступен"
            return None

    @staticmethod
    def _settle(cap: cv2.VideoCapture) -> bool:
        deadline = time.monotonic() + FIRST_FRAME_TIMEOUT
        good = 0
        while time.monotonic() < deadline:
            ok, img = cap.read()
            if ok and img is not None and img.size and not _is_black(img):
                good += 1
                if good >= 3:
                    return True
            else:
                time.sleep(0.03)
        return False


class CameraHub:
    def __init__(self, settings: Settings) -> None:
        entry = Camera("entry", settings.entry_camera_source)
        same = settings.exit_camera_source.strip() == settings.entry_camera_source.strip()
        self._cameras = {"entry": entry, "exit": entry if same else Camera("exit", settings.exit_camera_source)}

    def start(self) -> None:
        for cam in set(self._cameras.values()):
            cam.start()

    def stop(self) -> None:
        for cam in set(self._cameras.values()):
            cam.stop()

    def capture(self, gate: str) -> Tuple[np.ndarray, str]:
        cam = self._cameras.get(gate)
        if cam is None:
            raise CameraError(f"Камера для '{gate}' не настроена")
        requested_at = time.monotonic()
        try:
            return cam.get(requested_at), cam.label
        except CameraError as exc:
            raise CameraError(f"Камера для '{gate}' недоступна: {exc}") from exc
