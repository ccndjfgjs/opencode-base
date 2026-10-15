"""Лаунчер Spotify.

Пакет @xavifabregat/spotify-mcp 0.1.2, MIT, npm. Он ходит в официальный
Spotify Web API. Не продукт Spotify AB.

Что пакет требует, взято из его README (registry.npmjs.org, 15.10.2026), а
не из догадок:
  * Spotify Premium — нужен и для управления воспроизведением, и (с февраля
    2026) для создания своего приложения в кабинете разработчика;
  * Node.js не ниже 20;
  * токены лежат в ~/.spotify-mcp, не в репозитории;
  * вход делает мастер пакета (npx … init или … auth), он открывает браузер;
  * управлять воспроизведением можно только запущенным приложением Spotify:
    API «can only steer a running app».

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


def spotify_login_saved() -> bool:
    """Пакет хранит свой вход в ~/.spotify-mcp. Нет папки — входа не было."""
    return (Path.home() / ".spotify-mcp").exists()


def startup_notes(client_id: str, saved_login: bool, app: bool) -> list[str]:
    """Что сказать про готовность, не запуская пакет.

    Отдельной функцией, а не строкой в main: проверка не должна запускать
    npx, потому что мастер пакета при отсутствии входа открывает браузер,
    а эта программа его открывать не обещала.
    """
    notes: list[str] = []
    if client_id:
        notes.append("client id прочитан, в журнал не пишу")
    else:
        notes.append("client id в mcp-spotify.txt нет")
    if saved_login:
        notes.append("свою папку входа ~/.spotify-mcp пакет уже имеет")
    else:
        notes.append("входа нет: папки ~/.spotify-mcp нет, пакет ни разу не входил")
        notes.append("вход делает мастер пакета, браузер программа не открывает")
    if app:
        notes.append("приложение Spotify найдено: им можно управлять")
    else:
        notes.append(
            "приложение Spotify не найдено. Поиск и плейлист идут через Web API, "
            "а включение и переключение трека — нет: по README пакета API "
            "управляет только запущенным приложением"
        )
    notes.append(
        "Premium нужен по README пакета и для воспроизведения, и для создания "
        "своего приложения в кабинете разработчика. Наличие подписки мост не проверяет"
    )
    return notes


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
    for note in startup_notes(client_id, spotify_login_saved(), bool(common.spotify_app_path())):
        common.say(PREFIX, note)
    common.say(PREFIX, f"запускаю npx -y {PACKAGE}")
    common.say(PREFIX, "живой ответ Spotify эта программа не проверяла")
    return common.exec_stdio([npx, "-y", PACKAGE], env=env)


if __name__ == "__main__":
    sys.exit(main())
