"""Общие куски лаунчеров мостов.

Лаунчер запускает opencode как обычный скрипт и отдаёт ему stdin/stdout.
Лишний текст в stdout ломает протокол MCP, поэтому журнал — только в stderr.

Секреты (токен TikTok, токен Unreal) сюда не печатаются никогда.
"""

from __future__ import annotations

import csv
import glob
import io
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
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


#: Версии, которые реально лежали в каталогах на 2026-10-14.
#: Не «последняя навсегда»: закрепили, чтобы молча не приехала несовместимая.
UNITY_FROM = "mcpforunityserver==10.3.0"
#: Unreal здесь больше не нужен: в линии 0.6 сервер живёт внутри плагина
#: EngineWire, и npm не участвует. Константы UNREAL_PACKAGE нет намеренно —
#: она была причиной рассинхрона между кодом и указателем плагинов: в коде
#: стоял один релиз, в указателе другой, и мост падал бы на каждом вызове.
#: Проверка «мосту Unreal не нужен Node» стоит в test_bridge_regression.
TIKTOK_PACKAGE = "@getmcpads/tiktok-ads-mcp-server@2.0.1"
#: Пакет Godot на PyPI в тот же день. В команду его не подставляем:
#: док редактора сам пишет argv с портами и capability, чужой пин сломает вход.
GODOT_PYPI = "godot-ai==4.3.0"

#: Мосту Unreal Node не нужен, поэтому и минимальной версии Node для него
#: тут нет: в линии 0.6 сервер живёт внутри плагина EngineWire.
TIKTOK_NODE = (22, 12, 0)


def _force_utf8() -> None:
    """Журнал должен быть в UTF-8, а не в кодировке консоли.

    Мост объясняет человеку, почему не работает, — и именно этот текст
    читает смотритель мостов, разбирая причину отказа. В кодировке
    консоли русский превращается в кракозябры, и объяснение теряется
    вместе с причиной: 19.10.2026 так и вышло — «нет ключа» доехало
    как «�������� �� ������». Под pythonw потоков может не быть вовсе,
    тогда и перенастраивать нечего.
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
            stderr=sys.stderr, startupinfo=_hidden_startupinfo(),
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
    code, stdout, stderr, status = run_capture([exe, "--version"], timeout=15)
    if status:
        return None
    text = (stdout or stderr or "").strip()
    parsed = parse_version(text)
    return parsed or None


def probe_command(argv: list[str], timeout: int = 15) -> tuple[int | None, str]:
    """Пускает команду и отдаёт её код и текст. stdin закрыт.

    Нужна, чтобы узнать состояние чужой программы — есть ли вход, — ничего
    не печатая и не отдавая ей канал протокола MCP. Первый элемент None
    означает «не запустилась или не ответила вовремя», и это не «входа нет».
    """
    code, stdout, stderr, status = run_capture(argv, timeout=timeout)
    if status:
        # Контракт прежний: None значит «не договорились», а не «входа нет».
        # Отличие обычного сбоя и незакрытой очистки живёт в run_capture.
        return None, ""
    return code, ((stdout or "") + (stderr or "")).strip()


def spotify_app_path() -> str:
    """Путь к Spotify.exe, если приложение установлено. Пусто — не найдено.

    Само приложение мосту не нужно: пакет ходит в Spotify Web API. Оно
    требуется только для воспроизведения, поэтому отсутствие — не отказ
    запуска, а предупреждение. Пути те же, что у панели управления Spotify.
    """
    roots = (
        Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Spotify" / "Spotify.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Spotify" / "Spotify.exe",
    )
    return find_first(tuple(str(root) for root in roots))


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


# ---------------------------------------------------------------------------
# Поиск уже установленной программы. Часть A1 плана от 15.10.2026.
#
# Зачем: `resolve_exe` возвращает ПЕРВОЕ совпадение в PATH. Если оно не
# запускается, второе никогда не будет рассмотрено, и мост скажет «не
# найдено», хотя программа на машине есть и работает. Это и случилось с
# Codex: его CLI лежит в папке приложения и в PATH не стоит.
#
# Порядок обхода и допуск — разные вещи. Сначала решаем, КОГО смотреть
# первым (своё правило у каждого источника), потом — МОЖНО ЛИ его вообще
# запускать (политика по типу файла). Смешивать их нельзя.
# ---------------------------------------------------------------------------

#: Пакетные файлы. Через них идёт cmd.exe, а модель пишет текст запроса.
BATCH_SUFFIXES = (".cmd", ".bat")
#: Источники в порядке обхода. Имя источника попадает в ProgramFound.
SOURCE_PATH = "PATH"
SOURCE_CONFIG = "настройка программы"
SOURCE_APP = "папка приложения"
SOURCE_USER = "папка пользователя"
SOURCE_WINGET = "папка winget"
SOURCE_SHORTCUT = "ярлык «Пуск»"
SOURCE_NONE = "не найдено"
#: Три вида записи в attempts. Их нельзя сливать: отказ в допуске — это не
#: поломка программы, и человек должен видеть разницу.
REC_FOUND = "кандидат обнаружен"
REC_DENIED = "отклонён политикой типа файла"
REC_PROBED = "проверка запуска выполнена"
#: Таймаут проверки запуска. Короткий: это `--version`, а не работа.
PROBE_TIMEOUT = 15


#: Причина — строка для человека, а не дамп ошибки. Длиннее не полезно:
#: текст системной ошибки Windows легко занимает три строки, и в интерфейсе
#: от него ничего, кроме шума.
REASON_LIMIT = 160


def _short(text: str, limit: int = REASON_LIMIT) -> str:
    """Обрезает причину по длине, не разрывая слова на середине."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" .,;:") + "..."


