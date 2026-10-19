"""Лаунчер моста эмуляторов Android.

Зачем он нужен. Мост android-mcp вызывает adb просто по имени: и
`subprocess.run(["adb", "version"])`, и `adb shell …`. Имени достаточно
только если adb есть в PATH. На этой машине он не прописан: системный
лежит в %LOCALAPPDATA%\\Android\\Sdk\\platform-tools, а у LDPlayer свой,
в его папке. Без лаунчера мост падал бы с «adb is not installed».

Значит лаунчер делает три вещи:

    1. Находит adb — сначала свой у эмулятора, потом системный — и
       добавляет его папку в PATH процесса.
    2. Проверяет окружение моста.
    3. Запускает мост и передаёт ему stdio.

Про окружение — важное. 19.10.2026 мост отвечал «ModuleNotFoundError: No
module named 'mcp'». Причина была не в мосте: папки `.venv` рядом с ним
нет, и лаунчер ТИХО брал системный Python, где пакета `mcp` нет и
никогда не будет. То есть отказ выглядел как «сервер молчит», хотя на
самом деле мосту не было чем работать.

Поэтому тихого отката на чужой Python здесь больше нет: окружение либо
готово, либо лаунчер отказывается словами и называет причину.

Почему лаунчер не ставит окружение сам при старте. opencode даёт серверу
30 секунд на запуск, а установка окружения — дело на минуту и дольше.
Попытка впихнуть её в эти 30 секунд кончилась бы сообщением «Operation
timed out», которое ничего не объясняет. Поэтому долгую установку
делает кнопка «Настроить автоматически» — там есть и время, и
progress-бар; лаунчер только проверяет готовость.

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
sys.path.insert(0, str(HERE.parent))

from core import hidden_startupinfo  # noqa: E402 — путь задаётся строкой выше
from python_envs import ensure_venv, venv_python, venv_ready  # noqa: E402

SERVER_DIR = HERE.parent.parent / "thirdparty" / "android-mcp-server"
ENTRY = SERVER_DIR / "server.py"

#: Куда искать adb. Свой у эмулятора важнее системного: он заведомо той
#: же версии, что и сам эмулятор.
ADB_CANDIDATES = (
    Path("C:/LDPlayer/LDPlayer9/adb.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe",
    Path("C:/Program Files/BlueStacks_nxt/HD-Player.exe"),
)


def _force_utf8() -> None:
    """Журнал должен быть в UTF-8, а не в кодировке консоли.

    Ошибки моста читает человек, и по этому тексту он понимает, почему
    мост не запустился. В кодировке консоли русский превращается в
    кракозябры, и объяснение теряется вместе с причиной. Под pythonw
    потоков может не быть вовсе — тогда и перенастраивать нечего.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_force_utf8()


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

    # Окружение ставит кнопка «Настроить автоматически» — там на это есть
    # время. Здесь только проверяем: молча брать чужой Python нельзя,
    # мост на нём не запустится, а человек увидит «сервер молчит».
    if not venv_ready(SERVER_DIR):
        say("У моста нет окружения — запускать нечем.")
        say("Открой программу, вкладка opencode, блок «6. Серверы MCP», "
            "выбери Android-эмулятор и нажми «Настроить автоматически»: "
            "программа поставит окружение сама.")
        return 1
    python = venv_python(SERVER_DIR)

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
            startupinfo=hidden_startupinfo(),
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
