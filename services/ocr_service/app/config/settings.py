"""Конфигурация сервиса. Все значения читаются из переменных окружения.

Сохранены исходные переменные: BACKEND_BASE_URL, MAX_CORRECTIONS_TO_TRUST,
CAMERA_WARMUP_FRAMES, CAMERA_CAPTURE_DELAY_SECONDS.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _env_str(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return default if value is None else value.strip()


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом, получено {raw!r}") from exc


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} должен быть числом, получено {raw!r}") from exc


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} должен быть булевым значением (true/false), получено {raw!r}")


def _env_int_list(env: Mapping[str, str], name: str) -> Tuple[int, ...]:
    raw = env.get(name, "").strip()
    if not raw:
        return ()
    try:
        return tuple(int(part) for part in raw.replace(";", ",").split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(f"{name} должен быть списком целых через запятую, получено {raw!r}") from exc


@dataclass(frozen=True)
class CameraReliability:
    """Параметры устойчивости, общие для всех типов камер."""

    warmup_frames: int = 5
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    stall_timeout: float = 5.0     # столько секунд без нового кадра -> поток считается мёртвым
    frame_timeout: float = 5.0     # сколько ждём свежий кадр при запросе


@dataclass(frozen=True)
class IpCameraSettings:
    enabled: bool = False
    url: str = ""
    rtsp_transport: str = "tcp"    # tcp | udp (только для rtsp://)
    open_timeout_ms: int = 5000
    read_timeout_ms: int = 5000
    reliability: CameraReliability = field(default_factory=CameraReliability)


@dataclass(frozen=True)
class UsbCameraSettings:
    enabled: bool = True
    index: Optional[int] = None    # None -> автопоиск
    ignore_indexes: Tuple[int, ...] = ()
    scan_limit: int = 8
    backend: str = "auto"          # auto | dshow | msmf | v4l2 | any
    width: int = 0                 # 0 -> разрешение по умолчанию драйвера
    height: int = 0
    fourcc: str = ""               # например MJPG
    reliability: CameraReliability = field(default_factory=CameraReliability)


@dataclass(frozen=True)
class OcrSettings:
    preload: bool = True
    gpu: bool = False
    country_code: str = "KG"       # пусто -> принимаем любые две буквы
    min_slot_confidence: float = 0.0
    min_segmentation_score: float = 0.35


@dataclass(frozen=True)
class Settings:
    backend_base_url: str = "http://localhost:8000"
    max_corrections_to_trust: int = 2
    capture_delay_seconds: float = 0.0
    fixture_fallback: bool = True
    fixtures_dir: Path = PROJECT_ROOT / "fixtures"
    gate_sources: Tuple[Tuple[str, str], ...] = (("entry", "usb"), ("exit", "ip"))
    ip_camera: IpCameraSettings = field(default_factory=IpCameraSettings)
    usb_camera: UsbCameraSettings = field(default_factory=UsbCameraSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)

    def source_for_gate(self, gate: str) -> Optional[str]:
        return dict(self.gate_sources).get(gate)


def _reliability(env: Mapping[str, str], prefix: str, warmup_default: int) -> CameraReliability:
    base = CameraReliability()
    return CameraReliability(
        warmup_frames=_env_int(env, f"{prefix}_WARMUP_FRAMES", warmup_default),
        reconnect_min_delay=_env_float(env, f"{prefix}_RECONNECT_MIN_DELAY", base.reconnect_min_delay),
        reconnect_max_delay=_env_float(env, f"{prefix}_RECONNECT_MAX_DELAY", base.reconnect_max_delay),
        stall_timeout=_env_float(env, f"{prefix}_STALL_TIMEOUT", base.stall_timeout),
        frame_timeout=_env_float(env, f"{prefix}_FRAME_TIMEOUT", base.frame_timeout),
    )


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    warmup = _env_int(env, "CAMERA_WARMUP_FRAMES", 5)

    ip_url = _env_str(env, "CAMERA_IP_URL", "")
    ip = IpCameraSettings(
        enabled=_env_bool(env, "CAMERA_IP_ENABLED", bool(ip_url)),
        url=ip_url,
        rtsp_transport=_env_str(env, "CAMERA_IP_RTSP_TRANSPORT", "tcp").lower(),
        open_timeout_ms=_env_int(env, "CAMERA_IP_OPEN_TIMEOUT_MS", 5000),
        read_timeout_ms=_env_int(env, "CAMERA_IP_READ_TIMEOUT_MS", 5000),
        reliability=_reliability(env, "CAMERA_IP", warmup),
    )

    usb_index_raw = _env_str(env, "CAMERA_USB_INDEX", "auto").lower()
    usb = UsbCameraSettings(
        enabled=_env_bool(env, "CAMERA_USB_ENABLED", True),
        index=None if usb_index_raw in ("", "auto") else _env_int(env, "CAMERA_USB_INDEX", 0),
        ignore_indexes=_env_int_list(env, "CAMERA_USB_IGNORE_INDEXES"),
        scan_limit=_env_int(env, "CAMERA_USB_SCAN_LIMIT", 8),
        backend=_env_str(env, "CAMERA_USB_BACKEND", "auto").lower(),
        width=_env_int(env, "CAMERA_USB_WIDTH", 0),
        height=_env_int(env, "CAMERA_USB_HEIGHT", 0),
        fourcc=_env_str(env, "CAMERA_USB_FOURCC", "").upper(),
        reliability=_reliability(env, "CAMERA_USB", warmup),
    )

    ocr = OcrSettings(
        preload=_env_bool(env, "OCR_PRELOAD", True),
        gpu=_env_bool(env, "OCR_GPU", False),
        country_code=_env_str(env, "PLATE_COUNTRY_CODE", "KG").upper(),
        min_slot_confidence=_env_float(env, "OCR_MIN_SLOT_CONFIDENCE", 0.0),
        min_segmentation_score=_env_float(env, "OCR_MIN_SEGMENTATION_SCORE", 0.35),
    )

    gates = tuple(
        (gate, _env_str(env, f"CAMERA_{gate.upper()}_SOURCE", default).lower())
        for gate, default in (("entry", "usb"), ("exit", "ip"))
    )
    for gate, source in gates:
        if source not in ("usb", "ip"):
            raise ValueError(f"CAMERA_{gate.upper()}_SOURCE должен быть 'usb' или 'ip', получено {source!r}")
    if ip.rtsp_transport not in ("tcp", "udp"):
        raise ValueError("CAMERA_IP_RTSP_TRANSPORT должен быть 'tcp' или 'udp'")
    if usb.backend not in ("auto", "dshow", "msmf", "v4l2", "any"):
        raise ValueError("CAMERA_USB_BACKEND должен быть одним из: auto, dshow, msmf, v4l2, any")

    return Settings(
        backend_base_url=_env_str(env, "BACKEND_BASE_URL", "http://localhost:8000"),
        max_corrections_to_trust=_env_int(env, "MAX_CORRECTIONS_TO_TRUST", 2),
        capture_delay_seconds=_env_float(env, "CAMERA_CAPTURE_DELAY_SECONDS", 0.0),
        fixture_fallback=_env_bool(env, "CAMERA_FIXTURE_FALLBACK", True),
        fixtures_dir=Path(_env_str(env, "CAMERA_FIXTURES_DIR", str(PROJECT_ROOT / "fixtures"))),
        gate_sources=gates,
        ip_camera=ip,
        usb_camera=usb,
        ocr=ocr,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