@dataclass
class ProgramSpec:
    """Описание программы, которую ищем. Ничего не выполняет."""

    name: str
    exe_names: tuple[str, ...]
    extra_globs: tuple[str, ...] = ()
    #: "путь/к/файлу:КЛЮЧ" относительно дома пользователя. Для Codex:
    #: ".codex/config.toml:CODEX_CLI_PATH".
    config_hint: str = ""
    #: Где видно, что приложение стоит, даже если CLI нет.
    app_paths: tuple[str, ...] = ()


@dataclass
class ProgramFound:
    """Итог поиска. Подробности — в attempts, короткий вывод — в reason."""

    path: str = ""
    from_source: str = SOURCE_NONE
    checked: bool = False
    reason: str = ""
    attempts: list = field(default_factory=list)

    def attempt(self, source: str, path: str, record: str, result: str) -> None:
        self.attempts.append({
            "source": source, "path": path, "record": record,
            "result": _short(result),
        })


def _file_names(exe_names: tuple[str, ...]) -> list[str]:
    """Имена файлов, которые ищем в папке: без расширения — три варианта.

    Порядок внутри папки задаётся этим списком, а не файловой системой:
    вывод должен быть одинаковым на любой машине.
    """
    out: list[str] = []
    for base in exe_names:
        if Path(base).suffix.lower() in (".exe",) + BATCH_SUFFIXES:
            candidates = [base]
        else:
            candidates = [base + ".exe", base + ".cmd", base + ".bat"]
        for name in candidates:
            if name not in out:
                out.append(name)
    return out


def _usable(path: Path) -> tuple[bool, str]:
    """Ступень 1: есть ли файл и не пустой ли он.

    Нулевой размер — не редкость: 15.10.2026 так был битый python.exe в
    обеих папках uv, и «самый свежий» файл оказался как раз этим.
    """
    if not path.exists():
        return False, "файла нет"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"не удалось прочитать: {exc.strerror or exc}"
    if size == 0:
        return False, "файл нулевого размера"
    return True, ""


