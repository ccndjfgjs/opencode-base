# -*- coding: utf-8 -*-
"""Реестр MCP-серверов: что известно, что готово, что можно включить.

Модуль отдельный от core.py намеренно. Здесь три вещи, которые не должны
размазываться по программе: чтение реестра, живая проверка требований и
включение/выключение сервера в настройках opencode.

Про проверку требований. Реестр честно предупреждает: поле ready_here —
снимок на дату checked, а не обещание, и верить ему нельзя. Поэтому
состояние сервера считается здесь, на живой машине, а снимок из реестра
показывается рядом и помечен как устаревший. Иначе программа будет
врать пользователю про свою же готовность.

Про окружение. Мосту мало бывает программы: ghidra-mcp, например,
работает, только если Гидра видит Java, а Гира ищет Java по-своему, через
JAVA_HOME_OVERRIDE в своём launch.properties, и переменная окружения тут
ни при чём. Поэтому перед вписыванием блока вызывается env_setup: программа
проверяет нужные переменные и настройки и чинит их сама. Включение моста
должно заканчиваться рабочим состоянием, а не инструкцией «пропишите
JAVA_HOME вручную». Что именно нужно мосту, лежит в реестре, в блоке
`env_setup`, а не в коде.

Программа ничего не устанавливает из интернета и не покупает подписки.
Она только проверяет, вписывает блок в настройки и честно говорит, чего
не хватает.
"""

from __future__ import annotations

import glob
import json
import datetime
import os
import re
import shutil
import subprocess
import winreg
from dataclasses import dataclass, field
from pathlib import Path

# Общие правила для версий. Импорт двойной: при плоском запуске папка лежит
# в sys.path, при запуске как пакет нужен относительный.
try:
    import versions  # type: ignore[import-not-found]
    import env_setup  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - запуск как пакет
    from . import versions  # type: ignore[no-redef]
    from . import env_setup  # type: ignore[no-redef]

#: Плейсхолдер в команде запуска: {PROGRAM}, {UV}, {GHIDRA} и прочие.
#: В реестре лежат только имена, пути подставляются на машине человека.
_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")

#: Имя файла реестра. Лежит в корне базы и едет с ней.
REGISTRY_NAME = "mcp-registry.json"

#: Куда искать программу, если её нет в PATH. Ключ — имя файла,
#: значение — ветка реестра Windows, где записан полный путь.
PROGRAMS_IN_REGISTRY = {
    "excel.exe": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
    "blender.exe": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\blender.exe",
}

#: Сколько ждать ответа команды проверки, секунд. Проверка должна быть
#: мгновенной; если зависла — значит это не проверка версии.
CHECK_TIMEOUT = 8

#: Сколько ждать прогрева кэша npx. Холодная скачка пакета занимает до
#: минуты; если за это время не уложились, кэш считаем прогретым и
#: продолжаем: opencode всё равно попробует сам.
WARM_UP_TIMEOUT = 180


@dataclass
class Requirement:
    """Одно требование сервера и результат его проверки."""

    what: str
    kind: str = "manual"          # command | program | manual
    value: str = ""               # команда или имя программы
    args: list[str] = field(default_factory=list)
    min_version: int = 0
    max_version: int = 0          # 0 — сверху ограничения нет
    until: str = ""               # строковая граница «до этой включительно»
    note: str = ""
    blocks: bool = False         # ручное требование, без которого сервер бессмыслен
    ok: bool = False
    detail: str = ""              # что именно найдено, для показа


@dataclass
class PluginSpec:
    """Плагин чужой программы, который вкладка умеет докачать сама.

    Отдельный блок, а не поле в `ProgramInstall`, потому что это не про
    установку самой программы: OBS стоит, а не хватает одной её части.
    Смешивать их значило бы получить две разные кнопки из одного описания.

    `finder` — короткое имя, по которому код находит папку программы.
    Не имя программы и не путь: путь меняется при переносе, а программу
    вкладке называет реестр. На «obs» код знает, где папка OBS; на
    незнакомое имя кнопки не будет, и карточка это скажет.
    """

    finder: str = ""
    name: str = ""
    button: str = ""
    hint: str = ""
    unavailable: str = ""
    fallback: str = ""      # запасная дорога разрешена в реестре?


@dataclass
class ProgramInstall:
    """Как поставить программу, нужную серверу, и где вкладка должна остановиться.

    Живёт в реестре под именем `program_install`, а не `install`. Имя
    выбрано не по вкусу: поле `install` в реестре уже занято человеческим
    текстом («uvx mcp-for-blender + аддон в Blender») — это пояснение для
    читателя, а не машиночитаемые данные. Переписать его в объект значило бы
    выбросить то, что читают люди, и сломать старые копии реестра. Поэтому
    структура лежит рядом, под своим именем, а `install` остаётся текстом.

    Метод `method` — то, что вкладка умеет делать сама:

    | method | что получится |
    |---|---|
    | `winget` | кнопка «установить» ставит через winget |
    | `official-download` | кнопка качает с официального адреса и сверяет подпись |
    | `manual` | кнопки нет: официальная страница и команда в буфер |
    | `none` | программа не нужна, ставить нечего |

    `expected_signer` — имя, которому обязана совпасть цифровая подпись
    установщика, а для winget — издатель из каталога. Проверка подписи
    появляется на этапе 8, до него это записанное намерение, а не
    действующая проверка.
    """

    program: str = ""
    method: str = "manual"        # winget | official-download | manual | none
    winget_id: str = ""
    catalog_version: str = ""     # версия в каталоге, не установленная
    expected_publisher: str = ""  # издатель из МАНИФЕСТА winget
    expected_signer: str = ""     # кто подписал сам файл; иное поле, см. ниже
    signer_checked: str = ""      # когда CN подтверждён на настоящем файле
    signer_proof: str = ""        # чем подтверждён: путь и что сказала Windows
    needs_admin: bool = False
    needs_admin_verified: bool = False
    official_url: str = ""
    hand_over: bool = False       # дальше нужен человек: вход, оплата, галочка
    publisher_trusted: bool = True
    bridge: str = ""              # bundled — мост уже лежит внутри программы
    instructions: str = ""
    checked: str = ""             # когда сверяли с winget, а не когда ставили
    # Что известно о версии НА ЭТОЙ МАШИНЕ. Поле catalog_version — версия
    # в каталоге winget, это другое; здесь то, что реально стоит.
    installed_version: str = ""
    known_good: list[str] = field(default_factory=list)
    version_measured: str = ""    # когда сняли версию
    bridge_checked: bool = False  # мост проверен живым запросом
    version_note: str = ""        # что именно измерено и чем
    #: Какие версии стояли ДО последнего обновления. Откат строит команду
    #: `winget install --version` из этого списка, и winget сам эти версии
    #: не помнит — он знает только текущую. Поэтому список пополняется
    #: ДО запуска обновления, а не после: после обновления прежняя версия
    #: уже никому не известна. Пустой список означает, что откатываться
    #: нечем, и кнопка обязана быть выключена с этой причиной, а не
    #: спрятана: человек, только что обновившийся и сломавший мост, не
    #: должен гадать, появится ли возврат.
    previous_versions: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    plugin: PluginSpec | None = None

    @property
    def can_install(self) -> bool:
        """Есть ли кнопка, которая действительно поставит."""
        return self.method in ("winget", "official-download")

    @property
    def stops_for_human(self) -> bool:
        """Где кнопка обязана остановиться и позвать человека."""
        return self.hand_over


