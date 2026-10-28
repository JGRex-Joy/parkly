from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import OcrSettings
from app.models import Segmentation
from app.services.glyph_recognizer import combine_confidence, glyph_canvases
from app.services.plate_locator import find_plate_candidates, looks_like_crop
from app.services.preprocessing import detect_inverted, estimate_text_height, is_frame_component, normalize_line
from app.services.segmentation import segment_line
from tests.synthetic import PlateStyle, degrade, make_scene, random_plate, render_plate, rotate

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = cv2.imread(str(FIXTURES / "num.png"))
HERSHEY = ("simplex", "duplex", "complex")


def segment(img):
    line = normalize_line(img)
    return (line, segment_line(line)) if line is not None else (None, None)


def test_sample_is_light_on_dark_and_gets_normalized():
    gray = cv2.cvtColor(SAMPLE, cv2.COLOR_BGR2GRAY)
    assert detect_inverted(gray) is True
    line = normalize_line(SAMPLE)
    assert line.inverted and line.scale > 2          
    assert line.gray.shape == line.detail.shape == line.ink.shape
    assert np.median(line.gray) > 200                 


@pytest.mark.parametrize("light_on_dark", [False, True])
def test_polarity_detection_on_synthetic(light_on_dark):
    img = render_plate("07KG482XYZ", PlateStyle(text_height=34, light_on_dark=light_on_dark))
    assert detect_inverted(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)) is light_on_dark


def test_regression_dark_surround_does_not_hide_the_text():
    plate = render_plate("09KG512ABC", PlateStyle(text_height=30))
    framed = cv2.copyMakeBorder(plate, 12, 12, 30, 30, cv2.BORDER_CONSTANT, value=(35, 35, 35))
    line, seg = segment(framed)
    assert line is not None and seg is not None and len(seg.slots) == 10 and seg.score > 0.8


def test_regression_text_height_uses_line_of_glyphs_not_tallest_blob():
    ink = np.zeros((120, 600), np.uint8)
    for i in range(10):
        ink[40:80, 40 + i * 40:40 + i * 40 + 22] = 255       
    ink[0:120, 560:590] = 255                                 
    height, band = estimate_text_height(ink)
    assert height == 40 and band == (40, 80)


def test_frame_component_rules():
    shape = (60, 400)
    assert is_frame_component(0, 0, 400, 60, shape)            
    assert is_frame_component(0, 2, 380, 4, shape)             
    assert is_frame_component(0, 0, 3, 60, shape)              
    assert not is_frame_component(100, 15, 20, 30, shape)      
    assert not is_frame_component(0, 15, 20, 45, shape)        


def test_sample_splits_into_ten_even_slots_including_merged_AAA():
    _, seg = segment(SAMPLE)
    assert len(seg.slots) == 10 and seg.score > 0.9
    spans = [(s.x0, s.x1) for s in seg.slots]
    assert all(a[1] <= b[0] + 1 for a, b in zip(spans, spans[1:]))     
    last = [s.x1 - s.x0 for s in seg.slots[-3:]]                       
    assert max(last) - min(last) <= 0.2 * max(last)


@pytest.mark.parametrize("font", HERSHEY)
@pytest.mark.parametrize("light_on_dark", [False, True])
@pytest.mark.parametrize("pitch", [1.0, 0.88])
def test_segments_into_ten_slots_for_fonts_polarities_and_spacing(font, light_on_dark, pitch):
    rng = np.random.default_rng(5)
    img = degrade(render_plate(random_plate(rng), PlateStyle(font=font, text_height=30, pitch=pitch,
                                                            light_on_dark=light_on_dark)), rng, 0.5)
    _, seg = segment(img)
    assert seg is not None and len(seg.slots) == 10 and seg.score >= 0.8


def test_touching_glyphs_are_still_split_into_ten():
    img = render_plate("04KG123MWA", PlateStyle(font="duplex", text_height=34, pitch=0.78))
    _, seg = segment(img)
    assert seg is not None and len(seg.slots) == 10


def test_small_low_resolution_text_like_the_sample():
    rng = np.random.default_rng(9)
    style = PlateStyle(font="simplex", text_height=13, pitch=0.9, light_on_dark=True, frame=False,
                       margin_x=0.6, margin_y=1.0)
    _, seg = segment(degrade(render_plate(random_plate(rng), style), rng, 0.3))
    assert seg is not None and len(seg.slots) == 10


MIN_SCORE = OcrSettings().min_segmentation_score


@pytest.mark.parametrize("name,image", [
    ("blank", np.full((60, 300, 3), 200, np.uint8)),
    ("noise", np.random.default_rng(1).integers(0, 255, (60, 300, 3)).astype(np.uint8)),
])
def test_non_text_is_not_accepted_as_a_plate(name, image):
    _, seg = segment(image)
    assert seg is None or seg.score < MIN_SCORE


@pytest.mark.parametrize("font", ["simplex", "duplex"])
@pytest.mark.parametrize("text", ["01KG11", "01KG1111", "01KG111AA"])     
def test_lines_shorter_than_ten_characters_are_rejected(text, font):
    _, seg = segment(render_plate(text, PlateStyle(font=font, text_height=30)))
    assert seg is None or seg.score < MIN_SCORE


@pytest.mark.parametrize("font", ["simplex", "duplex"])
@pytest.mark.parametrize("text", ["01KG111AAAB", "01KG111AAAB1", "01KG111AAA01KG11"])   
def test_regression_lines_longer_than_ten_characters_are_rejected(text, font):
    _, seg = segment(render_plate(text, PlateStyle(font=font, text_height=30)))
    assert seg is None or seg.score < MIN_SCORE


