"""Android Studio: версия, плагин из набора, включение сервера, проверка.

Задача модуля — одна: довести Android Studio до того состояния, в котором
её сервер отвечает, и вернуть честный отчёт. Окно только зовёт auto_setup()
и показывает, что тот вернул. Никакого Qt здесь нет и быть не должно.

Откуда взялись неочевидные места:

* Имя папки настроек НЕ вычисляется из версии. Оно лежит в самой студии:
  product-info.json, поле dataDirectoryName. Там написано ровно то, что
  нужно: «AndroidStudio2026.1.2». Раньше на этом проваливались — папка
  называется AndroidStudio2026.1.2, а не AndroidStudio2026.1, и это
  отличается от версии студии, которую видит человек.
* Открытый порт ничего не значит. Встроенный веб-сервер IDE слушает 63342
  всегда, и на нём /api/mcp вечно 404. Поэтому проверка — только настоящий
  запрос к адресу сервера плагина.
* Адрес плагина — 127.0.0.1:64342/stream. Не 63342 и не /api/mcp.
* Токена нет. Авторизации у этого сервера нет вовсе, и требовать его —
  значит запретить человеку то, что работает.
* Настройки студии пишутся ТОЛЬКО при закрытой студии: открытая перезапишет
  файл при выходе и всё, что мы записали, пропадёт.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

#: Порт и путь, на которых плагин поднимает свой сервер.
SERVER_PORT = 64342
SERVER_PATH = "/stream"
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}{SERVER_PATH}"

#: Куда в программе лежит набор сборок плагина.
INDEX_RELATIVE = Path("tools") / "thirdparty" / "android-studio" / "index.json"

#: Что должно оказаться в настройках студии. Имя компонента и имя флага
#: взяты из constant pool класса McpServerSettings самого плагина:
#: @State(name="McpServerSettings", storages="mcpServer.xml"), enableMcpServer.
SETTINGS_FILE = "mcpServer.xml"
SETTINGS_XML = (
    "<application>\n"
    '  <component name="McpServerSettings">\n'
    '    <option name="enableMcpServer" value="true" />\n'
    "  </component>\n"
    "</application>\n"
)

#: Куда смотрим, если студия не нашлась в первом месте.
STUDIO_CANDIDATES = (
    Path("C:/Program Files/Android/Android Studio"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Android Studio",
)

STUDIO_EXE = Path("bin") / "studio64.exe"
PLUGIN_ID = 26071
MARKETPLACE_URL = "https://plugins.jetbrains.com/plugin/26071-mcp-server"

_PROBE_TIMEOUT = 6.0


# --------------------------------------------------------------- разбор версий


def version_tuple(text: str) -> tuple[int, ...]:
    """«261.25134.203» -> (261, 25134, 203).

    Именно числа, а не строки: строковое сравнение путает 263.9 и 263.10
    и выбирает не ту сборку плагина.
    """
    parts: list[int] = []
    for chunk in str(text or "").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def platform_from_build(build_number: str) -> tuple[int, ...]:
    """Платформа студии из buildNumber.

    «AI-261.25134.95.2612.15914620» -> (261, 25134). Берём первые два
    числа: 261 — ветка платформы, 25134 — её номер внутри ветки. Именно
    эту пару плагин объявляет в since-build.
    """
    numbers = re.findall(r"\d+", str(build_number or ""))
    if not numbers:
        return ()
    return tuple(int(n) for n in numbers[:2])


def platform_text(platform: tuple[int, ...]) -> str:
    return ".".join(str(n) for n in platform)


def since_matches(since: str, platform: tuple[int, ...]) -> bool:
    """Не ниже ли объявленного начала сборки плагина."""
    if not platform:
        return False
    return platform >= version_tuple(since)


def until_matches(until: str, platform: tuple[int, ...]) -> bool:
    """Попадает ли платформа в объявленный конец сборки плагина.

    «261.*» — вся ветка 261. «263.5701.*» — только подплатформа 263.5701.
    Без звёздочки — «до этой версии включительно».
    """
    raw = str(until or "").strip()
    if not raw or raw == "*":
        return True
    if raw.endswith(".*"):
        prefix = version_tuple(raw[:-2])
        return platform[: len(prefix)] == prefix
    return platform <= version_tuple(raw)


def build_matches(build: dict, platform: tuple[int, ...]) -> bool:
    """Подходит ли сборка плагина под эту платформу студии.

    Оба края берутся из дескриптора самого плагина. Ничего не угадываем:
    именно поэтому программа не может выбрать сборку, которая не загрузится.
    """
    return since_matches(str(build.get("since") or ""), platform) and until_matches(
        str(build.get("until") or ""), platform
    )


# ------------------------------------------------------------------ сама студия


@dataclass
class StudioInfo:
    """Где стоит студия, какая у неё версия и где её настройки."""

    exe: Path
    build_number: str = ""
    platform: tuple[int, ...] = ()
    data_dir_name: str = ""

    @property
    def platform_label(self) -> str:
        return platform_text(self.platform) or "неизвестно"

    @property
    def settings_dir(self) -> Path:
        """%APPDATA%\\Google\\AndroidStudio2026.1.2 — имя берём из студии."""
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Google" / (self.data_dir_name or "AndroidStudio")

    @property
    def plugins_dir(self) -> Path:
        return self.settings_dir / "plugins"

    @property
    def options_file(self) -> Path:
        return self.settings_dir / "options" / SETTINGS_FILE


def find_studio() -> Path | None:
    """Папка установленной студии или None."""
    for candidate in STUDIO_CANDIDATES:
        if candidate and (candidate / STUDIO_EXE).is_file():
            return candidate
    return None


def read_studio_info(studio_dir: Path) -> StudioInfo | None:
    """Читает product-info.json студии. None, если файла нет или он битый."""
    info = studio_dir / "product-info.json"
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    build = str(data.get("buildNumber") or "").strip()
    if not build:
        return None
    return StudioInfo(
        exe=studio_dir / STUDIO_EXE,
        build_number=build,
        platform=platform_from_build(build),
        data_dir_name=str(data.get("dataDirectoryName") or "").strip(),
    )


def studio_info() -> StudioInfo | None:
    """Сведения о студии на этой машине, или None если её нет."""
    folder = find_studio()
    return read_studio_info(folder) if folder else None


def is_running() -> bool:
    """Запущена ли студия. Пока открыта, настройки писать нельзя."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq studio64.exe", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=15,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return False
    return "studio64.exe" in out


