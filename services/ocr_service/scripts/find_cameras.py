from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  

import app  
from app.cameras import IpCameraSource, discover_usb_cameras, resolve_backends, validate_stream_url
from app.cameras.usb_camera import _open_index, _read_good_frame
from app.config import CameraReliability, IpCameraSettings

def probe_usb(backends, limit, ignore, save_dir, probe_seconds=4.0):
    found_any = False
    for name in backends:
        print(f"--- локальные камеры, бэкенд {name} ---")
        cams = discover_usb_cameras(name, limit, ignore, probe_seconds=probe_seconds)
        if not cams:
            print("  камер не найдено")
            continue
        for cam in cams:
            if cam.black:
                print(f"  индекс {cam.index}: {cam.width}x{cam.height}  ЧЁРНЫЕ КАДРЫ — запустите Iriun на телефоне "
                      f"или попробуйте другой --backend")
            else:
                found_any = True
                print(f"  индекс {cam.index}: {cam.width}x{cam.height}  OK   -> CAMERA_<USB|WIFI>_INDEX={cam.index} "
                      f"CAMERA_<USB|WIFI>_BACKEND={name}")
            if save_dir:
                capture = _open_index(cam.index, resolve_backends(name)[0][1])
                try:
                    good, black, _ = _read_good_frame(capture, probe_seconds)
                finally:
                    capture.release()
                frame = good if good is not None else black
                if frame is not None:
                    path = save_dir / f"local_{name}_{cam.index}.jpg"
                    cv2.imwrite(str(path), frame)
                    print(f"    снимок: {path}  (откройте и убедитесь, что это нужная камера)")
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
    except Exception as exc:  
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
                        help="бэкенд (можно несколько раз); по умолчанию — вся цепочка auto для вашей ОС")
    parser.add_argument("--limit", type=int, default=8, help="сколько индексов перебрать (по умолчанию 8)")
    parser.add_argument("--ignore", type=int, action="append", default=[], help="пропустить индекс (например, встроенную камеру)")
    parser.add_argument("--ip", help="URL потока телефона, например http://192.168.1.50:8080/video")
    parser.add_argument("--timeout", type=float, default=10.0, help="сколько ждать кадр от IP-камеры, с")
    parser.add_argument("--save", type=Path, help="папка для снимков")
    parser.add_argument("--skip-usb", action="store_true", help="не перебирать локальные камеры")
    args = parser.parse_args()

    if args.save:
        args.save.mkdir(parents=True, exist_ok=True)
    ok = True
    if not args.skip_usb:
        backends = args.backend or [name for name, _ in resolve_backends("auto")]
        ok = probe_usb(backends, args.limit, tuple(args.ignore), args.save) and ok
    if args.ip:
        ok = probe_ip(args.ip, args.save, args.timeout) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
