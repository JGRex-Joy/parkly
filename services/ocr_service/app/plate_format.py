from __future__ import annotations

import re
from typing import Optional, Tuple

from app.models import PlateCandidate

COUNTRY = "KG"
ALLOWLIST = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"          
PLATE_RE = re.compile(rf"^\d{{2}}{COUNTRY}\d{{3}}[A-Z]{{3}}$")  

LETTER_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "J": "1", "Z": "2",
                   "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}
DIGIT_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}


def clean(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def matches_format(plate_with_country: str) -> bool:
    return bool(PLATE_RE.match(plate_with_country))


def _fix(chunk: str, want_digits: bool) -> Tuple[Optional[str], int]:
    table = LETTER_TO_DIGIT if want_digits else DIGIT_TO_LETTER
    out, fixes = [], 0
    for ch in chunk:
        if ch.isdigit() == want_digits:
            out.append(ch)
        elif ch in table:
            out.append(table[ch])
            fixes += 1
        else:
            return None, 0
    if fixes > len(chunk) // 2:      
        return None, 0
    return "".join(out), fixes


def _country(read: str) -> Optional[Tuple[str, int]]:
    mismatches = sum(a != b for a, b in zip(read, COUNTRY))
    return (COUNTRY, mismatches) if len(read) == 2 and mismatches <= 1 else None


def _rank(c: PlateCandidate) -> Tuple[int, int]:
    return (0 if c.is_valid_region else 1, c.corrections)


def parse_text(raw_text: str) -> Optional[PlateCandidate]:
    s = clean(raw_text)
    best: Optional[PlateCandidate] = None

    def consider(region: str, serial: str, letters: str, fixes: int) -> None:
        nonlocal best
        if not matches_format(f"{region}{COUNTRY}{serial}{letters}"):      
            return
        cand = PlateCandidate(region, COUNTRY, serial, letters, fixes)
        if best is None or _rank(cand) < _rank(best):
            best = cand

    for i in range(len(s) - 9):                                   
        w = s[i:i + 10]
        region, serial, letters, cc = _fix(w[0:2], True), _fix(w[4:7], True), _fix(w[7:10], False), _country(w[2:4])
        if None in (region[0], serial[0], letters[0]) or cc is None:
            continue
        fixes = region[1] + serial[1] + letters[1] + cc[1]
        if fixes and len(s) != 10:        
            continue
        consider(region[0], serial[0], letters[0], fixes)

    return best


DIGITS = "0123456789"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def from_groups(words: list) -> Optional[PlateCandidate]:
    if len(words) != 4 or [len(w) for w in words] != [2, 2, 3, 3]:
        return None
    region, country, serial, letters = words
    cc = _country(country)
    if cc is None or not matches_format(f"{region}{COUNTRY}{serial}{letters}"):
        return None
    return PlateCandidate(region, COUNTRY, serial, letters, cc[1])