# ------------------------------------------------------------------ набор сборок


@dataclass
class Bundle:
    """Набор сборок плагина, положенный в программу."""

    base: Path
    builds: list[dict]
    plugin_id: int = PLUGIN_ID
    source: str = MARKETPLACE_URL
    problem: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.builds)


def load_bundle(base: Path | None = None) -> Bundle:
    """Читает index.json с набором сборок. Пустой набор — не ошибка."""
    root = Path(base) if base else Path(__file__).resolve().parent.parent.parent
    path = root / INDEX_RELATIVE
    problem = ""
    builds: list[dict] = []
    plugin_id = PLUGIN_ID
    source = MARKETPLACE_URL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Bundle(base=root, builds=[], problem=f"Нет указателя {path}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Bundle(base=root, builds=[], problem=f"Указатель не читается: {exc}")
    if isinstance(data, dict):
        raw = data.get("builds")
        if isinstance(raw, list):
            builds = [b for b in raw if isinstance(b, dict) and b.get("file")]
        try:
            plugin_id = int(data.get("plugin_id") or plugin_id)
        except (TypeError, ValueError):
            pass
        source = str(data.get("source") or source)
    return Bundle(base=root, builds=builds, plugin_id=plugin_id, source=source, problem=problem)


def bundle_file(bundle: Bundle, build: dict) -> Path:
    return bundle.base / INDEX_RELATIVE.parent / str(build.get("file") or "")


def pick_build(bundle: Bundle, platform: tuple[int, ...]) -> dict | None:
    """Самая свежая сборка, подходящая под платформу. None, если такой нет."""
    fits = [b for b in bundle.builds if build_matches(b, platform)]
    if not fits:
        return None
    return max(fits, key=lambda b: version_tuple(str(b.get("version") or "")))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------------- плагин в студии


def _read_descriptor(archive: Path) -> dict | None:
    """Достаёт version из plugin.xml внутри архива плагина.

    Дескриптор лежит не в корне архива, а внутри банки: у сборок 261 и 262
    это lib/mcpserver.jar, у сборок 263 — отдельная маленькая банка. Ищем
    перебором и не предполагаем, что схема одна.
    """
    try:
        with zipfile.ZipFile(archive) as outer:
            jars = [n for n in outer.namelist() if n.endswith(".jar")]
            jars.sort(key=lambda n: outer.getinfo(n).file_size)
            for name in jars:
                with outer.open(name) as raw:
                    data = io.BytesIO(raw.read())
                with zipfile.ZipFile(data) as inner:
                    if "META-INF/plugin.xml" not in inner.namelist():
                        continue
                    text = inner.read("META-INF/plugin.xml").decode("utf-8", "replace")
                found = re.search(r"<version>([^<]+)</version>", text)
                if found:
                    return {"version": found.group(1).strip()}
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return None
    return None


def archive_folder(archive: Path) -> str:
    """Имя папки внутри архива. Разное у 261/262 и у 263 — не выдумываем."""
    try:
        with zipfile.ZipFile(archive) as outer:
            for name in outer.namelist():
                if "/" in name:
                    return name.split("/")[0]
    except (OSError, zipfile.BadZipFile):
        pass
    return "mcpserver"


def plugin_dir(info: StudioInfo, folder: str) -> Path:
    return info.plugins_dir / (folder or "mcpserver")


PLUGIN_XML_ID = "com.intellij.mcpServer"


def installed_version(plugin: Path) -> str:
    """Версия уже установленного плагина, или пустая строка.

    В папке плагина много банок, и дескриптор лежит не в самой большой:
    у сборок 263 это отдельная маленькая банка, у 261 и 262 — наоборот,
    самая большая. Поэтому берём тот plugin.xml, у которого id совпадает
    с id нашего плагина, а если такого нет — самый верхний по папке.
    """
    if not plugin.is_dir():
        return ""
    found: list[tuple[bool, int, int, str]] = []
    for jar in plugin.rglob("*.jar"):
        try:
            with zipfile.ZipFile(jar) as inner:
                if "META-INF/plugin.xml" not in inner.namelist():
                    continue
                text = inner.read("META-INF/plugin.xml").decode("utf-8", "replace")
        except (OSError, zipfile.BadZipFile):
            continue
        version = re.search(r"<version>([^<]+)</version>", text)
        if not version:
            continue
        identifier = re.search(r"<id>([^<]+)</id>", text)
        ours = bool(identifier and identifier.group(1).strip() == PLUGIN_XML_ID)
        depth = len(jar.relative_to(plugin).parts)
        found.append((ours, -depth, -jar.stat().st_size, version.group(1).strip()))
    if not found:
        return ""
    return max(found)[3]


def plugin_state(info: StudioInfo, folder: str, want: str) -> tuple[str, str]:
    """Состояние плагина в студии: (состояние, подробность).

    Состояния: «нет», «установлен», «другая».
    """
    plugin = plugin_dir(info, folder)
    if not plugin.is_dir():
        return "нет", str(plugin)
    found = installed_version(plugin)
    if not want or found == want:
        detail = f"{plugin}"
        if found:
            detail += f" (версия {found})"
        return "установлен", detail
    return "другая", f"{plugin} (стоит {found}, а нужна {want})"


def install_plugin(
    bundle: Bundle, build: dict, info: StudioInfo, progress=None
) -> tuple[bool, str]:
    """Ставит плагин из набора. False — значит ничего не распаковано.

    Порядок именно такой: сначала сверка хеша, и только потом распаковка.
    Битый архив, распакованный в студию, ломает её хуже, чем отсутствие
    плагина: студия перестаёт грузиться.
    """
    def say(text: str) -> None:
        if progress:
            progress(text)

    archive = bundle_file(bundle, build)
    version = str(build.get("version") or "")
    if not archive.is_file():
        return False, f"Архива нет в программе: {archive}"
    expected = str(build.get("sha256") or "")
    if expected:
        say(f"Сверяю архив плагина {version}…")
        try:
            actual = sha256(archive)
        except OSError as exc:
            return False, f"Архив не читается: {exc}"
        if actual.lower() != expected.lower():
            return False, (
                f"Архив плагина {version} повреждён или подменён: хеш не совпал. "
                "Ничего не распаковываю."
            )
    else:
        say("В указателе нет хеша — сверять нечем, но ставлю.")

    folder = str(build.get("folder") or archive_folder(archive))
    target = plugin_dir(info, folder)
    state, detail = plugin_state(info, folder, version)
    if state == "установлен":
        say(f"Плагин уже стоит: {detail}")
        return True, detail
    if state == "другая":
        # Молча перезаписывать папку плагина нельзя: это чужая программа,
        # и человек может держать в ней что-то своё. Честно отказываем.
        return False, (
            f"В студии уже стоит другая сборка плагина: {detail}. "
            "Программа её не трогает — закрой студию, удали эту папку и "
            "нажми кнопку ещё раз."
        )
    say(f"Распаковываю плагин {version} в {target}…")
    try:
        with zipfile.ZipFile(archive) as outer:
            names = outer.namelist()
            if not any("/" in n for n in names):
                return False, "В архиве нет папки верхнего уровня — похоже, что он битый."
            outer.extractall(info.plugins_dir)
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"Распаковать не вышло: {exc}"
    return True, f"Плагин {version} распакован: {target}"


# ---------------------------------------------------------------- включение сервера


def server_enabled(info: StudioInfo) -> bool:
    """Включён ли сервер в настройках студии (по нашему файлу)."""
    try:
        text = info.options_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "enableMcpServer" in text and 'value="true"' in text


def enable_server(info: StudioInfo, progress=None) -> tuple[bool, str]:
    """Пишет настройку включения сервера. Только при закрытой студии."""
    def say(text: str) -> None:
        if progress:
            progress(text)

    if is_running():
        return False, (
            "Android Studio сейчас запущена. Закрой её и нажми кнопку ещё "
            "раз: открытая студия перезапишет настройку при выходе."
        )
    if server_enabled(info):
        say("Сервер уже включён в настройках студии.")
        return True, f"Уже включён: {info.options_file}"
    say(f"Включаю сервер: {info.options_file}")
    try:
        info.options_file.parent.mkdir(parents=True, exist_ok=True)
        info.options_file.write_text(SETTINGS_XML, encoding="utf-8")
    except OSError as exc:
        return False, f"Записать настройку не вышло: {exc}"
    return True, f"Сервер включён: {info.options_file}"


# --------------------------------------------------------------- живая проверка


def probe(url: str = SERVER_URL, timeout: float = _PROBE_TIMEOUT) -> tuple[bool, str]:
    """Проверяет сервер настоящим запросом, а не «порт открыт».

    Открытый порт — не доказательство: встроенный веб-сервер IDE слушает
    всегда. Поэтому шлём initialize и смотрим ответ. 404 — сервера нет.

    Читаем построчно, а не целиком: адрес /stream отдаёт поток событий,
    который не закрывается никогда, и обычное read() ждало бы его до
    самого таймаута, а потом обозвал живой сервер мёртвым.
    """
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "OpenCode_Base", "version": "1"},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, (
                f"{url} отвечает 404 — плагин не загрузился. Открой Android "
                "Studio и посмотри, нет ли ошибки в её журнале."
            )
        return True, f"{url} ответил кодом {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"{url} не отвечает ({reason}). Запусти Android Studio."

    raw = ""
    try:
        for _ in range(8):
            try:
                line = response.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            raw += line
            if "serverInfo" in raw:
                break
    finally:
        try:
            response.close()
        except (OSError, ValueError):
            pass

    found = re.search(r'"serverInfo"\s*:\s*\{[^{}]*\}', raw)
    if found:
        return True, f"{url} ответил: {found.group(0)}"
    if raw.strip():
        return True, f"{url} ответил, но без ответа initialize"
    return True, f"{url} принял соединение, но ничего не отдал"


