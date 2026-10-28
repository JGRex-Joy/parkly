import os

# Обход проблемного бэкенда obsensor в OpenCV на Windows (раньше выставлялся в test_find.py).
# Должен быть задан до первого открытия VideoCapture.
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
# MSMF с аппаратными трансформациями открывает виртуальные камеры (Iriun) по 30+ секунд.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
