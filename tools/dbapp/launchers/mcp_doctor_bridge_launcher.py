"""Мост «Смотритель мостов»: проверяет, кто из серверов MCP жив.

Зачем он. Красная строка в списке серверов сама по себе ни о чём не
говорит: то ли сервер молчит, то ли его команда не запускается, то ли про
него забыли. Смотритель отвечает на это списком и причиной по каждому.

Три инструмента:

* `server_list`      — кто вообще прописан и в каком файле настроек;
* `server_check`     — проверка одного сервера;
* `server_check_all` — проверка всех, параллельно.

Настройки читаются из ДВУХ файлов: `opencode.jsonc`, куда пишет программа,
и `opencode.json`, который тоже читает opencode. Одно имя в обоих —
конфликт, и он показывается прямо, а не прячется.

Осторожные серверы — те, что живут внутри редактора (плагин Unity,
встроенный сервер Roblox Studio, аддон Blender и подобные). Их живая
проверка по умолчанию НЕ выполняется: лишний клиент к тому же редактору
может занять единственное место и сломать то, что проверяют. Для них
делается быстрый осмотр, а полная проверка идёт только по явному
`live=True`.

stdout — протокол. Журнал — в stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import bridge_common as common  # noqa: E402
import mcp_doctor as doctor  # noqa: E402
import mcp_stdio  # noqa: E402

PREFIX = "mcp-doctor"
NAME = "mcp-doctor"
VERSION = "1.0.0"

DESCRIPTION = (
    "Проверка серверов MCP: кто жив, кто не работает и почему именно. "
    "Проверка двухшаговая — сначала быстрый осмотр команды и файлов "
    "(отвечает за секунды и называет причину словами), затем, если всё "
    "на месте, живой разговор по протоколу MCP."
)

TOOLS = [
    {
        "name": "server_list",
        "description": (
            "Список всех серверов MCP из настроек opencode: имя, включён "
            "ли, откуда запись (opencode.jsonc или opencode.json), "
            "противоречия между файлами."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "server_check",
        "description": (
            "Проверить один сервер. По умолчанию для серверов, живущих "
            "внутри редактора, делается только быстрый осмотр — живая "
            "проверка запускает второго клиента к тому же редактору и "
            "может занять единственное место. Включить её можно "
            "аргументом live=true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "имя сервера как в настройках"},
                "live": {"type": "boolean",
                         "description": "живая проверка даже для осторожных "
                                        "серверов; по умолчанию false"},
                "timeout": {"type": "integer",
                            "description": "сколько ждать ответа, секунд"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "server_check_all",
        "description": (
            "Проверить все серверы. Быстрый осмотр идёт сразу для всех, "
            "живая проверка — параллельно, ограниченным числом потоков, "
            "с отдельным ожиданием на каждый сервер. Аргумент "
            "quick_only=true даёт мгновенный снимок без запуска серверов."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quick_only": {
                    "type": "boolean",
                    "description": "только осмотр, без запуска; по "
                                   "умолчанию false"},
                "live_editor": {
                    "type": "boolean",
                    "description": "живая проверка серверов внутри "
                                   "редактора; по умолчанию false"},
                "concurrency": {
                    "type": "integer",
                    "description": "сколько серверов проверять одновременно"},
                "timeout": {
                    "type": "integer",
                    "description": "ожидание на один сервер, секунд"},
            },
        },
    },
]


def entries() -> list[doctor.Entry]:
    return doctor.read_entries(common.settings_dir())


def _known(names: list[str]) -> str:
    return "Прописанные серверы: " + ", ".join(names)


def call(tool: str, args: dict) -> str:
    items = entries()
    if not items:
        return (f"В папке настроек {common.settings_dir()} нет ни одного "
                f"сервера MCP — проверять нечего. Обычно это значит, что "
                f"мосты ещё не включались.")

    if tool == "server_list":
        return doctor.format_list(items)

    if tool == "server_check":
        wanted = str(args.get("name") or "").strip().lower()
        if not wanted:
            return _known([item.name for item in items])
        found = next((item for item in items
                      if item.name.lower() == wanted), None)
        if found is None:
            return (f"Сервера «{wanted}» в настройках нет.\n"
                    + _known([item.name for item in items]))
        live = bool(args.get("live"))
        timeout = int(args.get("timeout") or doctor.DEFAULT_TIMEOUT)
        result = doctor.live_check(found, timeout=timeout, force=live)
        return (f"{found.name} — "
                + ("работает" if result.ok else "не работает")
                + ("\n" + result.detail if result.detail else "")
                + (f"\nПричина: {result.reason}" if result.reason else "")
                + ("\nЗапись из " + found.source
                   + (f"\n⚠ конфликт: {found.conflict}" if found.conflict
                      else "")))

    if tool == "server_check_all":
        quick_only = bool(args.get("quick_only"))
        live_editor = bool(args.get("live_editor"))
        concurrency = int(args.get("concurrency")
                          or doctor.DEFAULT_CONCURRENCY)
        timeout = int(args.get("timeout") or doctor.DEFAULT_TIMEOUT)
        if quick_only:
            # Мгновенный снимок: ни один сервер не запускается. Для
            # осторожных всё равно зовём live_check — он при них делает
            # только осмотр и добавляет пометку, как получить полный ответ.
            return doctor.format_checks([
                doctor.live_check(item, timeout=timeout, force=False)
                if item.name in doctor.EDITOR_BACKED and not live_editor
                else doctor.quick_check(item)
                for item in items])
        return doctor.format_checks(
            doctor.check_all(items, concurrency=concurrency, timeout=timeout,
                             live_editor=live_editor))

    raise ValueError(f"инструмент не поддерживается: {tool}")


def main() -> int:
    common.say(PREFIX, f"мост готов, настроек читаю из "
                       f"{common.settings_dir()}")
    return mcp_stdio.serve(NAME, TOOLS, call)


if __name__ == "__main__":
    raise SystemExit(main())