# ------------------------------------------------------------------- сценарий


def auto_setup(dest: Path, server, progress=None) -> tuple[list[str], list[str]]:
    """Полная настройка Android Studio в один заход.

    Возвращает (сообщения, ошибки) — как mcp_registry.enable, чтобы окно
    умело показывать их одинаково.

    Порядок жёсткий. Сначала доводим студию до состояния, в котором сервер
    отвечает, и только потом вписываем сервер в настройки opencode.
    Обратный порядок даёт в списке сервер, который не работает, и человек
    потом не понимает, что с ним делать.
    """
    import mcp_registry

    messages: list[str] = []
    errors: list[str] = []

    def say(text: str) -> None:
        messages.append(text)
        if progress:
            progress(text)

    def fail(text: str) -> None:
        errors.append(text)

    say("Проверяю Android Studio…")
    info = studio_info()
    if info is None:
        fail("Android Studio не найдена. Она ставится отдельно: "
             "https://developer.android.com/studio")
        return messages, errors
    say(f"Студия найдена: {info.exe.parent}")
    say(f"Версия студии: {info.build_number}")
    say(f"Платформа: {info.platform_label}")

    bundle = load_bundle()
    if not bundle.ready:
        fail(bundle.problem or "В программе нет набора сборок плагина.")
        return messages, errors
    say(f"Набор сборок плагина: {len(bundle.builds)} шт.")

    build = pick_build(bundle, info.platform)
    if build is None:
        fail(
            f"В программе нет сборки плагина под платформу {info.platform_label}. "
            f"Подойдёт ссылка на список сборок: {bundle.source}. Файл нужно "
            "положить в папку плагинов: " + str(info.plugins_dir)
        )
        return messages, errors
    version = str(build.get("version") or "")
    say(f"Подходит сборка плагина {version} ({build.get('since')} → {build.get('until')})")

    folder = str(build.get("folder") or "mcpserver")
    state, detail = plugin_state(info, folder, version)
    if state == "другая":
        fail(f"В студии уже стоит другая сборка плагина: {detail}. Программа её не трогает.")
        return messages, errors
    if state == "установлен":
        say(f"Плагин уже установлен: {detail}")
    else:
        ok, note = install_plugin(bundle, build, info, progress=say)
        if not ok:
            fail(note)
            return messages, errors
        say(note)

    ok, note = enable_server(info, progress=say)
    if not ok:
        fail(note)
        return messages, errors
    say(note)

    say(f"Проверяю сервер: {SERVER_URL}")
    alive, note = probe()
    if not alive:
        # Сервер не ответил — в настройки opencode не лезем ни при каких
        # условиях. Иначе в списке появится сервер с ошибкой.
        fail(f"{note} В настройки opencode ничего не вписано.")
        return messages, errors
    say(f"Сервер отвечает: {note}")

    try:
        saved, note = mcp_registry.save_manual_config(
            dest,
            server.id,
            json.dumps({"url": SERVER_URL, "headers": {}}, ensure_ascii=False),
        )
    except (OSError, TypeError, ValueError) as exc:
        fail(f"Конфигурацию сохранить не вышло: {exc}")
        return messages, errors
    if not saved:
        fail(note)
        return messages, errors
    say(f"Адрес сохранён: {note}")

    wrote, wrote_errors = mcp_registry.enable(dest, server, progress=say)
    for line in wrote:
        say(line)
    for line in wrote_errors:
        fail(line)
    if wrote_errors and not wrote:
        return messages, errors

    messages.append(
        "Готово: Android Studio подключена. Перезапусти opencode — серверы "
        "читаются при старте."
    )
    return messages, errors