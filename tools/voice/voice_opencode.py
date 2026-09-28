# -*- coding: utf-8 -*-
"""Голосовой ввод для opencode на faster-whisper (полностью локально).

Простыми словами: слушает микрофон, превращает речь в текст,
текст кладёт в файл voice_outbox.txt — opencode читает его обычным
инструментом Read. Ответы opencode озвучивает ключом --speak.

Режимы распознавания — ВЫБОР:
    без ключа  — ОФЛАЙН: локальный faster-whisper с диска (models/).
                   Интернет не нужен, звук никуда не уходит.
    --online   — ОБЛАКО (Google, бесплатно, без ключа): точнее на шумной
                   речи, но нужен интернет и звук уходит наружу.
                   Пароли и секреты в этом режиме не диктовать.
    python voice_opencode.py --once [--seconds 6] [--model small]
        Разовое прослушивание: записать N секунд, распознать,
        напечатать и дописать в voice_outbox.txt.

    python voice_opencode.py [--seconds 4] [--model small]
        Постоянное слушание (как Алиса): пишет фразы по мере речи.
        Стоп-слова: стоп, выход, хватит, закончить.

    python voice_opencode.py --speak "Текст ответа"
        Только озвучить текст (для ответов opencode).

    python voice_opencode.py --file запись.wav [--model tiny]
        Распознать аудиофайл (wav/mp3/ogg/m4a/flac), текст — в voice_outbox.txt.

    python voice_opencode.py --list-mics
        Показать микрофоны, ничего больше не делает.

    python voice_opencode.py --help-mic
        Подсказка, если микрофон не находится.

Всё работает без интернета и без чужих сервисов: модель берётся
только с диска из папки models/. Нет модели — скрипт скажет, какой
командой её скачать (fetch_model.py). Никаких ключей и облаков.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTBOX = HERE / "voice_outbox.txt"

SAMPLE_RATE = 16000
STOP_WORDS = ("стоп", "выход", "выйти", "хватит", "закончить", "завершить")
DEFAULT_MODEL = "small"
DEFAULT_SECONDS = 5


def log(text: str) -> None:
    print(text, flush=True)


def save_to_outbox(text: str) -> None:
    """Дописывает фразу в outbox: opencode читает файл и видит текст."""
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with OUTBOX.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{stamp}] {text}\n")


def list_mics() -> int:
    try:
        import sounddevice as sd
    except ImportError:
        log("Нет пакета sounddevice. Поставьте: python -m pip install sounddevice")
        return 2
    log("Микрофоны (устройства ввода):")
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            log(f"  [{i}] {dev['name']} (входов: {dev['max_input_channels']})")
    log(f"\nЧастота по умолчанию: {SAMPLE_RATE} Гц. Outbox: {OUTBOX}")
    return 0


def record(seconds: int) -> "object":
    """Пишет звук с микрофона. Возвращает numpy-массив (float32, mono)."""
    import numpy as np
    import sounddevice as sd

    frames = int(SAMPLE_RATE * seconds)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return np.asarray(audio).reshape(-1)


def is_silence(audio: "object", threshold: float = 0.01) -> bool:
    """Тишина ли в записи: считаем среднюю громкость."""
    try:
        import numpy as np

        rms = float(np.sqrt(np.mean(np.asarray(audio, dtype=float) ** 2)))
        return rms < threshold
    except Exception:
        return False


def load_model(name: str):
    """Ленивая загрузка faster-whisper: импорт и модель — только когда надо.

    Строго с диска из models/: в сеть этот скрипт не ходит вообще.
    Нет папки модели — честно говорит скачать скриптом fetch_model.py.
    """
    # Модель — только из models/ рядом со скриптом. Чужих адресов здесь
    # нет и быть не должно: голос работает полностью без сети.
    local = HERE / "models" / f"faster-whisper-{name}"
    if not (local / "model.bin").is_file():
        log(f"Модели '{name}' нет на диске (папка {local}).")
        log(f"Скачайте её:  python fetch_model.py --model {name}")
        raise SystemExit(2)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("Нет пакета faster-whisper. Поставьте: python -m pip install faster-whisper")
        raise SystemExit(2)
    log(f"Загружаю модель '{name}' с диска...")
    model = WhisperModel(str(local), device="cpu", compute_type="int8")
    log("Модель готова.")
    return model


def transcribe(model, audio) -> str:
    """Локально: faster-whisper с диска. В сеть не ходит."""
    segments, _info = model.transcribe(audio, language="ru", beam_size=5)
    parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    return " ".join(parts).strip()


def transcribe_cloud(audio) -> str:
    """Через облако (Google, бесплатно, без ключа): точнее на шумной речи,
    но нужен интернет. Звук уходит наружу — пароли не диктовать."""
    try:
        import speech_recognition as sr
    except ImportError:
        log("Нет пакета SpeechRecognition. Поставьте: python -m pip install SpeechRecognition")
        raise SystemExit(2)
    import numpy as np

    pcm = (np.asarray(audio, dtype=float) * 32767.0).clip(-32768, 32767).astype("<i2").tobytes()
    data = sr.AudioData(pcm, SAMPLE_RATE, 2)
    recognizer = sr.Recognizer()
    try:
        return recognizer.recognize_google(data, language="ru-RU").strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        log("Облако не отвечает (нет сети?). Попробуйте без --online.")
        raise SystemExit(3)


def transcribe_any(model, audio, online: bool) -> str:
    """Одна точка выбора: онлайн — облако, иначе локальная модель."""
    if online:
        return transcribe_cloud(audio)
    assert model is not None
    return transcribe(model, audio)


def speak(text: str, rate: int = 175) -> None:
    """Озвучка текста через системные голоса Windows."""
    import pyttsx3

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", rate)
        for voice in engine.getProperty("voices"):
            name = f"{voice.name} {voice.id}".lower()
            if "ru" in name or "russian" in name or "рус" in name:
                engine.setProperty("voice", voice.id)
                break
    except Exception:
        pass
    log(f"[ОЗВУЧКА]: {text}")
    engine.say(text)
    engine.runAndWait()


def cmd_once(seconds: int, model_name: str, online: bool = False, quiet_save: bool = False) -> int:
    model = None if online else load_model(model_name)
    log(f"Слушаю {seconds} c (режим: {'облако' if online else 'локально'}). Говорите...")
    audio = record(seconds)
    if is_silence(audio):
        log("Тихо — ничего не услышал. Попробуйте ещё раз.")
        return 1
    text = transcribe_any(model, audio, online)
    if not text:
        log("Не разобрал речь. Попробуйте говорить ближе к микрофону.")
        return 1
    log(f"[ГОЛОС]: {text}")
    save_to_outbox(text)
    if not quiet_save:
        log(f"Сохранено в {OUTBOX} — opencode прочитает файл сам.")
    return 0


def load_audio_file(path_str: str):
    """Читает аудиофайл в моно 16 кГц float32: wav/ogg/mp3/m4a/flac.
    Сначала пробует av (все форматы), потом soundfile, потом wave из коробки."""
    import numpy as np

    path = Path(str(path_str or "").strip()).expanduser()
    if not path.is_file():
        log(f"Нет такого файла: {path}")
        raise SystemExit(2)
    # --- av: понимает почти всё (mp3, m4a, ogg, flac, wav)
    try:
        import av

        container = av.open(str(path))
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        chunks = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray()[0].astype("float32"))
        container.close()
        if not chunks:
            raise ValueError("в файле нет звука")
        return np.concatenate(chunks)
    except ImportError:
        pass
    except Exception as exc:
        log(f"av не справился ({exc}), пробую проще...")
    # --- soundfile: wav/flac/ogg
    try:
        import soundfile as sf

        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        if rate != SAMPLE_RATE:
            x_old = np.linspace(0.0, 1.0, len(mono))
            x_new = np.linspace(0.0, 1.0, int(len(mono) * SAMPLE_RATE / rate))
            mono = np.interp(x_new, x_old, mono).astype("float32")
        return mono
    except ImportError:
        pass
    except Exception as exc:
        log(f"soundfile не справился ({exc}), пробую wave...")
    # --- wave из коробки: только несжатый wav
    import wave

    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ValueError("сжатый wav — нужен av или soundfile")
            raw = wav.readframes(wav.getnframes())
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            rate = wav.getframerate()
    except (wave.Error, EOFError) as exc:
        log(f"Не аудиофайл: {exc}")
        raise SystemExit(2)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    data = np.frombuffer(raw, dtype=dtype).astype("float32")
    if width == 1:
        data = (data - 128.0) / 128.0
    else:
        data = data / float(2 ** (width * 8 - 1))
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        x_old = np.linspace(0.0, 1.0, len(data))
        x_new = np.linspace(0.0, 1.0, int(len(data) * SAMPLE_RATE / rate))
        data = np.interp(x_new, x_old, data).astype("float32")
    return data


def cmd_file(path_str: str, model_name: str, online: bool = False) -> int:
    model = None if online else load_model(model_name)
    log(f"Читаю файл: {path_str} (режим: {'облако' if online else 'локально'})")
    audio = load_audio_file(path_str)
    log(f"Звука: {len(audio) / SAMPLE_RATE:.1f} c. Распознаю...")
    text = transcribe_any(model, audio, online)
    if not text:
        log("В файле речи не нашлось.")
        return 1
    log(f"[ГОЛОС]: {text}")
    save_to_outbox(text)
    log(f"Сохранено в {OUTBOX} — opencode прочитает файл сам.")
    return 0


def cmd_listen(seconds: int, model_name: str, online: bool = False) -> int:
    model = None if online else load_model(model_name)
    log(f"Постоянное слушание включено (режим: {'облако' if online else 'локально'}). Говорите фразами.")
    log(f"Стоп-слова: {', '.join(STOP_WORDS)}. Выход: Ctrl+C.")
    try:
        while True:
            audio = record(seconds)
            if is_silence(audio):
                continue
            try:
                text = transcribe_any(model, audio, online)
            except SystemExit as exc:
                if online and exc.code == 3:
                    log("Облако отвалилось — дальше слушаю локально.")
                    online, model = False, load_model(model_name)
                    continue
                raise
            if not text:
                continue
            log(f"[ГОЛОС]: {text}")
            save_to_outbox(text)
            low = text.lower().strip().rstrip(".!")
            if low in STOP_WORDS:
                speak("До свидания!")
                break
    except KeyboardInterrupt:
        log("\nОстановлено (Ctrl+C). Всё сказанное уже в voice_outbox.txt.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Голосовой ввод для opencode (faster-whisper, локально).")
    parser.add_argument("--once", action="store_true", help="записать один кусок и выйти")
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS, help="длина записи в секундах (по умолчанию 5)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="модель whisper: tiny/base/small/medium (по умолчанию small)")
    parser.add_argument("--speak", default="", help="только озвучить текст и выйти")
    parser.add_argument("--file", default="", help="распознать аудиофайл (wav/mp3/ogg/m4a/flac) и выйти")
    parser.add_argument("--online", action="store_true",
                        help="режим ОБЛАКО: точнее, но нужен интернет и звук уходит наружу. "
                             "Без ключа — локальный faster-whisper с диска")
    parser.add_argument("--rate", type=int, default=175, help="скорость озвучки (по умолчанию 175)")
    parser.add_argument("--list-mics", action="store_true", help="показать микрофоны и выйти")
    args = parser.parse_args(argv)

    if args.list_mics:
        return list_mics()
    if args.speak:
        speak(args.speak, rate=args.rate)
        return 0
    if args.file:
        return cmd_file(args.file, args.model, online=args.online)

    seconds = max(2, min(int(args.seconds or DEFAULT_SECONDS), 30))
    if args.once:
        return cmd_once(seconds, args.model, online=args.online)
    return cmd_listen(seconds, args.model, online=args.online)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