@dataclass
class Server:
    """Один сервер из реестра вместе с живым состоянием."""

    id: str
    name: str
    raw: dict
    requirements: list[Requirement] = field(default_factory=list)
    installed: bool = False       # вписан ли в настройки opencode
    has_connection: bool = False  # есть ли что вписывать

    @property
    def missing(self) -> list[Requirement]:
        """Чего объективно не хватает: то, что программа умеет проверить."""
        return [r for r in self.requirements if not r.ok and r.kind != "manual"]

    @property
    def blocking_manual(self) -> list[Requirement]:
        """Ручные требования, без которых сервер работать не будет.

        Пример — приложения Adobe: сервер формально подключается, но
        отвечает отказом на всё. Отличать их надо, иначе программа
        предложит включить заведомо бесполезное.
        """
        return [r for r in self.requirements if r.kind == "manual" and r.blocks]

    @property
    def manual(self) -> list[Requirement]:
        """Ручные требования, которые человек проверяет сам."""
        return [r for r in self.requirements if r.kind == "manual" and not r.blocks]

    @property
    def ready(self) -> bool:
        """Можно ли включить.

        Обычные ручные требования НЕ мешают. Например, права
        администратора: без них сервер запускается, просто часть
        инструментов откажет. Если запретить включение из-за
        недоказанного, пользователь не сможет включить вполне рабочий
        сервер. А вот помеченные как blocks — мешают: без них сервер
        бесполезен, и честнее сказать об этом, чем вписать его зря.
        """
        if self.manual_setup:
            # Ручные требования здесь не блокируют: человек их уже
            # выполнил, если вставил конфигурацию. Блокировали бы - он
            # не смог бы дойти до окна, где эту конфигурацию вставлять.
            return not self.missing and self.has_connection
        return not self.missing and not self.blocking_manual and self.has_connection

    @property
    def license(self) -> str:
        return str(self.raw.get("license") or "—")

    @property
    def tools_count(self) -> str:
        value = self.raw.get("tools_count")
        return f"{value} инстр." if value else "—"

    @property
    def tools_note(self) -> str:
        value = self.raw.get("tools_note")
        return str(value) if value else ""

    @property
    def source(self) -> str:
        return str(self.raw.get("source") or "")

    # ------------------------------------------------ сервер с ручной настройкой

    @property
    def manual_setup(self) -> bool:
        """Настраивается ли сервер руками, изнутри своей программы.

        Такой сервер нельзя включить отсюда: его сначала надо включить
        там. Программа говорит об этом прямо и просит конфигурацию.
        """
        conn = self.raw.get("connection")
        return isinstance(conn, dict) and bool(conn.get("manual_config"))

    @property
    def ready_here(self) -> bool:
        """Честный ответ: можно ли этим сервером пользоваться на этой машине."""
        return bool(self.raw.get("ready_here"))

    @property
    def setup_steps(self) -> list[str]:
        """Пошаговая инструкция, если она есть в реестре."""
        steps = self.raw.get("setup_steps")
        if not isinstance(steps, list):
            return []
        return [str(s).strip() for s in steps if str(s).strip()]

    @property
    def auth(self) -> str:
        return str(self.raw.get("auth") or "")

    @property
    def only_while_running(self) -> str:
        return str(self.raw.get("only_while_running") or "")

    @property
    def why(self) -> str:
        return str(self.raw.get("why") or "")

    @property
    def program_install(self) -> ProgramInstall | None:
        """Как поставить программу для этого сервера.

        None в трёх случаях, и все три нормальны: блока нет вовсе (старый
        реестр), блок не объект (человек дописал строку) или программа
        серверу не нужна и метод равен `none`. Молча превращать это в
        «поставить нечем» нельзя — тогда потерялось бы «программа не нужна».
        """
        raw = self.raw.get("program_install")
        if not isinstance(raw, dict):
            return None
        return ProgramInstall(
            program=str(raw.get("program") or ""),
            method=str(raw.get("method") or "manual").strip().lower(),
            winget_id=str(raw.get("winget_id") or ""),
            catalog_version=str(raw.get("catalog_version") or ""),
            expected_publisher=str(raw.get("expected_publisher") or ""),
            expected_signer=str(raw.get("expected_signer") or ""),
            signer_checked=str(raw.get("signer_checked") or ""),
            signer_proof=str(raw.get("signer_proof") or ""),
            needs_admin=bool(raw.get("needs_admin")),
            needs_admin_verified=bool(raw.get("needs_admin_verified")),
            official_url=str(raw.get("official_url") or ""),
            hand_over=bool(raw.get("hand_over")),
            publisher_trusted=bool(raw.get("publisher_trusted", True)),
            bridge=str(raw.get("bridge") or ""),
            instructions=str(raw.get("instructions") or ""),
            checked=str(raw.get("checked") or ""),
            installed_version=str(raw.get("installed_version") or ""),
            known_good=[str(v).strip() for v in (raw.get("known_good") or [])
                        if str(v).strip()],
            version_measured=str(raw.get("version_measured") or ""),
            bridge_checked=bool(raw.get("bridge_checked")),
            version_note=str(raw.get("version_note") or ""),
            previous_versions=[str(v).strip()
                                for v in (raw.get("previous_versions") or [])
                                if str(v).strip()],
            alternatives=[a for a in (raw.get("alternatives") or []) if isinstance(a, dict)],
            plugin=_plugin_spec(raw.get("plugin")),
        )

    @property
    def verdict(self) -> str:
        return str(self.raw.get("verdict") or "")


# ------------------------------------------------------------------ чтение


#: Реестр уехал в `данные/` — это раздел 16 плана. Но в созданной базе он
#: остался в корне: оттуда его читают `programs.py` и окно управления, и
#: переносить его в базе незачем. Поэтому мест два, и порядок задан явно:
#: сначала новое, потом старое. Пустой элемент означает «в корне».
REGISTRY_FOLDERS = ("данные", "")


def registry_path(base: Path) -> Path:
    """Где лежит реестр: в новой папке программы или в корне базы."""
    base = Path(base)
    for part in REGISTRY_FOLDERS:
        candidate = base.joinpath(part, REGISTRY_NAME)
        if candidate.is_file():
            return candidate
    # Файла нет ни там, ни там. Возвращаем новое место, чтобы ошибка
    # называла то место, где файл должен лежать, а не то, где он был.
    return base.joinpath(REGISTRY_FOLDERS[0], REGISTRY_NAME)


