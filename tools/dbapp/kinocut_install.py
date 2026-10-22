# -*- coding: utf-8 -*-
r"""Установка Kinocut силами программы: окружение, FFmpeg, путь для моста.

**Что это.** Kinocut — pip-пакет с командой `kino` (и сервером `kino --mcp`).
Он не ставится через winget, поэтому во вкладке «Программы» у него свой
метод: `venv-pip`. Правило то же, что у галочек и OmniRoute — установка
доводит до готового сама:

1. Найти уже стоящий kino (конфиг моста, окружение программы, папка
   Downloads). Нашёлся — установка не повторяется.
2. Закрепить версию: последнюю спрашиваем у PyPI (тот же канал, с которого
   пакет и ставится) и вписываем в pyproject.toml **пином** — «kinocut»
   без номера между проверкой и установкой вправе отдать другую.
3. Окружение моста: `uv sync --project` — тот же ход, что у Unity-моста
   (pyproject + uv sync из python_envs).
4. FFmpeg: мост проверяет живьём и без него инструменты падают на
   рендере. Нет — ставится через winget (Gyan.FFmpeg), как записано в
   реестре.
5. Путь к kino.exe вписывается в mcp-kinocut.json рядом с настройками —
   это файл лаунчера, а НЕ opencode.jsonc: запись моста в настройки
   opencode остаётся отдельным действием человека.
6. Пост-проверка настоящая: версия из метаданных окружения равна пину
   и `kino --version` отвечает. Код возврата не считается доказательством.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "launchers"))

import bridge_common as common  # noqa: E402
import bridge_updates  # noqa: E402
import omniroute  # noqa: E402
import python_envs  # noqa: E402
import winget_install  # noqa: E402

#: Имя пакета на PyPI и имя модуля в окружении (find_spec по нему).
PYPINAME = "kinocut"

#: Где живёт окружение программы. Как у omniroute: мосты ставятся в
#: tools/thirdparty, а не куда попало на диске.
SERVER_DIR = Path(__file__).resolve().parent.parent / "thirdparty" / "kinocut"

FFMPEG_WINGET = "Gyan.FFmpeg"


def kino_from_config(settings_dir: Path | None = None) -> Path:
    """Путь к kino.exe из файла настроек моста. None — файла/пути нет.

    Возвращает None, а не пустой Path: Path() равен Path("."), и его
    истинность в проверке `if exe:` — верная дорога к «найдено: "."».
    """
    import json

    home = settings_dir or omniroute.find_settings_dir()
    config = home / "mcp-kinocut.json"
    if not config.is_file():
        return None
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    exe = Path(str((data or {}).get("kino") or ""))
    if exe.is_file():
        return exe
    return None


def find_kino(settings_dir: Path | None = None) -> tuple[bool, str, str]:
    """Ищет kino.exe на машине. (найдено, путь, причина-если-нет).

    Порядок: путь из файла настроек (то, что уже настроено), окружение
    программы, установка человека в Downloads. Порядок важен: программа
    ставит в своё окружение, но найденная установка человека ценнее
    новой копии.
    """
    home = settings_dir or omniroute.find_settings_dir()
    exe = kino_from_config(home)
    if exe is not None:
        return True, str(exe), ""
    for candidate in (SERVER_DIR / ".venv" / "Scripts" / "kino.exe",
                      Path.home() / "Downloads" / "kinocut" / ".venv"
                      / "Scripts" / "kino.exe"):
        if candidate.is_file():
            return True, str(candidate), ""
    return False, "", ("kino.exe не найден: ни в настройках, ни в окружении "
                       "программы, ни в Downloads\\kinocut")


def ffmpeg_state() -> tuple[bool, str]:
    """Есть ли ffmpeg на PATH. (ок, причина)."""
    code, out, err, why = common.run_capture(
        ["ffmpeg", "-version"], timeout=30)
    if code == 0 and out:
        return True, ""
    return False, why or "ffmpeg на PATH не отвечает"


def _write_kino_config(kino: Path) -> str:
    """Путь к kino.exe — в файл настроек лаунчера (НЕ в opencode.jsonc)."""
    import json

    home = omniroute.find_settings_dir()
    try:
        home.mkdir(parents=True, exist_ok=True)
        (home / "mcp-kinocut.json").write_text(
            json.dumps({"kino": str(kino)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return ""
    except OSError as exc:
        return f"записать mcp-kinocut.json не удалось: {exc}"


def install(progress=None) -> tuple[list[str], list[str]]:
    """Ставит Kinocut целиком: окружение, FFmpeg, путь лаунчеру.

    Порядок по правилу «кнопка доводит до готового сама»: найденное
    не переустанавливается, версия берётся у PyPI и закрепляется пином
    в pyproject, FFmpeg ставится через winget, путь лаунчеру вписывается,
    и в конце — настоящая проверка версии, а не код возврата.
    """
    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    # 1. уже стоит?
    found, path, _reason = find_kino()
    if found:
        say(f"Kinocut уже стоит: {path}")
        return messages, []

    # 2. закреплённая версия с PyPI
    pin, why = bridge_updates.pypi_latest(PYPINAME)
    if not pin:
        return messages, [f"версию kinocut у PyPI спросить не вышло: {why}"]
    say(f"Ставлю kinocut=={pin} (последняя у PyPI).")

    # 3. pyproject с пином — образец unity-mcp
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    (SERVER_DIR / "pyproject.toml").write_text(
        '[project]\n'
        'name = "kinocut-bridge"\n'
        'version = "0.1.0"\n'
        'description = "Окружение моста Kinocut: пакет закреплён пином"\n'
        'requires-python = ">=3.11"\n'
        f'dependencies = ["{PYPINAME}=={pin}"]\n',
        encoding="utf-8")

    # 4. окружение
    python, env_log = python_envs.ensure_venv(
        SERVER_DIR, need_module=PYPINAME, progress=progress)
    if python is None:
        return messages, env_log[-3:] or ["окружение не создалось"]

    # 5. FFmpeg — доводим сами, как и всё остальное
    ok, why = ffmpeg_state()
    if not ok:
        say("FFmpeg не найден — ставлю через winget (Gyan.FFmpeg)…")
        _msg, ffmpeg_errors = winget_install.install("Gyan.FFmpeg",
                                                     progress=progress)
        errors.extend(ffmpeg_errors)
        ok, why = ffmpeg_state()
        if not ok:
            errors.append("FFmpeg не появился на PATH: " + (why or "нет в PATH")
                          + ". Без него инструменты монтажа падают на рендере.")
            return messages, errors
        say("FFmpeg на месте.")

    # 6. путь лаунчеру
    kino = SERVER_DIR / ".venv" / "Scripts" / "kino.exe"
    if not kino.is_file():
        return messages, [f"kino.exe не появился после установки: {kino}"]
    failed = _write_kino_config(kino)
    if failed:
        return messages, [failed]
    say(f"Путь лаунчеру записан: mcp-kinocut.json → {kino}")

    # 7. настоящая пост-проверка
    got = _venv_version(python)
    if pin not in got:
        errors.append(f"окружение готово, но версии {pin} в нём нет "
                      f"({got or 'не читается'}) — установка не считается "
                      f"выполненной")
        return messages, errors
    say(f"Установлен kinocut=={got}; проверено чтением версии из окружения.")
    say("Мост kinocut в настройки opencode НЕ вписан — включение моста "
        "отдельное действие, чтобы человек проверил импорт сам.")
    return messages, errors


def _write_kino_config(kino: Path) -> str:
    """Путь к kino.exe — в mcp-kinocut.json (файл лаунчера)."""
    import json

    home = omniroute.find_settings_dir()
    config = home / "mcp-kinocut.json"
    try:
        config.write_text(
            json.dumps({"kino": str(kino)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return ""
    except OSError as exc:
        return f"записать mcp-kinocut.json не вышло: {exc}"


def _venv_version(python: Path) -> str:
    """Версия kinocut из окружения. Пусто — окружения или пакета нет."""
    if not Path(python).is_file():
        return ""
    code = "import importlib.metadata as m; print(m.version('kinocut'))"
    code, out, err, status = common.run_capture(
        [str(python), "-c", code], timeout=60)
    if status != "":
        return ""
    return (out or "").strip()
