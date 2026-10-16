from __future__ import annotations

from typing import List, Optional

import numpy as np

from app.models import GlyphSlot, Segmentation
from app.services.plate_format import SLOT_COUNT
from app.services.preprocessing import NormalizedLine

WIDTH_LAMBDA = 1.1        # штраф за отклонение ширины позиции от шага
MIN_WIDTH_FACTOR = 0.45   # допустимый диапазон ширины позиции относительно шага
MAX_WIDTH_FACTOR = 1.75
MULTI_GLYPH_GAP = 0.15      # зазор между пятнами внутри одной позиции (в высотах символа), после которого это два символа
MULTI_GLYPH_PENALTY = 0.3   # множитель оценки за каждую позицию, в которую попало два отдельных символа
TRUNCATION_PENALTY = 0.6    # текст упирается в край кропа — вероятно, строка обрезана
MIN_SLOT_INK = 0.05       # доля от (высота символа)^2: меньше — позиция пуста
PITCH_RANGE = (0.4, 1.8)   # допустимый шаг символов в высотах символа
RUN_RANGE = (5, 16)         # сколько отдельных «пятен» символов допустимо в строке из 10 позиций


def _column_profile(ink: np.ndarray, band: tuple, text_height: float) -> np.ndarray:
    y0, y1 = max(band[0], 0), min(band[1], ink.shape[0])
    return (ink[y0:y1] > 0).sum(axis=0).astype(np.float64) / max(text_height, 1.0)


def _ink_extent(profile: np.ndarray) -> Optional[tuple]:
    cols = np.where(profile > 0)[0]
    if len(cols) == 0:
        return None
    return int(cols[0]), int(cols[-1]) + 1


def _count_runs(profile: np.ndarray) -> int:
    inked = profile > 0
    return int(np.count_nonzero(inked[1:] & ~inked[:-1]) + (1 if inked.size and inked[0] else 0))


def _blob_count(part: np.ndarray, text_height: float) -> int:
    min_width = max(int(0.15 * text_height), 2)
    min_gap = max(int(MULTI_GLYPH_GAP * text_height), 2)
    runs, start = [], None
    for i, inked in enumerate(part > 0):
        if inked and start is None:
            start = i
        elif not inked and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, part.size))
    runs = [r for r in runs if r[1] - r[0] >= min_width]
    return (1 if runs else 0) + sum(1 for a, b in zip(runs, runs[1:]) if b[0] - a[1] >= min_gap)


def _best_cuts(profile: np.ndarray, xa: int, xb: int, n: int) -> Optional[List[int]]:
    span = xb - xa
    pitch = span / n
    wmin = max(int(np.floor(MIN_WIDTH_FACTOR * pitch)), 1)
    wmax = int(np.ceil(MAX_WIDTH_FACTOR * pitch))
    if span < n * wmin:
        return None

    padded = np.concatenate([[0.0], profile, [0.0]])
    cut_cost = np.zeros(profile.size + 1)
    cut_cost[:] = (padded[:-1] + padded[1:]) / 2.0

    inf = 1e18
    size = span + 1
    dp = np.full((n + 1, size), inf)
    back = np.zeros((n + 1, size), dtype=np.int32)
    dp[0, 0] = 0.0
    for k in range(1, n + 1):
        for w in range(wmin, wmax + 1):
            width_cost = WIDTH_LAMBDA * ((w - pitch) / pitch) ** 2
            prev = dp[k - 1, : size - w]
            cand = prev + width_cost
            if k < n:
                cand = cand + cut_cost[xa + w: xa + size]
            better = cand < dp[k, w:]
            dp[k, w:][better] = cand[better]
            back[k, w:][better] = w
    if dp[n, span] >= inf:
        return None

    cuts, pos = [xb], span
    for k in range(n, 0, -1):
        pos -= int(back[k, pos])
        cuts.append(xa + pos)
    cuts.reverse()
    return cuts


def _boundary_ink(profile: np.ndarray, cut: int) -> float:
    left = profile[cut - 1] if 0 <= cut - 1 < profile.size else 0.0
    right = profile[cut] if 0 <= cut < profile.size else 0.0
    return float(left + right) / 2.0


def segment_line(line: NormalizedLine, count: int = SLOT_COUNT) -> Optional[Segmentation]:
    profile = _column_profile(line.ink, line.band, line.text_height)
    extent = _ink_extent(profile)
    if extent is None:
        return None
    xa, xb = extent
    pitch = (xb - xa) / count
    if not (PITCH_RANGE[0] * line.text_height <= pitch <= PITCH_RANGE[1] * line.text_height):
        return None
    runs = _count_runs(profile[xa:xb])
    if not (RUN_RANGE[0] <= runs <= RUN_RANGE[1]):   # 4 символа, разрезанные на 10 частей, — не номер
        return None

    cuts = _best_cuts(profile, xa, xb, count)
    if cuts is None:
        return None

    y0 = max(line.band[0], 0)
    y1 = min(line.band[1], line.gray.shape[0])
    slots: List[GlyphSlot] = []
    ink_per_slot: List[float] = []
    for i in range(count):
        a, b = cuts[i], cuts[i + 1]
        ink_per_slot.append(float((line.ink[y0:y1, a:b] > 0).sum()) / line.text_height ** 2)
        cols = np.where(profile[a:b] > 0)[0]
        if len(cols):  # плотно по чернилам
            a, b = a + int(cols[0]), a + int(cols[-1]) + 1
        slots.append(GlyphSlot(index=i, x0=int(a), x1=int(b), y0=y0, y1=y1))

    if min(ink_per_slot) < MIN_SLOT_INK:   # в какой-то позиции нет символа — строка короче номера
        return Segmentation(gray=line.gray, slots=slots, score=0.0)

    gap_quality = float(np.mean([1.0 - min(_boundary_ink(profile, c), 1.0) for c in cuts[1:-1]]))
    widths = np.diff(cuts).astype(np.float64)
    regularity = 1.0 - min(float(widths.std() / max(widths.mean(), 1.0)) / 0.45, 1.0)
    score = 0.6 * gap_quality + 0.4 * regularity
    if xa <= 1 or xb >= profile.size - 1:
        score *= TRUNCATION_PENALTY
    # в позицию попало два отдельных символа — в строке больше 10 символов, это не наш номер
    crowded = sum(1 for i in range(count) if _blob_count(profile[cuts[i]:cuts[i + 1]], line.text_height) >= 2)
    score *= MULTI_GLYPH_PENALTY ** crowded
    return Segmentation(gray=line.gray, slots=slots, score=float(np.clip(score, 0.0, 1.0)))
