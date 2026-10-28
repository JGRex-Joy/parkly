from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

HERSHEY = {
    "simplex": cv2.FONT_HERSHEY_SIMPLEX,
    "duplex": cv2.FONT_HERSHEY_DUPLEX,
    "plain": cv2.FONT_HERSHEY_PLAIN,
    "complex": cv2.FONT_HERSHEY_COMPLEX,
}


def random_plate(rng: np.random.Generator, country: str = "KG") -> str:
    region = f"{int(rng.integers(1, 12)):02d}"
    serial = "".join(rng.choice(list(string.digits), 3))
    series = "".join(rng.choice(list(string.ascii_uppercase), 3))
    return f"{region}{country}{serial}{series}"


@dataclass
class PlateStyle:
    font: str = "simplex"            
    text_height: int = 28            
    pitch: float = 1.0               
    light_on_dark: bool = False      
    margin_x: float = 0.9            
    margin_y: float = 0.55
    frame: bool = True               
    fg: Optional[int] = None
    bg: Optional[int] = None


def _glyph_cv(ch: str, font_key: str, height: int) -> Tuple[np.ndarray, int]:
    font = HERSHEY[font_key]
    scale = 1.0
    (_, h), _ = cv2.getTextSize("H", font, scale, 1)
    scale = height / max(h, 1)
    thickness = max(1, int(round(height / 11)))
    (w, _), base = cv2.getTextSize(ch, font, scale, thickness)
    mask = np.zeros((height + base + 4, w + 4), np.uint8)
    cv2.putText(mask, ch, (2, height + 2), font, scale, 255, thickness, cv2.LINE_AA)
    return mask, w + 4


def _glyph_ttf(ch: str, path: str, height: int) -> Tuple[np.ndarray, int]:
    from PIL import Image, ImageDraw, ImageFont

    probe = ImageFont.truetype(path, 100)
    _, top, _, bottom = probe.getbbox("H")
    size = max(int(round(height * 100.0 / (bottom - top))), 6)
    font = ImageFont.truetype(path, size)
    _, top, _, _ = font.getbbox("H")
    width = int(font.getlength(ch)) + 8
    img = Image.new("L", (width, height + height // 2 + 8), 0)
    ImageDraw.Draw(img).text((4, 2 - top), ch, font=font, fill=255)
    return np.array(img), width


def render_plate(text: str, style: PlateStyle = PlateStyle()) -> np.ndarray:
    h = style.text_height
    glyph_fn = _glyph_ttf if style.font.endswith((".ttf", ".otf")) else _glyph_cv
    glyphs = [glyph_fn(ch, style.font, h) for ch in text]
    cell = max(w for _, w in glyphs)
    advance = int(round(cell * style.pitch))
    mx, my = int(h * style.margin_x), int(h * style.margin_y)
    width = mx * 2 + advance * (len(text) - 1) + cell
    height = my * 2 + h + h // 3

    if style.light_on_dark:
        bg, fg = (style.bg if style.bg is not None else 39), (style.fg if style.fg is not None else 255)
    else:
        bg, fg = (style.bg if style.bg is not None else 238), (style.fg if style.fg is not None else 22)
    canvas = np.full((height, width), bg, np.float32)
    ink = np.zeros((height, width), np.float32)
    for i, (mask, w) in enumerate(glyphs):
        x = mx + i * advance + (cell - w) // 2
        y = my - 2
        hh, ww = mask.shape
        region = ink[y:y + hh, x:x + ww]
        mh, mw = region.shape
        np.maximum(region, mask[:mh, :mw].astype(np.float32) / 255.0, out=region)
    canvas = canvas * (1 - ink) + fg * ink
    out = np.clip(canvas, 0, 255).astype(np.uint8)
    if style.frame:
        t = max(1, h // 14)
        cv2.rectangle(out, (0, 0), (width - 1, height - 1), int(fg) if not style.light_on_dark else int(bg), t)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def degrade(img: np.ndarray, rng: np.random.Generator, level: float = 1.0) -> np.ndarray:
    out = img.astype(np.float32)
    h, w = out.shape[:2]
    if level <= 0:
        return img.copy()

    ramp = np.linspace(1.0 - 0.28 * level * rng.random(), 1.0, w, dtype=np.float32)
    if rng.random() < 0.5:
        ramp = ramp[::-1]
    out *= ramp[None, :, None]
    out = (out - 128) * (1 - 0.25 * level * rng.random()) + 128 + rng.uniform(-18, 18) * level

    k = 1.0 - 0.35 * level * rng.random()
    if k < 0.98:
        small = cv2.resize(out, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

    sigma = 0.3 + 0.9 * level * rng.random()
    out = cv2.GaussianBlur(out, (0, 0), sigma)
    out += rng.normal(0, 3.0 * level, out.shape).astype(np.float32)
    out = np.clip(out, 0, 255).astype(np.uint8)

    quality = int(np.clip(90 - 30 * level * rng.random(), 35, 95))
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def rotate(img: np.ndarray, degrees: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def make_scene(
    plate: np.ndarray, rng: np.random.Generator, size: Tuple[int, int] = (1280, 720),
    plate_width: Optional[int] = None, tilt: float = 0.0, perspective: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray]:
    W, H = size
    base = rng.integers(60, 170)
    scene = np.full((H, W, 3), base, np.float32)
    scene += np.linspace(-25, 25, W, dtype=np.float32)[None, :, None] * rng.choice([-1, 1])
    for _ in range(int(rng.integers(4, 9))):  # крупные детали: кузов, окна, фары
        x0, y0 = int(rng.integers(0, W - 80)), int(rng.integers(0, H - 80))
        x1, y1 = x0 + int(rng.integers(60, W // 2)), y0 + int(rng.integers(40, H // 2))
        cv2.rectangle(scene, (x0, y0), (min(x1, W - 1), min(y1, H - 1)),
                      [float(rng.integers(20, 230))] * 3, -1 if rng.random() < 0.7 else 3)
    scene += rng.normal(0, 6, scene.shape).astype(np.float32)
    scene = np.clip(scene, 0, 255)

    ph, pw = plate.shape[:2]
    pw_target = plate_width or int(rng.integers(220, 420))
    s = pw_target / pw
    plate = cv2.resize(plate, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    ph, pw = plate.shape[:2]
    quad = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], np.float32)
    jitter = perspective * ph * (rng.random((4, 2)) - 0.5) * 2
    dst = quad + jitter
    c, sn = np.cos(np.radians(tilt)), np.sin(np.radians(tilt))
    dst = (dst - [pw / 2, ph / 2]) @ np.array([[c, -sn], [sn, c]], np.float32).T + [pw / 2, ph / 2]
    ox = int(rng.integers(40, max(41, W - pw - 40)))
    oy = int(rng.integers(40, max(41, H - ph - 40)))
    dst = dst + [ox, oy]
    m = cv2.getPerspectiveTransform(quad, dst.astype(np.float32))
    warped = cv2.warpPerspective(plate, m, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), m, (W, H), flags=cv2.INTER_LINEAR)
    scene = np.where(mask[..., None] > 127, warped, scene)
    return scene.astype(np.uint8), dst.astype(np.float32)
