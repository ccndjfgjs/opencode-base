"""Лаунчер моста Unity.

Сервер — пакет CoplayDev, не наш код. Команда взята из описания
mcpforunityserver 10.3.0 на PyPI (2026-10-14):

    uvx --from mcpforunityserver mcp-for-unity --transport stdio

Версия закреплена. Плагин в редактор этот файл не ставит: его ставят
в Unity через Package Manager, git URL из README проекта. Без открытого
редактора с плагином сервер поднимется, но управлять сценой будет нечем.
Журнал — в stderr.

Порядок запуска (обновлено 21.10.2026, причина в журнале):

    1. Постоянное окружение `.venv` рядом с мостом (tools/thirdparty/
       unity-mcp), ставится `uv sync --project` по pyproject.toml —
       той же механикой, что у моста android-emulator. В нём сервер
       стартует за секунды.
    2. Если окружения нет — прежний путь через uvx. Он тоже работает,
       но холодный качает пакет больше минуты, а opencode даёт серверу
       30 секунд: первый старт после чистки кэша таймаутится, и opencode
       затем перезапускает упавший сервер общим таймером каждые
       13-22 минуты (диагноз 21.10.2026). Поэтому молча молчать нельзя:
       лаунчер говорит в stderr, что идёт медленный путь.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core import hidden_startupinfo  # noqa: E402

sys.path.insert(0, str(HERE))

import bridge_common as common  # noqa: E402

PREFIX = "unity-bridge"
SERVER_DIR = HERE.parent.parent / "thirdparty" / "unity-mcp"
VENV_EXE = SERVER_DIR / ".venv" / "Scripts" / "mcp-for-unity.exe"
VENV_PYTHON = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
EDITOR_GLOBS = (
    r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
    r"C:\Program Files\Unity Hub\Unity Hub.exe",
)


def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo."""
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:  # noqa: BLE001 — без этого просто откроется окно
        return None


def _venv_exe() -> Path | None:
    """Файл mcp-for-unity.exe постоянного окружения, если оно готово.

    Проверка живая, а не «папка есть»: окружение может остаться
    недоделанным. Проверяем ПАКЕТ (importlib.metadata), а не модуль:
    у mcpforunityserver нет единого корневого модуля — он разложен
    на cli/core/services/transport (top_level.txt), и find_spec по
    имени пакета всегда пуст. Версию при этом не сверяем: пин стоит
    и в pyproject.toml, и в bridge_common.UNITY_FROM.
    """
    python = Path(VENV_PYTHON)
    if not python.is_file():
        return None
    code = (
        "import importlib.metadata as m, sys;"
        "sys.exit(0 if m.distribution('mcpforunityserver').version "
        "== '10.3.0' else 1)"
    )
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный путь
            [str(python), "-c", code],
            capture_output=True, timeout=60,
            startupinfo=hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    if VENV_EXE.is_file():
        return VENV_EXE
    return None


def main() -> int:
    venv_exe = _venv_exe()
    if venv_exe is not None:
        common.say(PREFIX, f"постоянное окружение готово: {venv_exe}")
        return common.exec_stdio([str(venv_exe), "--transport", "stdio"])

    uvx = common.resolve_exe("uvx")
    if not uvx:
        common.say(PREFIX, "uvx не найден. Его ставит пакет uv: https://docs.astral.sh/uv/")
        common.say(PREFIX, "Без uvx и без постоянного окружения сервер mcpforunityserver не запустить.")
        common.say(PREFIX, "Нажмите «Настроить автоматически» у моста Unity — оно поставит окружение.")
        return 1

    editor = common.find_first(EDITOR_GLOBS)
    if editor:
        common.say(PREFIX, f"редактор или Hub: {editor}")
    else:
        common.say(PREFIX, "Unity.exe по обычному пути не найден. "
                    "Если редактор стоит в другом месте — это не отказ, "
                    "но плагин должен быть включён в открытом проекте.")

    common.say(PREFIX, f"запускаю uvx --from {common.UNITY_FROM} mcp-for-unity --transport stdio")
    common.say(PREFIX, "телеметрия пакета выключается переменной DISABLE_TELEMETRY=1")
    return common.exec_stdio([
        uvx, "--from", common.UNITY_FROM, "mcp-for-unity", "--transport", "stdio",
    ])


if __name__ == "__main__":
    sys.exit(main())
