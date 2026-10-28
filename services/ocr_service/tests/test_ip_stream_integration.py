import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.cameras import CameraManager, CameraUnavailableError, IpCameraSource
from app.config import CameraReliability, IpCameraSettings, load_settings
from app.models import ConnectionState
from app.repositories import FixtureRepository
from app.services.camera_service import CameraService

PLATE = cv2.imread(str(Path(__file__).parent / "fixtures" / "num.png"))
RELIABILITY = CameraReliability(warmup_frames=2, reconnect_min_delay=0.1, reconnect_max_delay=0.4,
                                stall_timeout=1.0, frame_timeout=6.0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MjpegServer:
    def __init__(self, port: int):
        self.port = port
        self._halt = threading.Event()
        halt = self._halt

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/video":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                n = 0
                try:
                    while not halt.is_set():
                        frame = PLATE.copy()
                        cv2.putText(frame, str(n % 100), (2, 12), cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 255, 0), 1)
                        ok, jpg = cv2.imencode(".jpg", frame)
                        data = jpg.tobytes()
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(data))
                        self.wfile.write(data + b"\r\n")
                        n += 1
                        time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        ThreadingHTTPServer.allow_reuse_address = True
        ThreadingHTTPServer.daemon_threads = True
        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/video"

    def stop(self):
        self._halt.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(5)


def make_source(url: str) -> IpCameraSource:
    return IpCameraSource(IpCameraSettings(enabled=True, url=url, open_timeout_ms=2000, read_timeout_ms=2000,
                                           reliability=RELIABILITY))


@pytest.fixture
def server():
    srv = MjpegServer(free_port())
    yield srv
    srv.stop()


def wait_until(predicate, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_reads_real_mjpeg_stream(server):
    source = make_source(server.url)
    try:
        frame = source.get_frame()
        assert frame.source == "ip_camera" and frame.image.shape == PLATE.shape
        assert source.state is ConnectionState.CONNECTED
    finally:
        source.stop()


def test_frames_keep_flowing_and_newer_than_is_respected(server):
    source = make_source(server.url)
    try:
        first = source.get_frame()
        requested_at = time.monotonic()
        later = source.get_frame(newer_than=requested_at)
        assert later.captured_at >= requested_at > first.captured_at
        assert not np.array_equal(first.image, later.image)  
    finally:
        source.stop()


def test_reconnects_after_stream_is_lost_and_restored(server):
    port = server.port
    source = make_source(server.url)
    restarted = None
    try:
        source.get_frame()
        server.stop()                                        
        assert wait_until(lambda: source.state is not ConnectionState.CONNECTED)
        with pytest.raises(CameraUnavailableError):
            source.get_frame(timeout=0.5)                    
        restarted = MjpegServer(port)                        
        assert source.get_frame(timeout=15).image.shape == PLATE.shape
        assert source.state is ConnectionState.CONNECTED
    finally:
        source.stop()
        if restarted:
            restarted.stop()


def test_unreachable_phone_is_reported_not_hung():
    source = make_source(f"http://127.0.0.1:{free_port()}/video")
    try:
        t0 = time.monotonic()
        with pytest.raises(CameraUnavailableError):
            source.get_frame(timeout=1.5)
        assert time.monotonic() - t0 < 5
    finally:
        source.stop()


def test_stop_releases_stream_promptly(server):
    source = make_source(server.url)
    source.get_frame()
    t0 = time.monotonic()
    source.stop()
    assert time.monotonic() - t0 < 5 and not source.is_running
    assert not [t for t in threading.enumerate() if t.name == "camera-ip"]


def test_gate_capture_through_manager_and_service(server, tmp_path):
    settings = load_settings({"CAMERA_IP_URL": server.url, "CAMERA_ENTRY_SOURCE": "ip", "CAMERA_EXIT_SOURCE": "ip",
                              "CAMERA_USB_ENABLED": "0", "CAMERA_FIXTURE_FALLBACK": "0"})
    manager = CameraManager(settings, sources={"ip": make_source(server.url)})
    service = CameraService(settings, manager, FixtureRepository(tmp_path))
    try:
        manager.start()
        jpeg, source = service.capture_frame_bytes("exit")
        assert source == "ip_camera"
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == PLATE.shape
    finally:
        manager.stop()


def test_service_falls_back_to_fixture_only_when_enabled(tmp_path):
    cv2.imwrite(str(tmp_path / "sample_plate.jpg"), PLATE)
    dead_url = f"http://127.0.0.1:{free_port()}/video"
    fast = CameraReliability(warmup_frames=0, reconnect_min_delay=0.05, reconnect_max_delay=0.1, stall_timeout=0.5, frame_timeout=0.6)
    for enabled, expect in ((True, "fixture"), (False, None)):
        settings = load_settings({"CAMERA_IP_URL": dead_url, "CAMERA_ENTRY_SOURCE": "ip",
                                  "CAMERA_USB_ENABLED": "0", "CAMERA_FIXTURE_FALLBACK": str(enabled)})
        source = IpCameraSource(IpCameraSettings(enabled=True, url=dead_url, open_timeout_ms=500, read_timeout_ms=500, reliability=fast))
        manager = CameraManager(settings, sources={"ip": source})
        service = CameraService(settings, manager, FixtureRepository(tmp_path))
        try:
            if expect:
                assert service.capture_frame_bytes("entry")[1] == "fixture"
            else:
                with pytest.raises(RuntimeError, match="Камера для 'entry' недоступна"):
                    service.capture_frame_bytes("entry")
        finally:
            manager.stop()
