"""Лаунчер моста эмуляторов Android.

Зачем он нужен. Мост android-mcp вызывает adb просто по имени: и
`subprocess.run(["adb", "version"])`, и `adb shell …`. Имени достаточно
только если adb есть в PATH. На этой машине он не прописан: системный
лежит в %LOCALAPPDATA%\\Android\\Sdk\\platform-tools, а у LDPlayer свой,
в его папке. Без лаунчера мост падал бы с «adb is not installed».

Значит лаунчер делает две вещи:

    1. Находит adb — сначала свой у эмулятора, потом системный — и
       добавляет его папку в PATH процесса.
    2. Запускает мост и передаёт ему stdio.

Второй важный момент: у эмулятора может быть несколько устройств, и
мост без config.yaml возьмёт единственное. Если устройств несколько, он
скажет об этом и потребует выбрать — это его собственная проверка, и мы
её не обходим.

stdout у MCP-сервера — это протокол. Весь журнал идёт в stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER_DIR = HERE.parent.parent / "thirdparty" / "android-mcp-server"
ENTRY = SERVER_DIR / "server.py"
VENV_PYTHON = SERVER_DIR / ".venv" / "Scripts" / "python.exe"

#: Где искать adb. Свой у эмулятора важнее системного: он заведомо той
#: же версии, что и сам эмулятор.
ADB_CANDIDATES = (
    Path("C:/LDPlayer/LDPlayer9/adb.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe",
    Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"),
)


def say(text: str) -> None:
    print(f"[android-bridge] {text}", file=sys.stderr, flush=True)


def find_adb() -> Path | None:
    for candidate in ADB_CANDIDATES:
        if candidate.is_file() and candidate.name.lower().startswith("adb"):
            return candidate
    return None


def main() -> int:
    if not ENTRY.is_file():
        say(f"Мост не найден: {ENTRY}")
        return 1
    python = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    if not Path(python).is_file():
        say(f"Python не найден: {python}")
        return 1

    env = dict(os.environ)
    adb = find_adb()
    if adb is not None:
        # Кладём папку adb в PATH: мост зовёт его по имени.
        env["PATH"] = os.pathsep.join(
            [str(adb.parent), env.get("PATH", "")]
        )
        say(f"adb: {adb}")
    else:
        say("adb не найден ни у эмулятора, ни в system-tools.")

    env["PYTHONPATH"] = os.pathsep.join(
        [str(SERVER_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    say(f"запускаю мост: {python} {ENTRY}")
    try:
        proc = subprocess.Popen(
            [str(python), str(ENTRY)],
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