import time

import numpy as np
import pytest

from app import camera as cam
from app.camera import Camera, CameraError, CameraHub
from app.config import load_settings


class FakeCap:
    """Scripted cv2.VideoCapture: yields frames forever at ~100 fps; optionally dies after ``die_after`` grabs."""
    opened = 0

    def __init__(self, *args, die_after=None, black_first=0, **kw):
        FakeCap.opened += 1
        self.n, self.die_after, self.black_first = 0, die_after, black_first

    def isOpened(self): return True
    def set(self, *a): return True
    def release(self): pass

    def _frame(self):
        self.n += 1
        if self.n <= self.black_first:
            return np.zeros((20, 30, 3), np.uint8)
        return np.full((20, 30, 3), min(self.n, 250), np.uint8)

    def read(self):
        return self.grab(), self._frame() if self.grab_ok() else None

    def grab_ok(self): return self.die_after is None or self.n < self.die_after

    def grab(self):
        time.sleep(0.01)
        return self.grab_ok()

    def retrieve(self):
        return True, self._frame()


@pytest.fixture
def patch_cv(monkeypatch):
    def install(**kw):
        FakeCap.opened = 0
        monkeypatch.setattr(cam.cv2, "VideoCapture", lambda *a, **k: FakeCap(*a, **kw))
        monkeypatch.setattr(cam, "_backends", lambda: [None])
    return install


def test_source_validation():
    assert Camera("entry", "2").label == "webcam"
    assert Camera("entry", "rtsp://u:p@10.0.0.7/live").label == "ip_camera"
    with pytest.raises(ValueError):
        Camera("entry", "not-a-source")


def test_get_returns_a_frame_grabbed_after_the_request(patch_cv):
    patch_cv()
    c = Camera("entry", "0")
    c.start()
    try:
        first = c.get(time.monotonic())
        time.sleep(0.2)
        second = c.get(time.monotonic())
        assert second.mean() > first.mean()             # a newer frame, not the cached one
    finally:
        c.stop()


class BacklogCap(FakeCap):
    """First 30 grabs return instantly with 'old' frames (value 7), then live frames (value 200) every 10 ms."""
    grabs = 0

    def grab(self):
        BacklogCap.grabs += 1
        if BacklogCap.grabs <= 30:                  # backlog: returns instantly
            return True
        time.sleep(0.01)                            # live: waits for the sensor
        return True

    def _frame(self):
        self.n += 1
        return np.full((20, 30, 3), 7 if BacklogCap.grabs <= 30 else 200, np.uint8)

    def retrieve(self):
        return True, self._frame()


def test_backlog_frames_are_not_passed_off_as_fresh(monkeypatch):
    BacklogCap.grabs = 0
    monkeypatch.setattr(cam.cv2, "VideoCapture", lambda *a, **k: BacklogCap())
    monkeypatch.setattr(cam, "_backends", lambda: [None])
    monkeypatch.setattr(BacklogCap, "read", lambda self: (True, np.full((20, 30, 3), 200, np.uint8)))
    c = Camera("entry", "0")
    c.start()
    try:
        assert int(c.get(time.monotonic(), timeout=3.0).mean()) == 200
    finally:
        c.stop()


def test_black_frames_are_never_published(patch_cv):
    patch_cv(black_first=8)
    c = Camera("entry", "0")
    c.start()
    try:
        assert c.get(time.monotonic(), timeout=3.0).max() > 0
    finally:
        c.stop()


def test_reconnects_after_the_stream_dies(patch_cv, monkeypatch):
    monkeypatch.setattr(cam.time, "sleep", lambda s: None)
    patch_cv(die_after=12)
    c = Camera("entry", "0")
    c.start()
    try:
        deadline = time.monotonic() + 5
        while FakeCap.opened < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert FakeCap.opened >= 2
        assert c.get(time.monotonic(), timeout=3.0) is not None
    finally:
        c.stop()


def test_unavailable_camera_reports_a_reason(monkeypatch):
    class Dead:
        def __init__(self, *a, **k): pass
        def isOpened(self): return False
        def release(self): pass

    monkeypatch.setattr(cam.cv2, "VideoCapture", Dead)
    monkeypatch.setattr(cam, "_backends", lambda: [None])
    original = Camera.get
    monkeypatch.setattr(Camera, "get", lambda self, newer_than, timeout=0.6: original(self, newer_than, 0.6))
    hub = CameraHub(load_settings({"ENTRY_CAMERA_SOURCE": "0", "EXIT_CAMERA_SOURCE": "1"}))
    hub.start()
    try:
        with pytest.raises(CameraError) as e:
            hub.capture("entry")
        assert str(e.value).startswith("Камера для 'entry' недоступна:") and "устройство 0" in str(e.value)
    finally:
        hub.stop()


def test_same_source_for_both_gates_shares_one_reader():
    hub = CameraHub(load_settings({"ENTRY_CAMERA_SOURCE": "1", "EXIT_CAMERA_SOURCE": "1"}))
    assert hub._cameras["entry"] is hub._cameras["exit"]
    with pytest.raises(CameraError):
        hub.capture("side")
