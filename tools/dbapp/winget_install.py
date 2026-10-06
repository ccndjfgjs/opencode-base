# -*- coding: utf-8 -*-
"""Запуск winget из вкладки «Программы».

Этап 5 раздела 7 плана. Модуль собирает команду, запускает её и читает
вывод — ничего не зная о том, какая программа ставится. Идентификатор
приходит из реестра и подставляется в список аргументов, а не в строку
команды: склейка строк здесь означала бы, что значение из файла может
стать командой.

**Прав администратора модуль не берёт сам.** Реестр честно помечает
Blender и Adobe как `needs_admin`, но окно UAC неожиданно всплывать не
должно (раздел 14.5 плана), а поднимать процесс от имени всего
приложения — значит получить права там, где человек их не давал.
Поэтому команда запускается как есть: если пакет требует прав, winget
запросит их сам и покажет окно. Если установщик отказал из-за прав —
модуль говорит об этом прямо и даёт готовую команду с `--scope machine`,
которую человек запустит сам.

**Успех определяется не по коду возврата, а по факту.** winget местами
возвращает 0, не сделав ничего, а код «уже установлено» для нас не
ошибка. Поэтому после запуска проверку повторяют по-настоящему — так
и делает вызывающий код через `programs.server_views`. Этот модуль честно
возвращает и код, и вывод, и не делает вид, что проверил факт.
"""

from __future__ import annotations

import re
import shutil


#: Токен версии в выводе winget: цифры с точками и ничего больше.
#:
#: Колонку источника (`winget`, `msstore`) отбрасывать не пришлось: там
#: буквы, а токен версии требует цифр с точками, и булавы с цифрами не
#: пересекаются. Проверено откатом — снятие отбрасывания не изменило
#: ни одного разбора. Запись, которую ничем не сломать, не защищает, а
#: обещает; её убрали, а не оставили для вида.
VERSION_TOKEN = __import__("re").compile(r"\d+(?:\.\d+)+")

#: Сколько ждём ЧТЕНИЕ состояния. Отдельное от установки время, и это не
#: придирка: установка качает сотни мегабайт, а `list` и `show` отвечают за
#: секунды. Единый час на чтение означал бы, что вкладка замрёт на час там,
#: где winget просто не отвечает.
READ_TIMEOUT_SECONDS = 120

#: Ответы winget «обновлять нечего» — разные для обновления и возврата.
_ALREADY_UPDATE = ("no applicable upgrade", "нет применимых обновлений",
                   "уже установлено", "already installed")
_ALREADY_INSTALL = _ALREADY_UPDATE


def _run_install(argv: list[str], *, progress, already_markers, word: str) -> InstallResult:
    """Общий запуск установки, обновления и возврата версии.

    Три команды, одна механика: запуск, разбор отказа по правам, честный
    текст. Различаются они только аргументами и словами — и это лучше, чем
    три копии одного и того же разбора вывода.
    """
    def say(text: str) -> None:
        if progress:
            progress(text)

    say(word.split()[0] + ": запускаю winget " + argv[1])
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                             timeout=TIMEOUT_SECONDS, encoding="utf-8",
                             errors="replace")
    except subprocess.TimeoutExpired:
        return InstallResult(error=f"winget не закончил за {TIMEOUT_SECONDS} секунд")
    except OSError as exc:
        return InstallResult(error=f"запустить winget не удалось: {exc}")
    lines = [ln.rstrip() for ln in (done.stdout or "").splitlines() if ln.strip()]
    low = " ".join(lines).lower()
    result = InstallResult(
        ok=done.returncode == 0,
        code=done.returncode,
        lines=lines,
        tail=" | ".join(lines[-3:])[:300],
    )
    if any(marker in low for marker in already_markers):
        result.already = True
    if _looks_like_rights(low):
        result.needs_rights = True
    say(f"выполнено: код {done.returncode}")
    return result

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Сколько ждём установку. winget качает сотни мегабайт, но час — это
#: уже не установка, а зависание; по истечении говорим об этом прямо.
TIMEOUT_SECONDS = 3600


