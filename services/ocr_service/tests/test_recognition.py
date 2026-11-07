"""Real pipeline (OpenCV + EasyOCR) on the real fixture and on synthetic scenes."""
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.synthetic import PlateStyle, degrade, make_scene, random_plate, render_plate

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.ocr_model


def scene(font, seed, width, light_on_dark=False, pitch=1.0, tilt=3.0):
    rng = np.random.default_rng(seed)
    text = random_plate(rng)
    plate = render_plate(text, PlateStyle(font=font, text_height=34, light_on_dark=light_on_dark, pitch=pitch, frame=True))
    img, _ = make_scene(plate, rng, plate_width=width, tilt=tilt, perspective=0.06)
    return text[:2] + text[4:], degrade(img, rng, 0.5)


def test_real_fixture_reads_perfectly(service):
    """Light text on dark, tiny crop, 'AAA' glyphs touching each other."""
    r = service.recognize(cv2.imread(str(FIXTURES / "num.png")), thorough=False)
    assert r.candidate.formatted == "01 KG 111 AAA"
    assert r.candidate.plate_number == "01111AAA"      # contract: no country code
    assert r.candidate.corrections == 0 and r.crop.method == "already_cropped"


def test_accepts_encoded_bytes_like_the_http_layer(service):
    ok, png = cv2.imencode(".png", cv2.imread(str(FIXTURES / "num.png")))
    assert service.recognize(png.tobytes()).candidate.formatted == "01 KG 111 AAA"


def test_bad_bytes_raise_value_error(service):
    with pytest.raises(ValueError):
        service.recognize(b"not an image")


@pytest.mark.parametrize("light_on_dark,pitch", [(False, 1.0), (False, 0.8), (True, 1.0)])
def test_synthetic_scenes_never_give_a_wrong_plate(service, plate_font, light_on_dark, pitch):
    exact = wrong = 0
    for seed in range(6):
        expected, frame = scene(plate_font, 40 + seed, 380, light_on_dark, pitch)
        r = service.recognize(frame, thorough=False)
        got = r.candidate.plate_number if r.candidate else None
        exact += got == expected
        wrong += got is not None and got != expected
    assert wrong == 0
    assert exact >= 4


def test_fast_path_is_fast(service, plate_font):
    _, frame = scene(plate_font, 5, 380)
    service.recognize(frame, thorough=False)
    start = time.perf_counter()
    for _ in range(3):
        service.recognize(frame, thorough=False)
    assert (time.perf_counter() - start) / 3 < 1.0      # generous bound for slow CI; typically ~0.1-0.3 s


@pytest.mark.parametrize("make", [
    lambda: np.random.default_rng(1).integers(0, 255, (720, 1280, 3), dtype=np.uint8),
    lambda: np.full((720, 1280, 3), 120, np.uint8),
])
def test_frames_without_a_plate_are_rejected_quickly(service, make):
    start = time.perf_counter()
    assert service.recognize(make(), thorough=False).candidate is None
    assert time.perf_counter() - start < 1.0