def load_registry(base: Path) -> dict:
    """Читает реестр. При беде возвращает пустой — программа не падает."""
    try:
        data = json.loads(registry_path(base).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

#: Сколько прежних версий держим. Пять — с запасом на несколько обновлений
#: подряд, но без бесконечного роста файла: список не архив, а точки отката.
#: Сама константа забыта была при первой записи версии, и `NameError`
#: вылез на первой же записи — `py_compile` на такое не смотрит, он не
#: проверяет имена. Поймал живой вызов на копии реестра.
HISTORY_LIMIT = 5


def save_registry(base: Path, data: dict) -> tuple[bool, str]:
    """Записать реестр целиком. Атомарно, иначе обрыв оставил бы битый файл.

    Сначала временный файл **рядом** с настоящим, потом `os.replace`.
    Замена атомарна только внутри одной папки: временный файл в
    `TEMP` на другой файловой системе заменой не станет, и при обрыве
    останется половина. Отказ возвращается текстом, а не молчанием —
    реестр это данные пользователя, и молчаливая потеря хуже отказа.

    Формат записи измерен: `ensure_ascii=False, indent=2` и перевод
    строки в конце воспроизводят нынешний файл побайтово, поэтому правка
    одного поля не переписывает остальное форматирование.
    """
    path = registry_path(base)
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".новое")
        temp.write_text(body, encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        try:
            path.with_name(path.name + ".новое").unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"не удалось записать реестр: {exc}"
    return True, f"реестр записан: {path}"


def _program_block(data: dict, server_id: str) -> dict | None:
    """Блок `program_install` сервера. None, если сервера или блока нет."""
    for server in data.get("servers") or []:
        if not isinstance(server, dict):
            continue
        if str(server.get("id") or "") != str(server_id):
            continue
        block = server.get("program_install")
        return block if isinstance(block, dict) else {}
    return None


def remember_version(base: Path, server_id: str, version: str) -> tuple[bool, str]:
    """Запомнить версию, которая стоит сейчас, ДО обновления.

    Вызывать надо до запуска `winget upgrade`. После обновления прежняя
    версия не известна никому: winget её не хранит, а мы её ещё не
    записали. Отсюда и порядок, и проверка порядка в селфтесте.

    Дубли не копим: повторное обновление той же версии не должно
    превращать список в ten одинаковых строк.
    """
    want = str(version or "").strip()
    if not want:
        return False, "нечего запоминать: версия не названа"
    data = load_registry(base)
    if not data:
        return False, "реестр не прочитан — записывать некуда"
    block = _program_block(data, server_id)
    if block is None:
        return False, f"сервера {server_id} нет в реестре"
    history = [str(v).strip() for v in (block.get("previous_versions") or [])
               if str(v).strip()]
    history = [v for v in history if v != want]
    history.insert(0, want)
    del history[HISTORY_LIMIT:]
    block["previous_versions"] = history
    return save_registry(base, data)


def set_installed_version(base: Path, server_id: str, version: str,
                          note: str = "") -> tuple[bool, str]:
    """Записать, какая версия стоит после обновления, — и чем это снято.

    Отдельно от `remember_version` намеренно: первое пишет историю ДО
    обновления, второе — состояние ПОСЛЕ. Перепутать их — значит либо
    потерять точку отката, либо записать в историю версию, которая
    никогда не стояла.
    """
    want = str(version or "").strip()
    if not want:
        return False, "нечего записывать: версия не названа"
    data = load_registry(base)
    if not data:
        return False, "реестр не прочитан — записывать некуда"
    block = _program_block(data, server_id)
    if block is None:
        return False, f"сервера {server_id} нет в реестре"
    block["installed_version"] = want
    block["version_measured"] = datetime.date.today().isoformat()
    block["version_note"] = str(note or "снято живьём через winget list")
    return save_registry(base, data)



# --------------------------------------------------------------- проверки


def _hidden_startupinfo():
    """Окно консоли не показывать. Подробности — в core.hidden_startupinfo.

    Отдельная обёртка, потому что модуль проверяют и запускают без
    главного окна программы: тогда core может быть недоступен, и
    молча пропустить скрытие хуже, чем не спрятать вовсе.
    """
    try:
        from core import hidden_startupinfo

        return hidden_startupinfo()
    except Exception:
        return None


def _run(command: str, args: list[str]) -> tuple[bool, str]:
    """Запускает команду проверки. Ничего не устанавливает и не меняет.

    Отдельно про .cmd и .bat: на Windows такую обёртку нельзя выполнить
    напрямую, CreateProcess её не берёт — нужен cmd.exe. Наивный запуск
    «npx» молча падает, хотя npx на месте. Поэтому ищем настоящий файл
    и, если он пакетный, идём через cmd.
    """
    exe = shutil.which(command) or command
    argv = [exe, *args]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC") or "cmd.exe", "/c", exe, *args]
    try:
        # Окно консоли прячем: проверка требований дёргает node и npx для
        # каждого сервера, и каждая такая проба на миг открывала чёрное
        # окно. Измерено на запуске программы: 24 видимых окна за 17 секунд
        # — двенадцать серверов по две пробы. Здесь только capture_output,
        # потоки подставлены явными трубами, поэтому STARTUPINFO безопасен
        # и не рвёт обмен, в отличие от CREATE_NO_WINDOW.
        done = subprocess.run(
            argv,
            capture_output=True, text=True, timeout=CHECK_TIMEOUT,
            encoding="utf-8", errors="replace",
            startupinfo=_hidden_startupinfo(),
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    out = (done.stdout or "").strip() or (done.stderr or "").strip()
    return done.returncode == 0, out


def _find_by_pattern(pattern: str) -> str:
    """Ищет файл по шаблону пути и берёт самую новую версию.

    Только абсолютные шаблоны. Относительный означал бы угадывание
    («а где обычно ставят»), а угадывание молчит: не нашлось не там — и
    человек увидел «не установлена» про установленное.

    Версия выбирается по числам в имени папки, в которой лежит файл:
    `Blender 5.2` даёт (5, 2). Если чисел нет, порядок не меняется и
    берётся первый найденный — и это сказано здесь, потому что выбор
    «какая версия новее» по папке без номера иначе выглядел бы
    определённым.
    """
    if not re.match(r"^[A-Za-z]:[\\/]", pattern):
        return ""
    hits = [h for h in glob.glob(pattern) if Path(h).is_file()]
    if not hits:
        return ""
    best = max(hits, key=lambda h: _version_tuple(Path(h).parent.name))
    return str(Path(best).resolve())


def find_program(name: str) -> str:
    """Ищет исполняемый файл: PATH, ветка реестра Windows, шаблон пути.

    Шаблон нужен программам, которые кладут себя в папку с номером
    версии: `Blender 5.2`, `OBS 31`. Имя папки меняется при каждом
    обновлении, поэтому жёсткий путь протухает молча, а отсутствие пути
    вовсе выдаёт установленную программу за отсутствующую — и карточка
    предлагает поставить то, что уже стоит.
    """
    if any(ch in name for ch in "*?"):
        by_pattern = _find_by_pattern(name)
        if by_pattern:
            return by_pattern
        # Шаблон не нашёлся — не значит, что программы нет: она может
        # стоять в PATH, а в Program Files быть другой версии.
        return shutil.which(Path(name).name) or ""
    found = shutil.which(name)
    if found:
        return found
    key = PROGRAMS_IN_REGISTRY.get(name.lower())
    if not key:
        return ""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        path = str(value or "").strip()
        # Реестр отдаёт укороченный путь вида C:\PROGRA~2\... — он рабочий,
        # но показывать его пользователю неудобно, приводим к нормальному.
        if path and Path(path).exists():
            return str(Path(path).resolve())
    return ""


def _version_tuple(text: str) -> tuple[int, ...]:
    """Первая последовательность чисел в строке: v24.18.0 -> (24, 18, 0)."""
    match = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _plugin_spec(raw) -> PluginSpec | None:
    """Разобрать блок плагина. Нет блока или он не объект — плагина нет.

    Молчать об этом нельзя только в одном случае: если блок есть, но
    сломан. Пустой блок — обычное «плагина не описано», и карточка молчит
    правильно.
    """
    if not isinstance(raw, dict):
        return None
    return PluginSpec(
        finder=str(raw.get("finder") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        button=str(raw.get("button") or "").strip(),
        hint=str(raw.get("hint") or "").strip(),
        unavailable=str(raw.get("unavailable") or "").strip(),
        fallback=str(raw.get("fallback") or "").strip(),
    )


def _check_obs_websocket(name: str) -> tuple[bool, str]:
    """Живая проверка плагина obs-websocket: библиотека на месте или нет.

    Импорт внутри функции намеренно. `bridges` — тяжёлый модуль про
    OBS и эмуляторы, а читать реестр можно и без него; тянуть мосты на
    этапе чтения незачем.
    """
    import bridges  # noqa: PLC0415 - тяжёлый модуль, нужен в одном месте

    present, _can_write, note = bridges.obs_plugin_state()
    return present, note


def _check_blender_addon(name: str) -> tuple[bool, str]:
    """Живая проверка аддона Blender: файл на месте или нет.

    Возвращает текст и про «осталось включить руками», потому что файл
    и работающий аддон — разные вещи. Импорт внутри функции: модуль
    аддона тянет за собой вещи тяжелее, чем чтение реестра, и на этапе
    чтения он не нужен.
    """
    import blender_addon  # noqa: PLC0415 - тяжёлый модуль, нужен здесь

    present, _can_write, note = blender_addon.addon_state()
    return present, note


def _check_editor_plugin(name: str) -> tuple[bool, str]:
    """Живая проверка плагина редактора: unity, unreal, godot, ghidra.

    Импорт внутри функции: `editor_plugins` тянет за собой указатели и сеть,
    а читать реестр программа должна уметь и без них.
    """
    import editor_plugins  # noqa: PLC0415 — тяжёлый модуль, нужен здесь

    handler = {
        "unity-mcp-package": editor_plugins.unity_state,
        "enginewire-plugin": editor_plugins.unreal_state,
        "godot-ai-addon": editor_plugins.godot_state,
        "ghidra-mcp-extension": editor_plugins.ghidra_state,
        "roblox-studio-server": editor_plugins.roblox_state,
        "roblox-studio-app": editor_plugins.roblox_app_state,
    }.get(name.strip().lower())
    if handler is None:
        return False, f"плагин «{name}» программа не умеет проверять"
    # Обработчики отвечают двумя или тремя значениями: (есть, текст) либо
    # (есть, можно-поставить, текст). Раньше третье значение читалось как
    # текст, и в карточке вместо причины показывалось False.
    result = handler()
    if len(result) == 2:
        present, note = result
        return bool(present), str(note)
    present, _can_write, note = result
    return bool(present), str(note)


#: Чем проверяется требование типа `plugin`. Ключ — то, что написано в
#: реестре в поле `check`. Это не список программ вкладки: программу
#: называет реестр, и без записи о плагине требования не будет.
_PLUGIN_CHECKS = {"obs-websocket": _check_obs_websocket,
                   "blender-mcp-addon": _check_blender_addon,
                   "unity-mcp-package": _check_editor_plugin,
                   "enginewire-plugin": _check_editor_plugin,
                   "godot-ai-addon": _check_editor_plugin,
                   "ghidra-mcp-extension": _check_editor_plugin,
                   "roblox-studio-server": _check_editor_plugin,
                   "roblox-studio-app": _check_editor_plugin}


def check_requirement(spec: dict) -> Requirement:
    """Проверяет одно требование и возвращает его с результатом."""
    req = Requirement(
        what=str(spec.get("what") or ""),
        kind=str(spec.get("type") or "manual").strip().lower(),
        value=str(spec.get("check") or ""),
        args=[str(a) for a in (spec.get("args") or [])],
        min_version=int(spec.get("min_version") or 0),
        max_version=int(spec.get("max_version") or 0),
        until=str(spec.get("until") or "").strip(),
        note=str(spec.get("note") or ""),
        blocks=bool(spec.get("blocks")),
    )
    if not req.what:
        return req

    if req.kind == "manual":
        # Такое программа проверить не может: галочка в Excel, оплаченная
        # подписка, установленное приложение. Говорим прямо, а не угадываем.
        req.ok = False
        req.detail = "проверяется вручную"
        return req

    if req.kind == "plugin":
        # Плагин проверяется по-настоящему: папку установщик создаёт
        # всегда, даже когда плагин не выбран, и считать папку плагином —
        # значит вечно говорить «готово». Типа `manual` здесь быть не
        # должно: программа умеет и проверить, и починить, а «вручную»
        # скрыло бы и поломку, и кнопку.
        checker = _PLUGIN_CHECKS.get(req.value.strip().lower())
        if checker is None:
            req.ok = False
            req.detail = (f"в коде нет проверки для плагина «{req.value}» — "
                          f"состояние неизвестно, а не «есть»")
            return req
        req.ok, req.detail = checker(req.value)
        return req

    if req.kind == "program":
        path = find_program(req.value)
        req.ok = bool(path)
        req.detail = path or "не найден"
        return req

    # kind == "command"
    command = req.value
    if not command:
        req.detail = "нечего проверять"
        return req
    args = req.args or ["--version"]
    ok, out = _run(command, args)
    if not ok and not shutil.which(command):
        # Команды нет в PATH. На Windows npx/npm лежат .cmd-обёртками, и
        # shutil.which их находит, а вот запуск без расширения может
        # не сработать — пробуем с расширением .cmd.
        if shutil.which(command + ".cmd"):
            ok, out = _run(command + ".cmd", args)
    if not ok:
        req.ok = False
        req.detail = "не найден" if not out else f"не сработала: {out[:40]}"
        return req
    version = _version_tuple(out)
    if req.min_version and version and version[0] < req.min_version:
        req.ok = False
        req.detail = f"нужно {req.min_version}+, найдено {version[0]}"
        return req
    if req.max_version and version and version[0] > req.max_version:
        req.ok = False
        req.detail = f"слишком новая: нужно не выше {req.max_version}, найдено {version[0]}"
        return req
    if req.until and version and not versions.until_ok(req.until, version):
        # Строка та, что вернула программа, а не первый кусок: иначе про
        # 2026.2.1.8 человек прочитал бы «слишком новая: 2026» и не понял бы.
        req.ok = False
        req.detail = f"слишком новая: работает до {req.until}, найдено {'.'.join(str(n) for n in version)}"
        return req
    req.ok = True
    req.detail = out.splitlines()[0][:40] if out else "есть"
    return req


def load_extra_programs(base: Path) -> list[ProgramInstall]:
    """Программы вне списка серверов MCP: ставятся в той же вкладке, но
    серверами не являются.

    Отдельный ключ `extra_programs`, а не девятая запись в серверах. Иначе
    xray попал бы в проверку готовности серверов и в отчёт о подключении,
    а он там лишний: он не подключается к программе, а проксирует трафик.
    """
    data = load_registry(base)
    out: list[ProgramInstall] = []
    for raw in data.get("extra_programs") or []:
        if not isinstance(raw, dict):
            continue
        known = {f for f in ProgramInstall.__dataclass_fields__}
        extra = {k: v for k, v in raw.items() if k in known}
        extra.pop("id", None)
        out.append(ProgramInstall(**extra))
    return out


#: Разобранный реестр: ключ — отпечаток файла, значение — серверы.
_LOADED: dict[tuple, list] = {}


def _registry_key(base: Path) -> tuple | None:
    """Отпечаток файла реестра: содержимое, размер и время изменения.

    None, если файла нет или он не читается: тогда кэш не нужен, всё
    равно разбирать нечего.
    """
    path = registry_path(base)
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_size, stat.st_mtime_ns)


def load_servers(base: Path, check: bool = True) -> list[Server]:
    """Читает реестр и проверяет требования каждого сервера.

    Результат запоминается на время работы программы, и ключ — сам
    файл реестра: его содержимое, размер и время изменения. Проверка
    требований зовёт node и npx, это медленно: измерено, что одна
    проверка всех серверов занимает около секунды, а при запуске
    реестр читается пять раз, и каждое чтение платило полной
    проверкой заново. На старте программы это была половина всего
    времени до появления окна.

    `check=False` нужен на ранних шагах запуска, когда живая проверка
    ещё не требуется: миграции блоков настроек достаточно записей
    реестра. Кэш по check=False НЕ читается и НЕ пишется — иначе лёгкий
    вызов отравил бы кэш, и настоящая проверка получила бы пустые
    требования вместо живых. Состояния у таких серверов выходят
    «не проверено», что честно для миграции.

    Почему ключ по файлу, а не по спецификации требования. Проверка
    зависит не только от записи в реестре, но и от того, что стоит на
    машине. Кэш по спецификации устарел бы молча и показал бы
    неверное «готово». Ключ по файлу реестра этого не делает: правка
    реестра меняет ключ, и всё перепроверяется само.
    """
    key = _registry_key(base) if check else None
    if key is not None:
        cached = _LOADED.get(key)
        if cached is not None:
            return list(cached)
    data = load_registry(base)
    result: list[Server] = []
    for spec in data.get("servers") or []:
        if not isinstance(spec, dict):
            continue
        conn = spec.get("connection")
        server = Server(
            id=str(spec.get("id") or ""),
            name=str(spec.get("name") or ""),
            raw=spec,
            has_connection=isinstance(conn, dict) and bool(
                conn.get("command") or conn.get("url") or conn.get("manual_config")
            ),
        )
        if check:
            for item in spec.get("requires") or []:
                if isinstance(item, dict):
                    server.requirements.append(check_requirement(item))
        result.append(server)
    if key is not None:
        _LOADED[key] = list(result)
    return result


# ---------------------------------------------------------- блок настроек


def manual_config_path(dest: Path, server_id: str) -> Path:
    """Куда кладётся конфигурация, вставленная человеком.

    Рядом с opencode.jsonc, то есть в папке настроек пользователя, а не
    в репозитории: токен студии не должен уезжать на GitHub.
    """
    return Path(dest) / f"mcp-{server_id}.json"


def load_manual_config(dest: Path, server_id: str) -> dict | None:
    """Читает вставленную конфигурацию. None, если её нет или она битая."""
    path = manual_config_path(dest, server_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("url") or "").strip()
    headers = data.get("headers")
    if not url or not isinstance(headers, dict):
        return None
    return {"url": url, "headers": {str(k): str(v) for k, v in headers.items()}}


def save_manual_config(dest: Path, server_id: str, text: str) -> tuple[bool, str]:
    """Разбирает вставленную конфигурацию и сохраняет адрес с заголовком.

    Текст берётся как есть из буфера обмена: человек копирует его в
    студии целиком, а разбирать приходится то, что именно скопировали.
    """
    raw = str(text or "").strip()
    if not raw:
        return False, "Пусто: скопируй конфигурацию в студии и вставь сюда."
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, (
            "Это не конфигурация в формате JSON. Скопируй её целиком "
            "кнопкой Copy Config в студии."
        )

    found_url = ""
    found_headers: dict = {}

    def walk(node: object, depth: int = 0) -> None:
        nonlocal found_url, found_headers
        if depth > 6 or not isinstance(node, dict):
            return
        url = node.get("url")
        if isinstance(url, str) and url.strip() and not found_url:
            found_url = url.strip()
            headers = node.get("headers")
            if isinstance(headers, dict) and headers:
                found_headers = {
                    str(k): str(v) for k, v in headers.items() if v
                }
        for value in node.values():
            walk(value, depth + 1)

    walk(data)
    if not found_url:
        return False, (
            "В конфигурации не нашёлся адрес сервера. Обычно он "
            "выглядит как http://localhost:63342/api/mcp."
        )
    path = manual_config_path(dest, server_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"url": found_url, "headers": found_headers},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Не удалось сохранить конфигурацию: {exc}"
    tail = f", заголовков: {len(found_headers)}" if found_headers else ""
    return True, f"Конфигурация сохранена: {found_url}{tail}"


def drop_manual_config(dest: Path, server_id: str) -> bool:
    """Убирает сохранённую конфигурацию. True, если файла уже не было."""
    path = manual_config_path(dest, server_id)
    if not path.is_file():
        return True
    try:
        path.unlink()
        return True
    except OSError:
        return False


def resolve_command(command: list[str]) -> list[str]:
    """Подставляет пути вместо плейсхолдеров в команде запуска.

    Зачем. Реестр едет в публичный репозиторий, поэтому абсолютный путь
    компьютера в нём быть не может: у другого человека он неверен. Но в
    настройки opencode путь надо — иначе мост не запустится. Значит в
    реестре лежат плейсхолдеры, а подстановка происходит здесь, на
    машине человека.

    Плейсхолдеры:
        {PROGRAM}      — папка программы, где лежат мосты и thirdparty
        {DBAPP_PYTHON} — Python, на котором работает сама программа
    """
    if not any(_PLACEHOLDER.search(part) for part in command):
        return list(command)
    from core import find_python, program_root

    root = str(program_root())
    python = str(find_python() or "python")
    out: list[str] = []
    for part in command:
        part = part.replace("{PROGRAM}", root).replace("{DBAPP_PYTHON}", python)
        # Остальные плейсхолдеры ({UV}, {GHIDRA}, {NODE}...) ищет
        # env_setup: это пути, которые у каждого свои. Неразкрытый
        # плейсхолдер оставляем как есть — enable() его поймает и скажет
        # словами, чего не хватило, вместо того чтобы подсунуть в команду
        # мусор, который упадёт позже и непонятно.
        part = _PLACEHOLDER.sub(
            lambda m: env_setup.resolve_placeholder(m.group(1)) or m.group(0),
            part)
        # Разделители в разных частях команды разные: путь программы на
        # Windows приходит с обратными слэшами, а остальное написано с
        # прямыми. В настройках это выглядит неровно, поэтому приводим к
        # одному виду. На других системах ничего не меняется.
        if os.name == "nt":
            part = part.replace("/", "\\")
        out.append(part)
    return out


def quiet_command(command: list[str]) -> list[str]:
    """Оборачивает команду запуска так, чтобы окна консоли не было.

    Зачем. Серверы MCP говорят с opencode через стандартные потоки,
    поэтому их приходится запускать консольными программами — npx,
    uvx, python.exe. На каждом таком запуске Windows выделяет консоль,
    и при старте мостов на экране появляется до десятка чёрных окон
    cmd, причём они живут вместе с серверами.

    Обёртка — наш лаунчер под оконным Python: он скрывает окно и
    передаёт потоки ребёнку как есть. Проверено живьём обменом
    JSON-RPC: три запроса — три верных ответа.

    Повторная обёртка не добавляется: команда, уже ведущая через
    quiet_launcher, остаётся как есть.
    """
    if not command or command[0].lower().endswith(".py"):
        return list(command)
    if any("quiet_launcher" in part for part in command):
        return list(command)
    from core import find_python, program_root
    from pathlib import Path

    python = str(find_python() or "python")
    # pythonw лежит рядом с тем же интерпретатором и не создаёт
    # консоль вообще. Если его нет — берём обычный python: лаунчер
    # всё равно скроет окно, но без окна вовсе лучше.
    pythonw = Path(python).with_name("pythonw.exe")
    runner = str(pythonw) if pythonw.is_file() else python
    launcher = (Path(program_root()) / "tools" / "dbapp" / "launchers"
                / "quiet_launcher.py")
    return [runner, str(launcher), *command]


def expand_url(url: str, server: Server | None = None,
               dest: Path | None = None) -> str:
    """Подставить в адрес то, что знает только машина человека.

    У моста Unreal в адресе стоит `{PORT}`: порт задаёт сам плагин, и
    значение по умолчанию из документации не проверено. Программа спрашивает
    порт у человека и пишет его рядом с настройками — отсюда он и берётся.
    Выдумывать порт по умолчанию нельзя: молчаливый неверный адрес хуже
    явного отказа.
    """
    text = str(url or "")
    if "{PORT}" not in text or server is None:
        return text
    port = 0
    default = 0
    if isinstance(server.raw.get("connection"), dict):
        default = int(server.raw["connection"].get("port_default") or 0)
    if dest is not None:
        import engine_setup  # noqa: PLC0415 — настройки мостов живут там

        try:
            port = engine_setup.read_unreal_port(Path(dest))
        except Exception:  # noqa: BLE001 — нет файла или нет модуля
            port = 0
    if not port:
        port = default
    return text.replace("{PORT}", str(port) if port else "ПОРТ-НЕ-ЗАДАН")


def build_block(server: Server, manual: dict | None = None,
                dest: Path | None = None) -> str:
    """Кусок JSONC для секции mcp в opencode.jsonc. Пусто, если нечего.

    Формат ровно как у ncp_server_block: insert_entry ждёт готовую
    запись целиком — с именем сервера и запятой в конце, — а не только
    значение. Иначе в настройках появится лишняя скобка и файл
    перестанет читаться.
    """
    conn = server.raw.get("connection")
    if not isinstance(conn, dict):
        return ""
    url = str(conn.get("url") or "").strip()
    headers = {}
    if isinstance(manual, dict):
        url = str(manual.get("url") or url).strip()
        headers = manual.get("headers") or {}
    if url:
        body = {"type": "remote", "url": expand_url(url, server, dest),
                "enabled": True}
        if headers:
            body["headers"] = headers
    else:
        command = resolve_command(
            [str(part) for part in (conn.get("command") or [])]
        )
        if not command:
            return ""
        body = {"type": "local", "command": quiet_command(command),
                "enabled": True}
        # Некоторым мостам нужны свои переменные окружения (GHIDRA_MCP_URL
        # у ghidra-mcp). Значения — на этой машине, поэтому плейсхолдеры
        # в них раскрываются так же, как в команде.
        env_map = conn.get("environment")
        if isinstance(env_map, dict) and env_map:
            body["environment"] = {
                str(key): env_setup.expand(str(value))
                for key, value in env_map.items()
            }
    inner = json.dumps(body, ensure_ascii=False, indent=2).splitlines()
    # Первая строка — «{», последняя — «}». Их не берём: свои скобки мы
    # ставим сами, вместе с именем сервера. Если взять и их, в настройках
    # получится «"имя": { { … }, }» и файл перестанет читаться.
    body_lines = "\n".join("    " + line for line in inner[1:-1])
    return f'"{server.id}": {{\n{body_lines}\n  }},'


def is_installed(dest: Path, server_id: str) -> bool:
    """Есть ли уже такой сервер в настройках opencode.

    has_entry ждёт текст самого объекта mcp, а не всего файла, поэтому
    сначала вырезаем объект по его границам.
    """
    from opencode_caps import find_key_object, has_entry  # локальный импорт

    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    bounds = find_key_object(text, "mcp")
    if bounds is None:
        return False
    return has_entry(text[bounds[0]:bounds[1]], server_id)


def _write_config(dest: Path, text: str) -> str:
    """Пишет настройки, предварительно сделав копию. Возвращает путь копии."""
    import time  # только для метки времени

    cfg = Path(dest) / "opencode.jsonc"
    if not cfg.is_file():
        cfg.write_text(
            '{\n  "$schema": "https://opencode.ai/config.json"\n}\n', encoding="utf-8"
        )
    backup_dir = Path(dest) / "_previous-version"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"opencode.jsonc-{stamp}"
    shutil.copy2(cfg, backup)
    cfg.write_text(text, encoding="utf-8")
    return str(backup)


def warm_up(server: Server, progress=None) -> str:
    """Прогревает кэш npx: скачивает пакет заранее, до вписывания блока.

    Зачем это. Первый запуск через npx качает пакет около минуты, а
    opencode на старт сервера даёт 30 секунд и показывает «Не удалось».
    То есть платить за скачивание должен тот, кто его инициирует, а не
    opencode при следующем запуске. Здесь команда стартует, успевает
    скачать и тут же останавливается — кэш прогрет, дальше старт 2–3 с.

    Возвращает пустую строку, если прогрев не нужен или не удался:
    отсутствие прогрева не повод отказывать во включении.
    """
    conn = server.raw.get("connection")
    if not isinstance(conn, dict) or not conn.get("warm_up"):
        return ""
    # Плейсхолдеры разрешаются так же, как при записи в настройки. Без
    # этого прогрев у моста, который запускается лаунчером, пытался бы
    # запустить «{DBAPP_PYTHON}» — то есть ничего, — и сервер выглядел бы
    # неработающим на ровном месте.
    command = resolve_command([str(part) for part in (conn.get("command") or [])])
    if not command:
        return ""

    def say(text: str) -> None:
        if progress:
            progress(text)

    say(f"Первый запуск «{server.name}»: скачиваю пакет, это до минуты…")
    exe = shutil.which(command[0]) or command[0]
    argv = [exe, *command[1:]]
    if exe.lower().endswith((".cmd", ".bat")):
        argv = [os.environ.get("COMSPEC") or "cmd.exe", "/c", exe, *command[1:]]
    # Окружение прогрева — то же, что уедет в настройки. Без этого
    # прогрев моста, который поднимается общим лаунчером, запускал бы
    # лаунчер без MCP_BRIDGE_* и мгновенно получал отказ «запущен без
    # команды», а программа при этом говорила бы «кэш прогрет», ничего
    # не скачав. Проверено на 15 мостах с секретами 23.10.2026.
    env = dict(os.environ)
    env_map = conn.get("environment")
    if isinstance(env_map, dict) and env_map:
        for key, value in env_map.items():
            env[str(key)] = env_setup.expand(str(value))
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            startupinfo=_hidden_startupinfo(), env=env,
        )
    except OSError as exc:
        return f"Прогрев не запустился: {exc}"
    try:
        try:
            proc.wait(timeout=WARM_UP_TIMEOUT)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            # Сервер успешно стартовал и молча ждёт команды — значит
            # пакет уже скачан. Останавливаем, как и планировали.
            proc.kill()
            code = 0
        if code:
            # Прогрев не удался — и говорить «скачан» нельзя: лаунчер
            # мог отказать до скачивания (нет файла секретов). Включению
            # это не мешает, поэтому молчим, как обещает описание выше.
            return ""
        say(f"Пакет «{server.name}» скачан, кэш прогрет.")
        return ""
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _replace_command_array(block: str, command: list[str]) -> str | None:
    """Меняет только массив command внутри нашего блока.

    Зачем так узко. Общая перезапись блока целиком тут не годится: в
    настройках после наших меток остаются одиночные запятые от прежних
    правок, и полная перезапись на них ломает файл — проверено, ошибка
    выходила «после обновления файл не читается — откат», и переписывался
    один сервер из десяти. Точечная замена массива структуру файла не
    трогает вовсе.

    None, если массива в блоке нет.
    """
    at = block.find('"command"')
    if at == -1:
        return None
    open_at = block.find("[", at)
    if open_at == -1:
        return None
    # Ищем закрывающую скобку, считая вложенность и не считая скобки
    # внутри строк: в путях Windows скобок нет, но полагаться на это
    # при разборе чужого файла нельзя.
    depth = 0
    close_at = -1
    in_string = False
    escaped = False
    for pos in range(open_at, len(block)):
        ch = block[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                close_at = pos
                break
    if close_at == -1:
        return None

    # Отступ элементов берём у уже написанных, иначе блок «поедет».
    indent = ""
    for line in block[open_at:close_at].splitlines()[1:2]:
        indent = line[: len(line) - len(line.lstrip())]
    items = ",\n".join(
        f"{indent}{json.dumps(part, ensure_ascii=False)}" for part in command
    )
    return block[: open_at + 1] + "\n" + items + "\n" + block[close_at:]


def quiet_migrate(dest: Path, servers: list[Server]) -> tuple[list[str], str]:
    """Переписывает наши старые блоки так, чтобы окна не появлялись.

    Зачем. Обёртка в quiet_command попадает в настройки только при
    включении сервера. Уже включённые серверы остались со старой
    командой, и opencode по ней запускал npx и python.exe как обычно —
    то есть окна cmd продолжали открываться. Обёртка при этом
    добавлена была, просто никто её не применял к уже готовому файлу.

    Переписываются только наши собственные блоки — те, что между
    метками BEGIN/END. Чужие записи в mcp не трогаются: это не наш
    файл, а общий настройки пользователя.

    Возвращает (сообщения, что делать дальше). Если ничего менять не
    пришлось — второй элемент пустой.
    """
    from opencode_caps import BEGIN_TPL, END_TPL, check_jsonc

    messages: list[str] = []
    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], ""

    changed: list[str] = []
    for server in servers:
        begin = BEGIN_TPL.format(name=f"mcp.{server.id}")
        end = END_TPL.format(name=f"mcp.{server.id}")
        at = text.find(begin)
        if at == -1:
            continue  # блока нет — сервер не включён, трогать нечего
        stop = text.find(end, at)
        if stop == -1:
            continue  # метка не закрыта — лезем руками, а не программой
        block = text[at:stop + len(end)]
        if "quiet_launcher" in block:
            continue  # уже обёрнут
        raw = server.raw.get("connection") or {}
        if raw.get("url") or raw.get("manual_config"):
            continue  # удалённые и ручные настройки не наша забота
        command = quiet_command(
            resolve_command([str(part) for part in (raw.get("command") or [])])
        )
        if not command:
            continue
        new_block = _replace_command_array(block, command)
        if new_block is None:
            continue
        candidate = text[:at] + new_block + text[stop + len(end):]
        if not check_jsonc(candidate):
            continue  # после правки файл не читается — не трогаем вовсе
        text = candidate
        changed.append(server.name)

    if not changed:
        return [], ""
    try:
        backup = _write_config(dest, text)
    except OSError as exc:
        return [f"Не смог сохранить настройки: {exc}"], ""
    messages.append(
        "Переписаны на команды без окна консоли: " + ", ".join(changed)
    )
    messages.append(f"Прежняя версия сохранена: {backup}")
    messages.append(
        "Перезапусти opencode: серверы сейчас работают по старым командам, "
        "окна кончатся только после перезапуска."
    )
    return messages, "restart"


def bridge_versions(server: Server) -> tuple[bool, str]:
    """Что нужно этому мосту: программа, версия сервера, версия плагина.

    Сначала таблица `данные/bridge-versions.json` — она знает все мосты,
    включая те, у которых плагина нет. Раньше проверка касалась только
    мостов с плагином, и мост с неверно закреплённым сервером проходил
    мимо: а ведь рассинхронизация видна именно там.

    Второй слой — указатели плагинов: сервер и плагин обязаны быть из
    одного релиза. Мосты без указателя по существу (OBS, Blender, Roblox)
    проходят честно: сверять нечего, и молчать об этом не нужно.
    """
    import bridge_versions as need_table  # noqa: PLC0415 — модуль программы

    need = need_table.for_bridge(server.id)
    if not need.known:
        return False, need.note
    install = server.program_install
    finder = install.plugin.finder if (install is not None and install.plugin) else ""
    if finder:
        try:
            import editor_plugins  # noqa: PLC0415 — тяжёлый модуль, нужен здесь
        except ImportError as exc:
            return True, (f"указатели плагинов не читаются ({exc}) — "
                          f"сверка версий плагина не выполнена")
        ok_plugin, note_plugin = editor_plugins.bridge_versions(finder)
        if not ok_plugin:
            return False, note_plugin
    return True, "; ".join(need.lines())


def check_registry_pairs(base: Path) -> tuple[bool, str]:
    """Все мосты реестра: сервер и плагин из одного релиза, запись на месте.

    Это проверка «при добавлении моста»: новый мост без записи о версиях
    или с расхождением должен быть виден сразу, а не после первого
    упавшего вызова.
    """
    data = load_registry(base)
    if not isinstance(data, dict) or not data.get("servers"):
        return False, "реестр мостов не читается — сверять нечего"
    problems: list[str] = []
    try:
        import bridge_versions as need_table  # noqa: PLC0415 — модуль программы
        import editor_plugins  # noqa: PLC0415 — тяжёлый модуль, нужен здесь
    except ImportError as exc:
        return True, f"модули программы не импортируются ({exc}) — проверка не выполнена"
    for entry in (data.get("servers") or []):
        server_id = str(entry.get("id") or "")
        need = need_table.for_bridge(server_id, base)
        if not need.known:
            problems.append(need.note)
            continue
        install = entry.get("program_install") or {}
        plugin = install.get("plugin")
        if not isinstance(plugin, dict):
            continue
        finder = str(plugin.get("finder") or "")
        if editor_plugins.without_pointer(finder):
            continue
        if not editor_plugins.family_for(finder):
            problems.append(f"{server_id}: finder «{finder}» не знаком программе — "
                            f"версии плагина никто не сверяет")
            continue
        ok, note_plugin = editor_plugins.bridge_versions(finder)
        if not ok:
            problems.append(f"{server_id}: {note_plugin}")
    if problems:
        return False, ("; ".join(problems[:3])
                       + (f" (ещё {len(problems) - 3})" if len(problems) > 3 else ""))
    return True, "у всех мостов с плагином версии сервера и плагина совпадают"


def enable(dest: Path, server: Server, progress=None) -> tuple[list[str], list[str]]:
    """Включает сервер. Возвращает (сообщения, ошибки).

    Порядок именно такой: сначала проверка требований, потом запись.
    Вписать сервер, который не запустится, хуже, чем не вписать его и
    объяснить, чего не хватает.
    """
    from opencode_caps import check_jsonc, ensure_object, insert_entry

    messages: list[str] = []
    errors: list[str] = []
    if not server.has_connection:
        return ([], ["В реестре нет команды подключения - включать нечем."])
    # Сначала доводим окружение, потом проверяем требования. Обратный
    # порядок бессмыслен: требование «нужен Java 21» не выполнится, пока
    # программа сама не напишет JAVA_HOME, а проверка шла бы перед этим.
    env_spec = server.raw.get("env_setup")
    if isinstance(env_spec, dict) and env_spec:
        report = env_setup.prepare(env_spec, progress=progress)
        messages += [f"{server.name}: {line}" for line in report.lines()]
        if report.failed:
            return (messages, [
                f"{server.name}: окружение не довёл до рабочего — "
                + "; ".join(report.failed)
            ])

    missing = server.missing
    if missing:
        return ([], [f"Не хватает: {', '.join(r.what for r in missing)}"])

    # Версии сервера и плагина обязаны совпадать. Мост с расхождением
    # в настройки не попадает: он поднимется, но каждый вызов будет
    # падать с versionMismatch, и это выглядит как «мост сломан».
    ok_versions, note_versions = bridge_versions(server)
    if not ok_versions:
        return ([], [f"{server.name}: {note_versions}"])

    # Сервер, который настраивается руками: конфигурация лежит
    # рядом с opencode.jsonc. Если её нет - писать нечего: блок
    # без токена заведомо не подключится, и opencode покажет ошибку.
    _conn = server.raw.get("connection") or {}
    is_manual = bool(_conn.get("manual_config"))
    manual = None
    if is_manual:
        manual = load_manual_config(dest, server.id)
        if not manual:
            # Отказ должен говорить правду о том, где берётся конфигурация.
            # Общее «скопируй кнопкой Copy Config» верно для студий и оболочек,
            # но неверно там, где конфигурацию пишет окно программы: у CapCut
            # кнопки Copy Config нет, адрес вписывает «Настроить автоматически».
            # Поэтому реестр может подсказать свой текст — и подсказывает.
            _hint = _conn.get("manual_hint")
            if not isinstance(_hint, str) or not _hint.strip():
                _hint = (
                    "Для этого сервера нужна конфигурация из его программы. "
                    "Включи сервер у себя, скопируй конфигурацию кнопкой "
                    "Copy Config и вставь её здесь через «Включить»."
                )
            return ([], [_hint])
    elif server.blocking_manual:
        return ([], [
            "Сервер без этого работать не будет: "
            + ", ".join(r.what for r in server.blocking_manual)
        ])

    # Плейсхолдер, который не нашлось чем заменить, обязан остановить
    # включение словами. Иначе в настройки попадёт команда с фигурными
    # скобками, opencode её запустит, и человек увидит отказ без причины.
    _conn_cmd = server.raw.get("connection") or {}
    if isinstance(_conn_cmd, dict) and not str(_conn_cmd.get("url") or "").strip():
        _resolved = resolve_command([str(p) for p in (_conn_cmd.get("command") or [])])
        _left = sorted({m for part in _resolved
                        for m in _PLACEHOLDER.findall(part)})
        _left = [f"{{{name}}}" for name in _left]
        if _left:
            return (messages, [
                "на этой машине не нашлось, чем подставить: "
                + ", ".join(_left)
            ])

    block = build_block(server, manual=manual, dest=dest)
    if not block:
        return ([], ["Команда подключения пустая — проверь реестр."])

    # Прогрев до вписывания: иначе opencode на своём старте не дождётся
    # скачивания и покажет «Не удалось».
    note = warm_up(server, progress)
    if note:
        errors.append(note)

    cfg = Path(dest) / "opencode.jsonc"
    try:
        original = cfg.read_text(encoding="utf-8") if cfg.is_file() else "{}"
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"Настройки не прочитались: {exc}"])
    try:
        text = ensure_object(original, "mcp")
        text = insert_entry(text, "mcp", server.id, block)
    except ValueError as exc:
        return ([], [f"Настройки сломаны — правь вручную: {exc}"])
    if not check_jsonc(text):
        return ([], ["После вставки файл перестал читаться — не пишу его."])
    # Перезапись без нужды вредна: opencode следит за файлом и
    # перезапускает серверы MCP на каждое его изменение. Повторное
    # нажатие кнопки, когда блок уже записан, файл трогать не должно —
    # иначе на каждое нажатие рождается новый экземпляр моста, и
    # они копятся до трёх-четырёх копий.
    #
    # Сравниваем не тексты, а смысл: insert_entry при повторе оставляет
    # после себя лишние пустые строки, и побайтовое сравнение всегда
    # считает файл изменившимся.
    from opencode_caps import BEGIN_TPL, END_TPL
    begin = BEGIN_TPL.format(name=f"mcp.{server.id}")
    end = END_TPL.format(name=f"mcp.{server.id}")

    def _norm(chunk: str) -> str:
        # Запятая в конце строки не считается различием: build_block её
        # возвращает, а insert_entry перед записью срезает. Без этого
        # сравнение всегда говорило бы «файл изменился».
        return "\n".join(
            line.strip().rstrip(",")
            for line in chunk.splitlines() if line.strip()
        )

    if begin in original and end in original:
        current = original[original.index(begin) + len(begin):
                           original.index(end)]
        if _norm(current) == _norm(block):
            messages.append(
                f"Сервер «{server.name}» уже записан в настройки — "
                "файл не трогаю, opencode не перезапускаю"
            )
            return messages, errors
    try:
        backup = _write_config(dest, text)
    except OSError as exc:
        return ([], [f"Не записались настройки: {exc}"])
    messages.append(f"Сервер «{server.name}» вписан в настройки opencode")
    messages.append(f"Копия настроек: {backup}")
    if server.manual:
        messages.append(
            "Проверь вручную: "
            + "; ".join(f"{r.what} — {r.note}" for r in server.manual)
        )
    messages.append("Перезапусти opencode: серверы читаются при старте.")
    return messages, errors


