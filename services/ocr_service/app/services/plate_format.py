from __future__ import annotations

import re
from typing import Optional, Sequence, Tuple

from app.models import PlateCandidate

DIGITS = "0123456789"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

SLOT_CLASSES: Tuple[str, ...] = tuple("DDLLDDDLLL")
SLOT_COUNT = len(SLOT_CLASSES)

REGION, COUNTRY, SERIAL, SERIES = (0, 2), (2, 4), (4, 7), (7, 10)

PLATE_REGEX = re.compile(r"^[0-9]{2}[A-Z]{2}[0-9]{3}[A-Z]{3}$")

LETTER_TO_DIGIT = {
    "O": "0", "Q": "0", "D": "0",
    "I": "1", "L": "1", "J": "1",
    "Z": "2", "S": "5", "G": "6", "T": "7", "B": "8",
}
DIGIT_TO_LETTER = {
    "0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "7": "T", "8": "B",
}


def allowed_chars(slot_class: str) -> str:
    return DIGITS if slot_class == "D" else LETTERS


def clean(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def matches_format(plate: str) -> bool:
    return bool(PLATE_REGEX.match(plate))


def match_country(read: str, expected: str) -> Optional[Tuple[str, int]]:
    if not expected:
        return read, 0
    mismatches = sum(1 for a, b in zip(read, expected) if a != b)
    if mismatches > 1:
        return None
    return expected, mismatches


def build_candidate(chars: Sequence[str], corrections: int, country_code: str) -> Optional[PlateCandidate]:
    if len(chars) != SLOT_COUNT:
        return None
    for ch, cls in zip(chars, SLOT_CLASSES):
        if ch not in allowed_chars(cls):
            return None
    text = "".join(chars)
    country = match_country(text[COUNTRY[0]:COUNTRY[1]], country_code)
    if country is None:
        return None
    return PlateCandidate(
        region=text[REGION[0]:REGION[1]],
        country=country[0],
        serial=text[SERIAL[0]:SERIAL[1]],
        letters=text[SERIES[0]:SERIES[1]],
        corrections=corrections + country[1],
    )


def _fix(s: str, to_digits: bool) -> Tuple[Optional[str], int]:
    table = LETTER_TO_DIGIT if to_digits else DIGIT_TO_LETTER
    out, fixes = [], 0
    for ch in s:
        if (ch.isdigit() if to_digits else ch.isalpha()):
            out.append(ch)
        elif ch in table:
            out.append(table[ch])
            fixes += 1
        else:
            return None, 0
    if fixes > len(s) // 2:
        return None, 0
    return "".join(out), fixes


def _rank(c: PlateCandidate) -> Tuple[int, int]:
    return (0 if c.is_valid_region else 1, c.corrections)


def parse_text(raw_text: str, country_code: str) -> Optional[PlateCandidate]:
    s = clean(raw_text)
    best: Optional[PlateCandidate] = None

    def consider(cand: Optional[PlateCandidate]) -> None:
        nonlocal best
        if cand is not None and (best is None or _rank(cand) < _rank(best)):
            best = cand

    for start in range(0, len(s) - SLOT_COUNT + 1):
        w = s[start:start + SLOT_COUNT]
        parts = (_fix(w[0:2], True), _fix(w[2:4], False), _fix(w[4:7], True), _fix(w[7:10], False))
        if any(p[0] is None for p in parts):
            continue
        consider(build_candidate(list("".join(p[0] for p in parts)), sum(p[1] for p in parts), country_code))

    if country_code:  
        for start in range(0, len(s) - 8 + 1):
            w = s[start:start + 8]
            parts = (_fix(w[0:2], True), _fix(w[2:5], True), _fix(w[5:8], False))
            if any(p[0] is None for p in parts):
                continue
            region, serial, letters = (p[0] for p in parts)
            consider(PlateCandidate(region, country_code, serial, letters, sum(p[1] for p in parts)))
    return best
