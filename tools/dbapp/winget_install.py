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

import shutil
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
