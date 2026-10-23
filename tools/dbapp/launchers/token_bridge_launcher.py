"""Лаунчер мостов, которым нужны секреты из файла.

Зачем один файл на все такие мосты. У моста вроде Notion, Slack или
Telegram секрет — токен, — а правило программы одно и то же: в
opencode.jsonc и в журнал секрет не пишется, он лежит в файле
mcp-<имя>.txt рядом с настройками opencode. Раньше под каждое такое
правило писался свой лаунчер, и все они были одинаковы до последней
строки: прочитать файл, передать значения ребёнку, молчать о них.
Поэтому здесь одна реализация, а мост описывается данными в реестре.

Что мост передаёт лаунчеру ( connection.environment в реестре):

    MCP_BRIDGE_SECRETS = mcp-notion.txt
        Имя файла с секретами рядом с настройками opencode. Строки
        KEY=VALUE, # — комментарий. Если переменной нет — лаунчер
        просто запускает команду: файл не всегда нужен.

    MCP_BRIDGE_EXE = npx
        Чем запускать: npx, uvx, node — что велит реестр.

    MCP_BRIDGE_ARGS = -y @notionhq/notion-mcp-server@2.5.2
        Аргументы через пробел. Внутри допускается {КЛЮЧ} — такое
        место заменяется значением из файла секретов. В реестре на
        2026-10-23 такой надобности нет: все секреты уезжают к детям
        переменными окружения (NOTION_TOKEN, SLACK_MCP_XOXB_TOKEN,
        DB_PASSWORD и т.д.), потому что argv виден в списке процессов.
        {КЛЮЧ} оставлен запасом на пакеты, которые принимают секрет
        только аргументом.

Секреты не печатаются никогда: ни в сообщениях об отказе, ни в
журнале. stdout занят протоколом MCP, поэтому say() пишет в stderr.
Окно консоли не показывается: запуск идёт через
bridge_common.exec_stdio, а он прячет окно так же, как остальные
лаунчеры программы.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_common as common  # noqa: E402

PREFIX = "token-bridge"

#: {КЛЮЧ} в аргументах — значением из файла секретов.
_KEY = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


def _fail(lines: list[str]) -> int:
    for line in lines:
        common.say(PREFIX, line)
    return 1


def main() -> int:
    exe = (os.environ.get("MCP_BRIDGE_EXE") or "").strip()
    args_line = (os.environ.get("MCP_BRIDGE_ARGS") or "").strip()
    secrets_name = (os.environ.get("MCP_BRIDGE_SECRETS") or "").strip()
    if not exe or not args_line:
        return _fail([
            "лаунчер запущен без команды: у моста в реестре не заполнены",
            "MCP_BRIDGE_EXE и MCP_BRIDGE_ARGS. Правится реестр, не этот файл.",
        ])

    values: dict[str, str] = {}
    if secrets_name:
        base = common.settings_dir().resolve()
        path = (base / secrets_name).resolve()
        # Имя файла приходит из реестра, но проверять всё равно надо:
        # «../» или абсолютный путь иначе прочитали бы любой файл на
        # машине и отдали его содержимое серверу. Проверка дешёвая, а
        # дырка была настоящая — найдена аудитом 23.10.2026.
        if path != base and base not in path.parents:
            return _fail([
                f"файл секретов вне папки настроек: {secrets_name}",
                f"Разрешено только внутри: {base}",
                "Имя файла правится в реестре, а не здесь.",
            ])
        text = common.read_text(path)
        if not text.strip():
            return _fail([
                f"нет файла секретов: {path}",
                "Строки KEY=VALUE, по одной на строку, # — комментарий.",
                "Значения в журнал не пишутся и в opencode.jsonc не попадают:",
                "файл лежит рядом с настройками, а лаунчер передаёт их",
                "процессу моста через окружение.",
                "Заполни файл и перезапусти opencode.",
            ])
        values = common.parse_kv(text)
        common.say(PREFIX, f"файл секретов прочитан: {path.name}, "
                           f"строк {len(values)}, значения не печатаю")

    argv = [exe]
    for part in args_line.split(" "):
        if not part:
            continue

        def take(match: re.Match) -> str:
            key = match.group(1)
            value = values.get(key, "")
            if not value:
                raise KeyError(key)
            return value

        try:
            part = _KEY.sub(take, part)
        except KeyError as exc:
            where = (common.settings_dir() / secrets_name) if secrets_name else "реестр"
            return _fail([
                f"в файле секретов нет значения для {exc.args[0]}",
                f"файл: {where}",
                "Без него команду запускать нечем.",
            ])
        argv.append(part)

    env = dict(os.environ)
    env.update(values)
    # Печатаем строку аргументов как она записана в реестре: там стоят
    # {КЛЮЧ} в скобках, а не значения. Значения не печатаются никогда.
    common.say(PREFIX, f"запускаю: {exe} {args_line}")
    return common.exec_stdio(argv, env=env)


if __name__ == "__main__":
    sys.exit(main())
