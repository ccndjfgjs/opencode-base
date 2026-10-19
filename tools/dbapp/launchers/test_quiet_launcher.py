"""Проверка лаунчера без окна: команда без расширения должна запускаться.

Поломка была ровно тут. В реестре команда записана как `npx` — без
`.cmd`, — а на Windows `npx` лежит пакетным файлом и сам не
запускается. Лаунчер проверял расширение, но проверка работала только
когда `.cmd` уже написан: настоящая команда без расширения до неё
доходила и падала с `WinError 2`.

Проверка делает ровно то же, что делает opencode: запускает лаунчер с
командой БЕЗ расширения и ждёт её вывод. Подменять `npx` не нужно —
подставляется настоящая, и она тоже проверяется отдельной строкой.

Запуск: python tools/dbapp/launchers/test_quiet_launcher.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent.parent

passed = 0
failed = 0


def check(ok: bool, text: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  ok    " + text)
    else:
        failed += 1
        print("  FAIL  " + text)


def run_launcher(command: list[str], timeout: int = 120):
    """Лаунчер так, как его запускает opencode: pythonw + скрипт + команда."""
    pythonw = Path(sys.executable)
    if pythonw.name.lower() == "python.exe":
        pythonw = pythonw.with_name("pythonw.exe")
    argv = [str(pythonw), str(HERE / "quiet_launcher.py"), *command]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "", "таймаут"
    except OSError as exc:
        return None, "", str(exc)
    return done.returncode, done.stdout or "", done.stderr or ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="quiet-launcher-") as tmp:
        fake = Path(tmp)
        # Поддельная команда БЕЗ расширения в команде: пакетный файл
        # лежит как tool.cmd, а вызываем мы его как `tool`.
        (fake / "mytool.cmd").write_text(
            "@echo off\r\necho МОЙ-ОТВЕТ\r\n", encoding="utf-8", newline="")
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(fake) + os.pathsep + old_path

        code, out, err = run_launcher(["mytool", "первый", "второй"])
        check(code == 0 and "МОЙ-ОТВЕТ" in out,
              f"команда без расширения запустилась и ответила "
              f"(код {code}, вывод {out.strip()[:30]!r})")
        check("не запустилось" not in err,
              f"и лаунчер не жаловался: {err.strip()[:80]!r}")

        # Настоящая npx — ровно то, из-за чего был красный статус.
        code, out, err = run_launcher(["npx", "--version"], timeout=120)
        ok = code == 0 and out.strip()
        check(ok,
              f"настоящая npx запускается без .cmd (код {code}, "
              f"версия {out.strip()[:20]!r}) {err.strip()[:60]}")

        # Пустая команда — понятный отказ, а не падение.
        code, out, err = run_launcher([], timeout=30)
        check(code == 2,
              f"без команды код 2, а не исключение: {code}")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
