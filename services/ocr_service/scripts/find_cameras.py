"""Which video device index is which camera? (Iriun and USB cameras can change index between runs.)

    python scripts/find_cameras.py                 # scan 0..9, save one JPEG per working device to ./snapshots
    python scripts/find_cameras.py --url rtsp://10.0.0.7:8554/live

Open the snapshots to see what is behind each index, then start the service with
    ENTRY_CAMERA_SOURCE=<index>  EXIT_CAMERA_SOURCE=<index>
Stop the OCR service first: a device it holds open cannot be probed.
"""
import argparse
import platform
import time
from pathlib import Path

import cv2


def grab(source, backend=None, seconds=3.0):
    cap = cv2.VideoCapture(source) if backend is None else cv2.VideoCapture(source, backend)
    try:
        if not cap.isOpened():
            return None
        end = time.monotonic() + seconds
        frame = None
        while time.monotonic() < end:
            ok, img = cap.read()
            if ok and img is not None and img.mean() > 1.0:
                frame = img
            elif frame is not None:
                break
        return frame
    finally:
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-index", type=int, default=9)
    ap.add_argument("--url", help="also test a network stream")
    ap.add_argument("--save", default="snapshots")
    args = ap.parse_args()
    out = Path(args.save)
    out.mkdir(exist_ok=True)
    backends = {"Windows": [cv2.CAP_DSHOW, cv2.CAP_MSMF], "Linux": [cv2.CAP_V4L2]}.get(platform.system(), [None])

    for index in range(args.max_index + 1):
        for backend in backends:
            frame = grab(index, backend)
            if frame is not None:
                path = out / f"device_{index}.jpg"
                cv2.imwrite(str(path), frame)
                print(f"index {index}: OK  {frame.shape[1]}x{frame.shape[0]}  -> {path}")
                break
        else:
            print(f"index {index}: no frames")
    if args.url:
        frame = grab(args.url, cv2.CAP_FFMPEG, seconds=8.0)
        print(f"{args.url}: " + ("OK" if frame is not None else "no frames"))


if __name__ == "__main__":
    main()
