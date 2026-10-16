from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


class FixtureRepository:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path_for(self, gate: str) -> Optional[Path]:
        for candidate in (self._dir / f"{gate}_camera_sample.jpg", self._dir / "sample_plate.jpg"):
            if candidate.exists():
                return candidate
        return None

    def load_frame(self, gate: str) -> Optional[np.ndarray]:
        path = self._path_for(gate)
        if path is None:
            return None
        return cv2.imread(str(path))
