"""Донастройка окружения для мостов: сама проверяет и сама чинит.

Зачем этот модуль. Мост — это не одна программа, а цепочка: интерпретатор,
папка с самим мостом, переменные окружения и иногда настройка чужой
программы. Обычно всё это проверяет человек: поставил JDK, открыл Гидру,
увидел «Java не найдена», дописал JAVA_HOME, перезапустил, и только потом
мост заработал. Ровно это и произошло с ghidra-mcp 16.10.2026: JDK стоял,
а Гидра его не видела — она ищет Java по-своему, через JAVA_HOME_OVERRIDE в
своём launch.properties, и переменная окружения тут не при чём.

Поэтому здесь две вещи, которых не было:

1. **Проверка.** `check(server)` смотрит, что мосту реально нужно, и
   говорит словами, чего не хватает.
2. **Починка.** `prepare(server)` не только проверяет, но и приводит
   окружение в рабочее состояние: прописывает переменные окружения
   постоянно (а не только в своём процессе), добавляет папки в PATH и
   правит настройки чужих программ там, где они ищут Java сами.

Модуль общий: что именно проверять, решает реестр (`env_setup` у сервера),
а не код. Добавить мосту новую зависимость — значит дописать запись в
реестре, а не править этот файл.

Порядок работы `prepare` — «сломай, чтобы проверить, почини, проверь
ещё раз». Иначе легко отчитаться успехом на словах: переменная записана,
а программа, которой она нужна, запущенная раньше, её всё равно не видела.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

WIN = os.name == "nt"

#: Куда класть найденные пути. Не рядом с программой: программа может
#: лежать в папке, которую человек заменит, а пути нужны его машине в
#: целом. Файл маленький и переживает обновление программы.
_CACHE_NAME = "OpenCodeBase/resolved-paths.json"


# --------------------------------------------------------------- отчёт

@dataclass
class EnvReport:
    """Что было не так и что с этим сделали."""

    ok: bool = True
    fixed: list[str] = field(default_factory=list)
    already_ok: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def line(self, what: str) -> str:
        if what in self.failed:
            return f"не настроено: {what}"
        if what in self.fixed:
            return f"настроил сам: {what}"
        return f"уже было готово: {what}"

    def lines(self) -> list[str]:
        return ([f"настроил сам: {t}" for t in self.fixed]
                + [f"уже было готово: {t}" for t in self.already_ok]
                + [f"не настроено: {t}" for t in self.failed])

    def as_text(self) -> str:
        rows = self.lines()
        return "\n".join(rows) if rows else "ничего настраивать не пришлось"


# ------------------------------------------------- переменные окружения

def _broadcast_env_change() -> None:
    """Сообщить запущенным программам, что окружение изменилось.

    Без этого переменная записана, а уже открытые окна её не видят: они
    получили своё окружение при старте. Именно на этом people спотыкаются
    — «прописал, а Гидра не видит».
    """
    if not WIN:
        return
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x1A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        # lParam = строка "Environment" в кодировке Unicode.
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0,
            ctypes.c_wchar_p("Environment"),
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
        )
    except Exception:
        # Не сработало — не повод срывать установку: переменная всё равно
        # записана, окна подхватят её при следующем старте.
        pass


def env_persist_get(name: str) -> str:
    """Значение переменной окружения, записанное постоянно.

    Сначала пользовательская, потом общесистемная: так же, как их видит
    новая программа, запущенная из меню «Пуск».
    """
    if WIN:
        try:
            import winreg

            for hive, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                              (winreg.HKEY_LOCAL_MACHINE,
                               r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        value, _ = winreg.QueryValueEx(handle, name)
                        if value:
                            return str(value)
                except OSError:
                    continue
        except ImportError:
            pass
    return os.environ.get(name, "")


def env_persist_set(name: str, value: str, scope: str = "user") -> bool:
    """Записать переменную окружения постоянно. True — изменилось.

    Пишем в пользовательскую область всегда, когда не сказано иное:
    права администратора у программы нет, а общесистемная запись молча
    требует повышения и выглядит как «ничего не произошло».
    """
    if not WIN:
        os.environ[name] = value
        return True
    try:
        import winreg

        if scope == "machine":
            hive = winreg.HKEY_LOCAL_MACHINE
            key = (r"SYSTEM\CurrentControlSet\Control\Session Manager"
                   r"\Environment")
            flags = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        else:
            hive = winreg.HKEY_CURRENT_USER
            key = "Environment"
            flags = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        with winreg.CreateKeyEx(hive, key, 0, flags) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    except OSError as exc:
        raise OSError(f"не записать переменную {name}: {exc}") from exc
    # Сразу и в этом процессе: иначе только что настроенное не увидят
    # программы, которые программа запустит раньше, чем перезапустится
    # сама.
    os.environ[name] = value
    _broadcast_env_change()
    return True


def _clean_path_value(value: str) -> str:
    """Убрать хвостовой обратный слэш у пути — но не у корня диска.

    `JAVA_HOME` на этой машине заканчивался на обратном слэше, и Гидра
    потом склеивала его со своим путём к java.exe. Windows такое терпит,
    а половина сторонних разборщиков — нет. Укороченный вид работает
    везде одинаково.
    """
    text = str(value or "").strip().strip('"')
    if len(text) > 3 and text[-1] in "\\/":
        return text[:-1]
    return text


def ensure_env_var(name: str, desired: str) -> tuple[bool, str]:
    """Прописать переменную окружения, если её нет или она другая.

    Возвращает (изменилось ли, что в итоге).
    """
    current = env_persist_get(name).strip().strip('"')
    wanted = desired.strip().strip('"')
    # Хвостовой обратный слэш в JAVA_HOME — известная беда: часть
    # программ склеивает с ним путь и получает «...jdk-21\\bin\\java.exe».
    # Считаем это тем же самым и молча приводим к правильному виду.
    if current.rstrip("\\/") == wanted.rstrip("\\/"):
        if current != wanted:
            env_persist_set(name, wanted)
            return True, f"{name} = {wanted} (убрал лишний обратный слэш)"
        return False, f"{name} = {current}"
    env_persist_set(name, wanted)
    return True, f"{name} = {wanted}"


# ----------------------------------------------------------------- PATH

def ensure_path_entry(folder: str) -> tuple[bool, str]:
    """Добавить папку в PATH пользователя, если её там нет."""
    folder = str(folder).rstrip("\\/")
    if not folder:
        return False, "пустая папка"
    current = env_persist_get("PATH")
    parts = [p.strip().strip('"').rstrip("\\/").lower()
             for p in current.split(";") if p.strip()]
    if folder.lower() in parts:
        return False, folder
    new_value = current.rstrip(";") + ";" + folder
    env_persist_set("PATH", new_value)
    return True, f"PATH += {folder}"


# ------------------------------------------------------------------ JDK

_JAVA_MAJOR = re.compile(r'version\s+"(\d+)', re.IGNORECASE)


def java_major(java_exe: Path) -> int:
    """Главная версия Java по её собственному ответу, а не по имени папки."""
    try:
        res = subprocess.run([str(java_exe), "-version"], capture_output=True,
                             text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return 0
    blob = (res.stderr or "") + (res.stdout or "")
    match = _JAVA_MAJOR.search(blob)
    return int(match.group(1)) if match else 0


def _jdk_home_ok(home: Path, min_major: int) -> bool:
    java = home / "bin" / ("java.exe" if WIN else "java")
    return java.is_file() and java_major(java) >= min_major


def _registry_jdks() -> list[Path]:
    """JDK, о которых знает реестр Windows. Быстрее и надёжнее обхода диска."""
    found: list[Path] = []
    if not WIN:
        return found
    try:
        import winreg
    except ImportError:
        return found
    places = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JDK"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium\JDK"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\JavaSoft\JDK"),
    ]
    for hive, path in places:
        try:
            with winreg.OpenKey(hive, path) as handle:
                count = winreg.QueryInfoKey(handle)[0]
                for index in range(count):
                    name = winreg.EnumKey(handle, index)
                    if not name.replace(".", "").isdigit():
                        continue
                    with winreg.OpenKey(handle, name) as sub:
                        try:
                            home = winreg.QueryValueEx(sub, "JavaHome")[0]
                        except OSError:
                            home = str(Path(path) / name)
                    found.append(Path(str(home)))
        except OSError:
            continue
    return found


def find_jdk(min_major: int = 21) -> tuple[Path | None, str]:
    """Найти установленный JDK подходящей версии.

    Порядок предсказуемый: переменная окружения, потом реестр Windows, потом
    обычные папки. Реестр важнее обхода: он отвечает на вопрос «где
    поставили», а папки — на «что вообще лежит на диске».
    """
    tried: list[str] = []

    from_env = env_persist_get("JAVA_HOME").strip().strip('"')
    if from_env:
        home = Path(from_env)
        tried.append(f"JAVA_HOME={from_env}")
        if _jdk_home_ok(home, min_major):
            return home, f"JAVA_HOME → {home}"

    for home in _registry_jdks():
        tried.append(f"реестр → {home}")
        if _jdk_home_ok(home, min_major):
            return home, f"реестр Windows → {home}"

    patterns = [
        r"C:\Program Files\Eclipse Adoptium\jdk-*",
        r"C:\Program Files\Java\jdk-*",
        r"C:\Program Files\Microsoft\jdk-*",
        r"C:\Program Files\Amazon Corretto\*",
        r"C:\Program Files\Zulu\*",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Eclipse Adoptium" / "jdk-*"),
    ]
    for pattern in patterns:
        root = Path(pattern).anchor or Path(pattern)
        try:
            candidates = sorted(root.glob(Path(pattern).name))
        except (OSError, ValueError):
            continue
        for home in candidates:
            if home.is_dir():
                tried.append(f"папка → {home}")
                if _jdk_home_ok(home, min_major):
                    return home, f"папка → {home}"
    return None, "; ".join(tried[-3:]) if tried else "нигде не нашёл"


# -------------------------------------------------- настройки чужих программ

_PROP_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*=\s*(.*)$")


def read_props(path: Path) -> dict[str, str]:
    """Прочитать файл вида `key=value`, игнорируя комментарии.

    Комментарий бывает и в начале строки, и в конце: `KEY=value  # зачем`.
    Отбрасываем только `#`/`!` после пробела или табуляции — иначе знак
    внутри значения (`C:\\path#1`) разрезал бы его пополам.
    """
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if line.strip().startswith(("#", "!")):
            continue
        match = _PROP_LINE.match(line)
        if match:
            value = re.split(r"\s[#!]", match.group(2), maxsplit=1)[0]
            out[match.group(1)] = value.strip()
    return out


def set_prop(path: Path, key: str, value: str, why: str = "") -> tuple[bool, str]:
    """Записать `key=value` в файл настроек, сохранив комментарии.

    Строку с ключом меняем на месте, а не дописываем вторую: две строки с
    одним именем читаются как «какая из них», и человек гадает, почему
    сменившаяся настройка не подействовала.
    """
    if not path.is_file():
        return False, f"нет файла {path.name}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, f"{path.name} не прочитался: {exc}"

    lines = text.splitlines(keepends=True)
    replaced = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(("#", "!")):
            match = _PROP_LINE.match(line.rstrip("\n"))
            if match and match.group(1) == key:
                ending = "\r\n" if line.endswith("\r\n") else (
                    "\n" if line.endswith("\n") else "")
                note = f"  # {why}" if why else ""
                out.append(f"{key}={value}{note}{ending}")
                replaced = True
                continue
        out.append(line)
    if not replaced:
        ending = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"
        out.append(f"{key}={value}{ending}")

    body = "".join(out)
    if body == text:
        return False, f"{path.name}: {key} уже = {value or '(пусто)'}"

    # Перед правкой чужого файла — копия с датой. Файл не наш, версии у
    # него нет, и откатить его иначе нечем.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(path, path.with_name(path.name + f".bak-{stamp}"))
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        return False, f"{path.name} не записался: {exc}"
    return True, f"{path.name}: {key}={value}"


# --------------------------------------------------- поиск программ

def find_tool(names: list[str], hints: list[Path] | None = None) -> str:
    """Найти исполняемый файл: сначала PATH, потом известные папки."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for folder in (hints or []):
        for name in names:
            for candidate in (folder / name, folder / f"{name}.exe",
                              folder / f"{name}.cmd"):
                if candidate.is_file():
                    return str(candidate)
    return ""


