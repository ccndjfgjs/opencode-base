"""Редакторы и движки: найти, измерить версию, поставить плагин.

Пять программ в одном модуле — потому что работа у них одна и та же:
найти установленную, снять версию, выбрать по ней плагин из указателя,
сверить, положить куда надо и сказать честно, если положить нельзя.
Различаются они только путями и тем, куда кладётся плагин.

| Программа | Версия снимается с | Плагин кладётся |
|---|---|---|
| Unity | имя папки редактора + `ProjectSettings/ProjectVersion.txt` | строкой в `Packages/manifest.json` |
| Unreal Engine | `Engine/Build/Build.version` | `<проект>/Plugins/EngineWire` |
| Godot | `godot --version` | `<проект>/addons/godot_ai` |
| Ghidra | `Ghidra/application.properties` | `<гидра>/Extensions/Ghidra` + галочка в профиле |
| Roblox Studio | файл версии `RobloxStudioBeta.exe` | ничего: сервер встроенный |

Общее правило модуля: **отказ — это результат, а не ошибка.** Программа,
которую нельзя поставить без человека, говорит об этом текстом, а не
рисует зелёную галочку и не падает в окно.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "launchers"))

import plugin_index  # noqa: E402
import versions  # noqa: E402
from engine_setup import UNREAL_PORT_DEFAULT  # noqa: E402

WIN = os.name == "nt"
PROBE_TIMEOUT = 20
#: Куда складываются скачанные плагины. Внутри программы, не в чужих папках.
CACHE_DIRNAME = "плагины"


# --------------------------------------------------------------------------
# общие помощники
# --------------------------------------------------------------------------

@dataclass
class Found:
    """Что нашлось: путь, версия и где именно искали."""

    path: Path | None = None
    version: str = ""
    attempts: list[str] = field(default_factory=list)
    hint: str = ""   # чем ставится, если не нашлась

    @property
    def ok(self) -> bool:
        return self.path is not None and bool(self.version)

    def why(self, what: str) -> str:
        if self.ok:
            return f"{what}: {self.version}"
        looked = ("; ".join(self.attempts[-4:]) or "нигде не смотрела")
        tail = f" {self.hint}" if self.hint else " Поставь программу — тогда и версию смогу снять."
        return f"{what} не найдена. Искала: {looked}.{tail}"


def file_version(path: Path) -> str:
    """Версия из свойств файла Windows: «1.6.3.172».

    Нужна там, где имени папки нет: Roblox зовёт свои сборки случайными
    именами `version-11f155f3450f4c8e`, и версия живёт только в свойствах
    файла. На других системах возвращается пустая строка — честно, без выдумки.
    """
    import struct

    path = Path(path)
    if not WIN or not path.is_file():
        return ""
    raw = _version_block(path)
    if raw:
        # VS_FIXEDFILEINFO начинается с dwSignature = 0xFEEF04BD, записанного
        # как little-endian, то есть в байтах это BD 04 EF FE. Сразу после
        # подписи идёт dwStrucVersion, и только потом dwFileVersionMS и
        # dwFileVersionLS. Сдвиг на 4 байта даёт «1.0.1.6» вместо настоящей
        # версии — поэтому читаем с +8.
        start = raw.find(b"\xbd\x04\xef\xfe")
        if start >= 0:
            try:
                ms, ls = struct.unpack_from("<II", raw, start + 8)
            except struct.error:
                ms = ls = 0
            return ".".join(str(part) for part in
                            (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF))
    # Запасной путь: свойства файла через PowerShell. Медленно (около секунды),
    # поэтому только когда дешёвый способ не дал результата.
    code, out = run_capture(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Item -LiteralPath '{path}').VersionInfo.FileVersion"],
        timeout=40)
    text = (out or "").strip().splitlines()
    return text[0].strip() if code == 0 and text else ""


def _version_block(path: Path) -> bytes:
    """Сырой блок свойств версии файла.

    Функции лежат в version.dll, а не в kernel32: обращение через
    `ctypes.windll` даёт AttributeError, и его легко проглотить, решив, что
    «версии просто нет». Ошибка поэтому возвращается наружу словами.
    """
    try:
        dll = ctypes.WinDLL("version", use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p,
                                               ctypes.POINTER(ctypes.c_uint)]
        dll.GetFileVersionInfoSizeW.restype = ctypes.c_uint
        dll.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint,
                                            ctypes.c_uint, ctypes.c_void_p]
        dll.GetFileVersionInfoW.restype = ctypes.c_int
        handle = ctypes.c_uint(0)
        size = int(dll.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle)))
        if not size:
            return b""
        buf = ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(path), 0, size, buf):
            return b""
        return buf.raw[:size]
    except (OSError, AttributeError, ValueError):
        return b""


def run_capture(argv: list[str], timeout: int = PROBE_TIMEOUT) -> tuple[int, str]:
    """Запустить команду и вернуть её вывод. Ошибка — не исключение."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _no_window() -> int:
    """Не показывать чёрное окно консоли от чужих программ."""
    if not WIN:
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def process_running(image: str) -> bool:
    """Работает ли сейчас программа с таким именем файла.

    Нужно перед правкой файлов чужой программы: открытый редактор
    перезапишет их при выходе, и вся наша работа пропадёт молча.
    """
    if not WIN:
        return False
    code, out = run_capture(["tasklist", "/FI", f"IMAGENAME eq {image}",
                             "/NH", "/FO", "CSV"], timeout=PROBE_TIMEOUT)
    return code == 0 and image.lower() in (out or "").lower()


def process_running_any(images) -> bool:
    """Открыт ли хоть один из процессов.

    Список, а не одно имя: у разных версий редактора имя файла разное, и
    проверка по одному имени молчала бы там, где редактор открыт.
    """
    return any(process_running(str(image)) for image in images)