def _path_dirs(path_dirs: list[str] | None) -> list[str]:
    """Папки PATH в том порядке, в каком их задала система.

    Сортировать их по времени изменения файлов нельзя: PATH — это готовый
    список приоритетов, и переписывать его своим значит менять поведение
    чужой настройки.
    """
    if path_dirs is not None:
        return [d for d in path_dirs if d]
    raw = os.environ.get("PATH", "")
    return [d for d in raw.split(os.pathsep) if d]


def _toml_string(text: str, key: str) -> str:
    """Достаёт строку по ключу из TOML, не разбирая TOML целиком.

    Файл может быть битым, пустым или чужим — читаем построчно и молча
    возвращаем пусто, если ключа нет. Полный разбор здесь был бы лишним:
    нужен один ключ, а ломаться от чужой файла нельзя.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip().rstrip(",") != key:
            continue
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            return value[1:-1]
        return value
    return ""


def _from_config(home: Path, config_hint: str) -> list[str]:
    """Путь из настроек самой программы, например CODEX_CLI_PATH."""
    if ":" not in config_hint:
        return []
    rel, key = config_hint.rsplit(":", 1)
    path = home / rel.replace("/", os.sep)
    if not path.is_file():
        return []
    value = _toml_string(read_text(path), key)
    if not value:
        return []
    candidate = Path(os.path.expandvars(value))
    if not candidate.is_absolute():
        candidate = home / value
    return [str(candidate)]


def _from_globs(patterns: tuple[str, ...]) -> list[str]:
    r"""Папка приложения: маски вида ...\bin\*\codex.exe.

    Здесь порядок другой: сборки разных версий лежат рядом, и свежая обычно
    нужная. Сортируем по времени изменения, при равных датах — лексикографически
    большим путём, чтобы выбор не зависел от порядка обхода.
    """
    hits: list[Path] = []
    for pattern in patterns:
        hits.extend(Path(h) for h in glob.glob(os.path.expandvars(pattern)))
    uniq = {str(h): h for h in hits}
    # Сначала путь по убыванию, потом стабильной сортировкой свежесть по
    # убыванию: среди равных дат остаётся лексикографически больший путь.
    ordered = sorted(uniq.values(), key=lambda p: str(p), reverse=True)
    ordered.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0,
                 reverse=True)
    return [str(p) for p in ordered]


def _from_user_dirs(home: Path) -> list[str]:
    """Папка пользователя: продолжение поведения PATH, без сортировки по дате."""
    dirs = [home / ".local" / "bin"]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        dirs.append(Path(appdata) / "npm")
    names: list[str] = []
    for folder in dirs:
        if not folder.is_dir():
            continue
        for item in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if item.is_file():
                names.append(str(item))
    return names


def _winget_roots() -> list[Path]:
    """Папки, куда winget кладёт установленные пакеты."""
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    return [Path(local) / "Microsoft" / "WinGet" / "Packages"]


def _from_winget(spec: "ProgramSpec", roots: list[Path]) -> list[str]:
    r"""Папка winget: ...\WinGet\Packages\<пакет>\<имя>.exe.

    Живая находка 15.10.2026: winget поставил Claude Code в
    `WinGet\Packages\Anthropic.ClaudeCode_...\claude.exe` и НЕ создал
    псевдоним в `WinGet\Links`, поэтому ни PATH, ни папка пользователя её не
    видят. Без этого источника мост писал бы «не установлена» про стоящую
    программу.

    Порядок здесь как у папки приложения: рядом лежат разные пакеты и версии
    одного пакета, нужна свежая — сортируем по времени изменения, при равных
    датах лексикографически большим путём, чтобы выбор не зависел от порядка
    обхода. Вложенная папка версии проверяется тоже: манифест с версией в
    имени кладёт файлы на уровень глубже.
    """
    wanted = {n.lower() for n in spec.exe_names}
    wanted |= {n.lower() for n in _file_names(spec.exe_names)}
    hits: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*\\*", "*\\*\\*"):
            for raw in glob.glob(os.path.expandvars(str(root / pattern))):
                path = Path(raw)
                if not path.is_file():
                    continue
                if path.stem.lower() not in wanted and \
                        path.name.lower() not in wanted:
                    continue
                hits.append(path)
    uniq = {str(h): h for h in hits}
    ordered = sorted(uniq.values(), key=lambda p: str(p), reverse=True)
    ordered.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0,
                 reverse=True)
    return [str(p) for p in ordered]


def _read_shortcut_targets() -> dict[str, str]:
    """Ярлыки меню «Пуск»: имя ярлыка -> предполагаемая цель.

    Полноценный разбор .lnk здесь не нужен и был бы хрупким: цель
    вытаскивается эвристикой из самого файла, а потом проверяется запуском
    `--version`. То есть эвристика ничего не решает: негодная цель просто
    не пройдёт проверку.
    """
    out: dict[str, str] = {}
    roots = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    programdata = os.environ.get("PROGRAMDATA", "")
    if programdata:
        roots.append(Path(programdata) / "Microsoft/Windows/Start Menu/Programs")
    for root in roots:
        if not root.is_dir():
            continue
        try:
            links = list(root.rglob("*.lnk"))
        except OSError:
            continue
        for link in links:
            try:
                blob = link.read_bytes()
            except OSError:
                continue
            text = blob.decode("utf-16-le", errors="ignore")
            words = text.split("\x00")
            best = ""
            for word in words:
                word = word.strip()
                if word.lower().endswith((".exe",) + BATCH_SUFFIXES):
                    if len(word) > len(best):
                        best = word
            if best:
                out[link.stem.lower()] = best
    return out


def probe_candidate(path: str, allow_batch: bool = False) -> tuple[bool, bool, str]:
    """Можно ли запускать кандидата. Возвращает (годен, проверен, причина).

    Три случая по типу файла, и порядок именно такой:
      * `.exe` — запуск с `--version`, таймаут PROBE_TIMEOUT;
      * `.cmd`/`.bat` — только при allow_batch, иначе отказ ДО запуска;
      * прочее — только наличие и размер, запускать нечем.
    """
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix in BATCH_SUFFIXES and not allow_batch:
        return False, False, (
            "отказ в допуске: пакетный файл, через него идёт cmd.exe"
        )
    if suffix not in (".exe",) + BATCH_SUFFIXES:
        return True, False, (
            f"принят без проверки запуска: тип {suffix or 'без расширения'} "
            "запускать нечем, проверять нечем"
        )
    prepared = prepare_argv([str(target), "--version"])
    try:
        done = subprocess.run(
            prepared,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            encoding="utf-8",
            errors="replace", startupinfo=_hidden_startupinfo(),
        )
    except subprocess.TimeoutExpired:
        return False, True, (
            f"не ответил за {PROBE_TIMEOUT} секунд на --version"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, True, f"не запустилась: {exc.strerror if hasattr(exc, 'strerror') else exc}"
    if done.returncode == 0:
        return True, True, "ответила кодом 0 на --version"
    return False, True, f"--version вернул код {done.returncode}"


def _app_installed(app_paths: tuple[str, ...]) -> bool:
    return any(p and Path(os.path.expandvars(p)).exists() for p in app_paths)


def find_cli(spec: ProgramSpec, allow_batch: bool = False, *,
             path_dirs: list[str] | None = None,
             home: Path | None = None,
             winget_roots: list[Path] | None = None,
             shortcut_targets: dict[str, str] | None = None) -> ProgramFound:
    """Ищет установленную программу по списку источников и возвращает итог.

    Кандидаты проверяются по очереди, пока не найдётся пригодный; кончились
    в источнике — идём к следующему, а не сдаёмся. Путь, пришедший из
    команды агента, сюда не попадает: перебор идёт только по своему списку.
    """
    base = Path(home) if home is not None else Path.home()
    found = ProgramFound()

    # 1. PATH: порядок папок как в системе, внутри папки — по имени файла.
    for folder in _path_dirs(path_dirs):
        for name in _file_names(spec.exe_names):
            candidate = Path(folder) / name
            ok, why = _usable(candidate)
            if not ok:
                if candidate.exists():
                    found.attempt(SOURCE_PATH, str(candidate), REC_FOUND, why)
                continue
            good, checked, why = probe_candidate(str(candidate), allow_batch)
            found.attempt(SOURCE_PATH, str(candidate),
                          REC_PROBED if checked else REC_DENIED, why)
            if good:
                return ProgramFound(str(candidate), SOURCE_PATH, checked,
                                    "найдена в PATH и проверена", found.attempts)

    # 2. Путь из настроек самой программы.
    for raw in _from_config(base, spec.config_hint):
        candidate = Path(raw)
        ok, why = _usable(candidate)
        if not ok:
            found.attempt(SOURCE_CONFIG, raw, REC_FOUND, why)
            continue
        good, checked, why = probe_candidate(raw, allow_batch)
        found.attempt(SOURCE_CONFIG, raw, REC_PROBED if checked else REC_DENIED, why)
        if good:
            return ProgramFound(raw, SOURCE_CONFIG, checked,
                                "взята из настроек программы и проверена",
                                found.attempts)

    # 3. Папка приложения: маски, свежие сверху.
    for raw in _from_globs(spec.extra_globs):
        candidate = Path(raw)
        ok, why = _usable(candidate)
        if not ok:
            found.attempt(SOURCE_APP, raw, REC_FOUND, why)
            continue
        good, checked, why = probe_candidate(raw, allow_batch)
        found.attempt(SOURCE_APP, raw, REC_PROBED if checked else REC_DENIED, why)
        if good:
            return ProgramFound(raw, SOURCE_APP, checked,
                                "взята из папки приложения и проверена",
                                found.attempts)

    # 4. Папка пользователя.
    for raw in _from_user_dirs(base):
        candidate = Path(raw)
        if candidate.stem.lower() not in {n.lower() for n in spec.exe_names} \
                and candidate.name.lower() not in \
                {x.lower() for x in _file_names(spec.exe_names)}:
            continue
        ok, why = _usable(candidate)
        if not ok:
            found.attempt(SOURCE_USER, raw, REC_FOUND, why)
            continue
        good, checked, why = probe_candidate(raw, allow_batch)
        found.attempt(SOURCE_USER, raw, REC_PROBED if checked else REC_DENIED, why)
        if good:
            return ProgramFound(raw, SOURCE_USER, checked,
                                "взята из папки пользователя и проверена",
                                found.attempts)

    # 5. Папка winget: сюда кладут пакеты, псевдоним в PATH при этом может
    #    не появиться. Свежие сверху.
    roots = _winget_roots() if winget_roots is None else list(winget_roots)
    for raw in _from_winget(spec, roots):
        candidate = Path(raw)
        ok, why = _usable(candidate)
        if not ok:
            found.attempt(SOURCE_WINGET, raw, REC_FOUND, why)
            continue
        good, checked, why = probe_candidate(raw, allow_batch)
        found.attempt(SOURCE_WINGET, raw,
                      REC_PROBED if checked else REC_DENIED, why)
        if good:
            return ProgramFound(raw, SOURCE_WINGET, checked,
                                "взята из папки winget и проверена",
                                found.attempts)

    # 6. Ярлык «Пуск»: цель читается, ничего не запускается.
    targets = shortcut_targets
    if targets is None:
        targets = _read_shortcut_targets()
    for key, raw in sorted(targets.items()):
        if key != spec.name.lower():
            continue
        candidate = Path(raw)
        ok, why = _usable(candidate)
        if not ok:
            found.attempt(SOURCE_SHORTCUT, raw, REC_FOUND, why)
            continue
        good, checked, why = probe_candidate(raw, allow_batch)
        found.attempt(SOURCE_SHORTCUT, raw, REC_PROBED if checked else REC_DENIED, why)
        if good:
            return ProgramFound(raw, SOURCE_SHORTCUT, checked,
                                "взята из ярлыка «Пуск» и проверена",
                                found.attempts)

    # Ничего не нашлось. Итог короткий, подробности — в attempts.
    if not found.attempts:
        reason = ("не нашли ни одного кандидата: пусто в PATH, в настройках, "
                  "в папке приложения, в папке пользователя, в папке winget "
                  "и в ярлыках")
        if _app_installed(spec.app_paths):
            reason += "; приложение стоит, нужна CLI"
    else:
        denied = [a for a in found.attempts if a["record"] == REC_DENIED]
        broken = [a for a in found.attempts if a["record"] == REC_PROBED]
        last = (broken or denied or found.attempts)[-1]["result"]
        reason = _short(f"кандидатов было {len(found.attempts)}, подходящих нет; "
                        f"последняя причина: {last}")
    return ProgramFound("", SOURCE_NONE, False, reason, found.attempts)


def find_cli_path(spec: ProgramSpec, **kwargs) -> str | None:
    """Только путь, без подробностей. None — программы нет.

    Именно None, а не пустая строка: так же, как прежний `resolve_exe`, чтобы
    в местах вызова не пришлось различать два вида «нет программы».
    """
    found = find_cli(spec, **kwargs)
    return found.path or None


# ---------------------------------------------------------------------------
# Запуск с таймаутом и остановка дерева процессов. Часть A3 плана.
#
# `subprocess.run(timeout=…)` убивает только того, кого запустил. Потомки
# остаются жить: у Codex, кстати, есть чем плодиться — рядом лежат
# codex-command-runner.exe и codex-windows-sandbox-setup.exe. Приём остановки
# дерева в проекте уже есть (lmarena.py, pxpipe.py): taskkill /T /F плюс
# CREATE_NEW_PROCESS_GROUP.
#
# Код 0 у taskkill не считается доказательством, что всё исчезло, поэтому
# после остановки процессы проверяются по номерам — вместе с именем образа,
# иначе переиспользованный номер даст неверный вывод в любую сторону.
# ---------------------------------------------------------------------------

#: Отдельная группа процессов: иначе Ctrl+C в консоли моста убьёт и ребёнка.
_NEW_GROUP = 0x00000200
#: Без окна консоли: иначе taskkill и tasklist моргают окном при каждой проверке.
_NO_WINDOW = 0x08000000
#: Сколько ждём исчезновения процесса после taskkill.
KILL_WAIT_STEPS = 20
KILL_WAIT_STEP = 0.25


def _creation_flags() -> int:
    """Флаги создания процесса. Вне Windows CREATE_NEW_PROCESS_GROUP нет."""
    if os.name != "nt":
        return 0
    return _NEW_GROUP | _NO_WINDOW


def _process_alive(pid: int, image: str = "") -> bool:
    """Жив ли процесс с таким номером. Сверяется и имя образа.

    Одного номера мало: номер переиспользуется, и «жив такой PID» может
    означать чужую программу. Если образ известен и не совпал — считаем, что
    процесса нет.
    """
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for row in csv.reader(io.StringIO(done.stdout or "")):
        if len(row) < 2 or row[1].strip() != str(pid):
            continue
        if image and Path(row[0].strip()).name.lower() != image.lower():
            return False
        return True
    return False




# ---------------------------------------------------------------------------
# Группа заданий (Job Object) — чтобы пережить остановку было невозможно.
#
# taskkill /T убивает дерево по списку родителей. Если родитель умер раньше,
# потомок переподчиняется и в дереве больше не виден: мост скажет «остановлено»,
# а процесс работает. Группа заданий решает это: членство наследуется, а
# TerminateJobObject убивает всех членов разом, включая уже переподчинённых.
# ---------------------------------------------------------------------------

_JOB_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_JOB_OBJECT_ALL_ACCESS = 0x1F001FF


def _job_object() -> tuple[object, object]:
    """Создаёт группу заданий с KillOnClose. (ctypes-модуль, дескриптор).

    Пусто на выходе, если система не разрешила: тогда работает запасной путь
    через taskkill, и статус остановки это отразит.
    """
    if os.name != "nt":
        return None, None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None, None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
            ctypes.sizeof(info))
        if not ok:
            kernel32.CloseHandle(handle)
            return None, None
        return kernel32, handle
    except Exception:  # noqa: BLE001 - группа заданий необязательна
        return None, None


def _assign_job(kernel32, handle, pid: int) -> bool:
    """Кладёт процесс в группу заданий. True — кладёт.

    Делается именно через HANDLE процесса, а не через его номер:
    AssignProcessToJobObject принимает дескриптор, и если передать туда номер,
    вызов не сработает молча. Раньше было именно так — группа создавалась, а
    процесс в неё не попадал, и переживший потомок оставался живым.
    """
    if kernel32 is None or not handle or os.name != "nt":
        return False
    import ctypes

    try:
        access = _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | 0x1000
        proc_handle = kernel32.OpenProcess(access, False, int(pid))
        if not proc_handle:
            return False
        try:
            ok = kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(handle), proc_handle)
        finally:
            kernel32.CloseHandle(proc_handle)
        return bool(ok)
    except Exception:  # noqa: BLE001 - группа необязательна, есть taskkill
        return False


def _terminate_job(kernel32, handle) -> bool:
    """Убивает всех членов группы. True — команда выполнена."""
    import ctypes

    if kernel32 is None or not handle:
        return False
    try:
        return bool(kernel32.TerminateJobObject(
            ctypes.c_void_p(handle), 1))
    except Exception:  # noqa: BLE001
        return False


def _descendant_pids(pid: int) -> list[int]:
    """Номера всех потомков процесса, рекурсивно.

    Снимок снимается, пока корень ещё жив. После его смерти потомки
    переподчиняются и в дереве больше не видны — поэтому снимок нужен
    именно ДО остановки, иначе переживший потомок останется незамеченным.
    Список пустой, если PowerShell недоступен: тогда проверка остановки
    ослабляется, и это честно видно по статусу, а не спрятано.
    """
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$all=New-Object System.Collections.ArrayList;"
        f"$queue=New-Object System.Collections.Queue;"
        "[void]$queue.Enqueue({pid});"
        "while($queue.Count -gt 0){"
        "  $p=$queue.Dequeue();"
        "  foreach($k in (Get-CimInstance Win32_Process "
        "-Filter \"ParentProcessId=$p\")){"
        "    if(-not $all.Contains([int]$k.ProcessId)){"
        "      [void]$all.Add([int]$k.ProcessId);"
        "      [void]$queue.Enqueue([int]$k.ProcessId);}}}"
        "$all -join ','"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for piece in (done.stdout or "").split(","):
        piece = piece.strip()
        if piece.isdigit():
            out.append(int(piece))
    return out


def _sleep_short() -> None:
    """Короткая пауза, чтобы ребёнок успел появиться до снимка."""
    time.sleep(0.15)

def _kill_tree(pid: int, image: str = "") -> tuple[bool, list[int]]:
    """Останавливает дерево процессов. Возвращает (остановлено, осталось).

    `остановлено` — только после того, как процесс действительно исчез.
    Не удалось — возвращаем оставшиеся номера, чтобы человек увидел, что
    могло остаться работать.
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(KILL_WAIT_STEPS):
        if not _process_alive(pid, image):
            return True, []
        time.sleep(KILL_WAIT_STEP)
    return False, [pid]


