"""Лаунчер моста Roblox Studio.

Это встроенный сервер самой студии, не сторонний исполнитель кода.
Документация Roblox (страница обновлена 2026-10-13) даёт для Windows
команду:

    cmd.exe /c %LOCALAPPDATA%\\Roblox\\mcp.bat

Файл mcp.bat появляется, только когда в студии включено
«Enable Studio as MCP server». Старый Roblox/studio-rust-mcp-server
сами авторы пометили как неразвиваемый и просят пользоваться встроенным.
Исполнители (executor) сюда не подключаются: это обход платформы, не мост.

stdout — протокол. Журнал — в stderr.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "roblox-bridge"


def mcp_bat() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    path = Path(local) / "Roblox" / "mcp.bat"
    return path if path.is_file() else None


def main() -> int:
    bat = mcp_bat()
    if bat is None:
        local = os.environ.get("LOCALAPPDATA") or "%LOCALAPPDATA%"
        common.say(PREFIX, f"нет файла {local}\\Roblox\\mcp.bat")
        common.say(PREFIX, "Его создаёт сама Roblox Studio, не эта программа.")
        common.say(PREFIX, "Открой студию → Assistant → … → Manage MCP Servers")
        common.say(PREFIX, "→ включи Enable Studio as MCP server, затем запусти лаунчер снова.")
        common.say(PREFIX, "Нужна актуальная Studio. Старый rust-сервер Roblox не используем:")
        common.say(PREFIX, "авторы сами отправили на встроенный.")
        return 1

    common.say(PREFIX, f"запускаю {bat}")
    shell = os.environ.get("COMSPEC") or "cmd.exe"
    return common.exec_stdio([shell, "/c", str(bat)])


if __name__ == "__main__":
    sys.exit(main())
