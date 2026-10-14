"""Лаунчер моста Unity.

Сервер — пакет CoplayDev, не наш код. Команда взята из описания
mcpforunityserver 10.3.0 на PyPI (2026-10-14):

    uvx --from mcpforunityserver mcp-for-unity --transport stdio

Версия закреплена. Плагин в редактор этот файл не ставит: его ставят
в Unity через Package Manager, git URL из README проекта. Без открытого
редактора с плагином сервер поднимется, но управлять сценой будет нечем.
Журнал — в stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "unity-bridge"
EDITOR_GLOBS = (
    r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
    r"C:\Program Files\Unity Hub\Unity Hub.exe",
)


def main() -> int:
    uvx = common.resolve_exe("uvx")
    if not uvx:
        common.say(PREFIX, "uvx не найден. Его ставит пакет uv: https://docs.astral.sh/uv/")
        common.say(PREFIX, "Без uvx сервер mcpforunityserver не запустить.")
        return 1

    editor = common.find_first(EDITOR_GLOBS)
    if editor:
        common.say(PREFIX, f"редактор или Hub: {editor}")
    else:
        common.say(PREFIX, "Unity.exe по обычному пути не найден. "
                    "Если редактор стоит в другом месте — это не отказ, "
                    "но плагин должен быть включён в открытом проекте.")

    common.say(PREFIX, f"запускаю uvx --from {common.UNITY_FROM} mcp-for-unity --transport stdio")
    common.say(PREFIX, "телеметрия пакета выключается переменной DISABLE_TELEMETRY=1")
    return common.exec_stdio([
        uvx, "--from", common.UNITY_FROM, "mcp-for-unity", "--transport", "stdio",
    ])


if __name__ == "__main__":
    sys.exit(main())
