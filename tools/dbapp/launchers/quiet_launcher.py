"""Лаунчер без окна консоли.

Зачем он нужен. Серверы MCP общаются с opencode через стандартные
потоки, поэтому запускать их приходится консольным `python.exe` или
`npx`/`uvx`, а Windows на каждый такой запуск выделяет отдельную
консоль. При запуске мостов получается до десятка чёрных окон cmd,
которые потом ещё и живут вместе с серверами.

Решение — запускать консольное через оконный Python. У `pythonw.exe`
нет своих stdout и stderr (в Python они равны None), поэтому сначала
восстанавливаем потоки из системных дескрипторов 0 и 1, а потом
запускаем настоящую команду с флагом CREATE_NO_WINDOW: своя консоль у
неё не создаётся, а каналы остаются рабочими, потому что дескрипторы
наследуются.

Запуск такой:

    pythonw.exe quiet_launcher.py <команда> <аргументы...>

Скрипт не печатает ничего от себя: весь вывод целиком принадлежит
запущенной команде, иначе протокол MCP собьётся.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _restore_streams() -> None:
    """Возвращает stdin и stdout под оконным Python.

    У `pythonw.exe` в Python они равны None, и любой `print` упал бы с
    AttributeError. Дескрипторы 0 и 1 при этом живые — окно консоли
    просто не создавалось. Дублируем их и оборачиваем в файловые
    объекты без буферизации: протокол MCP не переносит задержку вывода.
    """
    if sys.stdin is None:
        try:
            sys.stdin = open(  # noqa: SIM115 — закрывает интерпретатор
                os.dup(0), "r", buffering=1, encoding="utf-8", errors="replace",
                closefd=False,
            )
        except OSError:
            pass
    if sys.stdout is None:
        try:
            sys.stdout = open(  # noqa: SIM115
                os.dup(1), "w", buffering=1, encoding="utf-8", errors="replace",
                closefd=False,
            )
        except OSError:
            pass
    if sys.stderr is None:
        try:
            sys.stderr = open(  # noqa: SIM115
                os.dup(2), "w", buffering=1, encoding="utf-8", errors="replace",
                closefd=False,
            )
        except OSError:
            pass


def hidden_startupinfo():
    """Окно консоли скрыть, а потоки оставить.

    Сначала пробовали CREATE_NO_WINDOW — он тоже прячет окно, но при
    нём ребёнок отрабатывает, а вывод в подставленную трубу теряется.
    Для сервера MCP это означает молчание: opencode не получит ответ.
    STARTUPINFO со скрытием проверен на живых запусках — и окна нет,
    и потоки работают.
    """
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def resolve_command(argv: list[str]) -> list[str]:
    """Найти исполняемый файл, когда в команде нет расширения.

    В реестре команда записана как `npx` или `uvx` — без `.cmd`. На
    Windows такие программы лежат пакетными файлами, и `CreateProcess`
    их не запускает: выходило `WinError 2`, то есть «системе не удаётся
    найти указанный файл», хотя `npx` есть и работает. Проверка ниже на
    расширение это не ловила — там `.cmd` должен быть уже написан.

    Здесь имя дополняется через PATH, и уже потом решается, запускать
    ли его через `cmd`. Работает для любого моста: OBS, Unity, Roblox,
    Unreal — везде, где команда начинается с `npx`, `uvx` или подобного.
    """
    if not argv:
        return argv
    head = argv[0]
    if os.path.isfile(head):
        return argv
    import shutil

    found = shutil.which(head)
    if not found:
        return argv
    return [found, *argv[1:]]


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        return 2
    _restore_streams()
    args = resolve_command(args)
    # Команда из реестра может начинаться с .cmd или .bat — такие файлы
    # Windows исполняет только через cmd, и без этого окно появится.
    if args[0].lower().endswith((".cmd", ".bat")):
        args = [os.environ.get("COMSPEC") or "cmd.exe", "/c", *args]
    try:
        # Потоки передаём обязательно явно. Без этого `pythonw`
        # передаёт ребёнку пустые стандартные дескрипторы: у него нет
        # консоли, и проверилось это так — ребёнок получал WinError 6
        # («неверный дескриптор») на всех трёх и не мог прочитать ни
        # одного байта от opencode.
        done = subprocess.run(
            args,
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
            startupinfo=hidden_startupinfo(), check=False,
        )
    except OSError as exc:
        # Пишем в stderr, а не в stdout: stdout занят протоколом.
        sys.stderr.write(f"quiet_launcher: не запустилось: {exc}\n")
        return 126
    return int(done.returncode or 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))