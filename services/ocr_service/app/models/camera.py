from __future__ import annotations

import enum
from dataclasses import dataclass

import numpy as np


class CameraKind(str, enum.Enum):
    USB = "usb"
    WIFI = "wifi"
    IP = "ip"


class ConnectionState(str, enum.Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass(frozen=True)
class CapturedFrame:
    image: np.ndarray       
    captured_at: float      
    source: str             