def find_ghidra() -> Path | None:
    """Папка установки Гидры — та, где лежит ghidraRun.bat.

    Ищем не «любую папку с названием ghidra», а признак установки: без
    ghidraRun.bat это не Гидра, а чужой каталог с похожим именем.

    Обход ограничен глубиной. Рекурсивный `**/ghidraRun.bat` по папке
    пользователя недопустим: там десятки тысяч файлов, и проверка
    зависимостей, которая должна идти секунды, идёт минутами. Глубины
    трёх-четырёх хватает: установка Гидры — это «Загрузки/Ghidra/...»
    или «Program Files/...», а не произвольная вложенность.
    """
    cache = cache_get("ghidra")
    if cache and (Path(cache) / "ghidraRun.bat").is_file():
        return Path(cache)

    home = Path(os.environ.get("USERPROFILE", "") or str(Path.home()))
    # Порядок — по вероятности, а не по алфавиту. Первым идёт «Загрузки»:
    # именно туда people ставят Гидру, и холодный поиск обязан быть быстрым
    # на обычном компьютере. Обход Program Files вперёд стоил 24 секунды
    # (там десятки тысяч файлов), хотя ответ лежал в первой же папке.
    roots: list[tuple[Path, int]] = [
        (home / "Downloads", 4),
        (home / "Desktop", 4),
        (home / "Documents", 3),
        (home / "Tools", 3),
        (home / "apps", 3),
        (Path("C:/ghidra"), 2),
    ]
    for var, depth in (("ProgramFiles", 2), ("ProgramFiles(x86)", 2),
                       ("LOCALAPPDATA", 2)):
        base = os.environ.get(var)
        if base and Path(base).is_dir():
            roots.append((Path(base), depth))

    for root, depth in roots:
        if not root.is_dir():
            continue
        level = [root]
        for _ in range(depth):
            found_here: list[Path] = []
            next_level: list[Path] = []
            for folder in level:
                try:
                    children = list(folder.iterdir())
                except (OSError, PermissionError):
                    continue
                for child in children:
                    if child.is_dir():
                        next_level.append(child)
                    elif child.name.lower() == "ghidrarun.bat":
                        found_here.append(child)
            if found_here:
                marker = sorted(found_here, key=lambda p: len(str(p)))[0]
                install = marker.parent
                if (install / "Ghidra" / "application.properties").is_file():
                    cache_set("ghidra", str(install))
                    return install
            level = next_level[:60]   # больше осматривать незачем
    return None