def disable(dest: Path, server: Server) -> tuple[list[str], list[str]]:
    """Выключает сервер: убирает его блок из настроек."""
    from opencode_caps import check_jsonc, remove_entry

    messages: list[str] = []
    errors: list[str] = []
    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"Настройки не прочитались: {exc}"])
    if server.id not in text:
        return ([f"Сервер «{server.name}» и так не вписан."], [])
    try:
        text = remove_entry(text, "mcp", server.id)
    except ValueError as exc:
        return ([], [f"Настройки сломаны — правь вручную: {exc}"])
    if not check_jsonc(text):
        return ([], ["После удаления файл перестал читаться — не пишу его."])
    try:
        backup = _write_config(dest, text)
    except OSError as exc:
        return ([], [f"Не записались настройки: {exc}"])
    messages.append(f"Сервер «{server.name}» убран из настроек")
    messages.append(f"Копия настроек: {backup}")
    # Токен - тоже часть включения. Оставлять его на диске после
    # «Выключить» значило бы соврать человеку про то, что он отключил.
    if manual_config_path(dest, server.id).is_file():
        if drop_manual_config(dest, server.id):
            messages.append("Сохранённая конфигурация с токеном удалена.")
        else:
            errors.append(
                "Файл с токеном не удалился: "
                f"{manual_config_path(dest, server.id)}"
            )
    return messages, errors