@dataclass
class InstallResult:
    """Что получилось. Ни одно поле не врёт: код — это код winget."""

    ok: bool = False
    code: int = -1
    already: bool = False               # winget сказал «уже установлено»
    needs_rights: bool = False          # отказ из-за прав, а не из-за сети
    lines: list[str] = field(default_factory=list)
    tail: str = ""                     # последние строки вывода — для показа
    error: str = ""                    # сбой самого запуска

    def describe(self) -> str:
        """Одна строка для человека — живым языком, не кодом."""
        if self.error:
            return f"запуск не удался: {self.error}"
        if self.already:
            return "уже было установлено"
        if self.ok:
            return "установлено"
        if self.needs_rights:
            return ("установщик запросил права и не получил их. Запусти "
                    "вручную с правами администратора — команда показана "
                    "рядом")
        if not self.tail:
            return f"winget закончил с кодом {self.code}, но ничего не написал"
        return f"winget закончил с кодом {self.code}: {self.tail}"


def winget_path() -> str:
    """Где лежит winget. Пустая строка — его нет на машине."""
    return shutil.which("winget") or ""


def available() -> bool:
    """Есть ли winget. Без него вкладка обязана сказать об этом, а не
    показывать кнопку, которая ничего не сделает."""
    return bool(winget_path())