# ------------------------------------------------------------- кэш путей

def _cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / _CACHE_NAME


def cache_get(key: str) -> str:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return str(data.get(key, ""))
    except (OSError, ValueError, AttributeError):
        return ""


def cache_set(key: str, value: str) -> None:
    path = _cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------- плейсхолдеры

def find_bridge_dir(name: str) -> Path | None:
    """Папка с самим мостом (например, ghidra-mcp).

    В реестре лежит только имя, потому что абсолютный путь компьютера там
    быть не может. Программа ищет папку сама и запоминает найденное, иначе
    пришлось бы искать заново при каждой проверке.

    Проверка подлинности — по файлам репозитория, а не по имени папки:
    папка `ghidra-mcp` может оказаться чем угодно, и мост, запущенный из
    неё, молча не поднимется.
    """
    cache_key = f"bridge:{name}"
    cached = cache_get(cache_key)
    if cached and _looks_like_bridge(Path(cached)):
        return Path(cached)

    home = Path(os.environ.get("USERPROFILE", "") or str(Path.home()))
    candidates: list[Path] = []
    try:
        from core import program_root  # рядом лежит, но импорт только здесь

        candidates.append(Path(program_root()) / "tools" / "thirdparty" / name)
    except ImportError:
        pass
    candidates += [
        home / name,
        home / "Downloads" / name,
        home / "Downloads" / "repos" / name,
        home / "Documents" / name,
    ]
    for folder in candidates:
        if _looks_like_bridge(folder):
            cache_set(cache_key, str(folder))
            return folder
    return None


