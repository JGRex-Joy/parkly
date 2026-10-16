from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  

import app  
from app.cameras import IpCameraSource, discover_usb_cameras, validate_stream_url  
from app.cameras.usb_camera import _open_index, resolve_backend  
from app.config import CameraReliability, IpCameraSettings  

def probe_usb(backends, limit, ignore, save_dir):
    found_any = False
    for name in backends:
        print(f"--- USB, бэкенд {name} ---")
        cams = discover_usb_cameras(name, limit, ignore)
        if not cams:
            print("  камер не найдено")
            continue
        found_any = True
        for cam in cams:
            print(f"  индекс {cam.index}: {cam.width}x{cam.height}   -> CAMERA_USB_INDEX={cam.index} CAMERA_USB_BACKEND={name}")
            if save_dir:
                capture = _open_index(cam.index, resolve_backend(name))
                try:
                    for _ in range(5):
                        capture.read()
                    ok, frame = capture.read()
                finally:
                    capture.release()
                if ok:
                    path = save_dir / f"usb_{name}_{cam.index}.jpg"
                    cv2.imwrite(str(path), frame)
                    print(f"    снимок: {path}")
    return found_any


def probe_ip(url, save_dir, timeout):
    print(f"--- IP-камера {url} ---")
    try:
        validate_stream_url(url)
    except ValueError as exc:
        print(f"  ОШИБКА: {exc}")
        return False
    reliability = CameraReliability(warmup_frames=2, reconnect_min_delay=1.0, reconnect_max_delay=5.0,
                                    stall_timeout=timeout, frame_timeout=timeout)
    source = IpCameraSource(IpCameraSettings(enabled=True, url=url, reliability=reliability))
    started = time.monotonic()
    try:
        frame = source.get_frame(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"  НЕ ПОДКЛЮЧИЛАСЬ за {timeout:.0f} с: {exc}")
        return False
    finally:
        source.stop()
    height, width = frame.image.shape[:2]
    print(f"  OK: {width}x{height}, первый кадр через {time.monotonic() - started:.1f} с")
    if save_dir:
        path = save_dir / "ip_camera.jpg"
        cv2.imwrite(str(path), frame.image)
        print(f"    снимок: {path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", action="append", choices=["auto", "dshow", "msmf", "v4l2", "any"],
                        help="бэкенд USB (можно несколько раз); по умолчанию auto")
    parser.add_argument("--limit", type=int, default=8, help="сколько индексов перебрать (по умолчанию 8)")
    parser.add_argument("--ignore", type=int, action="append", default=[], help="пропустить индекс (например, встроенную камеру)")
    parser.add_argument("--ip", help="URL потока телефона, например http://192.168.1.50:8080/video")
    parser.add_argument("--timeout", type=float, default=10.0, help="сколько ждать кадр от IP-камеры, с")
    parser.add_argument("--save", type=Path, help="папка для снимков")
    parser.add_argument("--skip-usb", action="store_true", help="не перебирать USB-камеры")
    args = parser.parse_args()

    if args.save:
        args.save.mkdir(parents=True, exist_ok=True)
    ok = True
    if not args.skip_usb:
        ok = probe_usb(args.backend or ["auto"], args.limit, tuple(args.ignore), args.save) and ok
    if args.ip:
        ok = probe_ip(args.ip, args.save, args.timeout) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