def build_command(winget_id: str, *, machine: bool = False) -> list[str]:
    """Команда установки. Список аргументов, не строка.

    Идентификатор из реестра подставляется значением аргумента, поэтому
    пробелы, кавычки и `&` в нём ничего не сломают: командой станет
    только то, что здесь перечислено.

    `--exact` обязателен: без него winget ищет по похожему имени и
    ставит не то. `--accept-*-agreements` — иначе установщик остановится
    на вопросе о согласии, а вопрос задаётся в консоли, которой у
    человека нет.
    """
    exe = winget_path() or "winget"
    out = [
        exe, "install",
        "--id", str(winget_id),
        "--exact",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    if machine:
        out.append("--scope")
        out.append("machine")
    return out


def command_text(winget_id: str, *, machine: bool = False) -> str:
    """Команда строкой — чтобы показать человеку и положить в буфер."""
    return " ".join(build_command(winget_id, machine=machine))


#: Признаки отказа именно из-за прав, а не из-за сети или иных причин.
_RIGHTS_MARKERS = (
    "access is denied",
    "requires elevation",
    "elevat",
    "нужны права",
    "отказано в доступе",
    "elevated",
)


def _looks_like_rights(text: str) -> bool:
    low = text.casefold()
    return any(marker in low for marker in _RIGHTS_MARKERS)


def install(winget_id: str, progress=None, *, machine: bool = False) -> InstallResult:
    """Поставить программу. Молчания нет: всё, что сказал winget, отдаётся.

    `progress` получает каждую строку вывода, чтобы карточка могла
    показывать ход дела. Ошибки запуска не проглатываются — они попадают
    в `error`, иначе пустое окно выглядело бы как «установлено».
    """
    if not winget_id:
        return InstallResult(error="в реестре нет идентификатора winget")
    if not available():
        return InstallResult(
            error="winget на этой машине нет. Он входит в Windows 10 версии "
                   "1809 и новее; обновить Windows или поставить вручную")

    result = InstallResult()
    command = build_command(winget_id, machine=machine)
    try:
        proc = subprocess.Popen(  # noqa: S603 - список аргументов, без shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001 - причину показываем человеку
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            result.lines.append(line)
            if len(result.lines) > 4000:      # иначе память растёт без границ
                result.lines.pop(0)
            if progress is not None:
                progress(line)
        proc.wait(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        result.error = f"установка не закончилась за {TIMEOUT_SECONDS // 60} минут"
        return result
    except Exception as exc:  # noqa: BLE001
        proc.kill()
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.code = proc.returncode
    joined = "\n".join(result.lines)
    low = joined.casefold()
    result.already = any(marker in low for marker in (
        "уже установлено", "already installed", "no applicable upgrade",
    ))
    result.needs_rights = result.code != 0 and _looks_like_rights(joined)
    result.ok = result.code == 0
    result.tail = "\n".join(result.lines[-6:]).strip()
    return result


def check_installed(winget_id: str) -> tuple[bool, str]:
    """Стоит ли пакет по мнению winget. Только чтение, ничего не меняет.

    Нужна карточке, чтобы сказать «уже стоит» до кнопки, и чтобы отметить
    несостоявшийся факт после неудачной установки. При ошибке возвращается
    «не знаю», а не «нет»: разница видна глазом.
    """
    if not winget_id or not available():
        return False, "winget на машине нет"
    command = [winget_path(), "list", "--id", str(winget_id), "--exact"]
    try:
        done = subprocess.run(  # noqa: S603 - список аргументов, без shell
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"winget не ответил: {type(exc).__name__}: {exc}"
    output = (done.stdout or "") + (done.stderr or "")
    if winget_id.casefold() in output.casefold():
        return True, "пакет есть в списке winget"
    if "no installed package" in output.casefold() or not output.strip():
        return False, "в списке winget его нет"
    return False, "winget не сказал ни да ни нет — смотри вывод"


# --------------------------------------------------------------- обновление

@dataclass
class RemoteState:
    """Что источник знает об установленной программе.

    Четыре поля — четыре разных состояния, и их нельзя сливать:

    * `seen` — winget вообще знает про эту программу. Не знает значит
      «смотреть некуда», а не «обновлений нет»;
    * `installed` — версия, которую winget считает стоящей;
    * `available` — версия, которую он предлагает. Пусто значит обновлений
      нет, и это правда, а не отсутствие данных;
    * `note` — причина, если что-то пошло не так. Без неё молчание
      выглядело бы как «проверено, обновлений нет».
    """

    seen: bool = False
    installed: str = ""
    available: str = ""
    note: str = ""

    @property
    def update_available(self) -> bool:
        """Есть ли обновление. Сравнение числовое, а не строковое.

        Настоящая ловушка рядом: 24.9.0 **новее** 24.10.0 по числам,
        но как строки «9» больше «10», и строковое сравнение предложило бы
        откатиться не туда. Первая версия примера в этой докстрине
        утверждала обратное — мол, 24.9.0 окажется новее 24.18.0, — и это
        было неверно: 24.18.0 действительно новее 24.9.0, так и отвечает
        числовое сравнение. Примеры берутся из настоящих строк вывода
        winget, а не выдумываются: выдуманный проходит всегда.
        """
        if not (self.installed and self.available):
            return False
        import versions as _vs  # noqa: PLC0415 - лёгкий модуль

        here = _vs.version_tuple(self.installed)
        there = _vs.version_tuple(self.available)
        if not here or not there:
            return False
        return there > here


def _version_tokens(text: str, winget_id: str = "") -> list[str]:
    """Версии из вывода winget: сначала после идентификатора, иначе по форме.

    **Зачем якорь.** Название программы может содержать версию. Живой
    вывод `winget upgrade` на этой машине:

        WinRAR 7.01 (64-разрядная)   RARLab.WinRAR          7.01.0
        Docker Desktop 4.92.0         Docker.DockerDesktop   4.92.0
        Antigravity 2.18.1            Google.Antigravity     2.18.1

    Разбор по форме брал первыми два токена вида «цифры с точками», то
    есть для WinRAR — `7.01` из названия и `7.01.0` настоящую версию.
    Сравнение чисел после этого честно решало, что (7, 1, 0) новее
    (7, 1), и программа предлагала обновить WinRAR до несуществующей
    версии.

    **Почему якорь надёжен.** Идентификатор мы сами передали в `--id`, и
    он возвращается в своей колонке. Всё, что стоит после него, —
    версии; всё, что до него, — название, а в названии числа законны.

    **Почему вторая фильтрация не понадобилась.** Колонка источника
    состоит из букв, а токен версии требует цифр с точками, поэтому
    `winget`, `msstore` и прочие названия источников в версии не попадают
    сами. Проверялось откатом: с отбрасыванием источника и без него
    разборы совпадали до символа.

    **Без якоря** разбор идёт по форме числа: заголовки переводятся, а
    числа нет, так что список колонок в коде протух бы молча. Такой
    разбор нужен для `winget show --versions`, где колонки с ИД нет
    вовсе: там заголовок, черточки и просто список версий.
    """
    out: list[str] = []
    in_data = False
    for line in text.splitlines():
        if not in_data:
            # Шапка и черточки пропускаются, а не обрывают разбор. Раньше
            # здесь стоял `break`, и токены собирались из заголовка, а
            # строки с данными не читались вовсе: пустой список молчал, и
            # кнопка обновления просто не появлялась.
            if "-" * 5 in line:
                in_data = True
            continue
        if not line.strip():
            continue
        tokens = line.split()
        start = 0
        if winget_id:
            try:
                start = tokens.index(str(winget_id)) + 1
            except ValueError:
                start = 0      # якоря нет — разбор по форме, как раньше
        for token in tokens[start:]:
            if VERSION_TOKEN.fullmatch(token):
                out.append(token)
    return out


def build_list_command(winget_id: str) -> list[str]:
    """Команда чтения состояния. Ничего не меняет — только list."""
    exe = winget_path() or "winget"
    return [exe, "list", "--id", str(winget_id), "--exact",
            "--accept-source-agreements", "--disable-interactivity"]


def remote_state(winget_id: str) -> RemoteState:
    """Что стоит и что доступно. Живой запрос, ничего не меняющий."""
    if not available():
        return RemoteState(note="winget на машине нет — обновления не проверить")
    try:
        done = subprocess.run(
            build_list_command(winget_id), capture_output=True, text=True,
            timeout=READ_TIMEOUT_SECONDS, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return RemoteState(note=f"winget не ответил: {exc}")
    out = (done.stdout or "") + (done.stderr or "")
    low = out.lower()
    if "не найдены пакеты" in low or "no installed package" in low \
            or "no packages found" in low:
        return RemoteState(note=(
            "winget не считает эту программу установленной. Значит, она "
            "ставлена была не через winget, и список обновлений её не "
            "покажет"))
    tokens = _version_tokens(out, winget_id)
    if not tokens:
        return RemoteState(seen=True,
                           note="winget не назвал версию — обновления не проверить")
    return RemoteState(seen=True, installed=tokens[0],
                       available=tokens[1] if len(tokens) > 1 else "")


def build_upgrade_command(winget_id: str, *, machine: bool = False) -> list[str]:
    """Команда обновления. Список аргументов — по тем же причинам, что и
    у команды установки: идентификатор из реестра не должен попасть в
    строку, а `--exact` обязателен, иначе обновится не та программа."""
    exe = winget_path() or "winget"
    out = [exe, "upgrade", "--id", str(winget_id), "--exact",
           "--accept-package-agreements", "--accept-source-agreements",
           "--disable-interactivity"]
    if machine:
        out += ["--scope", "machine"]
    return out


def upgrade(winget_id: str, progress=None, *, machine: bool = False) -> InstallResult:
    """Обновляет программу. Отдельная функция, а не флаг у install:
    обновление и установка — разные действия с разными последствиями, и
    смешивать их значит забыть одну из проверок."""
    return _run_install(build_upgrade_command(winget_id, machine=machine),
                        progress=progress, already_markers=_ALREADY_UPDATE,
                        word="обновлено")


def build_install_version_command(winget_id: str, version: str, *,
                                  machine: bool = False) -> list[str]:
    """Команда возврата к конкретной версии.

    Номер версии идёт отдельным аргументом `--version`, а не дописывается
    к идентификатору: иначе значение из реестра снова оказалось бы частью
    командной строки.
    """
    exe = winget_path() or "winget"
    out = [exe, "install", "--id", str(winget_id), "--version", str(version),
           "--exact", "--accept-package-agreements",
           "--accept-source-agreements", "--disable-interactivity"]
    if machine:
        out += ["--scope", "machine"]
    return out


def install_version(winget_id: str, version: str, progress=None, *,
                    machine: bool = False) -> InstallResult:
    """Возвращает указанную версию. Откат одной кнопкой."""
    if not str(version).strip():
        return InstallResult(error="не указано, к какой версии возвращаться")
    return _run_install(
        build_install_version_command(winget_id, version, machine=machine),
        progress=progress, already_markers=_ALREADY_INSTALL,
        word="возвращена версия " + str(version))


def build_show_versions_command(winget_id: str) -> list[str]:
    """Команда перечисления версий источника."""
    exe = winget_path() or "winget"
    return [exe, "show", "--id", str(winget_id), "--exact", "--versions",
            "--accept-source-agreements", "--disable-interactivity"]


def catalog_versions(winget_id: str) -> list[str]:
    """Какие версии вообще есть в источнике. Только чтение.

    Нужна для одного честного отказа: версия, которую мы записали перед
    обновлением, могла уйти из каталога. Предлагать откат на такую версию
    нельзя — человек нажмёт и получит отказ вместо возврата.
    """
    if not available():
        return []
    try:
        done = subprocess.run(
            build_show_versions_command(winget_id), capture_output=True,
            text=True, timeout=READ_TIMEOUT_SECONDS, encoding="utf-8",
            errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    return _version_tokens((done.stdout or "") + (done.stderr or ""))


def version_offered(winget_id: str, version: str) -> bool:
    """Есть ли эта версия в источнике прямо сейчас."""
    want = str(version or "").strip()
    if not want:
        return False
    offered = catalog_versions(winget_id)
    if not offered:
        return False
    return want in offered
