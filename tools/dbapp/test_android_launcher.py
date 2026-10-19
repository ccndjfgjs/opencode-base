"""Проверка лаунчера моста android-emulator.

Запуск: python tools/dbapp/test_android_launcher.py

Поломка, которую проверка закрывает. 19.10.2026 мост android-emulator
отвечал «ModuleNotFoundError: No module named 'mcp'». Причина: папки
`.venv` в мосте нет, и лаунчер тихо брал системный Python, где пакета
`mcp` нет и никогда не будет. То есть отказ выглядел как «сервер молчит»,
а на самом деле мост даже не было чем запустить.

Правильное поведение: окружение ставится само (uv рядом с проектом), а
если поставить нечем — лаунчер отказывается словами, а не делает вид,
что запустил сервер.

Проверка идёт на временных папках и ничего не трогает в настоящем мосте.
Механизм постановки проверяется настоящим uv на пустом проекте без
зависимостей: это доказывает, что окружение действительно создаётся, и
не тащит при этом ничего из сети.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHERS = HERE / "launchers"
sys.path.insert(0, str(LAUNCHERS))
sys.path.insert(0, str(HERE))

import android_bridge_launcher as launcher  # noqa: E402
import python_envs  # noqa: E402

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


EMPTY_PROJECT = """[project]
name = "probe"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []
"""


def main() -> int:
    check(hasattr(launcher, "ensure_venv"),
          "в лаунчере есть функция постановки окружения ensure_venv")

    uv = python_envs.find_uv()
    print(f"  ..    uv найден: {uv}")

    # --- ветка «uv есть»: окружение ставится само.
    python = None
    with tempfile.TemporaryDirectory(prefix="android-venv-") as tmp:
        server_dir = Path(tmp) / "server"
        server_dir.mkdir()
        (server_dir / "pyproject.toml").write_text(EMPTY_PROJECT, encoding="utf-8")

        if uv is None:
            check(True, "uv на этой машине нет — ветку постановки пропускаем")
        else:
            python, log = python_envs.ensure_venv(server_dir, need_module=None)
            joined = " | ".join(log)
            check(python is not None and Path(python).is_file(),
                  f"окружение создано настоящим uv: {python}")
            check("sync" in joined or "окружение" in joined.lower(),
                  f"и сказано, что именно делалось: {joined[:110]}")
            if python is not None and Path(python).is_file():
                probe = subprocess.run(
                    [str(python), "-c", "print('окружение живое')"],
                    capture_output=True, text=True, timeout=120)
                check(probe.returncode == 0,
                      f"питон из окружения запускается: {(probe.stdout or '').strip()}")

            # --- повторный запуск: готовое окружение не переставляется.
            again, log2 = python_envs.ensure_venv(server_dir, need_module=None)
            check(again is not None and "уже готово" in " ".join(log2),
                  f"повторный запуск увидел готовое окружение: {' | '.join(log2)[:110]}")

    # --- ветка «uv нет»: честный отказ, а не молчаливый запуск.
    with tempfile.TemporaryDirectory(prefix="android-novenv-") as tmp:
        server_dir = Path(tmp) / "server"
        server_dir.mkdir()
        (server_dir / "pyproject.toml").write_text(EMPTY_PROJECT, encoding="utf-8")
        was = python_envs.find_uv
        try:
            python_envs.find_uv = lambda: None
            result, log = python_envs.ensure_venv(server_dir, need_module=None)
        finally:
            python_envs.find_uv = was
        joined = " | ".join(log)
        check(result is None,
              "без uv лаунчер не берёт чужой Python и отказывается")
        check("uv" in joined.lower(),
              f"и называет причину словами: {joined[:140]}")
        check(not (server_dir / ".venv").is_dir(),
              "и ничего не создаёт на диске вместо моста")

    # --- главное правило: тихого отката на системный Python быть не должно.
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    check("Path(sys.executable)" not in source,
          "в лаунчере больше нет отката на системный Python "
          "(именно он и давал «No module named 'mcp'»)")

    # --- лаунчер обязан отказаться, когда окружения нет.
    # Проверка идёт В СВОЁМ процессе: переменные модуля подменяются
    # здесь, а отдельный процесс взял бы настоящую папку моста. 19.10.2026
    # проверка запускала лаунчер отдельным процессом и подменяла
    # переменные у себя — процесс видел настоящий мост, и проверка
    # «проходила» по случайной причине: тогда окружения ещё не было.
    with tempfile.TemporaryDirectory(prefix="android-nostart-") as tmp:
        server_dir = Path(tmp) / "server"
        server_dir.mkdir()
        (server_dir / "server.py").write_text("print('мост', flush=True)\n",
                                              encoding="utf-8")
        was_dir = launcher.SERVER_DIR
        was_entry = launcher.ENTRY
        try:
            launcher.SERVER_DIR = server_dir
            launcher.ENTRY = server_dir / "server.py"
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                code = launcher.main()
        finally:
            launcher.SERVER_DIR = was_dir
            launcher.ENTRY = was_entry
        err = buffer.getvalue()
        check(code != 0,
              f"без окружения лаунчер не стартует мост: код {code}")
        check("окружен" in err.lower(),
              f"и объясняет это словами: {err.strip()[-190:]}")
        check("Настроить автоматически" in err,
              "и называет кнопку, которая поставит окружение")

    print(f"ИТОГ: {passed + failed} проверок, {failed} провалов")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
