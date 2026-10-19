"""Окружения Python для мостов, которые на чужом коде.

Зачем этот модуль. Мост android-emulator написан на Python, и запускать
его нужно не тем Python, на котором стоит программа, а тем, который стоит
вместе с его зависимостями. Такое окружение лежит в папке моста (`.venv`)
и ставится через uv — того же самого, на котором программа ставит другие
вещи.

Поломка, из-за которой модуль появился. 19.10.2026 мост android-emulator
отвечал «ModuleNotFoundError: No module named 'mcp'». Папки `.venv` рядом с
мостом не было, и лаунчер ТИХО брал системный Python, где пакета `mcp`
нет и никогда не будет. Отказ выглядел как «сервер молчит», хотя на самом
деле мосту не было чем работать: никто не сказал, что окружения нет, и
чинить было нечем.

Поэтому здесь три вещи, и все три — по одной схеме:

    1. Найти uv. Имя папки, в которой он лежит, — личное обстоятельство
       человека: на одной машине uv приносят вместе с другой программой,
       на другой он стоит в своей. Поэтому ищется сам инструмент, а не
       его адрес.
    2. Проверить, готово ли окружение: питон есть И нужный пакет в нём
       есть. Наличие папки недостаточно — окружение может остаться
       недоделанным.
    3. Поставить окружение, если его нет, и сказать словами, если
       поставить нечем.

Модуль ничего не пишет в настройки opencode и не знает про них: он
работает только с папкой моста.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo.

    Отдельная функция с ленивым импортом, а не `import core` наверху:
    модуль читают и лаунчеры, и проверки, и лишняя связь между ними
    лишний раз ломается.

    Зачем это. 19.10.2026 человек нажал кнопку у моста OBS, и у него
    открылось чёрное окно консоли. Программа работает на pythonw — у
    неё самой консоли нет, и Windows на каждый запуск внешней
    программы без этой просьбы создаёт новое окно.
    """
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:  # noqa: BLE001 — без этого просто откроется окно
        return None


#: Пакет, без которого мост android-mcp не поднимется.
NEED_MODULE = "mcp"

#: Сколько ждать установки. Обычно uv укладывается в минуту.
INSTALL_TIMEOUT = 900


def find_uv() -> Path | None:
    """Ищет uv — тем же способом, что и остальная программа.

    Сначала пробуем общий поиск программы (он смотрит и в PATH, и в
    %LOCALAPPDATA%\\*\\bin, и в ~/.local/bin), потом — свой простой
    перебор. Двойной поиск нужен потому, что лаунчер моста запускается
    отдельным процессом и не обязан видеть всё, что видит окно.
    """
    try:
        import env_setup  # noqa: PLC0415 — рядом лежит, тяжёлых импортов нет
    except ImportError:
        env_setup = None  # type: ignore[assignment]
    if env_setup is not None:
        try:
            raw = env_setup.resolve_placeholder("{UV}")
        except Exception:  # noqa: BLE001 — поиск не должен ронять мост
            raw = ""
        if raw:
            path = Path(raw)
            if path.is_file():
                return path
    return _find_uv_bare()


def _find_uv_bare() -> Path | None:
    """Простой поиск uv: PATH, ~/.local/bin, все `*\\bin` под LOCALAPPDATA."""
    import shutil

    found = shutil.which("uv") or shutil.which("uv.exe")
    if found:
        return Path(found)

    candidates = [Path.home() / ".local" / "bin",
                  Path.home() / ".cargo" / "bin"]
    root = os.environ.get("LOCALAPPDATA", "")
    if root:
        try:
            for child in Path(root).iterdir():
                candidates.append(child / "bin")
        except OSError:
            pass
    for folder in candidates:
        for name in ("uv.exe", "uv"):
            path = folder / name
            if path.is_file():
                return path
    return None


def venv_python(server_dir: Path) -> Path:
    """Путь к Python окружения."""
    return Path(server_dir) / ".venv" / "Scripts" / "python.exe"


def venv_ready(server_dir: Path, need_module: str | None = NEED_MODULE) -> bool:
    """Готово ли окружение: питон есть и нужный пакет в нём есть."""
    python = venv_python(server_dir)
    if not python.is_file():
        return False
    if not need_module:
        return True
    code = (
        "import importlib.util,sys;"
        f"sys.exit(0 if importlib.util.find_spec({need_module!r}) else 1)"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            capture_output=True, timeout=120, startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def ensure_venv(server_dir: Path,
                need_module: str | None = NEED_MODULE,
                progress=None) -> tuple[Path | None, list[str]]:
    """Готовит окружение. Возвращает (python, журнал).

    python равен None — запускать нечем, и журнал говорит почему.
    """
    log: list[str] = []

    def say_step(text: str) -> None:
        log.append(text)
        if progress:
            progress(text)

    server_dir = Path(server_dir)
    if venv_ready(server_dir, need_module):
        say_step("Окружение моста уже готово.")
        return venv_python(server_dir), log

    uv = find_uv()
    if uv is None:
        say_step("uv не найден — поставить окружение моста нечем.")
        say_step("uv ставится с https://docs.astral.sh/uv/getting-started/"
                 "installation/ и нужен один раз.")
        return None, log

    say_step(f"Ставлю окружение моста: {uv} sync. Это минута, не больше.")
    try:
        proc = subprocess.run(
            [str(uv), "sync", "--project", str(server_dir)],
            cwd=str(server_dir), capture_output=True, text=True,
            timeout=INSTALL_TIMEOUT, startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say_step(f"uv не отработал: {exc}")
        return None, log
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        say_step("uv вернул ошибку: " + " / ".join(tail)[:300])
        return None, log
    if not venv_ready(server_dir, need_module):
        say_step("Окружение создалось, но нужного пакета в нём нет.")
        return None, log
    say_step("Окружение моста готово.")
    return venv_python(server_dir), log