def run_capture(argv: list[str], *, cwd: str | None = None,
                timeout: int = 600, env: dict | None = None
                ) -> tuple[int | None, str, str, str]:
    """Запуск с таймаутом и остановкой дерева.

    Возвращает (код, stdout, stderr, статус). Статус — это не «ошибка»:
      * `""` — процесс отработал сам, код настоящий (в том числе ненулевой);
      * `"таймаут"` — время вышло, дерево подтверждённо остановлено;
      * `"ошибка_остановки"` — время вышло, но подтверждения нет: что-то
        могло остаться работать, и молчать об этом нельзя;
      * `"не_запустился"` — запустить не вышло.

    Три последних статуса различимы по-настоящему, а не спрятаны в тексте:
    вызывающий код обязан их различать, а читатель журнала — видеть.

    Про кодировку (21.10.2026, найдено полным прогоном). Ребёнок печатает
    по-русски в трубу: его stdout — не консоль, и Python-ребёнок пишет в
    него в КОДИРОВКЕ КОНСОЛИ (cp1251), а отец читает трубу как UTF-8.
    Русский доезжает кракозябрами, и «живой ответ» не узнаётся в своём
    же выводе — полный прогон самопроверки поймал это на
    test_process_tree. Лечение: ребёнку-питону принудительно задаётся
    UTF-8 через PYTHONIOENCODING. Переменная безопасна для чужих детей:
    не-Python её просто игнорирует, а системные команды (tasklist,
    taskkill) печатают в ASCII или cp866 — их вывод в эти проверки не
    разбирается по русским буквам.
    """
    prepared = prepare_argv(argv)
    if not prepared:
        return None, "", "пустая команда", "не_запустился"
    # Наследуем среду отца и просим питона-ребёнка говорить по-UTF-8.
    # Свой env вызывающего уважается: его ключи сильнее наших добавок.
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    child_env.setdefault("PYTHONUTF8", "1")
    if env:
        child_env.update(env)
    image = Path(prepared[0]).name
    kernel32, job = _job_object()
    try:
        proc = subprocess.Popen(
            prepared,
            cwd=cwd,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
        )
    except OSError as exc:
        return None, "", f"не запустился: {exc}", "не_запустился"
    in_job = _assign_job(kernel32, job, proc.pid)
    # Потомки снимаются, пока корень жив: после его смерти они переподчиняются.
    _sleep_short()
    family = _descendant_pids(proc.pid)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        family = list({*family, *_descendant_pids(proc.pid)})
        # Сначала группа заданий: она достаёт и переподчинённых, которых
        # taskkill /T уже не видит. Потом taskkill — как запасной путь.
        job_done = _terminate_job(kernel32, job) if in_job else False
        stopped, leftover = _kill_tree(proc.pid, image)
        # Группа — основной путь; taskkill — запасной. Если процесса в группе
        # не было, успешным считаем только то, что подтвердил taskkill.
        stopped = stopped and (job_done or not in_job)
        try:
            proc.communicate(timeout=10)
        except (OSError, subprocess.SubprocessError,
                subprocess.TimeoutExpired):
            pass
        # Подтверждаем не только корень, но и каждого снятого потомка.
        for child in family:
            if _process_alive(child):
                leftover.append(child)
        leftover = sorted(set(leftover))
        left = (f"; остались процессы: {', '.join(str(x) for x in leftover)}"
                if leftover else "")
        if stopped and not leftover:
            return None, "", f"не ответил за {timeout} секунд, процесс остановлен", "таймаут"
        return (None, "",
                f"не ответил за {timeout} секунд, остановить не удалось{left}",
                "ошибка_остановки")
    return proc.returncode, stdout or "", stderr or "", ""


def stop_status_text(status: str, program: str, timeout: int) -> str:
    """Человеческий текст по статусу остановки. Один на все мосты."""
    if status == "таймаут":
        return f"{program} не ответил за {timeout} секунд, процесс остановлен."
    if status == "ошибка_остановки":
        return (f"{program} не ответил за {timeout} секунд, и остановить его "
                "не удалось: какие-то процессы могли остаться работать.")
    if status == "не_запустился":
        return f"{program} не запустился."
    return ""