def cache_dir() -> Path:
    """Папка для скачанных плагинов внутри программы."""
    target = HERE / CACHE_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def _fail_closed(path: Path) -> str:
    """Человеческое имя диска, на который нельзя ставить."""
    try:
        drive = Path(os.path.splitdrive(str(Path(path).resolve()))[0]).resolve()
    except (OSError, ValueError):
        return ""
    return str(drive).upper() if drive else ""


def project_markers() -> tuple[str, ...]:
    """Маркеры папки проекта — по ним проект опознаётся, а не по имени."""
    return ("Assets", "ProjectSettings", "Plugins", "addons", "Content")


def is_project(path: Path, marker: str) -> bool:
    """Похоже ли на проект программы: есть её собственная папка."""
    try:
        return (Path(path) / marker).is_dir()
    except OSError:
        return False


# --------------------------------------------------------------------------
# Unity
# --------------------------------------------------------------------------

UNITY_HUBS = (
    r"C:\Program Files\Unity\Hub\Editor",
    r"C:\Program Files\Unity Hub\Editor",
)
UNITY_PROJECT_MARKER = "Assets"
UNITY_PACKAGE = "com.coplaydev.unity-mcp"
UNITY_STANDALONE_PREFIX = "Unity "


def program_files_dirs() -> list[Path]:
    """Папки, куда установщики по умолчанию кладут программы."""
    out: list[Path] = []
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(name, "")
        if value:
            out.append(Path(value))
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        out.append(Path(local) / "Programs")
    return out


def unity_standalone_editors(bases) -> list[tuple[str, Path]]:
    """Редакторы, поставленные winget без хаба.

    Такой установщик кладёт редактор отдельной папкой рядом с Program
    Files — «Unity 6000.6.6f1\\Editor\\Unity.exe», — а не в раскладку хаба
    «Unity\\Hub\\Editor\\<версия>». Раньше программа искала только вторую и
    установленный редактор объявляла ненайденным.

    Папки передаются снаружи специально: так проверка идёт по временным
    каталогам, а не по тому, что случайно стоит на машине.
    """
    found: list[tuple[str, Path]] = []
    for base in (Path(item) for item in bases):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            # Только папка редактора: у «Unity Hub» такого префикса нет.
            if not child.is_dir() or not child.name.startswith(UNITY_STANDALONE_PREFIX):
                continue
            version = child.name[len(UNITY_STANDALONE_PREFIX):].strip()
            exe = child / "Editor" / "Unity.exe"
            if version and exe.is_file():
                found.append((version, exe))
    return found


def unity_editors() -> Found:
    """Все редакторы Unity: имя папки и есть версия.

    Имя папки — единственное место, где версия написана текстом: сам
    `Unity.exe` в свойствах файла версию редактора не отдаёт.
    """
    found = Found(hint="Ставится через winget: Unity.UnityHub (хаб) и "
                       "Unity.Unity.6000 (редактор). Редактор без хаба "
                       "кладётся отдельной папкой рядом с Program Files. "
                       "Бесплатную лицензию Unity Personal активирует "
                       "только хаб.")
    roots = [Path(p) for p in UNITY_HUBS]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(Path(local) / "Programs" / "Unity Hub" / "Editor")
    for root in roots:
        found.attempts.append(str(root))
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            exe = child / "Editor" / "Unity.exe"
            if not exe.is_file():
                continue
            if not found.ok or versions.version_tuple(child.name) > versions.version_tuple(found.version):
                found.path = exe
                found.version = child.name
    for version, exe in unity_standalone_editors(program_files_dirs()):
        found.attempts.append(str(exe.parent.parent))
        if not found.ok or versions.version_tuple(version) > versions.version_tuple(found.version):
            found.path = exe
            found.version = version
    return found


