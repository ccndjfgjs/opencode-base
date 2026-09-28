# -*- coding: utf-8 -*-
"""Качает модель обычным HTTPS с докачкой при обрыве (без XET и без API).

Кладёт файлы в models/faster-whisper-* рядом с этим скриптом.
WhisperModel понимает папку напрямую — кэш HuggingFace не нужен.

Источники по порядку: сначала официальный huggingface.co, потом
запасное зеркало. Это единственный скрипт базы, которому нужен
интернет, — и только на время скачивания. Всё остальное (голос,
мосты, агенты, окно) в сеть не ходит вообще.
"""
import argparse
import time
import urllib.request
from pathlib import Path

#: Официальный источник — первый. Зеркало — запасное, если официальный
#: недоступен. Свои адреса сюда не добавляем: только эти два.
SOURCES = ("https://huggingface.co", "https://hf-mirror.com")
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
HERE = Path(__file__).resolve().parent
RETRIES = 4


def fetch(repo: str, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        out = dest / name
        part = dest / (name + ".part")
        if out.is_file() and out.stat().st_size > 0:
            print(f"есть: {name} ({out.stat().st_size} байт)", flush=True)
            continue
        done = False
        for source in SOURCES:
            if done:
                break
            url = f"{source}/{repo}/resolve/main/{name}"
            for attempt in range(1, RETRIES + 1):
                try:
                    have = part.stat().st_size if part.is_file() else 0
                    req = urllib.request.Request(url)
                    if have:
                        req.add_header("Range", f"bytes={have}-")
                    print(f"качаю: {name} ({source}, попытка {attempt}/{RETRIES}, "
                          f"уже есть {have // 1024} КБ) ...", flush=True)
                    started = time.time()
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        total = resp.headers.get("Content-Range", "") or resp.headers.get("Content-Length", "")
                        mode = "ab" if (have and resp.status == 206) else "wb"
                        if mode == "wb":
                            have = 0
                        print(f"  ответ {resp.status}, всего: {total or '?'}", flush=True)
                        with part.open(mode) as fh:
                            while True:
                                chunk = resp.read(1024 * 256)
                                if not chunk:
                                    break
                                fh.write(chunk)
                                have += len(chunk)
                                if time.time() - started > 0 and have % (1024 * 1024 * 5) < 256 * 1024:
                                    speed = have / max(time.time() - started, 0.1) / 1024
                                    print(f"  ... {have // 1024} КБ ({speed:.0f} КБ/с)", flush=True)
                    part.rename(out)
                    print(f"готово: {name} ({out.stat().st_size} байт)", flush=True)
                    done = True
                    break
                except Exception as exc:  # noqa: BLE001 - сеть капризная, пробуем дальше
                    print(f"  сбой: {exc}.", flush=True)
                    time.sleep(5)
            if not done:
                print(f"  источник {source} не отдал файл — пробую следующий.", flush=True)
        if not done:
            print(f"НЕ СКАЧАЛОСЬ полностью: {name}. Запустите скрипт ещё раз — докачка продолжится.", flush=True)
            return 1
    print("ВСЕ ФАЙЛЫ НА МЕСТЕ", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Скачать модель голоса (официальный источник, зеркало — запасное).")
    parser.add_argument("--model", default="tiny", help="tiny/base/small (по умолчанию tiny)")
    args = parser.parse_args()
    repo = f"Systran/faster-whisper-{args.model}"
    dest = HERE / "models" / f"faster-whisper-{args.model}"
    return fetch(repo, dest)


if __name__ == "__main__":
    raise SystemExit(main())