def _mcp_names(text: str) -> list[str] | None:
    """Имена серверов из настроек или None, если файл не читается."""
    from opencode_caps import strip_jsonc

    try:
        data = json.loads(strip_jsonc(text))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return list(data.get("mcp") or {})


def disable_all(dest: Path) -> tuple[list[str], list[str]]:
    """Отключает ВСЕ серверы разом, включая мосты памяти базы.

    Решение человека: полная чистая листка, после которой остаётся
    включить ровно нужное. Поэтому снимаются и `ncp`, и `pc` — без них
    программа не помнит и не читает компьютер, и об этом сказано словами,
    а не остаётся сюрпризом.

    Список берётся из самих настроек, а не из реестра: мосты памяти в
    реестре не значатся, и обход по реестру тихо оставил бы их включёнными
    при кнопке, которая обещает «все».

    Способ — заменить содержимое раздела `mcp` пустым объектом, а не
    вырезать блоки по одному. Вырезание по одному опирается на метки
    программы, а блок может быть написан руками: такой молча не
    вырезался, и кнопка рапортовала об успехе, ничего не сделав. Здесь
    результат не зависит от того, чьей рукой написан блок, — и он
    проверяется: после записи раздел `mcp` обязан быть пустым.

    Копия настроек делается одна, до записи, а не по одной на сервер:
    иначе на диске остаётся десяток почти одинаковых копий.

    Настоящие настройки эта функция не проверяет и не трогает — вызывающий
    код обязан передать копию, если проверяет.
    """
    from opencode_caps import check_jsonc, find_key_object

    messages: list[str] = []
    errors: list[str] = []
    cfg = Path(dest) / "opencode.jsonc"
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ([], [f"Настройки не прочитались: {exc}"])
    names = _mcp_names(text)
    if names is None:
        return ([], ["Настройки не читаются — правь вручную, я их не трогал."])
    if not names:
        return (["В настройках нет ни одного сервера — отключать нечего."],
                [])

    bounds = find_key_object(text, "mcp")
    if bounds is None:
        return ([], ["Раздел mcp в настройках не найден — не трогал."])
    # Границы — это индексы САМИХ скобок, а ключ "mcp" стоит перед ними.
    # Поэтому меняется только содержимое, иначе ключ продублировался бы.
    updated = text[:bounds[0]] + "{}" + text[bounds[1] + 1:]
    if not check_jsonc(updated):
        return ([], ["После отключения файл перестал читаться — не пишу его."])
    if _mcp_names(updated):
        return ([], ["Раздел mcp не опустел — не пишу настройки."])
    try:
        backup = _write_config(dest, updated)
    except OSError as exc:
        return ([], [f"Не записались настройки: {exc}"])
    messages.append(f"Отключено серверов: {len(names)} — " + ", ".join(names))
    memory = [name for name in names if name in ("ncp", "pc")]
    if memory:
        messages.append(
            f"Сняты и мосты памяти базы ({', '.join(memory)}): навыки, "
            f"агенты и чтение компьютера перестанут работать, пока их не "
            f"включат заново.")
    messages.append(f"Копия настроек: {backup}")
    messages.append("Перезапусти opencode: серверы читаются при старте.")
    return messages, errors


def mark_installed(servers: list[Server], dest: Path) -> None:
    for server in servers:
        server.installed = is_installed(dest, server.id)
