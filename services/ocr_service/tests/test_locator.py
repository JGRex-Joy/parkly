import numpy as np

from app.plate_locator import extract_line, find_candidates, looks_like_crop, slot_groups
from tests.synthetic import PlateStyle, make_scene, render_plate


def frame(font="simplex", tilt=0.0, width=380, seed=3):
    rng = np.random.default_rng(seed)
    plate = render_plate("01KG111AAA", PlateStyle(font=font, text_height=34, frame=True))
    return make_scene(plate, rng, plate_width=width, tilt=tilt, perspective=0.0)[0]


def test_crop_detection():
    assert looks_like_crop(np.zeros((40, 150, 3), np.uint8))
    assert not looks_like_crop(np.zeros((720, 1280, 3), np.uint8))


def test_finds_the_plate_and_cuts_a_ten_glyph_strip(plate_font):
    img = frame(plate_font, tilt=4.0)
    lines = [extract_line(c.image) for c in find_candidates(img)]
    good = [l for l in lines if l is not None and l.glyphs == 10]
    assert good, "no candidate produced a 10-glyph character strip"
    strip = good[0].image
    assert strip.shape[0] == 64 and strip.dtype == np.uint8
    assert strip[:, :].mean() > 128                                    # dark text on a light background
    assert [cls for cls, _ in slot_groups(good[0])] == ["D", "L", "D", "L"]


def test_light_on_dark_plates_are_normalised_to_dark_on_light(plate_font):
    rng = np.random.default_rng(4)
    plate = render_plate("01KG111AAA", PlateStyle(font=plate_font, text_height=34, light_on_dark=True, frame=True))
    img = make_scene(plate, rng, plate_width=380, tilt=0, perspective=0.0)[0]
    lines = [extract_line(c.image) for c in find_candidates(img)]
    assert any(l is not None and l.glyphs == 10 and l.image.mean() > 128 for l in lines)


def test_no_text_means_no_strip():
    assert extract_line(np.full((90, 300, 3), 200, np.uint8)) is None
    noise = np.random.default_rng(0).integers(0, 255, (90, 300, 3), dtype=np.uint8)
    assert extract_line(noise) is None


def test_huge_crops_are_cheap():
    import time
    big = np.full((900, 3000, 3), 180, np.uint8)
    t = time.perf_counter()
    extract_line(big)
    assert time.perf_counter() - t < 0.5
