"""Лаунчер моста OBS.

Зачем он нужен. Мост obs-mcp читает пароль из переменной окружения
OBS_WEBSOCKET_PASSWORD при старте. В opencode.jsonc пароль класть нельзя:
конфиг открыт, переносится между компьютерами и ездит в репозиторий
программы. Поэтому мост запускается не напрямую, а через этот файл:
пароль лежит рядом с настройками, читается здесь и передаётся дальше
уже как переменная окружения.

Что делает:
    1. Берёт пароль из файла рядом с настройками opencode.
    2. Подставляет его в OBS_WEBSOCKET_PASSWORD и OBS_WEBSOCKET_URL.
    3. Запускает установленный мост и передаёт ему stdio.

Почему Node, а не Python. В репозитории obs-mcp есть две реализации,
и Python-порядка в нём нерабочий: он зовёт FastMCP с параметром
description, которого в актуальном SDK нет, и падает на старте.
Проверено 02.10.2026: TypeScript-реализация — основная и рабочая, её же
рекомендует README проекта.

Ничего не пишет в stdout: stdout у MCP-сервера — это протокол, и лишний
текст в нём ломает связь. Весь журнал идёт в stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Папка с установленным мостом лежит рядом с лаунчером, внутри thirdparty.
NODE_DIR = HERE.parent.parent / "thirdparty" / "obs-mcp-node"
ENTRY = NODE_DIR / "node_modules" / "obs-mcp" / "build" / "index.js"


def say(text: str) -> None:
    """Журнал только в stderr. stdout занят протоколом MCP."""
    print(f"[obs-bridge] {text}", file=sys.stderr, flush=True)


def find_settings_dir() -> Path:
    """Папка настроек opencode.

    Порядок тот же, что и у остальной программы: переменная окружения,
    затем стандартное место пользователя. Ничего не выдумываем — если
    папку найти не удалось, говорим об этом, а не читаем чужую.
    """
    raw = os.environ.get("OPENCODE_CONFIG_DIR") or os.environ.get("XDG_CONFIG_HOME")
    if raw:
        candidate = Path(raw)
        if candidate.name == ".config":
            candidate = candidate / "opencode"
        if candidate.is_dir():
            return candidate
    return Path.home() / ".config" / "opencode"


def read_password(settings: Path) -> str:
    """Читает пароль из файла рядом с настройками."""
    path = settings / "mcp-obs-password.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("Пароль", "Нужен", "opencode", "Порт")):
            return line
    return ""


def main() -> int:
    settings = find_settings_dir()
    password = read_password(settings)
    if not password:
        say(f"Пароль не найден: {settings / 'mcp-obs-password.txt'}")
        say("Открой программу, вкладка opencode, блок серверов MCP, "
            "выбери OBS и нажми «Настроить автоматически».")
        return 1

    if not ENTRY.is_file():
        say(f"Мост не найден: {ENTRY}")
        say("Установи его: в папке thirdparty/obs-mcp-node выполни "
            "npm install obs-mcp")
        return 1

    env = dict(os.environ)
    env["OBS_WEBSOCKET_PASSWORD"] = password
    env["OBS_WEBSOCKET_URL"] = (
        env.get("OBS_WEBSOCKET_URL") or "ws://localhost:4455"
    )
    say(f"адрес OBS: {env['OBS_WEBSOCKET_URL']}")

    node = env.get("OBS_BRIDGE_NODE") or shutil_which("node")
    if not node:
        say("Node.js не найден. Он нужен мосту obs-mcp.")
        return 1

    say(f"запускаю мост: {node} {ENTRY}")
    try:
        proc = subprocess.Popen(
            [node, str(ENTRY)], cwd=str(NODE_DIR), env=env,
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
        )
    except OSError as exc:
        say(f"мост не запустился: {exc}")
        return 1
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def shutil_which(name: str) -> str | None:
    """Ищет программу в PATH. shutil.which, но с внятным именем."""
    from shutil import which

    return which(name)


if __name__ == "__main__":
    sys.exit(main())