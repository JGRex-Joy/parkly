import threading
import time
from typing import Callable, List, Optional

import numpy as np
import pytest

from app.cameras import (
    CameraConnectError,
    CameraManager,
    CameraSource,
    CameraTimeoutError,
    CameraUnavailableError,
    IpCameraSource,
    UsbCameraSource,
    discover_usb_cameras,
    validate_stream_url,
)
from app.cameras import ip_camera as ip_module
from app.cameras import usb_camera as usb_module
from app.config import CameraReliability, IpCameraSettings, UsbCameraSettings, load_settings
from app.models import ConnectionState
from app.utils.urls import mask_url_credentials

FAST = CameraReliability(
    warmup_frames=2, reconnect_min_delay=0.01, reconnect_max_delay=0.05, stall_timeout=0.15, frame_timeout=1.0
)


def make_frame(value: int = 10) -> np.ndarray:
    return np.full((8, 8, 3), value, dtype=np.uint8)


class FakeCapture:
    """Выдаёт кадры с интервалом; можно «оборвать» поток (read -> False)."""

    def __init__(self, interval: float = 0.005, fail_after: Optional[int] = None):
        self.interval, self.fail_after = interval, fail_after
        self.reads = 0
        self.released = threading.Event()
        self.release_thread: Optional[str] = None
        self.reading_thread: Optional[str] = None
        self.read_during_release = False
        self._releasing = False

    def isOpened(self):
        return not self.released.is_set()

    def read(self):
        self.reading_thread = threading.current_thread().name
        if self._releasing:
            self.read_during_release = True
        time.sleep(self.interval)
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return False, None
        return True, make_frame(self.reads % 255)

    def release(self):
        self._releasing = True
        self.release_thread = threading.current_thread().name
        self.released.set()


class FakeSource(CameraSource):
    frame_source = "fake"

    def __init__(self, opener: Callable[[int], FakeCapture], rel: CameraReliability = FAST):
        super().__init__("fake", rel)
        self._opener = opener
        self.open_attempts = 0
        self.captures: List[FakeCapture] = []

    def _open_capture(self):
        self.open_attempts += 1
        capture = self._opener(self.open_attempts)  # может бросить CameraConnectError
        self.captures.append(capture)
        return capture


@pytest.fixture
def started():
    sources = []

    def _start(source):
        sources.append(source)
        source.start()
        return source

    yield _start
    for s in sources:
        s.stop()


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_returns_frame_and_skips_warmup(started):
    src = started(FakeSource(lambda n: FakeCapture()))
    frame = src.get_frame()
    assert frame.source == "fake" and frame.image.shape == (8, 8, 3)
    assert src.state is ConnectionState.CONNECTED
    assert src.captures[0].reads >= 3  # 2 прогревочных кадра прочитаны и выброшены


def test_newer_than_waits_for_a_frame_captured_after_the_request(started):
    src = started(FakeSource(lambda n: FakeCapture(interval=0.02)))
    src.get_frame()
    t0 = time.monotonic()
    frame = src.get_frame(newer_than=t0)
    assert frame.captured_at >= t0


def test_reconnects_after_open_failures_with_backoff(started):
    def opener(attempt):
        if attempt < 4:
            raise CameraConnectError("нет связи")
        return FakeCapture()

    src = started(FakeSource(opener))
    assert src.get_frame(timeout=3).image is not None
    assert src.open_attempts == 4


def test_unavailable_when_never_connects(started):
    def opener(attempt):
        raise CameraConnectError("телефон выключен")

    src = started(FakeSource(opener))
    with pytest.raises(CameraUnavailableError, match="телефон выключен"):
        src.get_frame(timeout=0.3)
    assert src.state in (ConnectionState.CONNECTING, ConnectionState.RECONNECTING)


def test_reconnects_after_stream_stalls_and_releases_old_device(started):
    def opener(attempt):
        return FakeCapture(fail_after=5) if attempt == 1 else FakeCapture()

    src = started(FakeSource(opener))
    src.get_frame()
    assert wait_until(lambda: src.open_attempts >= 2)
    assert src.captures[0].released.wait(2)
    assert src.get_frame(timeout=2).image is not None


def test_stale_frame_is_not_served_after_disconnect(started):
    def opener(attempt):
        if attempt == 1:
            return FakeCapture(fail_after=5)
        raise CameraConnectError("камера пропала")

    src = started(FakeSource(opener))
    src.get_frame()
    assert wait_until(lambda: src.state is not ConnectionState.CONNECTED)
    with pytest.raises(CameraUnavailableError):
        src.get_frame(timeout=0.2)