def test_exactly_ten_characters_are_accepted_with_high_score():
    _, seg = segment(render_plate("01KG111AAA", PlateStyle(font="simplex", text_height=30)))
    assert seg is not None and seg.score > 0.9


def test_text_touching_the_crop_edge_scores_lower_than_a_complete_line():
    full = render_plate("03KG777KKK", PlateStyle(text_height=30, frame=False))
    cut = full[:, : int(full.shape[1] * 0.78)]               
    _, seg_full = segment(full)
    _, seg_cut = segment(cut)
    assert seg_full is not None and (seg_cut is None or seg_cut.score < seg_full.score)


def test_crop_vs_full_frame_detection():
    assert looks_like_crop(SAMPLE)
    assert not looks_like_crop(np.zeros((720, 1280, 3), np.uint8))
    assert find_plate_candidates(SAMPLE)[0].method == "already_cropped"


@pytest.mark.parametrize("seed", range(6))
def test_plate_is_found_in_a_cluttered_scene(seed):
    rng = np.random.default_rng(100 + seed)
    plate = degrade(render_plate(random_plate(rng), PlateStyle(font=HERSHEY[seed % 3], text_height=34)), rng, 1.0)
    scene, _ = make_scene(plate, rng, tilt=float(rng.uniform(-5, 5)), perspective=0.05)
    best = 0.0
    for crop in find_plate_candidates(scene):
        _, seg = segment(crop.image)
        if seg is not None and len(seg.slots) == 10:
            best = max(best, seg.score)
    assert best >= 0.8


def test_confidence_when_model_agrees_with_constraint_is_its_own_confidence():
    assert combine_confidence("K", 0.61, "K", 1.0) == pytest.approx(0.61)


def test_confidence_when_constraint_overrode_the_model_is_discounted():
    assert combine_confidence("O", 0.9, "0", 1.0) == pytest.approx(0.1)
    assert combine_confidence("O", 0.3, "0", 0.8) == pytest.approx(0.56)


def test_glyph_canvases_have_equal_height_and_minimum_aspect():
    _, seg = segment(SAMPLE)
    canvases = glyph_canvases(Segmentation(gray=seg.gray, slots=seg.slots, score=seg.score))
    assert len(canvases) == 10 and len({c.shape[0] for c in canvases}) == 1
    assert all(c.shape[1] >= 0.85 * c.shape[0] for c in canvases)       


@pytest.fixture(scope="module")
def service():
    pytest.importorskip("easyocr")
    from app.repositories import OcrModelRepository
    from app.services.recognition_service import RecognitionService

    repo = OcrModelRepository()
    try:
        repo.get_reader()
    except Exception as exc:  
        pytest.skip(f"модель EasyOCR недоступна: {exc}")
    return RecognitionService(repo, OcrSettings())


def encode(img):
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.mark.ocr_model
def test_attached_sample_is_read_correctly(service):
    result = service.recognize((FIXTURES / "num.png").read_bytes())
    plate = result.candidate
    assert plate is not None and plate.formatted == "01 KG 111 AAA" and plate.plate_number == "01111AAA"
    assert plate.corrections == 0 and plate.is_valid_region
    assert result.crop.method == "already_cropped" and result.confidence > 0.8
    assert [d.text for d in result.detections] and len(result.slot_readings) == 10


@pytest.mark.ocr_model
@pytest.mark.parametrize("light_on_dark", [False, True])
def test_clean_synthetic_plates_are_read_exactly(service, light_on_dark):
    rng = np.random.default_rng(21)
    for i in range(6):
        truth = random_plate(rng)
        img = degrade(render_plate(truth, PlateStyle(font=HERSHEY[i % 3], text_height=32, light_on_dark=light_on_dark)), rng, 0.3)
        plate = service.recognize(encode(img)).candidate
        assert plate is not None and plate.plate_number == truth[:2] + truth[4:], truth


@pytest.mark.ocr_model
def test_plate_in_a_full_frame_is_read(service):
    rng = np.random.default_rng(31)
    hits = 0
    for i in range(5):
        truth = random_plate(rng)
        plate = degrade(render_plate(truth, PlateStyle(font=HERSHEY[i % 3], text_height=34)), rng, 1.0)
        scene, _ = make_scene(plate, rng, tilt=float(rng.uniform(-4, 4)), perspective=0.04)
        candidate = service.recognize(encode(scene)).candidate
        hits += candidate is not None and candidate.plate_number == truth[:2] + truth[4:]
    assert hits >= 4


@pytest.mark.ocr_model
def test_class_constraint_never_puts_a_letter_in_a_digit_slot(service):
    rng = np.random.default_rng(41)
    for _ in range(4):
        img = degrade(render_plate(random_plate(rng), PlateStyle(font="duplex", text_height=30)), rng, 1.5)
        for r in service.recognize(encode(img)).slot_readings:
            assert r.char == "" or (r.char.isdigit() if r.index in (0, 1, 4, 5, 6) else r.char.isalpha())


@pytest.mark.ocr_model
def test_rotated_crop_and_garbage_input_do_not_crash(service):
    img = rotate(render_plate("05KG246PQR", PlateStyle(font="simplex", text_height=30)), 4)
    assert service.recognize(encode(img)).candidate is not None
    assert service.recognize(encode(np.full((200, 300, 3), 90, np.uint8))).candidate is None
    with pytest.raises(ValueError):
        service.recognize(b"not an image")