def unity_project_version(project: Path) -> str:
    """Версия редактора, записанная самим проектом."""
    path = Path(project) / "ProjectSettings" / "ProjectVersion.txt"
    if not path.is_file():
        return ""
    match = re.search(r"m_EditorVersion:\s*(\S+)",
                      path.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else ""


# Папки пользователя, где проекты лежат чаще всего. Обход всего диска не
# делается никогда: это минуты ожидания и окно, в котором всё зависло.
UNITY_PROJECT_FOLDERS = ("Documents", "Desktop", "Downloads", "Projects",
                         "Unity", "Unity Projects", "Games", "Source", "Repos")
# Внутри этих папок проектов не бывает, а обход вхолостую — это минуты.
UNITY_SCAN_SKIP = frozenset({
    "Library", "Temp", "Obj", "obj", "Logs", "Build", "Builds",
    "node_modules", ".git", ".svn", "$RECYCLE.BIN", "System Volume Information",
})
UNITY_SCAN_DEPTH = 3
UNITY_SCAN_LIMIT = 200
# Бюджет папок: без него поиск по «Загрузкам» с 38 тысячами файлов идёт
# полторы минуты, и окно с этим окном выглядит зависшим. Обрезанный поиск
# честно говорит, что он обрезан — иначе это молчаливый пропуск проекта.
UNITY_SCAN_BUDGET = 2000


@dataclass
class ProjectScan:
    """Результат поиска проектов: что нашлось и не обрезался ли обход."""

    items: list[tuple[Path, str]] = field(default_factory=list)
    truncated: bool = False
    visited: int = 0


def unity_project_roots() -> list[Path]:
    """Папки пользователя и дисков, в которых ищутся проекты Unity.

    Игры и проекты часто лежат не в профиле, а на отдельном диске, поэтому
    смотрятся и несколько папок верхнего уровня дисков. Обход диска целиком
    не делается никогда: смотреть будут только эти папки.
    """
    out: list[Path] = []
    home = os.environ.get("USERPROFILE", "")
    if home:
        base = Path(home)
        for name in UNITY_PROJECT_FOLDERS:
            for candidate in (base / name, base / "Documents" / name):
                if candidate.is_dir() and candidate not in out:
                    out.append(candidate)
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        if not drive.is_dir():
            continue
        for name in UNITY_PROJECT_FOLDERS:
            candidate = drive / name
            if candidate.is_dir() and candidate not in out:
                out.append(candidate)
    return out


def is_unity_project(path: Path) -> bool:
    """Проект ли это: нужны и Assets, и ProjectSettings.

    Одной папки Assets мало — так устроены и обычные папки с картинками.
    """
    path = Path(path)
    return is_project(path, UNITY_PROJECT_MARKER) and (path / "ProjectSettings").is_dir()


def scan_unity_projects(roots=None, max_depth: int = UNITY_SCAN_DEPTH,
                        limit: int = UNITY_SCAN_LIMIT,
                        budget: int = UNITY_SCAN_BUDGET) -> ProjectScan:
    """Проекты Unity под указанными папками: (путь, версия редактора).

    Версия берётся из самого проекта, а не из установленного редактора:
    плагин выбирается под версию проекта — иначе проект на 2022 получит
    пакет от 6000 и не откроется.

    Обход ограничен бюджетом папок: папка «Загрузки» с программами внутри
    обходится минуту с лишним. Если бюджет исчерпан, `truncated` говорит
    об этом прямо — выбрать проект из списка можно, но молчать нельзя.
    """
    if roots is None:
        roots = unity_project_roots()
    scan = ProjectScan()
    for root in (Path(item) for item in roots):
        if not root.is_dir() or len(scan.items) >= limit:
            continue
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack and len(scan.items) < limit:
            current, depth = stack.pop()
            scan.visited += 1
            if scan.visited > budget:
                scan.truncated = True
                break
            try:
                children = sorted(item for item in current.iterdir() if item.is_dir())
            except OSError:
                continue
            for child in children:
                if child.name in UNITY_SCAN_SKIP or child.name.startswith("."):
                    continue
                if is_unity_project(child):
                    scan.items.append((child, unity_project_version(child)))
                    continue  # внутри проекта других проектов не бывает
                if depth < max_depth:
                    stack.append((child, depth + 1))
        if scan.truncated:
            break
    scan.items.sort(key=lambda pair: str(pair[0]).lower())
    return scan


def unity_package_state(project: Path, package: str = UNITY_PACKAGE) -> tuple[bool, str]:
    """Пакет в проекте или нет. Смотрим и lock-файл, и кэш распакованного."""
    project = Path(project)
    if not is_project(project, UNITY_PROJECT_MARKER):
        return False, (f"{project} не похож на проект Unity: нет папки Assets. "
                       f"Укажи папку проекта — ту, где лежит Assets")
    lock = project / "Packages" / "packages-lock.json"
    if lock.is_file():
        text = lock.read_text(encoding="utf-8", errors="replace")
        if f'"{package}"' in text:
            return True, f"пакет {package} есть в packages-lock.json"
    cache = project / "Library" / "PackageCache"
    if cache.is_dir():
        for item in cache.iterdir():
            if item.name.startswith(package.split("/")[-1].replace(".", "_")[:12]):
                return True, f"пакет распакован в Library/PackageCache ({item.name})"
    return False, (f"в проекте нет пакета {package}. До добавления мост подняться "
                   f"не над чем: серверу не к чему подключаться")


def install_unity_package(project: Path, plugin: plugin_index.Plugin,
                          progress=None) -> tuple[bool, str]:
    """Прописать пакет в `Packages/manifest.json` с бэкапом и откатом.

    Файл принадлежит Unity, и открытый редактор перезапишет его при выходе.
    Поэтому сначала проверяется, что редактор закрыт: иначе наша правка
    исчезнет без единого слова.
    """
    project = Path(project)
    manifest = project / "Packages" / "manifest.json"
    if not manifest.is_file():
        return False, f"в проекте нет {manifest} — это не проект Unity"
    if process_running("Unity.exe"):
        return False, ("редактор Unity открыт и перезапишет manifest.json при "
                       "выходе. Закрой проект в редакторе и повтори")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, f"manifest.json не читается ({exc}) — ничего не меняю"
    deps = data.get("dependencies")
    if not isinstance(deps, dict):
        return False, "в manifest.json нет раздела dependencies — не правлю"
    package = plugin.manifest_entry or UNITY_PACKAGE
    if deps.get(package):
        return False, (f"пакет {package} уже прописан ({deps[package]}). "
                       f"Обновить версию можно вручную в Unity")
    backup = manifest.with_suffix(".json.opencode-base.bak")
    try:
        backup.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError as exc:
        return False, f"не смогла сделать копию manifest.json: {exc}"
    deps[package] = plugin.url
    ordered = {"dependencies": deps}
    for key, value in data.items():
        if key != "dependencies":
            ordered[key] = value
    if progress is not None:
        progress(f"добавляю {package} в manifest.json (копия: {backup.name})")
    temp = manifest.with_suffix(".json.opencode-base.tmp")
    try:
        temp.write_text(json.dumps(ordered, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, manifest)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        try:
            manifest.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
        return False, f"записать manifest.json не вышло ({exc}); вернула исходный"
    return True, (f"пакет {package} прописан в manifest.json. Скачает и применит "
                  f"его сам редактор при следующем открытии проекта")


# --------------------------------------------------------------------------
# Unreal Engine
# --------------------------------------------------------------------------

UNREAL_ROOTS = (r"C:\Program Files\Epic Games", r"C:\Program Files (x86)\Epic Games")
UNREAL_PROJECT_MARKER = "Content"
UNREAL_PLUGIN_FOLDER = "EngineWire"


def unreal_engines() -> Found:
    """Движки Unreal. Версия — из `Engine/Build/Build.version`, не из имени папки."""
    found = Found(hint="Сам Unreal через winget не ставится: лаунчер "
                       "EpicGames.EpicGamesLauncher ставится, а движок — только "
                       "через него и с входом в аккаунт Epic.")
    for root_text in UNREAL_ROOTS:
        root = Path(root_text)
        found.attempts.append(root_text)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            build = child / "Engine" / "Build" / "Build.version"
            if not child.is_dir() or not child.name.upper().startswith("UE"):
                continue
            if not build.is_file():
                found.attempts.append(f"{child} (нет Engine/Build/Build.version)")
                continue
            version = unreal_version(child)
            if not version:
                continue
            if not found.ok or versions.version_tuple(version) > versions.version_tuple(found.version):
                found.path = child
                found.version = version
    return found


def unreal_version(engine_dir: Path) -> str:
    """«5.7.1» из Build.version. Файл-источник надёжнее свойств exe."""
    build = Path(engine_dir) / "Engine" / "Build" / "Build.version"
    if not build.is_file():
        return ""
    try:
        data = json.loads(build.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return ""
    parts = [str(data.get(key) or "") for key in
             ("MajorVersion", "MinorVersion", "PatchVersion")]
    numbers = [p for p in parts if p != ""]
    return ".".join(numbers)


def enginewire_state(project: Path) -> tuple[bool, str]:
    """Плагин EngineWire в проекте или нет, и какой он версии."""
    project = Path(project)
    uplugin = project / "Plugins" / UNREAL_PLUGIN_FOLDER / "EngineWire.uplugin"
    if not uplugin.is_file():
        return False, (f"в {project} нет Plugins/{UNREAL_PLUGIN_FOLDER}. "
                       f"Серверу не к чему подключаться: плагин EngineWire "
                       f"не установлен")
    version = ""
    engine = ""
    try:
        data = json.loads(uplugin.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if isinstance(data, dict):
        version = str(data.get("Version") or data.get("VersionName") or "")
        engine = str(data.get("EngineVersion") or "")
    return True, (f"плагин EngineWire на месте"
                  + (f", версия {version}" if version else "")
                  + (f", проверен на движке {engine}" if engine else ""))


def enginewire_pair(engine_version: str) -> tuple[bool, str]:
    """Совпадают ли версии плагина и сервера для этого движка Unreal.

    Это ровно тот случай, который выглядит как «мост сломан», хотя сломан
    не мост: сервер и плагин из разных релизов, и Unreal отвечает на
    каждый вызов `versionMismatch`. Проверяется до установки и до записи
    моста в настройки — включать то, что упадёт, нельзя.
    """
    plugin, why = plugin_index.pick_for("enginewire", engine_version)
    if plugin is None:
        return False, why
    same, note = plugin_index.server_matches(plugin)
    if not same:
        return False, note
    return True, note



#: Кому какое семейство указателей. Ключ — `finder` в реестре: по нему
#: программа знает, какой указатель читать для этого моста.
FAMILY_BY_FINDER = {
    "unity": "unity-mcp",
    "unreal": "enginewire",
    "godot": "godot-ai",
    "ghidra-mcp": "ghidra-mcp",
}
#: Мосты, у которых указателя нет по существу, а не по недосмотру: плагин
#: ставится руками (OBS, Blender) или сервер встроенный (Roblox). Их версии
#: сверять не по чему, и называть это проблемой было бы враньём.
NO_POINTER_FINDERS = ("obs", "blender-addon", "roblox")


def family_for(finder: str) -> str:
    """Семейство указателя по имени моста. Пусто — указателя нет."""
    return FAMILY_BY_FINDER.get(str(finder or "").strip().lower(), "")


def without_pointer(finder: str) -> bool:
    """Указателя нет по существу — молчание здесь честно."""
    return str(finder or "").strip().lower() in NO_POINTER_FINDERS


def bridge_versions(finder: str, program_version: str = "") -> tuple[bool, str]:
    """Какие версии сервера и плагина нужны этому мосту — и совпадают ли.

    Пустая версия программы означает «движок, может быть, ещё не измерен»:
    берётся самая свежая полоса указателя, а не выдуманная «9999».
    """
    family = family_for(finder)
    if not family:
        if without_pointer(finder):
            return True, (f"у моста «{finder}» указателя плагинов нет по существу: "
                          f"плагин ставится руками или сервер встроенный, сверять "
                          f"нечего")
        return True, (f"у моста «{finder}» указателя плагинов нет: версии "
                      f"сверять не по чему")
    if program_version:
        plugin, note = plugin_index.family_pair(family, program_version)
    else:
        plugin, note = plugin_index.latest_for(family)
        if plugin is not None:
            same, note2 = plugin_index.server_matches(plugin)
            if not same:
                return False, note2
    if plugin is None:
        return False, note
    return True, (f"{plugin.name} {plugin.version}; сервер "
                  f"{plugin_index.server_package(plugin) or '—'}")


def install_enginewire(project: Path, engine_version: str,
                       progress=None) -> tuple[bool, str]:
    """Скачать плагин под версию движка и разложить в проект."""
    project = Path(project)
    if not is_project(project, UNREAL_PROJECT_MARKER):
        return False, (f"{project} не похож на проект Unreal: нет папки Content")
    plugin, why = plugin_index.family_pair("enginewire", engine_version)
    if plugin is None:
        return False, why
    if progress is not None:
        progress(f"для движка {engine_version} беру плагин {plugin.version}")
    archive, note = plugin_index.obtain(plugin, cache_dir(), progress)
    if archive is None:
        return False, note
    target = project / (plugin.dest or "Plugins")
    where, note2 = plugin_index.extract(plugin, archive, target)
    if where is None:
        return False, note2
    if progress is not None:
        progress(note)
    return True, (f"{note2}. Сервер поднимает сам плагин в редакторе: мост "
                  f"заработает, когда Unreal открыт с этим плагином")


# --------------------------------------------------------------------------
# Godot
# --------------------------------------------------------------------------

GODOT_NAMES = ("Godot.exe", "Godot_v4*.exe", "Godot_v3*.exe")
GODOT_PROJECT_MARKER = "addons"
GODOT_ADDON = Path("addons") / "godot_ai"


def godot_editor() -> Found:
    """Редактор Godot: где стоит и какая у него версия.

    Версию спрашиваем у самого редактора (`--version`) — она точнее имени
    файла, и это единственный способ, который одинаково работает и для
    обычной установки, и для переносимой.
    """
    found = Found(hint="Ставится через winget: GodotEngine.GodotEngine. "
                       "Godot AI v4 требует редактор 4.7 или новее.")
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
             Path(os.environ.get("USERPROFILE", "")) / "Downloads"]
    seen: list[Path] = []
    for root in roots:
        if not root or not root.is_dir():
            continue
        found.attempts.append(str(root))
        try:
            items = sorted(root.iterdir())
        except OSError:
            continue
        for item in items:
            if item.is_dir() and item.name.lower().startswith("godot"):
                found.attempts.append(str(item))
                for pattern in GODOT_NAMES:
                    for exe in item.glob(pattern):
                        seen.append(exe)
                    if item.match(pattern):
                        seen.append(item)
            elif item.is_file() and item.name.lower().startswith("godot") and item.suffix == ".exe":
                seen.append(item)
    for exe in seen:
        code, out = run_capture([str(exe), "--version"], timeout=40)
        text = (out or "").strip().splitlines()
        version = text[0].strip() if code == 0 and text else ""
        if not version:
            version = file_version(exe)
        if not version:
            continue
        if not found.ok or versions.version_tuple(version) > versions.version_tuple(found.version):
            found.path = exe
            found.version = version
    return found


def godot_addon_state(project: Path) -> tuple[bool, str]:
    """Аддон Godot AI в проекте или нет."""
    project = Path(project)
    marker = project / GODOT_ADDON / "plugin.cfg"
    if marker.is_file():
        return True, f"аддон Godot AI на месте: {marker}"
    if not (project / "project.godot").is_file():
        return False, (f"{project} не похож на проект Godot: нет файла "
                       f"project.godot")
    return False, ("в проекте нет addons/godot_ai. Плагин лежит только внутри "
                   "проекта — глобальной папки аддонов у Godot нет")


def install_godot_addon(project: Path, godot_version: str,
                        progress=None) -> tuple[bool, str]:
    """Скачать аддон под версию редактора и распаковать в корень проекта."""
    project = Path(project)
    if not (project / "project.godot").is_file():
        return False, f"в {project} нет project.godot — это не проект Godot"
    plugin, why = plugin_index.family_pair("godot-ai", godot_version)
    if plugin is None:
        return False, why
    if plugin.file != "godot-ai-v4-plugin.zip":
        return False, (f"указатель назвал файл {plugin.file}, а ставить можно "
                       f"только godot-ai-v4-plugin.zip — это другой релиз")
    if progress is not None:
        progress(f"для Godot {godot_version} беру аддон {plugin.version}")
    archive, note = plugin_index.obtain(plugin, cache_dir(), progress)
    if archive is None:
        return False, note
    where, note2 = plugin_index.extract(plugin, archive, project)
    if where is None:
        return False, note2
    if progress is not None:
        progress(note)
    return True, (note2 + ". Включи аддон в Godot: Project → Project Settings "
                  "→ Plugins → Godot AI")


# --------------------------------------------------------------------------
# Ghidra
# --------------------------------------------------------------------------

GHIDRA_EXTENSION_CLASS = "com.xebyte.GhidraMCPPlugin"
GHIDRA_EXTENSION_NAME = "GhidraMCP"


def ghidra_install() -> Path | None:
    """Папка установки Гидры. Поиск тот же, что у программы, — не второй."""
    try:
        import env_setup  # тяжёлый модуль, нужен в одном месте
    except ImportError:
        return None
    return env_setup.find_ghidra()


def ghidra_version(install: Path | None = None) -> str:
    """Версия Гидры из её же `application.properties`."""
    install = Path(install) if install else ghidra_install()
    if not install:
        return ""
    props = Path(install) / "Ghidra" / "application.properties"
    if not props.is_file():
        return ""
    for line in props.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("application.version"):
            return line.split("=", 1)[-1].strip()
    return ""


def ghidra_profile(install: Path) -> Path:
    """Папка профиля Гидры — там её список включённых расширений."""
    version = ghidra_version(install)
    name = f"ghidra_{version}_PUBLIC" if version else ""
    root = Path(os.environ.get("APPDATA", "")) / "ghidra"
    return root / name if name else root


def ghidra_extension_state(install: Path | None = None) -> tuple[bool, str]:
    """Расширение скачано (zip в Extensions) и/или распаковано Гидрой."""
    install = Path(install) if install else ghidra_install()
    if not install:
        return False, ("Гидра не найдена. Поставь её и запусти программу заново — "
                       "без неё расширение ставить некуда")
    version = ghidra_version(install)
    profile = ghidra_profile(install)
    unpacked = profile / "Extensions" / GHIDRA_EXTENSION_NAME
    if unpacked.is_dir():
        enabled = _ghidra_extension_enabled(profile)
        if enabled:
            return True, (f"расширение {GHIDRA_EXTENSION_NAME} установлено и "
                           f"включено (Гидра {version or '?'})")
        return False, (f"расширение лежит в профиле, но не включено. "
                       f"Включение — галочка в Front-End: File → Configure → "
                       f"Utility → {GHIDRA_EXTENSION_CLASS.rsplit('.', 1)[-1]}. "
                       f"Могу включить сама и сохранить файл, если скажешь")
    zips = sorted((install / "Extensions" / "Ghidra").glob("GhidraMCP-*.zip"))
    if zips:
        return False, (f"архив расширения уже скачан ({zips[-1].name}), но Гидра "
                       f"ещё не распаковала его — она делает это при следующем "
                       f"запуске. После распаковки включи расширение")
    return False, (f"в Гидре {version or '?'} расширения {GHIDRA_EXTENSION_NAME} "
                   f"нет. Расширение приходит с меткой своей версии Гидры — "
                   f"под другую оно не загрузится")


def _ghidra_extension_enabled(profile: Path) -> bool:
    """Включено ли расширение в файле настроек Гидры."""
    front = Path(profile) / "FrontEndTool.xml"
    if not front.is_file():
        return False
    return GHIDRA_EXTENSION_CLASS in front.read_text(encoding="utf-8", errors="replace")


def enable_ghidra_extension(install: Path | None = None) -> tuple[bool, str]:
    """Включить расширение в файле настроек Гидры, с копией файла.

    Гидра переписывает `FrontEndTool.xml` при выходе, поэтому: копия файла,
    отказ при работающей Гидре и проверка результата. Иначе человек включил
    бы плагин, а через минуту он бы тихо выключился сам.
    """
    install = Path(install) if install else ghidra_install()
    if not install:
        return False, "Гидра не найдена — включать нечего"
    profile = ghidra_profile(install)
    front = profile / "FrontEndTool.xml"
    if not front.is_file():
        return False, (f"не найден {front}. Значит расширение ещё ни разу не "
                       f"запускалось: сначала поставь его и открой Гидру")
    if process_running("ghidraRun.bat") or process_running("javaw.exe"):
        if _ghidra_extension_enabled(profile):
            return False, "расширение уже включено"
        return False, ("Гидра сейчас открыта и перезапишет файл настроек при "
                       "выходе. Закрой её и повтори")
    text = front.read_text(encoding="utf-8", errors="replace")
    if GHIDRA_EXTENSION_CLASS in text:
        return True, "расширение уже включено в настройках Гидры"
    backup = front.with_suffix(".xml.opencode-base.bak")
    try:
        shutil.copy2(front, backup)
    except OSError as exc:
        return False, f"не смогла сделать копию FrontEndTool.xml: {exc}"
    block = (f'<PACKAGE NAME="{GHIDRA_EXTENSION_NAME}">'
             f'<INCLUDE CLASS="{GHIDRA_EXTENSION_CLASS}"/></PACKAGE>')
    closing = "</TOOL>"
    if closing not in text:
        return False, (f"в {front.name} не найден закрывающий </TOOL> — "
                       f"структура файла не та, оставляю как есть")
    patched = text.replace(closing, f"  {block}\n{closing}", 1)
    try:
        front.write_text(patched, encoding="utf-8")
    except OSError as exc:
        try:
            shutil.copy2(backup, front)
        except OSError:
            pass
        return False, f"записать FrontEndTool.xml не вышло ({exc}); вернула исходный"
    if GHIDRA_EXTENSION_CLASS not in front.read_text(encoding="utf-8", errors="replace"):
        shutil.copy2(backup, front)
        return False, "правка не подтвердилась после записи — вернула исходный файл"
    return True, (f"расширение включено в {front.name} (копия: {backup.name}). "
                  f"При выходе из Гидры скажи сохранить настройки, иначе она "
                  f"перепишет файл и выключит плагин")


def install_ghidra_extension(engine_version: str, install: Path | None = None,
                             progress=None) -> tuple[bool, str]:
    """Скачать расширение под версию Гидры и положить в Extensions."""
    install = Path(install) if install else ghidra_install()
    if not install:
        return False, "Гидра не найдена — качать некуда"
    plugin, why = plugin_index.family_pair("ghidra-mcp", engine_version)
    if plugin is None:
        return False, why
    if progress is not None:
        progress(f"для Гидры {engine_version} беру {plugin.version}")
    archive, note = plugin_index.obtain(plugin, cache_dir(), progress)
    if archive is None:
        return False, note
    target = install / (plugin.dest or "Extensions/Ghidra")
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(archive, target / plugin.file)
    except OSError as exc:
        return False, f"положить архив в {target} не вышло: {exc}"
    if progress is not None:
        progress(note)
    return True, (f"расширение {plugin.file} лежит в {target}. Гидра распакует его "
                  f"при следующем запуске; после этого включи его в Front-End "
                  f"или скажи «включи» — включу сама")


# --------------------------------------------------------------------------
# Roblox Studio
# --------------------------------------------------------------------------

def roblox_studio() -> Found:
    """Roblox Studio: где стоит и какая версия.

    Сборки лежат в папках с именами `version-11f155f3450f4c8e`, поэтому
    версия снимается со свойств файла, а не из имени папки.
    """
    found = Found(hint="Ставится через winget: Roblox.RobloxStudio. Установщик "
                       "официальный, ключа тихой установки у него нет.")
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return found
    roots = [Path(local) / "Roblox" / "Versions",
             Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
             / "Roblox" / "Versions"]
    for root in roots:
        found.attempts.append(str(root))
        if not root.is_dir():
            continue
        for item in sorted(root.iterdir()):
            exe = item / "RobloxStudioBeta.exe"
            if not exe.is_file():
                continue
            version = file_version(exe)
            if not version:
                continue
            if not found.ok or versions.version_tuple(version) > versions.version_tuple(found.version):
                found.path = exe
                found.version = version
    return found


def roblox_app_state() -> tuple[bool, str]:
    """Установлена ли Roblox Studio — без разбора, включён сервер или нет.

    Отдельная проверка от `roblox_mcp_state` намеренно: «студия стоит» и
    «сервер в ней включён» — разные вещи. Когда обе были одной строкой,
    программа писала «проверяется вручную» про студию, даже когда она
    стояла, и человек думал, что настройка не сработала.
    """
    studio = roblox_studio()
    if studio.ok:
        return True, f"Roblox Studio {studio.version} на месте ({studio.path})"
    return False, (studio.why("Roblox Studio") + " Ставится через winget, "
                   "идентификатор Roblox.RobloxStudio — официальный установщик, "
                   "тихой установки у него нет, нужно нажать Install в окне")


def roblox_mcp_state() -> tuple[bool, str]:
    """Включён ли встроенный сервер Roblox.

    Проверяется файл, который создаёт сама студия. Плагина у Roblox нет
    вообще: сервер встроенный, и включается он только в окне студии —
    Roblox не документирует способа включить его без окна.
    """
    local = os.environ.get("LOCALAPPDATA", "")
    bat = Path(local) / "Roblox" / "mcp.bat" if local else None
    studio = roblox_studio()
    if not studio.ok:
        return False, (
            "Roblox Studio не установлена, включать нечего. Ставится через winget, "
            "идентификатор Roblox.RobloxStudio. Плагина у Roblox нет: сервер "
            "встроенный, и включается он только в окне студии")
    if bat is not None and bat.is_file():
        return True, (f"встроенный сервер включён, файл {bat.name} на месте "
                      f"(студия {studio.version})")
    return False, (f"студия {studio.version} стоит, но файл mcp.bat не появился — "
                   f"сервер выключен. Включается только в окне студии: "
                   f"Assistant → … → Manage MCP Servers → Enable Studio as MCP "
                   f"server. Плагина у Roblox нет, сервер встроенный")


# --------------------------------------------------------------------------
# мост с интерфейсом программы: три ответа и поставить
# --------------------------------------------------------------------------

UNITY_PROJECT_FILE = "mcp-unity-project.txt"
GODOT_PROJECT_FILE = "mcp-godot-project.txt"
UNREAL_PROJECT_FILE = "mcp-unreal.txt"
# Рядом с настройками opencode, не в проекте Unreal: версия сервера — дело
# моста, а не проекта, и лаунчер читает её отсюда.


def settings_dir() -> Path:
    """Папка настроек opencode. Та же, что у лаунчеров."""
    try:
        import bridge_common as common  # noqa: PLC0415 — нужен в одном месте

        return common.settings_dir()
    except (ImportError, AttributeError):
        return Path(os.environ.get("APPDATA", "")) / "opencode"


def project_from_file(name: str) -> Path | None:
    """Папка проекта из файла рядом с настройками.

    Файл кладёт сам человек или окно настройки. Без него ставить плагин
    некуда, и это говорится прямо: «укажи проект», а не «плагина нет».
    """
    path = settings_dir() / name
    if not path.is_file():
        return None
    raw = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if "=" in text:
            key, _, value = text.partition("=")
            if key.strip().lower() in ("project", "проект"):
                raw = value.strip().strip('"')
                break
        raw = text.strip('"')
        break
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.suffix.lower() == ".uproject":
        candidate = candidate.parent
    return candidate if candidate.is_dir() else None


def _no_project(file_name: str, marker: str) -> tuple[bool, bool, str]:
    return False, False, (f"не указан проект. Создай рядом с настройками файл "
                          f"{file_name} с одной строкой — папкой проекта "
                          f"(узнаётся по папке {marker}); «Настроить автоматически» "
                          f"спросит и запишет его сам")


def unity_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """Пакет MCP for Unity в проекте. Плагин лежит в проекте, а не в редакторе.

    `use_fallback` принимается ради единой подписи обработчиков плагинов: у
    OBS и Blender он означает запасную папку, а у редакторов запасной папки
    нет — игнорируется. Подпись одна, чтобы карточка не разбиралась, кому
    какой вызов достался.
    """
    project = project_from_file(UNITY_PROJECT_FILE)
    if project is None:
        return _no_project(UNITY_PROJECT_FILE, UNITY_PROJECT_MARKER)
    present, note = unity_package_state(project)
    return present, not present, note


def unity_fetch(progress=None) -> tuple[bool, str]:
    """Прописать пакет в проект по измеренной версии редактора."""
    project = project_from_file(UNITY_PROJECT_FILE)
    if project is None:
        return False, _no_project(UNITY_PROJECT_FILE, UNITY_PROJECT_MARKER)[2]
    editors = unity_editors()
    if not editors.ok:
        return False, editors.why("Unity")
    version = unity_project_version(project) or editors.version
    plugin, why = plugin_index.family_pair("unity-mcp", version)
    if plugin is None:
        return False, why
    return install_unity_package(project, plugin, progress)



#: Признаки ответа настоящего MCP-сервера: код 4xx/5xx либо тело с полем
#: error или заголовком сессии. Ровно это отличает сервер плагина от любой
#: другой программы, которая заняла порт.
MCP_MARKERS = ("jsonrpc", "\"error\"", "mcp-session-id", "streamable")
UNREAL_EDITOR_IMAGES = ("UnrealEditor.exe", "UE4Editor.exe")


def _probe_http(url: str, timeout: float = 3.0):
    """Спросить адрес один раз. Нет ответа — None, а не «ошибка 0»."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "opencode-base/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(2048).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — тело не обязано читаться
            body = ""
        return exc.code, body
    except Exception:  # noqa: BLE001 — сеть может отказать по-разному
        return None


def unreal_http_state(port: int, editor_running=None, timeout: float = 3.0) -> tuple[bool, str]:
    """Отвечает ли сервер в плагине — и почему нет, если не отвечает.

    Четыре разные причины и четыре разных ответа: одна общая ошибка не
    говорит человеку ничего.

    * редактор не открыт — мост отвечать не может в принципе;
    * редактор открыт, порт молчит — плагин не включён или порт другой;
    * порт отвечает, но не MCP — заняла другая программа;
    * отвечает MCP — адрес можно вписывать в настройки.

    Параметр `editor_running` передаётся только в проверках: по умолчанию
    смотрится настоящий процесс редактора.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, f"порт «{port}» — не число"
    if not 1 <= port <= 65535:
        return False, f"порт {port} — за пределами 1…65535"
    running = (process_running_any(UNREAL_EDITOR_IMAGES)
               if editor_running is None else bool(editor_running))
    answer = _probe_http(f"http://127.0.0.1:{port}/mcp", timeout)
    if answer is None:
        if not running:
            return False, ("Unreal не открыт — мост отвечает, только пока "
                           "запущен редактор с плагином EngineWire. "
                           "Открой проект и повтори")
        return False, (f"редактор открыт, но на порту {port} никто не слушает: "
                       f"либо плагин не включён, либо в его настройках другой "
                       f"порт (по документации автора — {UNREAL_PORT_DEFAULT}, "
                       f"на этой машине не проверено)")
    code, body = answer
    low = (body or "").lower()
    if code >= 400 or any(marker in low for marker in MCP_MARKERS):
        return True, (f"сервер плагина отвечает на 127.0.0.1:{port}/mcp "
                      f"(код {code}). Мост можно вписывать; работать он будет, "
                      f"пока открыт редактор")
    return False, (f"порт {port} занят другой программой: отвечает код {code}, "
                   f"и это не MCP-сервер. Освободи порт или укажи в настройках "
                   f"плагина другой")


def unreal_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """Плагин EngineWire в проекте Unreal и отвечает ли его сервер.

    Отдельной версии сервера больше нет: в линии 0.6 он живёт внутри
    плагина, и проверять надо не две строки, а живой ответ по адресу.
    """
    project = project_from_file(UNREAL_PROJECT_FILE)
    if project is None:
        return _no_project(UNREAL_PROJECT_FILE, UNREAL_PROJECT_MARKER)
    present, note = enginewire_state(project)
    if present:
        engines = unreal_engines()
        if engines.ok:
            same, note_same = enginewire_pair(engines.version)
            if not same:
                # Плагин лежит, но из другого релиза: кнопка поставит тот,
                # который задуман. Молчать об этом нельзя.
                return True, True, (f"{note}. {note_same}. Кнопка поставит "
                                    f"версию, которая совпадает с указателем")
        from engine_setup import read_unreal_port  # noqa: PLC0415 — настройки рядом

        port = read_unreal_port(settings_dir())
        live, live_note = unreal_http_state(port)
        if not live:
            # Плагин на месте, а сервер молчит: причину называем, кнопка
            # остаётся рабочей — человек может починить и повторить.
            return True, True, f"{note}. {live_note}"
        return True, False, f"{note}. {live_note}"
    return present, not present, note


def unreal_fetch(progress=None) -> tuple[bool, str]:
    """Скачать плагин под версию установленного движка и разложить в проект."""
    project = project_from_file(UNREAL_PROJECT_FILE)
    if project is None:
        return False, _no_project(UNREAL_PROJECT_FILE, UNREAL_PROJECT_MARKER)[2]
    engines = unreal_engines()
    if not engines.ok:
        return False, (engines.why("Unreal Engine")
                       + " Версию движка снять не с чему — плагин подбирается "
                         "именно по ней")
    return install_enginewire(project, engines.version, progress)


def godot_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """Аддон Godot AI в проекте."""
    project = project_from_file(GODOT_PROJECT_FILE)
    if project is None:
        return _no_project(GODOT_PROJECT_FILE, "project.godot")
    present, note = godot_addon_state(project)
    return present, not present, note


def godot_fetch(progress=None) -> tuple[bool, str]:
    """Скачать аддон под версию редактора и распаковать в проект."""
    project = project_from_file(GODOT_PROJECT_FILE)
    if project is None:
        return False, _no_project(GODOT_PROJECT_FILE, "project.godot")[2]
    editor = godot_editor()
    if not editor.ok:
        return False, editor.why("Godot")
    return install_godot_addon(project, editor.version, progress)


def ghidra_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """Расширение GhidraMCP: положено, включено и соответствует версии."""
    present, note = ghidra_extension_state()
    return present, not present, note


def ghidra_fetch(progress=None) -> tuple[bool, str]:
    """Скачать расширение под версию Гидры и включить его в профиле."""
    install = ghidra_install()
    version = ghidra_version(install) if install else ""
    if not version:
        return False, ghidra_extension_state()[2]
    ok, note = install_ghidra_extension(version, install, progress)
    if not ok:
        return False, note
    enabled, note2 = enable_ghidra_extension(install)
    return enabled, note2 if enabled else note + " " + note2


#: Кому какой обработчик плагина. Ключ — короткое имя программы, как его
#: называет карточка; проверки требований в реестре используют другое
#: пространство имён (имя плагина), и это разные словари намеренно.
HANDLERS = {
    "unity": (unity_state, unity_fetch),
    "unreal": (unreal_state, unreal_fetch),
    "godot": (godot_state, godot_fetch),
    "ghidra-mcp": (ghidra_state, ghidra_fetch),
}


def roblox_state(use_fallback: bool = False) -> tuple[bool, bool, str]:
    """У Roblox плагина нет: сервер встроенный и включается в окне студии."""
    present, note = roblox_mcp_state()
    return present, False, note


def auto_setup(server_id: str, progress=None) -> tuple[bool, str]:
    """«Настроить автоматически» для моста с плагином: измерить и поставить.

    Порядок один для всех: сперва состояние (имя файла проекта уже записан
    окном), затем установка. Отказ возвращается как отказ, а не бросается
    исключением: окно должно показать текст, а не упасть.
    """
    handler = HANDLERS.get(str(server_id))
    if handler is None:
        return False, (f"у моста «{server_id}» плагина нет — автоматическая "
                       f"установка не предусмотрена")
    state, fetch = handler
    present, can_write, note = state()
    if present:
        return True, note
    if not can_write:
        return False, note
    if progress is not None:
        progress(f"ставлю плагин: {note}")
    try:
        ok, note2 = fetch(progress=progress)
    except Exception as exc:  # noqa: BLE001 — окну нужен текст, а не traceback
        return False, f"установка прервалась: {exc}"
    return ok, note2