def _looks_like_bridge(folder: Path) -> bool:
    """Похоже ли на репозиторий моста."""
    if not folder.is_dir():
        return False
    if (folder / "pyproject.toml").is_file() and (folder / "src").is_dir():
        return True
    # У ghidra-mcp мост лежит в python/, а не в src/ — проверяем оба вида.
    return bool((folder / "pyproject.toml").is_file()
                and (folder / "python").is_dir())


def _localapp_bin_dirs() -> list[Path]:
    """Папки `*\\bin` прямо под %LOCALAPPDATA%, где программы держат uv.

    Перечисление имён не годится: на этой машине uv лежит внутри папки
    сторонней программы, на чужой — внутри другой, а имя той папки знать
    не нужно. Смотрим все сразу и берём ту, где лежит настоящий uv.
    """
    root = os.environ.get("LOCALAPPDATA", "")
    if not root:
        return []
    found: list[Path] = []
    try:
        for child in Path(root).iterdir():
            bin_dir = child / "bin"
            if not bin_dir.is_dir():
                continue
            for name in ("uv.exe", "uv", "uvx.exe", "uvx"):
                if (bin_dir / name).is_file():
                    found.append(bin_dir)
                    break
    except OSError:
        return []
    return found


def resolve_placeholder(token: str) -> str:
    """Значение `{ИМЯ}` для команды запуска.

    В реестре лежат плейсхолдеры, а не пути компьютера: реестр едет в
    публичный репозиторий. Здесь путь ищется на этой машине, причём
    ищется по-настоящему, а не берётся из настроек программы.
    """
    name = token.strip("{}").strip()
    if name == "UV":
        # Пути uv: он ставится и в PATH, и в свою папку, и внутри папок
        # других программ, которые его приносят. Имя такой папки — личное
        # обстоятельство человека, поэтому вместо перечисления имён
        # просматривается %LOCALAPPDATA%: на чужом компьютере сработает
        # любая из них, и ничего моего в коде не останется.
        return find_tool(["uv", "uv.exe"],
                         [Path.home() / ".local" / "bin",
                          Path.home() / ".cargo" / "bin",
                          *_localapp_bin_dirs()])
    if name == "GHIDRA":
        folder = find_ghidra()
        return str(folder) if folder else ""
    if name == "GHIDRA_MCP":
        folder = find_bridge_dir("ghidra-mcp")
        return str(folder) if folder else ""
    if name == "NODE":
        return find_tool(["node", "node.exe"])
    if name == "NPM":
        return find_tool(["npm", "npm.cmd"])
    if name == "GIT":
        return find_tool(["git", "git.exe"])
    return ""


