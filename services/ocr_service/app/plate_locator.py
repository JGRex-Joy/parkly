from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.models import PlateCrop

WORK_SIDE = 960               
MAX_CANDIDATES = 8            
MIN_ASPECT, MAX_ASPECT = 2.0, 8.0       
MIN_PLATE_WIDTH = 48          
CROP_ALREADY_ASPECT = 2.6     
CROP_ALREADY_MAX_WIDTH = 1400

WORK_HEIGHT = 110             
LINE_HEIGHT = 64              
GLYPH_FILL = 0.62             
SIDE_MARGIN = 0.9             
MERGED_MAX = 3.6              
MIN_GLYPHS = 6                
MIN_GLYPH_PX = 9              


@dataclass
class Line:
    image: np.ndarray         
    glyphs: int               
    quality: float            
    band: Optional[np.ndarray] = None          
    spans: Optional[List[Tuple[int, int]]] = None   
    glyph_h: float = 0.0


def looks_like_crop(img: np.ndarray) -> bool:
    h, w = img.shape[:2]
    return w / h >= CROP_ALREADY_ASPECT and w <= CROP_ALREADY_MAX_WIDTH


def _text_band_boxes(gray: np.ndarray) -> List[Tuple[tuple, str]]:
    s = max(gray.shape[1] / 960.0, 0.5)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    sobel = np.abs(cv2.Sobel(cv2.GaussianBlur(g, (3, 3), 0), cv2.CV_32F, 1, 0, ksize=3))
    sobel = cv2.normalize(sobel, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, th = cv2.threshold(sobel, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(int(21 * s) | 1, 9), max(int(5 * s), 3))))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(int(9 * s), 3), 3)))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [(cv2.minAreaRect(c), "gradient") for c in cnts if cv2.contourArea(c) > 150]


def _bright_plate_boxes(gray: np.ndarray) -> List[Tuple[tuple, str]]:
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    out: List[Tuple[tuple, str]] = []
    otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    for thr in sorted({int(otsu), 190, 150}, reverse=True):
        _, th = cv2.threshold(blur, thr, 255, cv2.THRESH_BINARY)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 300:
                continue
            rect = cv2.minAreaRect(c)
            (rw, rh) = rect[1]
            if rw * rh > 0 and area / (rw * rh) > 0.7:           
                out.append((rect, "bright"))
    return out


