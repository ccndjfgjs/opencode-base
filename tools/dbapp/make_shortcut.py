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


def make_with_powershell(link: Path) -> bool:
    """Создаёт ярлык через встроенную в Windows PowerShell."""
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{target}';"
        "$s.WorkingDirectory='{work}';"
        "$s.Description='Создание и подключение базы';"
        "$s.IconLocation='%SystemRoot%\\System32\\shell32.dll,71';"
        "$s.WindowStyle=7;"
        "$s.Save()"
    ).format(link=link, target=TARGET, work=BASE)

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


def main() -> int:
    if not TARGET.is_file():
        print(f"Не найден файл запуска: {TARGET}")
        return 1

    desktop = desktop_dir()
    link = desktop / NAME

    if link.exists():
        print(f"Ярлык уже есть: {link}")
        print("Ничего не меняю.")
        return 0

    if make_with_powershell(link):
        print(f"Ярлык создан: {link}")
        print("Теперь программу можно открывать с рабочего стола.")
        return 0

    print("Ярлык создать не удалось.")
    print("Создайте его вручную: правый щелчок по файлу")
    print(f"  {TARGET}")
    print("→ «Отправить» → «Рабочий стол (создать ярлык)».")
    return 2


if __name__ == "__main__":
    sys.exit(main())
