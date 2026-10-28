from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  
import numpy as np  

from app.config import get_settings  
from app.repositories import OcrModelRepository  
from app.services.recognition_service import RecognitionService  


def canonical(plate: str) -> str:
    return plate[:2] + plate[4:] if len(plate) == 10 else plate


def synthetic_samples(count, fonts):
    from tests.synthetic import PlateStyle, degrade, make_scene, random_plate, render_plate

    rng = np.random.default_rng(2024)
    fonts = fonts or ["simplex", "duplex", "complex"]
    tiers = [("crop_clean", 0.3, False), ("crop_phone", 1.0, False), ("scene_phone", 1.0, True), ("scene_heavy", 2.0, True)]
    for name, level, scene in tiers:
        for i in range(count):
            truth = random_plate(rng)
            style = PlateStyle(font=fonts[i % len(fonts)], text_height=int(rng.integers(24, 46)), pitch=float(rng.uniform(0.9, 1.0)))
            img = degrade(render_plate(truth, style), rng, level)
            if scene:
                img, _ = make_scene(img, rng, tilt=float(rng.uniform(-5, 5)), perspective=0.05)
            yield name, truth, img


def dataset_samples(directory, labels_path):
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    for name, truth in labels.items():
        img = cv2.imread(str(Path(directory) / name))
        if img is None:
            print(f"пропуск {name}: не открывается", file=sys.stderr)
            continue
        yield "dataset", truth.replace(" ", "").upper(), img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    syn = sub.add_parser("synthetic")
    syn.add_argument("--count", type=int, default=20, help="номеров на каждый уровень сложности")
    syn.add_argument("--font", action="append", help="путь к .ttf/.otf шрифту номера")
    data = sub.add_parser("dataset")
    data.add_argument("--dir", required=True)
    data.add_argument("--labels", required=True)
    args = parser.parse_args()

    samples = synthetic_samples(args.count, args.font) if args.mode == "synthetic" else dataset_samples(args.dir, args.labels)
    settings = get_settings()
    service = RecognitionService(OcrModelRepository(gpu=settings.ocr.gpu), settings.ocr)
    gate_limit = settings.max_corrections_to_trust

    rows = collections.defaultdict(lambda: collections.Counter())
    confusions = collections.Counter()
    slot_conf = []  
    started = time.time()
    for group, truth, img in samples:
        result = service.recognize(cv2.imencode(".png", img)[1].tobytes())
        cand, want = result.candidate, canonical(truth)
        stat = rows[group]
        stat["n"] += 1
        if cand is None:
            stat["none"] += 1
            continue
        correct = cand.plate_number == want
        stat["exact" if correct else "wrong"] += 1
        if cand.is_valid_region and cand.corrections <= gate_limit:
            stat["gate_ok" if correct else "gate_WRONG"] += 1
        if result.slot_readings:
            slot_conf.append((min(r.confidence for r in result.slot_readings), correct))
            if not correct:
                got = "".join(r.char for r in result.slot_readings)
                confusions.update((a, b) for a, b in zip(truth, got) if a != b)

    print(f"\n{'группа':14s}{'n':>5s}{'точно':>8s}{'неверно':>9s}{'не найден':>11s}{'прошло гейт':>13s}{'НЕВЕРНО принято':>17s}")
    for group, s in rows.items():
        n = s["n"]
        print(f"{group:14s}{n:5d}{s['exact']/n:8.0%}{s['wrong']/n:9.0%}{s['none']/n:11.0%}{s['gate_ok']/n:13.0%}{s['gate_WRONG']/n:17.0%}")
    if confusions:
        print("\nчаще всего путаются (верно -> прочитано):", confusions.most_common(8))
    if slot_conf:
        print("\nOCR_MIN_SLOT_CONFIDENCE: порог -> принято / неверных среди принятых")
        for t in (0.0, 0.3, 0.5, 0.7):
            kept = [ok for c, ok in slot_conf if c >= t]
            if kept:
                print(f"  {t:.1f}: {len(kept):3d}/{len(slot_conf)}  неверных {sum(not k for k in kept)/len(kept):.0%}")
    print(f"\n{time.time() - started:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
