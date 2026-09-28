# -*- coding: utf-8 -*-
"""Проверка связки: локальная tiny-модель + транскрибация."""
from pathlib import Path

import numpy as np

from faster_whisper import WhisperModel

MODEL_DIR = str(Path(__file__).resolve().parent / "models" / "faster-whisper-tiny")

print("Загружаю локальную модель...", flush=True)
m = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8")
print("MODEL OK", flush=True)
segs, info = m.transcribe(np.zeros(16000, dtype="float32"), language="ru")
print("TRANSCRIBE OK:", repr("".join(s.text for s in segs)), flush=True)
print("Язык:", info.language, "вероятность:", round(info.language_probability, 2), flush=True)
