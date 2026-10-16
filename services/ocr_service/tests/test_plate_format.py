import pytest

from app.models import PlateCandidate
from app.services.plate_format import (
    SLOT_CLASSES,
    build_candidate,
    matches_format,
    match_country,
    parse_text,
)


def test_slot_layout_is_2_digits_2_letters_3_digits_3_letters():
    assert "".join(SLOT_CLASSES) == "DDLLDDDLLL"


@pytest.mark.parametrize("plate,ok", [
    ("01KG111AAA", True), ("11KG999ZZZ", True),
    ("01KG11AAA", False), ("01KG1111AAA", False), ("O1KG111AAA", False),
    ("01KG111AA", False), ("01kg111aaa", False), ("0KKG111AAA", False), ("", False),
])
def test_matches_format(plate, ok):
    assert matches_format(plate) is ok


def test_candidate_output_matches_legacy_contract():
    cand = build_candidate(list("01KG111AAA"), 0, "KG")
    assert cand == PlateCandidate("01", "KG", "111", "AAA", 0)
    assert cand.plate_number == "01111AAA"       # как раньше: без пробелов и без KG
    assert cand.formatted == "01 KG 111 AAA"     # то, что получает backend
    assert cand.is_valid_region


@pytest.mark.parametrize("region,valid", [("00", False), ("01", True), ("11", True), ("12", False), ("99", False)])
def test_region_validity_range_unchanged(region, valid):
    cand = build_candidate(list(f"{region}KG111AAA"), 0, "KG")
    assert cand.is_valid_region is valid


def test_wrong_class_in_slot_is_rejected():
    assert build_candidate(list("0OKG111AAA"), 0, "KG") is None
    assert build_candidate(list("01KG1I1AAA"), 0, "KG") is None
    assert build_candidate(list("01KG111AA1"), 0, "KG") is None
    assert build_candidate(list("01KG111AA"), 0, "KG") is None


def test_country_code_tolerates_one_misread_letter_and_counts_it():
    assert match_country("KG", "KG") == ("KG", 0)
    assert match_country("KC", "KG") == ("KG", 1)
    assert match_country("XY", "KG") is None
    assert match_country("XY", "") == ("XY", 0)   # проверка страны отключена
    cand = build_candidate(list("01KC111AAA"), 1, "KG")
    assert cand.country == "KG" and cand.corrections == 2
    assert build_candidate(list("01XY111AAA"), 0, "KG") is None


@pytest.mark.parametrize("raw,formatted,corrections", [
    ("01KG111AAA", "01 KG 111 AAA", 0),
    ("01 KG 111 AAA", "01 KG 111 AAA", 0),
    ("  01-kg-111-aaa ", "01 KG 111 AAA", 0),
    ("O1KG111AAA", "01 KG 111 AAA", 1),
    ("01KG1I1AAA", "01 KG 111 AAA", 1),
    ("01K6111AAA", "01 KG 111 AAA", 1),
    ("O1KG1I1AAA", "01 KG 111 AAA", 2),
    ("xx01KG111AAAyy", "01 KG 111 AAA", 0),
    ("01111AAA", "01 KG 111 AAA", 0),       # страна не прочиталась — достраиваем
])
def test_parse_text_recovers_plate(raw, formatted, corrections):
    cand = parse_text(raw, "KG")
    assert cand is not None and cand.formatted == formatted and cand.corrections == corrections


@pytest.mark.parametrize("raw", ["", "KG", "HELLO WORLD", "0123456789", "01KG111", "AAAAAAAAAA"])
def test_parse_text_rejects_garbage(raw):
    assert parse_text(raw, "KG") is None
