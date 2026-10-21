"""Лаунчер моста Kinocut — монтажа видео для агентов.

Kinocut (github.com/KyaniteLabs/kinocut, бывший mcp-video) — сервер MCP
монтажа на FFmpeg: режет, склеивает, подписывает, переворачивает в
вертикалку, проверяет качество и отдаёт «видеоквитанцию» после рендера.
203 инструмента, Apache-2.0, всё локально.

Что делает лаунчер:
    1. Читает `mcp-kinocut.json` рядом с настройками opencode — там один
       ключ `kino`: путь к `kino.exe` установленного Kinocut.
    2. Проверяет FFmpeg: без него сервер поднялся бы, но все инструменты
       падали бы на рендере. Поэтому отсутствие — отказ со словами, а не
       пустой старт.
    3. Запускает `kino --mcp` и передаёт ему stdio.

Почему путь берётся из файла, а не ищется по диску. Kinocut — Python-
пакет: на одной машине он стоит в окружении в Загрузках, на другой —
в pip-установке или вообще через uvx. Имена папок — личное
обстоятельство человека (урок 15.10 про uv в чужой папке), поэтому
лаунчер не угадывает: путь записан в `mcp-kinocut.json` рядом с
настройками opencode — по образцу `mcp-unreal.txt` и
`mcp-browsers.json`. Файл пишет сам лаунчер:

    kinocut_bridge_launcher.py --set-kino <путь-к-kino.exe>

Без файла мост отказывается словами и называет эту команду, а не молчит.

Запуск (как у остальных мостов):

    pythonw.exe quiet_launcher.py pythonw.exe kinocut_bridge_launcher.py

stdout у MCP-сервера — протокол. Весь журнал — только в stderr.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402

PREFIX = "kinocut-bridge"

#: Файл рядом с настройками opencode: {"kino": "путь/к/kino.exe"}.
#: По образцу mcp-browsers.json и mcp-unreal.txt: машина-специфичное
#: живёт рядом с настройками, в код и репозиторий не едет.
CONFIG_NAME = "mcp-kinocut.json"


def say(text: str) -> None:
    """Журнал только в stderr. stdout занят протоколом MCP."""
    print(f"[{PREFIX}] {text}", file=sys.stderr, flush=True)


def read_kino_path(settings: Path) -> str:
    """Путь к kino.exe из mcp-kinocut.json. Пусто — не задан или битый.

    Читаем только ключ `kino`, чужие ключи игнорируем. Битый файл —
    это отказ с причиной, а не молчание: без пути мосту нечем быть
    мостом.
    """
    path = settings / CONFIG_NAME
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        say(f"файл {path.name} не прочитан: {exc}")
        return ""
    if not isinstance(data, dict):
        say(f"файл {path.name} не словарь — ждём {{\"kino\": \"путь\"}}")
        return ""
    raw = data.get("kino", "")
    if not isinstance(raw, str) or not raw.strip():
        return ""
    return os.path.expandvars(raw.strip())


def ffmpeg_ready() -> tuple[bool, str]:
    """Есть ли FFmpeg. (есть, путь). Пустой путь — не нашли нигде."""
    found = common.resolve_exe("ffmpeg")
    if found:
        return True, found
    # winget кладёт ffmpeg без псевдонима в PATH (урок 15.10 с Claude:
    # resolve_exe не видит пакет без псевдонима — ищем папку Packages).
    root = os.environ.get("LOCALAPPDATA", "")
    hit = common.find_first((
        str(Path(root) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg*"
            / "*" / "bin" / "ffmpeg.exe"),
        str(Path(root) / "Microsoft" / "WinGet" / "Packages" / "*FFmpeg*"
            / "*" / "bin" / "ffmpeg.exe"),
    ))
    return bool(hit), hit


def set_kino_path(kino_exe: str) -> int:
    """Записывает путь к kino.exe в mcp-kinocut.json рядом с настройками."""
    target = Path(os.path.expandvars(kino_exe)).resolve()
    if not Path(kino_exe).is_file():
        say(f"файла нет: {kino_exe} — записывать нечего")
        return 1
    settings = common.settings_dir()
    settings.mkdir(parents=True, exist_ok=True)
    config = settings / CONFIG_NAME
    data: dict = {}
    if (settings / CONFIG_NAME).is_file():
        try:
            data = json.loads((settings / CONFIG_NAME).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
    data["kino"] = str(Path(kino_exe).resolve())
    (settings / CONFIG_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"записано в {settings / CONFIG_NAME}: kino = {kino_exe}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--set-kino":
        if len(args) < 2:
            say("нужен путь: --set-kino <путь к kino.exe>")
            return 2
        return set_kino_path(args[1])

    settings = common.settings_dir()
    kino = read_kino_path(settings)
    if not kino:
        say(f"не найден путь к kino: файла {CONFIG_NAME} рядом с настройками нет "
            f"или ключа kino в нём нет ({settings}).")
        say("Запишите путь командой: kinocut_bridge_launcher.py --set-kino <путь к kino.exe>")
        say("Kinocut ставится вместе с пакетом kinocut: pip install kinocut, "
            "либо запуск без установки: uvx --from kinocut kino")
        return 1
    if not Path(kino).is_file():
        say(f"kino по записанному пути не существует: {kino}")
        say("Запишите свежий путь командой: kinocut_bridge_launcher.py --set-kino <путь>")
        return 1

    ok, where = ffmpeg_ready()
    if not ok:
        say(f"ffmpeg не найден ({where or 'ни PATH, ни папка winget'})")
        say("Без FFmpeg Kinocut не монтирует. Ставится: winget install Gyan.FFmpeg")
        say("не поднимаюсь: сервер стартовал бы, но все инструменты падали бы на рендере.")
        return 1
    say(f"ffmpeg найден: {Path(where).name}")

    common.say(PREFIX, f"запускаю {kino} --mcp")
    return common.exec_stdio([kino, "--mcp"])


if __name__ == "__main__":
    sys.exit(main())
