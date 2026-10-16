from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np

from app.models import PlateCrop
from app.utils.geometry import warp_quad
from app.utils.image import to_gray

MIN_ASPECT, MAX_ASPECT = 2.2, 14.0
MIN_WIDTH_PX = 50
MAX_WORK_SIDE = 1100
ALREADY_CROPPED_ASPECT = 3.0
ALREADY_CROPPED_MAX_WIDTH = 1400
MAX_CANDIDATES = 12


def looks_like_crop(img: np.ndarray) -> bool:
    h, w = img.shape[:2]
    return w / h >= ALREADY_CROPPED_ASPECT and w <= ALREADY_CROPPED_MAX_WIDTH


def _gradient_candidates(gray: np.ndarray) -> List[Tuple[tuple, str]]:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    grad = np.abs(cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3))
    grad = cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, th = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    scale = max(gray.shape[1] / 1100.0, 0.5)
    kx = max(int(25 * scale) | 1, 9)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, max(int(5 * scale), 3))))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(int(9 * scale), 3), 3)))
    th = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(int(5 * scale), 3))))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [(cv2.minAreaRect(c), "gradient") for c in cnts if cv2.contourArea(c) > 300]


def _region_candidates(gray: np.ndarray, bright: bool) -> List[Tuple[tuple, str]]:
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    out = []
    levels = (200, 170, 140) if bright else (55, 85, 115)
    for thr in levels:
        mode = cv2.THRESH_BINARY if bright else cv2.THRESH_BINARY_INV
        _, th = cv2.threshold(blur, thr, 255, mode)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3)))
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out += [(cv2.minAreaRect(c), "bright" if bright else "dark") for c in cnts if cv2.contourArea(c) > 300]
    return out


def _geometry_ok(rect: tuple) -> bool:
    (_, _), (rw, rh), _ = rect
    if rw < 1 or rh < 1:
        return False
    w, h = max(rw, rh), min(rw, rh)
    return MIN_ASPECT <= w / h <= MAX_ASPECT and w >= MIN_WIDTH_PX


def _prior(rect: tuple, gray_shape: Tuple[int, int]) -> float:
    (_, _), (rw, rh), _ = rect
    w, h = max(rw, rh), min(rw, rh)
    aspect_score = 1.0 - min(abs(np.log(w / h / 5.0)) / np.log(2.8), 1.0)
    area_frac = (w * h) / float(gray_shape[0] * gray_shape[1])
    size_score = 1.0 if 0.002 <= area_frac <= 0.35 else 0.4
    return 0.7 * aspect_score + 0.3 * size_score


def _same_object(a: tuple, b: tuple) -> bool:
    (ax, ay), (aw, ah), _ = a
    (bx, by), (bw, bh), _ = b
    wa, ha, wb, hb = max(aw, ah), min(aw, ah), max(bw, bh), min(bw, bh)
    return (
        abs(ax - bx) < 0.12 * max(wa, wb)
        and abs(ay - by) < 0.5 * max(ha, hb)
        and 0.85 < wa / wb < 1.18
    )


def find_plate_candidates(img: np.ndarray, limit: int = MAX_CANDIDATES) -> List[PlateCrop]:
    h, w = img.shape[:2]
    if looks_like_crop(img):
        return [PlateCrop(img, "already_cropped", 0.9, None)]

    scale = 1.0
    small = img
    if max(h, w) > MAX_WORK_SIDE:
        scale = MAX_WORK_SIDE / max(h, w)
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = to_gray(small)

    raw = _gradient_candidates(gray) + _region_candidates(gray, True) + _region_candidates(gray, False)
    scored = sorted(
        ((_prior(r, gray.shape), m, r) for r, m in raw if _geometry_ok(r)), key=lambda t: t[0], reverse=True
    )

    kept: List[Tuple[float, str, tuple]] = []
    for score, method, rect in scored:
        if all(not _same_object(rect, k[2]) for k in kept):
            kept.append((score, method, rect))
        if len(kept) >= limit:
            break

    crops: List[PlateCrop] = []
    for score, method, rect in kept:
        (cx, cy), (rw, rh), ang = rect
        grow_w, grow_h = (1.12, 1.35) if method == "gradient" else (1.10, 1.20)
        padded = ((cx, cy), (rw * grow_w + 8, rh * grow_h + 8), ang)
        box = cv2.boxPoints(padded) / scale
        crops.append(PlateCrop(warp_quad(img, box), method, float(score), box))
    return crops
