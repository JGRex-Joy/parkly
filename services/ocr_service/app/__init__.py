import os

# Обход проблемного бэкенда obsensor в OpenCV на Windows (раньше выставлялся в test_find.py).
# Должен быть задан до первого открытия VideoCapture.
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
