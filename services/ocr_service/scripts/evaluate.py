"""Measure the recognition pipeline.

    python scripts/evaluate.py                 # built-in synthetic benchmark (plates of growing size, ~1280x720 scenes)
    python scripts/evaluate.py photos/         # read every .jpg/.png in a folder, print plate + time per image

Prints accuracy (synthetic only), mean / worst latency, and how many reads were wrong (the number that matters).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.recognizer import OcrEngine, RecognitionService  # noqa: E402


def read(svc, frame):
    t = time.perf_counter()
    r = svc.recognize(frame, thorough=False)
    return r, (time.perf_counter() - t) * 1000


def folder(svc, path):
    for p in sorted(Path(path).iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            img = cv2.imread(str(p))
            if img is None:
                continue
            r, ms = read(svc, img)
            plate = r.candidate.formatted if r.candidate else "-"
            print(f"{p.name:40} {plate:16} conf={r.confidence:.2f} {ms:5.0f} ms  via {r.crop.method if r.crop else '-'}")


def synthetic(svc, n=36):
    from tests.synthetic import PlateStyle, degrade, make_scene, random_plate, render_plate
    fonts = ["/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "C:/Windows/Fonts/arialbd.ttf", "simplex"]
    font = next((f for f in fonts if f == "simplex" or Path(f).exists()), "simplex")
    rng = np.random.default_rng(7)
    ok = wrong = 0
    times = []
    for i in range(n):
        text = random_plate(rng)
        plate = render_plate(text, PlateStyle(font=font, text_height=34))
        width = int(220 + 240 * i / max(n - 1, 1))
        scene, _ = make_scene(plate, rng, plate_width=width, tilt=float(rng.uniform(-6, 6)), perspective=float(rng.uniform(0, 0.1)))
        r, ms = read(svc, degrade(scene, rng, 0.5))
        times.append(ms)
        expected = text[:2] + text[4:]
        got = r.candidate.plate_number if r.candidate else None
        ok += got == expected
        wrong += got is not None and got != expected
    print(f"font={Path(font).name}  exact {ok}/{n}  wrong reads {wrong}  mean {np.mean(times):.0f} ms  worst {max(times):.0f} ms")


if __name__ == "__main__":
    engine = OcrEngine()
    engine.warm_up()
    service = RecognitionService(engine)
    folder(service, sys.argv[1]) if len(sys.argv) > 1 else synthetic(service)
