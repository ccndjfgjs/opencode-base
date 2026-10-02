"""Лаунчер моста LDPlayer.

Мост `mcp-ldplayer` написан без внешних зависимостей: свой JSON-RPC
поверх stdin, только стандартная библиотека. Поэтому ничего ставить не
нужно — достаточно указать Python корень пакета.

Что делает:
    1. Находит LDPlayer и передаёт мосту его папку (он ищет сам, но
       путь лучше задать: у него в списке автопоиска есть каталоги, где
       LDPlayer не бывает, и первый же подходящий путь он может выбрать
       неверно).
    2. Запускает модуль mcp_ldplayer.mcp_server и передаёт ему stdio.

Про имя инстанта. Почти все инструменты ADB у этого моста требуют
параметр name — по умолчанию он пустой, и тогда мост обращается к
несуществующему устройству и возвращает ошибку вида
`device 'emulator-5552' not found`. Имя инстанса нужно указывать явно,
например «LDPlayer». Это не поломка, а особенность чужого кода.

stdout у MCP-сервера — это протокол. Весь журнал идёт в stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER_DIR = HERE.parent.parent / "thirdparty" / "mcp-ldplayer"

#: Где может стоять LDPlayer. Первый существующий и передаётся мосту.
LDPLAYER_CANDIDATES = (
    Path("C:/LDPlayer/LDPlayer9"),
    Path("C:/LDPlayer/LDPlayer4.0"),
    Path("C:/Program Files/LDPlayer/LDPlayer9"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "LDPlayer/LDPlayer9",
)


def say(text: str) -> None:
    print(f"[ldplayer-bridge] {text}", file=sys.stderr, flush=True)


def find_ldplayer() -> Path | None:
    for candidate in LDPLAYER_CANDIDATES:
        if candidate and (candidate / "ldconsole.exe").is_file():
            return candidate
    return None


def main() -> int:
    if not (SERVER_DIR / "mcp_ldplayer" / "mcp_server.py").is_file():
        say(f"Мост не найден: {SERVER_DIR}")
        return 1

    installed = find_ldplayer()
    if installed is None:
        say("LDPlayer не найден. Мост им управляет, а не эмулятором вообще.")
        return 1
    say(f"LDPlayer: {installed}")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SERVER_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    say("запускаю мост LDPlayer")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_ldplayer.mcp_server",
             "--ldplayer-path", str(installed)],
            cwd=str(SERVER_DIR), env=env,
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


if __name__ == "__main__":
    sys.exit(main())