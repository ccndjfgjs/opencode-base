"""Лаунчер моста Godot.

Сервер — hi-godot/godot-ai, MIT, на PyPI 2026-10-14 это godot-ai 4.3.0.
Сам редакторный плагин стартует сервер и выдаёт команду attach: в ней
порты и capability. README прямо говорит, что голый адрес
http://127.0.0.1:8000/mcp не проходит проверку. Поэтому здесь нет
выдуманной команды. Лаунчер запускает только ту, которую записал док
Godot AI или человек, скопировав «Run this manually».

Файл лежит рядом с настройками opencode, не в репозитории:

    mcp-godot-attach.json
    { "command": ["uvx", "...", "godot-ai", "attach", "..."] }

В команде обязано быть слово attach. Команда на этот же лаунчер
отклоняется, иначе получится петля.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "godot-bridge"


def settings_file() -> Path:
    return common.settings_dir() / "mcp-godot-attach.json"


def load_command(path: Path) -> list[str] | None:
    text = common.read_text(path)
    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return common.godot_command(data)


def main() -> int:
    path = settings_file()
    command = load_command(path)
    if not command:
        common.say(PREFIX, f"нет команды attach: {path}")
        common.say(PREFIX, "Godot 4.7+, плагин Godot AI в addons/godot_ai/,")
        common.say(PREFIX, "включён в Project → Project Settings → Plugins.")
        common.say(PREFIX, "В доке Godot AI нажми Configure или скопируй")
        common.say(PREFIX, "«Run this manually» в этот JSON, поле command.")
        common.say(PREFIX, "Голый http://127.0.0.1:8000/mcp не подходит:")
        common.say(PREFIX, "README говорит, что так capability не передаётся.")
        common.say(PREFIX, f"Пакет на PyPI в день проверки: {common.GODOT_PYPI}.")
        return 1

    common.say(PREFIX, "запускаю команду attach из файла настроек, аргументы в журнал не пишу")
    return common.exec_stdio(command)


if __name__ == "__main__":
    sys.exit(main())