def test_timeout_when_connected_but_no_fresh_frame(started):
    src = started(FakeSource(lambda n: FakeCapture(interval=0.01)))
    src.get_frame()
    with pytest.raises(CameraTimeoutError):
        src.get_frame(newer_than=time.monotonic() + 60, timeout=0.2)


def test_stop_releases_device_from_reader_thread_and_ends_thread(started):
    src = FakeSource(lambda n: FakeCapture())
    src.start()
    src.get_frame()
    capture = src.captures[0]
    src.stop()
    assert capture.released.is_set()
    assert capture.release_thread == capture.reading_thread  # ресурс освобождает тот же поток, что читал
    assert not capture.read_during_release
    assert not src.is_running and src.state is ConnectionState.STOPPED
    assert not [t for t in threading.enumerate() if t.name == "camera-fake"]


def test_no_implicit_restart_after_explicit_stop():
    src = FakeSource(lambda n: FakeCapture())
    src.start()
    src.get_frame()
    src.stop()
    with pytest.raises(CameraUnavailableError):
        src.get_frame(timeout=0.1)
    assert not src.is_running


def test_stop_is_prompt_even_while_reconnecting():
    def opener(attempt):
        raise CameraConnectError("нет связи")

    src = FakeSource(opener, CameraReliability(1, 5.0, 30.0, 5.0, 1.0))
    src.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    src.stop()
    assert time.monotonic() - t0 < 1.0


# ---------------------------------------------------------------- IP-камера
def test_validate_stream_url():
    assert validate_stream_url("http://192.168.1.50:8080/video")
    assert validate_stream_url("rtsp://user:pw@192.168.1.50:8554/live")
    for bad in ("", "ftp://host/x", "http://", "192.168.1.50:8080/video"):
        with pytest.raises(ValueError):
            validate_stream_url(bad)


def test_mask_url_credentials():
    assert mask_url_credentials("rtsp://admin:secret@10.0.0.5:554/s") == "rtsp://admin:***@10.0.0.5:554/s"
    assert "secret" not in mask_url_credentials("http://a:secret@h/p")
    assert mask_url_credentials("http://h:8080/video") == "http://h:8080/video"


class RecordingVideoCapture:
    calls: list = []
    opened = True

    def __init__(self, *args):
        type(self).calls.append(args)
        self.released = False

    def isOpened(self):
        return type(self).opened and not self.released

    def read(self):
        time.sleep(0.005)
        return True, make_frame()

    def release(self):
        self.released = True

    def set(self, *a):
        return True


def test_ip_camera_opens_ffmpeg_with_timeouts_and_never_leaks_password(monkeypatch):
    import cv2

    RecordingVideoCapture.calls, RecordingVideoCapture.opened = [], True
    monkeypatch.setattr(ip_module.cv2, "VideoCapture", RecordingVideoCapture)
    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    settings = IpCameraSettings(
        enabled=True, url="rtsp://u:topsecret@192.168.1.50:8554/live", open_timeout_ms=1234,
        read_timeout_ms=4321, rtsp_transport="udp", reliability=FAST,
    )
    src = IpCameraSource(settings)
    capture = src._open_capture()
    url, backend, params = RecordingVideoCapture.calls[0]
    assert url.startswith("rtsp://") and backend == cv2.CAP_FFMPEG
    assert params == [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1234, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4321]
    import os
    assert os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] == "rtsp_transport;udp"
    capture.release()

    RecordingVideoCapture.opened = False
    with pytest.raises(CameraConnectError) as err:
        src._open_capture()
    assert "topsecret" not in str(err.value) and "***" in str(err.value)


def test_ip_camera_end_to_end_with_reconnect(monkeypatch):
    RecordingVideoCapture.calls, RecordingVideoCapture.opened = [], False
    monkeypatch.setattr(ip_module.cv2, "VideoCapture", RecordingVideoCapture)
    src = IpCameraSource(IpCameraSettings(enabled=True, url="http://192.168.1.50:8080/video", reliability=FAST))
    src.start()
    try:
        with pytest.raises(CameraUnavailableError):
            src.get_frame(timeout=0.2)
        RecordingVideoCapture.opened = True  # телефон «появился» в сети
        assert src.get_frame(timeout=3).source == "ip_camera"
    finally:
        src.stop()


# ---------------------------------------------------------------- USB-камера
class FakeUsbDevices:
    """Подменяет cv2.VideoCapture: работают только индексы из `working`."""

    def __init__(self, working):
        self.working = set(working)
        self.opened = []

    def __call__(self, index, backend=None):
        outer = self
        outer.opened.append(index)

        class Dev(RecordingVideoCapture):
            def __init__(self):
                self.released = False

            def isOpened(self):
                return index in outer.working and not self.released

            def read(self):
                time.sleep(0.003)
                return (True, make_frame(index)) if index in outer.working else (False, None)

        return Dev()


