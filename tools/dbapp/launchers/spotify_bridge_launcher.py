"""Лаунчер Spotify.

Пакет @xavifabregat/spotify-mcp 0.1.2, MIT, npm на 2026-10-14.
Он ходит в официальный Spotify Web API. Не продукт Spotify AB.
Воспроизведение Spotify отдаёт только Premium. Вход — свой, через
мастер пакета. Токены пакет кладёт в ~/.spotify-mcp, не в репозиторий.

Client ID, если его записала кнопка, передаётся переменной и в журнал
не печатается.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "spotify-bridge"
PACKAGE = "@xavifabregat/spotify-mcp@0.1.2"
NODE_FLOOR = (20, 0, 0)


def settings_file() -> Path:
    return common.settings_dir() / "mcp-spotify.txt"


def main() -> int:
    node = common.node_version()
    if node is None:
        common.say(PREFIX, "Node.js не найден. Пакету нужен Node 20 или новее.")
        return 1
    if not common.version_at_least(node, NODE_FLOOR):
        common.say(PREFIX, f"Node слишком старый: {'.'.join(map(str, node))}.")
        return 1
    npx = common.resolve_exe("npx")
    if not npx:
        common.say(PREFIX, "npx не найден. Он приезжает вместе с Node.js.")
        return 1

    env = dict(os.environ)
    values = common.parse_kv(common.read_text(settings_file()))
    client_id = values.get("SPOTIFY_CLIENT_ID", "").strip()
    if client_id:
        env["SPOTIFY_CLIENT_ID"] = client_id
        common.say(PREFIX, "client id прочитан, в журнал не пишу")
    else:
        common.say(PREFIX, "client id в mcp-spotify.txt нет")
        common.say(PREFIX, "пакет посмотрит свой ~/.spotify-mcp, если вход уже был")
    common.say(PREFIX, f"запускаю npx -y {PACKAGE}")
    common.say(PREFIX, "живой ответ Spotify эта программа не проверяла")
    return common.exec_stdio([npx, "-y", PACKAGE], env=env)


if __name__ == "__main__":
    sys.exit(main())
