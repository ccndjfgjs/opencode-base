"""Проверки лаунчеров без редакторов и без сети.

Запуск из любой папки:

    python tools/dbapp/launchers/test_bridge_launchers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402


def check(ok: bool, text: str) -> None:
    mark = "ok" if ok else "FAIL"
    print(f"  {mark}  {text}")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    check(common.parse_version("v24.19.0") == (24, 19, 0), "версия node разбирается")
    check(common.version_at_least((22, 12, 0), common.TIKTOK_NODE), "22.12 годится TikTok")
    check(not common.version_at_least((22, 11, 9), common.TIKTOK_NODE), "22.11 TikTok не берёт")
    check(not hasattr(common, "UNREAL_NODE"),
          "мосту Unreal Node не нужен, и минимальной версии для него нет")
    check(not hasattr(common, "UNREAL_PACKAGE"),
          "и npm-пакета в коде нет: сервер внутри плагина EngineWire")

    kv = common.parse_kv("# секрет\nTIKTOK_APP_ID=abc\nTIKTOK_ACCESS_TOKEN=\"tok en\"\n\n")
    check(kv["TIKTOK_APP_ID"] == "abc", "ключ без комментария")
    check(kv["TIKTOK_ACCESS_TOKEN"] == "tok en", "кавычки снимаются, пробел внутри остаётся")
    check("секрет" not in str(kv), "комментарий не стал значением")

    project, plugin = common.unreal_settings("# путь\nD:\\Games\\MyGame\n")
    check(project == r"D:\Games\MyGame" and plugin == "", "одна строка — это проект")
    project, plugin = common.unreal_settings("project=C:/Game\nplugin=C:/EngineWire\n")
    check(project == "C:/Game" and plugin == "C:/EngineWire", "project= и plugin=")

    check(common.godot_command({"command": ["uvx", "godot-ai", "attach"]}) ==
          ["uvx", "godot-ai", "attach"], "attach принимается")
    check(common.godot_command({"command": ["uvx", "godot-ai"]}) is None,
          "без attach команда отвергается")
    check(common.godot_command(
        {"command": ["python", "godot_bridge_launcher.py", "attach"]}) is None,
          "петля на свой лаунчер отвергается")
    check(common.godot_command({"command": "attach"}) is None, "строка вместо списка отвергается")

    prepared = common.prepare_argv(["npx.cmd", "-y", "pkg"])
    check(prepared[0].lower().endswith("cmd.exe") or prepared[0].lower().endswith("cmd"),
          "пакетный файл идёт через cmd, а не напрямую")
    check("token" not in " ".join(prepared), "в argv проверки нет секрета")
    print("лаунчеры: проверки прошли")


if __name__ == "__main__":
    main()
