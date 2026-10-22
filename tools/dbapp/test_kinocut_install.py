# -*- coding: utf-8 -*-
"""Тест kinocut_install без сети и без установки: поиск, конфиг, версии."""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kinocut_install  # noqa: E402

tmp = Path(tempfile.mkdtemp())

# 1. kino_from_config: конфиг с путём к существующему файлу
fake_exe = tmp / "kino.exe"
fake_exe.write_bytes(b"")
(tmp / "mcp-kinocut.json").write_text(
    json.dumps({"kino": str(fake_exe)}), encoding="utf-8")
found = kinocut_install.kino_from_config(tmp)
assert found == fake_exe, found
print("1. конфиг моста читается и путь проверяется")

# 2. find_kino: конфиг указывает на несуществующий файл — в конфиге
# «найдено» не считается; но в Downloads на этой машине kino стоит,
# поэтому по смыслу: либо нашлось в известном месте, либо отказ.
(tmp / "mcp-kinocut.json").write_text(
    json.dumps({"kino": r"C:\нет\такого\kino.exe"}), encoding="utf-8")
found, path, reason = kinocut_install.find_kino(tmp)
if found:
    print("2. конфиг битый, но нашлось в известном месте:", path)
else:
    assert "не найден" in reason, reason
    print("2. ничего нет — причина с перечнем мест")

# 3. find_kino через подменённое окружение программы
real_dir = kinocut_install.SERVER_DIR
thirdparty = tmp / ".venv" / "Scripts"
thirdparty.mkdir(parents=True, exist_ok=True)
(thirdparty / "kino.exe").write_bytes(b"")
kinocut_install.SERVER_DIR = tmp
found, path, _ = kinocut_install.find_kino(tmp / "пусто")
assert found and "kino.exe" in path, (found, path)
kinocut_install.SERVER_DIR = real_dir
print("3. окружение программы находится")

# 4. ffmpeg_state возвращает пару без падений
ok, why = kinocut_install.ffmpeg_state()
assert isinstance(ok, bool) and isinstance(why, str)
print("4. ffmpeg_state — пара без падений, причина словами при отказе")

# 5. версия из окружения: настоящая установка kinocut на этой машине
real_python = Path.home() / "Downloads" / "kinocut" / ".venv" / "Scripts" / "python.exe"
if real_python.is_file():
    version = kinocut_install._venv_version(real_python)
    assert version, "версия из настоящего окружения не читается"
    print("5. версия из окружения:", version)
else:
    print("5. (установки kinocut на машине нет — проверка пропущена)")
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
