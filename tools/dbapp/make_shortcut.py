"""Создаёт ярлык «Управление базой» на рабочем столе.

Запуск:  python make_shortcut.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Корень базы — на две папки выше tools/dbapp. Лаунчер лежит в корне.
BASE = HERE.parent.parent
TARGET = BASE / "Управление-базой.cmd"
NAME = "Управление базой.lnk"


def desktop_dir() -> Path:
    """Папка рабочего стола текущего пользователя."""
    for candidate in (
        Path.home() / "Desktop",
        Path.home() / "Рабочий стол",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "OneDrive" / "Рабочий стол",
    ):
        if candidate.is_dir():
            return candidate
    return Path.home() / "Desktop"


def _quote(text: str) -> str:
    """Экранировать одинарную кавычку для строки PowerShell.

    Внутрь команды скрипта подставляется путь пользователя, а в пути
    может оказаться апостроф. Без экранирования такой путь рвёт
    команду, и ярлык молча не создаётся.
    """
    return str(text).replace("'", "''")


def read_target(link: Path) -> str:
    """Куда ведёт ярлык. Пустая строка — прочитать не вышло."""
    import subprocess

    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "Write-Output $s.TargetPath"
    ).format(link=_quote(link))
    for exe in ("powershell.exe", "pwsh.exe"):
        try:
            done = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True, text=True, timeout=60,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            return (done.stdout or "").strip()
    return ""


def make_with_powershell(link: Path) -> bool:
    """Создаёт (или переписывает) ярлык через встроенный PowerShell."""
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{target}';"
        "$s.WorkingDirectory='{work}';"
        "$s.Description='Создание и подключение базы';"
        "$s.IconLocation='%SystemRoot%\\System32\\shell32.dll,71';"
        "$s.WindowStyle=7;"
        "$s.Save()"
    ).format(link=_quote(link), target=_quote(TARGET), work=_quote(BASE))

    import subprocess

    for exe in ("powershell.exe", "pwsh.exe"):
        try:
            done = subprocess.run(
                [
                    exe,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", script,
                ],
                capture_output=True,
                timeout=60,
            )
        except (FileNotFoundError, OSError):
            continue
        except subprocess.TimeoutExpired:
            continue
        if done.returncode == 0 and link.is_file():
            return True
    return False


def shortcut_links(desktop: Path) -> list[Path]:
    """Все ярлыки про эту программу, включая «... 2.lnk».

    Windows и сам проводник любят добавлять к имени цифру, если
    ярлык с таким именем уже есть. Старые копии молча указывают на
    прежнее место программы и выглядят исправными, поэтому их тоже
    надо чинить.
    """
    stem = NAME[:-len(".lnk")]
    found: list[Path] = []
    for path in desktop.glob(f"{stem}*.lnk"):
        if path.is_file():
            found.append(path)
    return sorted(found)


def main() -> int:
    if not TARGET.is_file():
        print(f"Не найден файл запуска: {TARGET}")
        return 1

    desktop = desktop_dir()
    wanted = str(TARGET)
    problems: list[str] = []
    fixed: list[str] = []

    for link in shortcut_links(desktop) or [desktop / NAME]:
        if not link.is_file():
            continue
        current = read_target(link)
        if current and Path(current) == TARGET:
            continue
        # Ярлык есть, а ведёт он в никуда: прежняя папка программы
        # удалена или переехала. Такой ярлык молча не работает, и
        # человек думает, что программа сломалась. Переписываем.
        if make_with_powershell(link):
            fixed.append(link.name)
            problems.append(
                f"{link.name}: вёл на «{current or 'неизвестно'}» — "
                f"перенаправлен на {TARGET}"
            )
        else:
            problems.append(f"{link.name}: переписать не вышло")

    main_link = desktop / NAME
    if not main_link.is_file():
        if make_with_powershell(main_link):
            problems.append(f"создан новый ярлык: {main_link.name}")
        else:
            print("Ярлык создать не удалось.")
            print("Создайте его вручную: правый щелчок по файлу")
            print(f"  {TARGET}")
            print("→ «Отправить» → «Рабочий стол (создать ярлык)».")
            return 2

    for line in problems:
        print(line)
    if fixed:
        print(f"Исправлено ярлыков: {len(fixed)}")
    if not problems:
        print(f"Ярлык в порядке: {main_link}")
    else:
        print(f"Теперь программу можно открывать с рабочего стола: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