def _edge_quad_boxes(gray: np.ndarray) -> List[Tuple[tuple, str]]:
    g = cv2.bilateralFilter(gray, 5, 40, 40)
    edges = cv2.Canny(g, 60, 160)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out: List[Tuple[tuple, str]] = []
    for c in cnts:
        if cv2.contourArea(c) < 300:
            continue
        hull = cv2.convexHull(c)
        approx = cv2.approxPolyDP(hull, 0.04 * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            out.append((cv2.minAreaRect(approx), "quad"))
    return out


def _best_chain(x: np.ndarray, y: np.ndarray, w: np.ndarray, h: np.ndarray, free: np.ndarray) -> Optional[list]:
    bottom = y + h
    best: Optional[list] = None
    for j in np.flatnonzero(free):
        ids = np.flatnonzero(free & (np.abs(h - h[j]) <= 0.25 * h[j]))
        ids = ids[np.argsort(x[ids])]
        pos = int(np.flatnonzero(ids == j)[0])
        chain, cur = [int(j)], int(j)
        for k in ids[pos + 1:]:                                      
            gap = x[k] - (x[cur] + w[cur])
            if gap > 1.8 * h[j]:
                break
            if gap >= -0.3 * w[cur] and abs(bottom[k] - bottom[cur]) <= 0.3 * h[j]:
                chain.append(int(k))
                cur = int(k)
        cur = int(j)
        for k in ids[:pos][::-1]:                                    
            gap = x[cur] - (x[k] + w[k])
            if gap > 1.8 * h[j]:
                break
            if gap >= -0.3 * w[k] and abs(bottom[k] - bottom[cur]) <= 0.3 * h[j]:
                chain.insert(0, int(k))
                cur = int(k)
        if best is None or len(chain) > len(best):
            best = chain
    return best


def _glyph_row_boxes(gray: np.ndarray) -> List[Tuple[tuple, str, float]]:
    H, W = gray.shape
    block = max(int(W * 0.035) | 1, 15)
    out: List[Tuple[tuple, str, float]] = []
    for img in (gray, 255 - gray):                       
        ink = cv2.adaptiveThreshold(cv2.GaussianBlur(img, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, block, 9)
        n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        if n < 8:
            continue
        x, y, w, h, area = (stats[1:, i].astype(np.float64) for i in range(5))
        fill = area / np.maximum(w * h, 1.0)
        ok = (h >= 8) & (h <= 0.25 * H) & (w >= 0.08 * h) & (w <= MERGED_MAX * h) & (fill >= 0.12) & (fill <= 0.92)
        idx = np.flatnonzero(ok)
        if len(idx) < MIN_GLYPHS:
            continue
        if len(idx) > 400:
            idx = idx[np.argsort(-area[idx])[:400]]
        x, y, w, h = x[idx], y[idx], w[idx], h[idx]
        free = np.ones(len(idx), dtype=bool)
        for _ in range(3):                               
            best = _best_chain(x, y, w, h, free)
            if best is None or len(best) < MIN_GLYPHS:
                break
            best = np.array(best)
            free[best] = False
            gh = float(np.median(h[best]))
            pts = np.concatenate([np.c_[x[best], y[best]], np.c_[x[best] + w[best], y[best]],
                                  np.c_[x[best], y[best] + h[best]], np.c_[x[best] + w[best], y[best] + h[best]]])
            (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts.astype(np.float32))
            long_is_w = rw >= rh
            rw2, rh2 = (rw + 3.4 * gh, rh + 1.4 * gh) if long_is_w else (rw + 1.4 * gh, rh + 3.4 * gh)   # generous at the ends: a dropped end glyph must stay inside
            n_glyphs = len(best)       
            evidence = 1.0 if 8 <= n_glyphs <= 11 else 0.5 if n_glyphs in (7, 12) else 0.2
            out.append((((cx, cy), (rw2, rh2), ang), "gradient", evidence))
    return out


def _dims(rect: tuple) -> Tuple[float, float]:
    (_, _), (rw, rh), _ = rect
    return max(rw, rh), min(rw, rh)


def _geometry_ok(rect: tuple, scale: float) -> bool:
    w, h = _dims(rect)
    return h >= 1 and MIN_ASPECT <= w / h <= MAX_ASPECT and w / scale >= MIN_PLATE_WIDTH


def _prior(rect: tuple, shape: Tuple[int, int]) -> float:
    w, h = _dims(rect)
    aspect = 1.0 - min(abs(np.log(w / h / 4.6)) / np.log(2.2), 1.0)
    area = (w * h) / float(shape[0] * shape[1])
    return 0.75 * aspect + 0.25 * (1.0 if 0.0015 <= area <= 0.4 else 0.3)


def _same_object(a: tuple, b: tuple) -> bool:
    (ax, ay), (bx, by) = a[0], b[0]
    wa, ha = _dims(a)
    wb, hb = _dims(b)
    return abs(ax - bx) < 0.05 * max(wa, wb) and abs(ay - by) < 0.4 * max(ha, hb) and 0.92 < wa / wb < 1.09 and 0.7 < ha / hb < 1.4


def _order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.astype("float32")
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def warp_quad(img: np.ndarray, box: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = _order_points(box)
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if height > width:
        width, height = height, width
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], dtype="float32"), dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def find_candidates(frame: np.ndarray, limit: int = MAX_CANDIDATES) -> List[PlateCrop]:
    if looks_like_crop(frame):
        return [PlateCrop(frame, "already_cropped", 0.9)]

    h, w = frame.shape[:2]
    scale = min(1.0, WORK_SIDE / max(h, w))
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small

    pools = [[(r, m, 0.0) for r, m in _text_band_boxes(gray)],
             _glyph_row_boxes(gray),
             [(r, m, 0.0) for r, m in _bright_plate_boxes(gray)],
             [(r, m, 0.0) for r, m in _edge_quad_boxes(gray)]]
    scored: List[Tuple[float, str, tuple]] = []
    for pool in pools:                                   
        ranked = sorted(((_prior(r, gray.shape) + 0.35 * ev, m, r) for r, m, ev in pool       
                         if _geometry_ok(r, scale)), key=lambda t: -t[0])                      
        scored += ranked[:3]
    scored.sort(key=lambda t: -t[0])

    kept: List[Tuple[float, str, tuple]] = []
    for score, method, rect in scored:
        if all(not _same_object(rect, k[2]) for k in kept):
            kept.append((score, method, rect))
        if len(kept) >= limit:
            break

    crops: List[PlateCrop] = []
    for score, method, rect in kept:
        (cx, cy), (rw, rh), ang = rect
        grow_w, grow_h = (1.10, 1.45) if method == "gradient" else (1.06, 1.25)   
        box = cv2.boxPoints(((cx, cy), (rw * grow_w + 6, rh * grow_h + 6), ang)) / scale
        crops.append(PlateCrop(warp_quad(frame, box), "gradient" if method in ("gradient", "quad") else method, float(min(score, 1.0)), box))
    return crops


def _is_light_on_dark(gray: np.ndarray) -> bool:
    h, w = gray.shape
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    win = gray[int(h * 0.2):max(int(h * 0.8), int(h * 0.2) + 1), int(w * 0.08):max(int(w * 0.92), int(w * 0.08) + 1)]
    bright = float(np.mean(win > thr))
    if abs(bright - 0.5) > 0.08:
        return bright < 0.5                      
    ring = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    return float(np.median(ring)) < thr


def _flatten(dark_on_light: np.ndarray) -> np.ndarray:
    k = max(int(dark_on_light.shape[0] * 0.55) | 1, 9)
    bg = cv2.morphologyEx(dark_on_light, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 4.0)
    return np.clip(dark_on_light.astype(np.float32) * 255.0 / np.maximum(bg.astype(np.float32), 1.0), 0, 255).astype(np.uint8)


def _split_merged(members: np.ndarray, labels: np.ndarray) -> np.ndarray:
    gh = float(np.median(members[:, 4]))
    rows = []
    for idx, x, y, w, h in members:
        if w <= 1.2 * gh:
            rows.append([idx, x, y, w, h])
            continue
        k = max(2, int(round(w / (0.82 * gh))))                       
        mask = labels[int(y):int(y + h), int(x):int(x + w)] == int(idx)
        profile = np.convolve(mask.sum(axis=0).astype(np.float64), np.ones(3) / 3.0, mode="same")
        guard, cuts = max(int(0.35 * gh), 2), []
        masked = profile.copy()
        masked[:guard] = masked[-guard:] = np.inf
        for _ in range(k - 1):
            c = int(np.argmin(masked))
            if not np.isfinite(masked[c]):
                break
            cuts.append(c)
            masked[max(c - guard, 0):c + guard + 1] = np.inf
        edges = [0] + sorted(cuts) + [int(w)]
        rows += [[idx, x + a, y, b - a, h] for a, b in zip(edges[:-1], edges[1:]) if b - a >= 2]
    return np.array(rows, dtype=np.float64)


def _glyph_cluster(ink: np.ndarray):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    H, W = ink.shape
    rows = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        touches = x <= 0 or y <= 0 or x + w >= W or y + h >= H
        if (0.12 * H <= h <= 0.97 * H) and (0.08 * h <= w <= MERGED_MAX * h) and area >= 0.04 * h * h and not (touches and h > 0.9 * H):
            rows.append((i, x, y, w, h))
    if len(rows) < MIN_GLYPHS:
        return None
    arr = np.array(rows, dtype=np.float64)
    chain = _best_chain(arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], np.ones(len(arr), dtype=bool))
    if chain is None or len(chain) < MIN_GLYPHS:
        return None
    best = np.array(chain)
    return _split_merged(arr[best], labels), labels


