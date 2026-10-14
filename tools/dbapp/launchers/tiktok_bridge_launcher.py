"""Лаунчер моста TikTok.

Это не редактор и не обход входа. Пакет
@getmcpads/tiktok-ads-mcp-server 2.0.1 (Apache-2.0, реестр npm на
2026-10-14) ходит в TikTok Business API с токеном самого человека.
Описание пакета: чтение и отдельные записи, запись только после
предпросмотра и явного подтверждения.

Скрейпер, вход в чужой аккаунт и обход проверки сюда не входят.

Токен и App ID лежат рядом с настройками opencode, не в репозитории:

    mcp-tiktok.txt
    TIKTOK_ACCESS_TOKEN=...
    TIKTOK_APP_ID=...

В stderr значения не печатаются. stdout — протокол MCP.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "tiktok-bridge"
TOKEN_KEY = "TIKTOK_ACCESS_TOKEN"
APP_KEY = "TIKTOK_APP_ID"


def settings_file() -> Path:
    return common.settings_dir() / "mcp-tiktok.txt"


def main() -> int:
    path = settings_file()
    values = common.parse_kv(common.read_text(path))
    token = values.get(TOKEN_KEY, "").strip()
    app_id = values.get(APP_KEY, "").strip()
    if not token or not app_id:
        common.say(PREFIX, f"нет токена или App ID: {path}")
        common.say(PREFIX, "Две строки, без кавычек вокруг файла:")
        common.say(PREFIX, "TIKTOK_ACCESS_TOKEN=...")
        common.say(PREFIX, "TIKTOK_APP_ID=...")
        common.say(PREFIX, "Их выдаёт кабинет TikTok Business API, не эта программа.")
        common.say(PREFIX, "Официальный удалённый MCP TikTok в открытый доступ")
        common.say(PREFIX, "на день проверки не подтверждался, поэтому берётся")
        common.say(PREFIX, "самостоятельный пакет, и запросы идут прямо в API TikTok.")
        return 1

    node = common.node_version()
    if node is None:
        common.say(PREFIX, "Node.js не найден. Пакету нужен Node 22.12 или новее.")
        return 1
    if not common.version_at_least(node, common.TIKTOK_NODE):
        common.say(PREFIX, f"Node слишком старый: {'.'.join(map(str, node))}. "
                    "В engines пакета написано >=22.12.0.")
        return 1
    npx = common.resolve_exe("npx")
    if not npx:
        common.say(PREFIX, "npx не найден. Он приезжает вместе с Node.js.")
        return 1

    env = dict(os.environ)
    env[TOKEN_KEY] = token
    env[APP_KEY] = app_id
    common.say(PREFIX, "токен прочитан, в журнал не пишу")
    common.say(PREFIX, f"запускаю npx -y {common.TIKTOK_PACKAGE}")
    return common.exec_stdio([npx, "-y", common.TIKTOK_PACKAGE], env=env)


if __name__ == "__main__":
    sys.exit(main())
