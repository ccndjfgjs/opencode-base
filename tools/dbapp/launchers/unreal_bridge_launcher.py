"""Лаунчер моста Unreal Engine.

Сервер — npm-пакет ChiR24, не наш код. На 2026-10-14 в реестре npm:
  latest = 0.5.30, beta = 0.6.0-beta-e.
README проекта прямо говорит: без метки beta ставится 0.5.30, и он
не совпадает с плагином 0.6. Поэтому запускаем закреплённую 0.6.0-beta-e,
а не «latest» и не плавающий @beta.

Плагин 0.6 называется EngineWire и лежит в проекте:
  MyGame/Plugins/EngineWire/
Токен capability сервер читает сам из проекта, если задан UE_PROJECT_PATH.
В этот репозиторий путь проекта не пишется: он у каждого свой и в
настройках opencode, файл mcp-unreal.txt.

stdout — протокол. Журнал и отказы — в stderr.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "unreal-bridge"


def settings_file() -> Path:
    return common.settings_dir() / "mcp-unreal.txt"


def explain_file(path: Path) -> None:
    common.say(PREFIX, f"нет пути проекта: {path}")
    common.say(PREFIX, "Создай этот файл. Одна строка — папка проекта или .uproject.")
    common.say(PREFIX, "Либо две строки: project=... и, если плагин не внутри")
    common.say(PREFIX, "проекта, plugin=...\\EngineWire")
    common.say(PREFIX, "Плагин: скачать EngineWire с релизов ChiR24/Unreal_mcp")
    common.say(PREFIX, "и положить в Plugins/EngineWire, затем открыть проект.")


def main() -> int:
    path = settings_file()
    project_raw, plugin_raw = common.unreal_settings(common.read_text(path))
    project = common.project_dir(project_raw)
    if project is None:
        explain_file(path)
        return 1
    if not common.enginewire_present(project, plugin_raw):
        common.say(PREFIX, f"в {project} нет Plugins/EngineWire")
        common.say(PREFIX, "Сервер закреплён на 0.6.0-beta-e. Старый плагин")
        common.say(PREFIX, "McpAutomationBridge к этой версии не подходит,")
        common.say(PREFIX, "и запускать 0.5.30 вместо неё нельзя: README говорит,")
        common.say(PREFIX, "что ветки не совпадают.")
        return 1

    node = common.node_version()
    if node is None:
        common.say(PREFIX, "Node.js не найден. Пакету нужен Node 20.19 или новее.")
        return 1
    if not common.version_at_least(node, common.UNREAL_NODE):
        common.say(PREFIX, f"Node слишком старый: {'.'.join(map(str, node))}. "
                    "Нужен 20.19 или новее — так написано в engines пакета.")
        return 1
    npx = common.resolve_exe("npx")
    if not npx:
        common.say(PREFIX, "npx не найден. Он приезжает вместе с Node.js.")
        return 1

    env = dict(os.environ)
    env["UE_PROJECT_PATH"] = str(project)
    common.say(PREFIX, f"проект: {project}")
    common.say(PREFIX, f"запускаю npx -y {common.UNREAL_PACKAGE}")
    return common.exec_stdio(
        [npx, "-y", common.UNREAL_PACKAGE],
        env=env,
    )


if __name__ == "__main__":
    sys.exit(main())