def _deskew(img: np.ndarray, centres: np.ndarray) -> np.ndarray:
    if len(centres) < 4:
        return img
    vx, vy, _, _ = cv2.fitLine(centres.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    angle = float(np.degrees(np.arctan2(vy, vx)))
    if abs(angle) < 0.8 or abs(angle) > 15:
        return img
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _merge_spans(spans: List[Tuple[int, int]], gh: float) -> List[Tuple[int, int]]:
    merged: List[List[int]] = []
    for a, b in sorted(spans):
        if merged and a < merged[-1][1] - 0.02 * gh:         
            merged[-1][1] = max(merged[-1][1], b)           
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


SLOT_LAYOUT = (("D", 0, 2), ("L", 2, 4), ("D", 4, 7), ("L", 7, 10))


def slot_groups(line: Line) -> Optional[List[Tuple[str, np.ndarray]]]:
    if line.band is None or not line.spans or len(line.spans) != 10:
        return None
    band, spans, gh = line.band, line.spans, line.glyph_h
    ratio = LINE_HEIGHT / band.shape[0]
    margin = int(round(0.5 * gh))
    out = []
    for cls, first, last in SLOT_LAYOUT:
        lo, hi = spans[first][0] - margin, spans[last - 1][1] + margin
        if first:                                               
            lo = max(lo, (spans[first - 1][1] + spans[first][0]) // 2)
        if last < len(spans):
            hi = min(hi, (spans[last - 1][1] + spans[last][0]) // 2 + 1)
        piece = band[:, max(lo, 0):max(hi, 1)]
        out.append((cls, cv2.resize(piece, (max(int(piece.shape[1] * ratio), 8), LINE_HEIGHT),
                                    interpolation=cv2.INTER_CUBIC if ratio > 1 else cv2.INTER_AREA)))
    return out


def extract_line(crop: np.ndarray) -> Optional[Line]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    if gray.shape[0] < 8 or gray.shape[1] < 30 or float(gray.std()) < 3.0:
        return None

    up = float(np.clip(WORK_HEIGHT / gray.shape[0], 0.02, 6.0))        
    if abs(up - 1.0) > 0.05:                                           
        gray = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC if up > 1 else cv2.INTER_AREA)
    gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(gray)
    dol = 255 - gray if _is_light_on_dark(gray) else gray              
    dol = _flatten(cv2.GaussianBlur(dol, (0, 0), 0.8))

    def ink_of(img: np.ndarray) -> np.ndarray:
        thr, _ = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        return (img < thr).astype(np.uint8) * 255

    found = _glyph_cluster(ink_of(dol))
    if found is None:
        return None
    members, _ = found
    dol = _deskew(dol, np.c_[members[:, 1] + members[:, 3] / 2.0, members[:, 2] + members[:, 4] / 2.0])
    found = _glyph_cluster(ink_of(dol))
    if found is None:
        return None
    members, _ = found

    gh = float(np.median(members[:, 4]))
    if gh / up < MIN_GLYPH_PX:
        return None
    y0, y1 = float(np.median(members[:, 2])), float(np.median(members[:, 2] + members[:, 4]))
    strip_h = gh / GLYPH_FILL
    cy = (y0 + y1) / 2.0
    top, bottom = int(round(cy - strip_h / 2)), int(round(cy + strip_h / 2))
    x0, x1 = members[:, 1].min(), (members[:, 1] + members[:, 3]).max()
    mx = SIDE_MARGIN * gh
    left, right = int(round(x0 - mx)), int(round(x1 + mx))

    pad = max(0, -top, -left, bottom - dol.shape[0], right - dol.shape[1])
    if pad:
        dol = cv2.copyMakeBorder(dol, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        top, bottom, left, right = top + pad, bottom + pad, left + pad, right + pad
    band = dol[top:bottom, :]
    if band.size == 0:
        return None

    strip = band[:, left:right]
    ratio = LINE_HEIGHT / strip.shape[0]
    strip = cv2.resize(strip, (max(int(strip.shape[1] * ratio), 8), LINE_HEIGHT),
                       interpolation=cv2.INTER_CUBIC if ratio > 1 else cv2.INTER_AREA)

    spacing = np.diff(np.sort(members[:, 1]))
    regular = 1.0 - min(float(spacing.std() / max(spacing.mean(), 1.0)), 1.0) if len(spacing) > 1 else 0.0
    quality = 0.65 * min(len(members) / 10.0, 1.0) + 0.35 * regular
    spans = _merge_spans([(int(m[1]) + pad, int(m[1] + m[3]) + pad) for m in members], gh)
    return Line(image=strip, glyphs=len(members), quality=float(quality), band=band, spans=spans, glyph_h=gh)
