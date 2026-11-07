from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

BACKEND_TIMEOUT_SECONDS = 5.0
MAX_CORRECTIONS_TO_TRUST = 2     


@dataclass(frozen=True)
class Settings:
    backend_base_url: str = "http://localhost:8000"
    backend_service_token: str = ""
    entry_camera_source: str = "1"
    exit_camera_source: str = "3"


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env

    def get(name: str, default: str) -> str:
        value = (env.get(name) or "").strip()
        return value or default

    return Settings(
        backend_base_url=get("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/"),
        backend_service_token=get("BACKEND_SERVICE_TOKEN", ""),
        entry_camera_source=get("ENTRY_CAMERA_SOURCE", "1"),
        exit_camera_source=get("EXIT_CAMERA_SOURCE", "3"),
    )
