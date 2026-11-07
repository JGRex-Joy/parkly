import pytest

from app.plate_format import PLATE_RE, from_groups, matches_format, parse_text


@pytest.mark.parametrize("text", ["01KG111AAA", "11KG999ZZZ"])
def test_regex_accepts_kyrgyz_plates(text):
    assert PLATE_RE.match(text) and matches_format(text)


@pytest.mark.parametrize("text", ["01KC111AAA", "1KG111AAA", "01KG11AAA", "01KG111AA", "01KG1111AAA", "01KG111AA1", "O1KG111AAA", ""])
def test_regex_rejects_false_reads(text):
    assert not matches_format(text)


def test_parse_clean_and_noisy_text():
    c = parse_text("01 KG 111 AAA")
    assert (c.plate_number, c.formatted, c.corrections) == ("01111AAA", "01 KG 111 AAA", 0)
    assert parse_text("junk 07KG977OIZ more junk").plate_number == "07977OIZ"


def test_position_aware_fixes_are_counted():
    c = parse_text("O1KG1I1AAA")                   # letter O / I standing in digit slots
    assert c.plate_number == "01111AAA" and c.corrections == 2
    c = parse_text("01KG111OC2")                   # a digit standing in a letter slot -> O C Z
    assert c.letters == "OCZ" and c.corrections == 1
    assert parse_text("01KG1110C2") is None         # two of three letters guessed: not trustworthy


def test_misaligned_reads_are_never_repaired():
    assert parse_text("01KG7864LWC") is None        # inserted character: a '4' must not become an 'A'
    assert parse_text("xx 01KG111AAA yy").plate_number == "01111AAA"   # an exact plate inside noise is fine


def test_country_code_is_mandatory_and_tolerates_one_misread_letter():
    assert parse_text("01111AAA") is None                   # no KG: not a plate in this format
    c = parse_text("01K6111AAA")
    assert c.country == "KG" and c.corrections == 1
    assert parse_text("01XX111AAA") is None


def test_from_groups():
    assert from_groups(["01", "KG", "111", "AAA"]).formatted == "01 KG 111 AAA"
    assert from_groups(["01", "KG", "11", "AAA"]) is None
    assert from_groups(["01", "111", "AAA"]) is None


def test_region_validity():
    assert parse_text("11KG111AAA").is_valid_region
    assert not parse_text("12KG111AAA").is_valid_region
    assert not parse_text("00KG111AAA").is_valid_region