# ----------------------------------------------------------- главный вход

def _placeholder_hint(text: str) -> str:
    """Человеческое имя для нераскрытого плейсхолдера."""
    names = {
        "GHIDRA": "папку установки Гидры",
        "GHIDRA_MCP": "папку с мостом ghidra-mcp",
        "UV": "uv",
        "NODE": "Node.js",
        "NPM": "npm",
        "GIT": "Git",
    }
    found = sorted(set(re.findall(r"\{([A-Z_]+)\}", str(text or ""))))
    if not found:
        return "нужную папку"
    return ", ".join(names.get(name, name) for name in found)


def expand(text: str, progress=None) -> str:
    """Публичная замена `{ИМЯ}` на значение с этой машины.

    Именно её зовёт реестр, когда собирает команду запуска: путь к uv или
    к установке Гидры человек не знает, знать и не должен — выясняет
    программа.
    """
    return _expand(str(text or ""), progress)


def _expand(text: str, progress=None) -> str:
    """Подставить `{ИМЯ}` в текст настройки."""
    def repl(match: re.Match) -> str:
        value = resolve_placeholder(match.group(1))
        if not value and progress:
            progress(f"не нашёл, чем подставить {match.group(0)}")
        # Нераскрытый плейсхолдер оставляем на месте. Раньше он заменялся
        # пустой строкой, и путь «{GHIDRA}/support/launch.properties»
        # превращался в «\support\launch.properties» — отказ выглядел так,
        # будто сломался сам модуль. Сохранённый плейсхолдер позволяет
        # сказать словами, чего именно не нашлось.
        return value or match.group(0)

    return re.sub(r"\{([A-Z_]+)\}", repl, text)