def usb_settings(**kw):
    return UsbCameraSettings(enabled=True, reliability=FAST, **kw)


def test_usb_auto_scan_skips_ignored_builtin_webcam(monkeypatch):
    devices = FakeUsbDevices(working={0, 2, 3})
    monkeypatch.setattr(usb_module.cv2, "VideoCapture", devices)
    src = UsbCameraSource(usb_settings(index=None, ignore_indexes=(0,), backend="any"))
    capture = src._open_capture()
    assert 0 not in devices.opened and src._last_index == 2
    capture.release()


def test_usb_explicit_index_and_missing_device(monkeypatch):
    devices = FakeUsbDevices(working={3})
    monkeypatch.setattr(usb_module.cv2, "VideoCapture", devices)
    assert UsbCameraSource(usb_settings(index=3, backend="any"))._open_capture() is not None
    with pytest.raises(CameraConnectError, match=r"\[1\]"):
        UsbCameraSource(usb_settings(index=1, backend="any"))._open_capture()


def test_usb_replugged_device_is_picked_up(monkeypatch):
    devices = FakeUsbDevices(working=set())
    monkeypatch.setattr(usb_module.cv2, "VideoCapture", devices)
    src = UsbCameraSource(usb_settings(index=2, backend="any"))
    src.start()
    try:
        with pytest.raises(CameraUnavailableError):
            src.get_frame(timeout=0.2)
        devices.working = {2}
        frame = src.get_frame(timeout=3)
        assert frame.source == "webcam" and int(frame.image[0, 0, 0]) == 2
    finally:
        src.stop()


def test_discover_usb_cameras(monkeypatch):
    monkeypatch.setattr(usb_module.cv2, "VideoCapture", FakeUsbDevices(working={1, 4}))
    assert [c.index for c in discover_usb_cameras("any", scan_limit=6)] == [1, 4]
    assert [c.index for c in discover_usb_cameras("any", scan_limit=6, ignore=(1,))] == [4]


# ---------------------------------------------------------------- менеджер и конфигурация
def test_sources_are_independent_and_bound_per_gate(started):
    ok = started(FakeSource(lambda n: FakeCapture()))
    ok.frame_source = "webcam"
    broken = FakeSource(lambda n: (_ for _ in ()).throw(CameraConnectError("wifi down")))
    broken.frame_source = "ip_camera"
    settings = load_settings({"CAMERA_ENTRY_SOURCE": "usb", "CAMERA_EXIT_SOURCE": "ip"})
    manager = CameraManager(settings, sources={"usb": ok, "ip": broken})
    try:
        manager.start()
        assert manager.capture("entry").source == "webcam"
        with pytest.raises(CameraUnavailableError):
            manager.capture("exit")
        assert manager.capture("entry").source == "webcam"  # поломка IP не мешает USB
    finally:
        manager.stop()


def test_manager_unavailable_when_source_disabled():
    manager = CameraManager(load_settings({"CAMERA_USB_ENABLED": "0", "CAMERA_IP_URL": ""}))
    with pytest.raises(CameraUnavailableError, match="Камера для 'entry' недоступна"):
        manager.capture("entry")


def test_settings_defaults_and_overrides():
    s = load_settings({})
    assert s.backend_base_url == "http://localhost:8000" and s.max_corrections_to_trust == 2
    assert s.usb_camera.enabled and s.usb_camera.index is None and not s.ip_camera.enabled
    s = load_settings({
        "BACKEND_BASE_URL": "http://api:9000", "CAMERA_IP_URL": "http://10.0.0.7:8080/video",
        "CAMERA_USB_INDEX": "3", "CAMERA_USB_IGNORE_INDEXES": "0, 1", "CAMERA_WARMUP_FRAMES": "9",
        "CAMERA_ENTRY_SOURCE": "ip", "CAMERA_EXIT_SOURCE": "usb",
    })
    assert s.ip_camera.enabled and s.usb_camera.index == 3 and s.usb_camera.ignore_indexes == (0, 1)
    assert s.ip_camera.reliability.warmup_frames == 9 and s.source_for_gate("entry") == "ip"
    for bad in ({"CAMERA_ENTRY_SOURCE": "bluetooth"}, {"CAMERA_USB_INDEX": "x"}, {"CAMERA_USB_BACKEND": "zzz"}):
        with pytest.raises(ValueError):
            load_settings(bad)
