from __future__ import annotations

import cv2
import numpy as np


def decode_image(image_bytes: bytes) -> np.ndarray:
    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Не удалось декодировать изображение")
    return img


def encode_jpeg(frame: np.ndarray, quality: int = 95) -> bytes:
    success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("Не удалось закодировать кадр в JPEG")
    return buf.tobytes()


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
