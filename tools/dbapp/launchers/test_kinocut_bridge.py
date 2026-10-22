"""Проверка моста Kinocut: чтение пути, запись пути, отказы со словами.

    python tools/dbapp/launchers/test_kinocut_bridge.py

Проверки работают во временном каталоге настроек, а не в настоящем:
подменяется OPENCODE_CONFIG_DIR, и каждый случай меряется сам — на этой
машине Kinocut может стоять или не стоять, проверка не должна от этого
зависеть (урок 19.10 про проверку состояния машины).
"""

from __future__ import annotations

import contextlib
import io as _io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import kinocut_bridge_launcher as kinocut  # noqa: E402

passed = 0
failed = 0


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def with_temp_settings():
    """Временная папка настроек, видимая модулю через переменную среды."""
    tmp = tempfile.TemporaryDirectory()
    os.environ["OPENCODE_CONFIG_DIR"] = str(Path(tmp.name))
    return tmp


def main() -> int:
    # === 1. Чтение пути из файла настроек ===
    with with_temp_settings() as tmp:
        settings = Path(tmp)
        check(kinocut.read_kino_path(settings) == "",
              "без файла настроек путь пуст, а не выдуман")
        cfg = settings / kinocut.CONFIG_NAME
        cfg.write_text('{"kino": "C:/kino/kino.exe"}', encoding="utf-8")
        check(kinocut.read_kino_path(settings) == "C:/kino/kino.exe",
              "ключ kino читается из файла")
        cfg.write_text("не json вовсе", encoding="utf-8")
        check(kinocut.read_kino_path(settings) == "",
              "битый файл даёт пусто и не роняет лаунчер")
        cfg.write_text("[1, 2]", encoding="utf-8")
        check(kinocut.read_kino_path(settings) == "",
              "не-словарь даёт пусто и не роняет лаунчер")
        cfg.write_text('{"kino": ""}', encoding="utf-8")
        check(kinocut.read_kino_path(settings) == "",
              "пустой ключ даёт пусто")

    # === 2. Запись пути (--set-kino во временную папку настроек) ===
    with with_temp_settings() as tmp:
        settings = Path(tmp)
        fake_kino = Path(tmp) / "kino.exe"
        fake_kino.write_bytes(b"MZ")
        code = kinocut.set_kino_path(str(fake_kino))
        check(code == 0, "запись существующего файла отвечает кодом 0")
        cfg = settings / kinocut.CONFIG_NAME
        data = json.loads(cfg.read_text(encoding="utf-8"))
        check(Path(data["kino"]) == fake_kino.resolve(),
              "записан именно тот путь, что назван")
        code_missing = kinocut.set_kino_path(str(Path(tmp) / "нет-такого.exe"))
        check(code_missing == 1,
              "запись несуществующего пути отказывается, а не пишет вслепую")

    # === 3. main() без настроек: отказ со словами, код 1 ===
    with with_temp_settings() as tmp:
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                code = kinocut.main()
        finally:
            os.environ.pop("OPENCODE_CONFIG_DIR", None)
        err = buf.getvalue()
        check(code == 1, "без настроек main() отвечает отказом (код 1)")
        check(kinocut.CONFIG_NAME in buf.getvalue(),
              "и называет, какого файла не хватает")

    # === 4. FFmpeg: поиск возвращает пару (есть, путь) ===
    ok, where = kinocut.ffmpeg_ready()
    check(isinstance(ok, bool) and isinstance(where, str),
          "ffmpeg_ready отвечает парой (есть, путь)")
    check(not ok or where.lower().endswith("ffmpeg.exe"),
          "если нашла — то файл ffmpeg.exe, а не случайный путь")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
