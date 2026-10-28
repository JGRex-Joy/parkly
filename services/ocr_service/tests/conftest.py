import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("OCR_PRELOAD", "0")
os.environ.setdefault("CAMERA_USB_ENABLED", "0")
os.environ.setdefault("CAMERA_IP_URL", "")
os.environ.setdefault("CAMERA_FIXTURE_FALLBACK", "0")