def prepare(spec: dict, progress=None) -> EnvReport:
    """Привести окружение в состояние, описанное в реестре.

    `spec` — блок `env_setup` сервера:

    | ключ | что означает |
    |---|---|
    | `vars` | переменные окружения: имя, чем искать, какая версия нужна |
    | `settings` | строки в настройках чужих программ (`JAVA_HOME_OVERRIDE`) |
    | `path` | папки, которые должны быть в PATH |

    Каждая запись сначала проверяется, потом чинится, потом проверяется
    снова. Вторую проверку пропустить нельзя: запись переменной
    окружения ничего не значит для программы, которая её ищет не так.
    """
    report = EnvReport()
    if not isinstance(spec, dict):
        return report

    for item in spec.get("vars") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        why = str(item.get("why") or "")
        kind = str(item.get("kind") or "path").strip().lower()
        try:
            if kind == "jdk":
                min_major = int(item.get("min_major") or 21)
                current = env_persist_get(name).strip().strip('"')
                if current and _jdk_home_ok(Path(current), min_major):
                    report.already_ok.append(f"{name} = {current}")
                    continue
                home, how = find_jdk(min_major)
                if not home:
                    report.failed.append(
                        f"{name} (нужен JDK {min_major}+) — {how}")
                    continue
                changed, line = ensure_env_var(name, str(home))
                if _jdk_home_ok(Path(env_persist_get(name)), min_major):
                    report.fixed.append(f"{line}, искал {how}"
                                        + (f"; {why}" if why else ""))
                    if not changed:
                        report.fixed.pop()
                        report.already_ok.append(f"{line}")
                else:
                    report.failed.append(
                        f"{name} — записал, но Java с этой папки не отвечает")
            else:
                wanted = _expand(str(item.get("value") or ""), progress)
                if not wanted:
                    report.failed.append(
                        f"{name} — реестр не сказал, какое значение нужно")
                    continue
                changed, line = ensure_env_var(name, wanted)
                (report.fixed if changed else report.already_ok).append(
                    line + (f"; {why}" if why else ""))
        except OSError as exc:
            report.failed.append(f"{name} — {exc}")
            report.ok = False

    for folder in spec.get("path") or []:
        target = _expand(str(folder), progress)
        if not target:
            report.failed.append(f"PATH: не понял папку {folder!r}")
            continue
        try:
            changed, line = ensure_path_entry(target)
            (report.fixed if changed else report.already_ok).append(line)
        except OSError as exc:
            report.failed.append(f"PATH += {target} — {exc}")

    for item in spec.get("settings") or []:
        if not isinstance(item, dict):
            continue
        raw_file = str(item.get("file") or "")
        key = str(item.get("key") or "").strip()
        if not raw_file or not key:
            continue
        target_file = Path(_expand(raw_file, progress))
        if "{" in str(target_file):
            # Остался нераскрытый плейсхолдер: нужной программы на машине
            # нет. Писать в такой путь бессмысленно, а сообщение вида
            # «нет файла {GHIDRA}/support/launch.properties» человеку
            # ничего не объясняет — объясняем словами.
            report.failed.append(
                f"{key}: на этой машине не нашлось {_placeholder_hint(raw_file)}")
            continue
        source = str(item.get("value_from") or "").strip()
        if source:
            # `value_from` — ИМЯ переменной окружения, а не плейсхолдер.
            # Раньше здесь стояло расширение `{ИМЯ}`, и в файл попадало
            # слово «JAVA_HOME» вместо пути: Гидра искала папку с таким
            # именем и не находила. Теперь имя читается как имя.
            raw_value = (env_persist_get(source).strip().strip('"')
                         or os.environ.get(source, "").strip().strip('"'))
            wanted = _expand(raw_value, progress)
        else:
            wanted = _expand(str(item.get("value") or ""), progress)
        wanted = _clean_path_value(wanted)
        if not target_file.is_file():
            report.failed.append(
                f"нет файла настроек: {target_file}")
            continue
        if not wanted:
            report.failed.append(
                f"{key} — нечем заполнить, значение пустое")
            continue
        props = read_props(target_file)
        # Сравниваем с тем, что хотим записать, а не «очищенное с
        # очищенным»: иначе грязное значение с хвостовым обратным слэшем
        # вечно считалось бы правильным, и файл так и остался бы грязным.
        if props.get(key, "") == wanted:
            report.already_ok.append(f"{target_file.name}: {key} уже задан")
            continue
        try:
            changed, line = set_prop(target_file, key, wanted,
                                     str(item.get("why") or ""))
        except OSError as exc:
            report.failed.append(f"{target_file.name}: {exc}")
            continue
        again = _clean_path_value(read_props(target_file).get(key, ""))
        if again == wanted:
            (report.fixed if changed else report.already_ok).append(line)
        else:
            report.failed.append(
                f"{target_file.name}: записал, но в файле всё ещё {again!r}")
    report.ok = not report.failed
    return report


def check(spec: dict) -> EnvReport:
    """Только проверить, ничего не меняя. Для кнопки «проверить»."""
    if not isinstance(spec, dict):
        return EnvReport()
    report = EnvReport()
    for item in spec.get("vars") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = env_persist_get(name).strip().strip('"')
        if not value:
            report.failed.append(f"{name} — не задана")
        elif str(item.get("kind") or "").lower() == "jdk":
            min_major = int(item.get("min_major") or 21)
            if _jdk_home_ok(Path(value), min_major):
                report.already_ok.append(f"{name} = {value}")
            else:
                report.failed.append(
                    f"{name} = {value} — нужен JDK {min_major}+")
        else:
            report.already_ok.append(f"{name} = {value}")
    for item in spec.get("settings") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        target_file = Path(_expand(str(item.get("file") or "")))
        if not key or not target_file.is_file():
            report.failed.append(f"нет файла настроек: {target_file.name}")
            continue
        value = read_props(target_file).get(key, "").strip()
        if not value:
            report.failed.append(f"{target_file.name}: {key} не задан")
        else:
            report.already_ok.append(f"{target_file.name}: {key} = {value}")
    report.ok = not report.failed
    return report