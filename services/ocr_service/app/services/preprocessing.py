from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.utils.image import to_gray

TARGET_TEXT_HEIGHT = 40     
MAX_UPSCALE = 6.0
MIN_TEXT_HEIGHT = 6         


@dataclass
class NormalizedLine:
    gray: np.ndarray        
    detail: np.ndarray      
    ink: np.ndarray         
    text_height: float      
    band: Tuple[int, int]   
    inverted: bool          
    scale: float            


def detect_inverted(gray: np.ndarray) -> bool:
    h, w = gray.shape
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.08), max(int(w * 0.92), int(w * 0.08) + 1)
    window = gray[y0:y1, x0:x1]
    bright_fraction = float(np.mean(window > thr))
    if abs(bright_fraction - 0.5) > 0.08:
        return bright_fraction < 0.5          

    ring = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    return float(np.median(ring)) < thr


def _components(ink: np.ndarray):
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    return stats[1:]  


def is_frame_component(x: int, y: int, w: int, h: int, shape: Tuple[int, int]) -> bool:
    img_h, img_w = shape
    enclosing_ring = w >= 0.85 * img_w and h >= 0.7 * img_h
    horizontal_bar = w >= 0.6 * img_w and h <= 0.2 * img_h
    vertical_bar = h >= 0.9 * img_h and w <= 0.08 * img_h and (x <= 1 or x + w >= img_w - 1)
    touches_border = x <= 0 or y <= 0 or x + w >= img_w or y + h >= img_h
    large_blob = touches_border and w * h >= 0.35 * img_w * img_h
    return enclosing_ring or horizontal_bar or vertical_bar or large_blob


def _drop_frame_components(stats: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    keep = [row for row in stats if not is_frame_component(int(row[0]), int(row[1]), int(row[2]), int(row[3]), shape)]
    return np.array(keep, dtype=np.int32).reshape(-1, 5)


MIN_LINE_COMPONENTS = 4     


def estimate_text_height(ink: np.ndarray) -> Optional[Tuple[float, Tuple[int, int]]]:
    stats = _drop_frame_components(_components(ink), ink.shape)
    if len(stats) == 0:
        return None
    x, y, w, h, area = stats.T
    usable = (h >= MIN_TEXT_HEIGHT) & (w >= 1) & (area >= 6) & (w <= 1.6 * h)
    stats = stats[usable]
    if len(stats) < MIN_LINE_COMPONENTS:
        return None

    heights = stats[:, 3].astype(np.float64)
    bottoms = (stats[:, 1] + stats[:, 3]).astype(np.float64)
    best_members, best_count = None, 0
    for i in range(len(stats)):
        members = (np.abs(heights - heights[i]) <= 0.15 * heights[i]) & (np.abs(bottoms - bottoms[i]) <= 0.25 * heights[i])
        count = int(members.sum())
        if count > best_count:
            best_members, best_count = members, count
    if best_members is None or best_count < MIN_LINE_COMPONENTS:
        return None

    line = stats[best_members]
    glyph_h = float(np.median(line[:, 3]))
    top = int(round(float(np.median(line[:, 1]))))
    bottom = int(round(float(np.median(line[:, 1] + line[:, 3]))))
    return glyph_h, (top, bottom)


def _flatten_background(dark_on_light: np.ndarray, text_height: float) -> np.ndarray:
    k = max(int(text_height * 1.3) | 1, 9)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    background = cv2.morphologyEx(dark_on_light, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), k / 4.0)
    flat = dark_on_light.astype(np.float32) * 255.0 / np.maximum(background.astype(np.float32), 1.0)
    return np.clip(flat, 0, 255).astype(np.uint8)


def normalize_line(image: np.ndarray) -> Optional[NormalizedLine]:
    gray = to_gray(image)
    if gray.shape[0] < 8 or gray.shape[1] < 30:
        return None

    inverted = detect_inverted(gray)
    dark_on_light = 255 - gray if inverted else gray

    smooth = cv2.GaussianBlur(dark_on_light, (0, 0), 0.7)
    thr, _ = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    first_ink = (smooth < thr).astype(np.uint8) * 255
    estimate = estimate_text_height(first_ink)
    if estimate is None:
        return None
    height0, _ = estimate

    scale = float(np.clip(TARGET_TEXT_HEIGHT / height0, 1.0, MAX_UPSCALE))
    if scale > 1.01:
        dark_on_light = cv2.resize(dark_on_light, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    text_height = height0 * scale

    detail = _flatten_background(dark_on_light, text_height)
    flat = cv2.GaussianBlur(detail, (0, 0), max(0.6, text_height / 40.0))
    thr, _ = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    ink = (flat < thr).astype(np.uint8) * 255

    refined = estimate_text_height(ink)
    if refined is None:
        return None
    text_height, band = refined

    mask = np.zeros_like(ink)
    count, labels, lab_stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in lab_stats[i])
        in_band = y + h > band[0] and y < band[1]
        glyph_like = 0.45 * text_height <= h <= 1.5 * text_height and area >= 0.02 * text_height ** 2
        if in_band and glyph_like and not is_frame_component(x, y, w, h, ink.shape):
            mask[labels == i] = 255
    return NormalizedLine(gray=flat, detail=detail, ink=mask, text_height=text_height, band=band, inverted=inverted, scale=scale)
