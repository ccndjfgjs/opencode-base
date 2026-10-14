"""Общие куски лаунчеров мостов.

Лаунчер запускает opencode как обычный скрипт и отдаёт ему stdin/stdout.
Лишний текст в stdout ломает протокол MCP, поэтому журнал — только в stderr.

Секреты (токен TikTok, токен Unreal) сюда не печатаются никогда.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Версии, которые реально лежали в каталогах на 2026-10-14.
#: Не «последняя навсегда»: закрепили, чтобы молча не приехала несовместимая.
UNITY_FROM = "mcpforunityserver==10.3.0"
UNREAL_PACKAGE = "unreal-engine-mcp-server@0.6.0-beta-e"
TIKTOK_PACKAGE = "@getmcpads/tiktok-ads-mcp-server@2.0.1"
#: Пакет Godot на PyPI в тот же день. В команду его не подставляем:
#: док редактора сам пишет argv с портами и capability, чужой пин сломает вход.
GODOT_PYPI = "godot-ai==4.3.0"

UNREAL_NODE = (20, 19, 0)
TIKTOK_NODE = (22, 12, 0)


def say(prefix: str, text: str) -> None:
    """Журнал только в stderr. stdout занят протоколом MCP."""
    print(f"[{prefix}] {text}", file=sys.stderr, flush=True)


def settings_dir() -> Path:
    """Папка настроек opencode. Тот же порядок, что у лаунчера OBS."""
    raw = os.environ.get("OPENCODE_CONFIG_DIR") or os.environ.get("XDG_CONFIG_HOME")
    if raw:
        candidate = Path(raw)
        if candidate.name == ".config":
            candidate = candidate / "opencode"
        if candidate.is_dir():
            return candidate
    return Path.home() / ".config" / "opencode"


def resolve_exe(name: str) -> str | None:
    """Ищет программу: полный путь, PATH, затем .cmd/.exe.

    На Windows npx и uvx часто лежат как .cmd. CreateProcess такой файл
    сам не запускает — это уже дело prepare_argv.
    """
    if not name:
        return None
    direct = Path(name)
    if direct.is_file():
        return str(direct)
    found = shutil.which(name)
    if found:
        return found
    for suffix in (".cmd", ".exe", ".bat"):
        found = shutil.which(name + suffix)
        if found:
            return found
    return None


def prepare_argv(argv: list[str]) -> list[str]:
    """Делает argv, который Windows сможет запустить.

    Пакетный файл идёт через cmd.exe. Остальное — как есть, после
    поиска в PATH. Список, не строка: кавычки и пробелы не разбирает shell.
    """
    if not argv:
        return []
    exe = resolve_exe(argv[0]) or argv[0]
    rest = list(argv[1:])
    if exe.lower().endswith((".cmd", ".bat")):
        shell = os.environ.get("COMSPEC") or "cmd.exe"
        return [shell, "/c", exe, *rest]
    return [exe, *rest]


def exec_stdio(argv: list[str], env: dict[str, str] | None = None,
               cwd: str | None = None) -> int:
    """Запускает процесс и отдаёт ему stdin/stdout. Код возврата — его."""
    prepared = prepare_argv(argv)
    if not prepared:
        return 1
    try:
        proc = subprocess.Popen(
            prepared,
            cwd=cwd,
            env=env,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except OSError as exc:
        print(f"не запустилось: {exc}", file=sys.stderr, flush=True)
        return 1
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def parse_version(text: str) -> tuple[int, ...]:
    """Достаёт числа версии из строки вида v24.19.0. Пусто — не разобрали."""
    nums: list[int] = []
    current = ""
    for ch in text:
        if ch.isdigit():
            current += ch
            continue
        if current:
            nums.append(int(current))
            current = ""
            if len(nums) >= 4:
                break
    if current and len(nums) < 4:
        nums.append(int(current))
    return tuple(nums)


def version_at_least(found: tuple[int, ...], minimum: tuple[int, ...]) -> bool:
    """Сравнивает кортежи версий. Пустая найденная — не годится."""
    if not found:
        return False
    width = max(len(found), len(minimum))
    left = found + (0,) * (width - len(found))
    right = minimum + (0,) * (width - len(minimum))
    return left >= right


def node_version() -> tuple[int, ...] | None:
    """Версия node, если он есть. None — нет или не ответил."""
    exe = resolve_exe("node")
    if not exe:
        return None
    argv = prepare_argv([exe, "--version"])
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (done.stdout or done.stderr or "").strip()
    parsed = parse_version(text)
    return parsed or None


def parse_kv(text: str) -> dict[str, str]:
    """Читает KEY=VALUE. Комментарии и пустые строки пропускает.

    Значение не обрезается до первого пробела: токен может их не содержать,
    но путь — может. Кавычки по краям снимаются.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def unreal_settings(text: str) -> tuple[str, str]:
    """Путь проекта и, если указан, путь плагина.

    Допустимо одно из двух:
      * одна строка — папка проекта или файл .uproject;
      * строки project= и plugin=.
    Комментарии (#) пропускаются.
    """
    kv = parse_kv(text)
    project = kv.get("project", "").strip()
    plugin = kv.get("plugin", "").strip()
    if project:
        return project, plugin
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" not in line:
            return line, plugin
    return "", plugin


def project_dir(raw: str) -> Path | None:
    """Папка проекта Unreal. Файл .uproject сводится к его папке."""
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_file() and path.suffix.lower() == ".uproject":
        return path.parent
    if path.is_dir():
        return path
    return None


def enginewire_present(project: Path, plugin_raw: str = "") -> bool:
    """Есть ли плагин 0.6. Старый McpAutomationBridge — это другая ветка."""
    if plugin_raw:
        extra = Path(plugin_raw).expanduser()
        if extra.is_dir() and extra.name == "EngineWire":
            return True
        if (extra / "EngineWire").is_dir():
            return True
    return (project / "Plugins" / "EngineWire").is_dir()


def godot_command(data: object) -> list[str] | None:
    """Команда из файла настроек. Без слова attach — не наша."""
    if not isinstance(data, dict):
        return None
    command = data.get("command")
    if not isinstance(command, list) or not command:
        return None
    if not all(isinstance(part, str) and part.strip() for part in command):
        return None
    if "attach" not in command:
        return None
    joined = " ".join(command).lower()
    if "godot_bridge_launcher" in joined:
        return None
    return [part.strip() for part in command]


def find_first(patterns: tuple[str, ...]) -> str:
    """Первый существующий файл по абсолютным шаблонам. Пусто — не нашли."""
    import glob

    for pattern in patterns:
        hits = [hit for hit in glob.glob(pattern) if Path(hit).is_file()]
        if hits:
            return str(Path(hits[-1]))
    return ""
