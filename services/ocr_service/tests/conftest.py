import os
import pytest

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


@pytest.fixture(scope="session")
def plate_font():
    return next((f for f in FONT_CANDIDATES if os.path.exists(f)), "simplex")


@pytest.fixture(scope="session")
def service():
    from app.recognizer import OcrEngine, RecognitionService
    engine = OcrEngine()
    engine.warm_up()
    return RecognitionService(engine)
