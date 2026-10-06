# -*- coding: utf-8 -*-
"""Проверка цифровой подписи установщика.

Зачем. Установщик, скачанный через чужой прокси, может быть подменён.
Правило плана: подпись проверяется **до** запуска, и сверяется не «есть
ли подпись», а **кто подписал файл**. Подпись бывает и поддельной, поэтому
одного факта её наличия мало.

Почему статусы числами. Windows отдаёт статус как имя перечисления
(`Valid`, `NotSigned`, …), а эти имена локализованы и завтра могут
измениться. Сверять их строками нельзя, поэтому значения зафиксированы
числами, а имена лежат рядом для показа человеку.

Почему сверка словами, а не сравнением строк. Подпись пишет как
`CN=Microsoft Windows, O=Microsoft Corporation`, а в реестре программ
ожидание лежит как `Microsoft Corporation`. Сравнение строк никогда бы не
сошлось. Правило: **все слова ожидания должны найтись среди слов
подписанта**. Отсюда следует и обратное — короткое фактическое имя не
подтверждает длинное ожидание: `CN=Microsoft` не подтверждает
`Microsoft Corporation`, потому что слова `Corporation` в подписанте нет.

Пустое ожидание не проходит: нечего сверять — это «не проверено», а не
«совпало». Иначе программа с незаполненным реестром получала бы
установку любого подписанного файла.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

#: Статусы подписи. Значения сняты через
#: `[enum]::GetNames([System.Management.Automation.SignatureStatus])`
#: и зафиксированы числами намеренно: имена локализованы.
STATUS_VALID = 0
STATUS_UNKNOWN_ERROR = 1
STATUS_NOT_SIGNED = 2
STATUS_HASH_MISMATCH = 3
STATUS_NOT_TRUSTED = 4
STATUS_NOT_SUPPORTED_FILE_FORMAT = 5
STATUS_INCOMPATIBLE = 6

#: Имя статуса по-русски — для показа человеку, не для сверки.
STATUS_NAMES = {
    STATUS_VALID: "подпись действительна",
    STATUS_UNKNOWN_ERROR: "система не смогла прочитать подпись",
    STATUS_NOT_SIGNED: "подписи нет",
    STATUS_HASH_MISMATCH: "подпись не совпадает с содержимым файла",
    STATUS_NOT_TRUSTED: "подпись есть, цепочке доверия не доверяют",
    STATUS_NOT_SUPPORTED_FILE_FORMAT: "файл вообще не подписывается этим способом",
    STATUS_INCOMPATIBLE: "подпись несовместима с этой версией",
}

#: Значение, когда подпись спросить не удалось. Отличается от «сбой»:
#: одно означает «подписи нет», другое — «спросить не вышло».
STATUS_UNREADABLE = -1

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(subject: str | None) -> list[str]:
    """Разбирает строку на слова.

    `CN=A B, O=C` -> `['CN', 'A', 'B', 'O', 'C']`.

    Сравнивать строки целиком нельзя: подпись пишет `CN=Microsoft Windows,
    O=Microsoft Corporation`, а ожидание — `Microsoft Corporation`. Слова
    убирают и порядок, и префиксы, и регистр. Подчёркивание не часть слова:
    в `CN=Some_Company` это один идентификатор, а не два слова.

    Пустая строка и None дают пустой список, а не исключение: отсутствие
    подписанта — обычное дело, а не сбой.
    """
    if not subject:
        return []
    return _WORD.findall(str(subject))


def _appears_in_order(have: list[str], want: list[str]) -> bool:
    """Есть ли want в have как НЕПРЕРЫВНЫЙ кусок.

    Непрерывность — единственное, что отличает одну фирму от
    другой. Мягкое правило «все слова есть где-то» пропускало
    подмену: CN=Microsoft Windows, O=Contoso Corporation содержит
    и Microsoft, и Corporation, но это две разных фирмы в разных полях.
    """
    n, m = len(have), len(want)
    for start in range(n - m + 1):
        if have[start:start + m] == want:
            return True
    return False


def signer_matches(subject: str | None, expected: str | None) -> bool:
    """Сошлось ли имя подписавшего с ожидаемым.

    Правило одно: ожидание непустое и **каждое** его слово встречается
    среди слов подписанта. Отсюда следует всё остальное, что нужно:

      CN=OpenJS Foundation, O=OpenJS Foundation  и  Node.js Foundation -> False
          слова Node нет в подписанте
      CN=Microsoft Windows, O=Microsoft Corporation  и  Google LLC      -> False
      CN=Microsoft  и  Microsoft Corporation                              -> False
          короткое фактическое имя не подтверждает длинное ожидание
      пустое ожидание                                                   -> False
          сверять не с чем
    """
    exp = [w.lower() for w in _tokens(expected)]
    if not exp:
        return False
    have = [w.lower() for w in _tokens(subject)]
    return _appears_in_order(have, exp)


def _ask_system(path: Path) -> tuple[int, str]:
    """Спрашивает у Windows статус подписи и подписанта.

    Возвращает пару (статус, подписант). Статус — число из набора выше
    либо STATUS_UNREADABLE, если спросить не вышло.
    """
    if os.name != "nt":
        return STATUS_UNREADABLE, ""
    # Путь идёт через переменную окружения: при -Command переменная $args
    # не заполняется, PowerShell молча спрашивал подпись у пустого пути,
    # а молчание выглядит как «подписи нет».
    env = dict(os.environ)
    env["DBAPP_SIGN_TARGET"] = str(path)
    script = (
        "$ErrorActionPreference='Stop';"
        "$s=Get-AuthenticodeSignature -LiteralPath $env:DBAPP_SIGN_TARGET;"
        "[int]$s.Status; $s.SignerCertificate.Subject"
    )
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, env=env)
    except (OSError, subprocess.SubprocessError):
        return STATUS_UNREADABLE, ""
    if p.returncode != 0:
        return STATUS_UNREADABLE, ""
    lines = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return STATUS_UNREADABLE, ""
    try:
        status = int(lines[0])
    except ValueError:
        return STATUS_UNREADABLE, ""
    return status, lines[1] if len(lines) > 1 else ""


#: Разрешает ли статус запуск файла. Ключи — статусы, значения — можно ли.
#: Главное свойство: **неизвестность означает отказ**. Статус, который мы
#: не умеем читать, или подпись, которой не доверяют, запускаться не
#: должны. Иначе проверка подписи пропускает ровно те файлы, ради которых
#: и делалась.
STATUS_ALLows = {
    STATUS_VALID: True,
    STATUS_UNKNOWN_ERROR: False,
    STATUS_NOT_SIGNED: False,
    STATUS_HASH_MISMATCH: False,
    STATUS_NOT_TRUSTED: False,
    STATUS_NOT_SUPPORTED_FILE_FORMAT: False,
    STATUS_INCOMPATIBLE: False,
}


class SignatureResult:
    """Итог проверки. Поля — те же, что читает движок вкладки.

    Имена полей зафиксированы проверкой раздела 8н: `status`, `verified`,
    `safe_to_run`, `signer`, `detail`. Переименование ломает не только
    проверку, но и движок, который по ним решает, запускать ли файл.

    Три разных ответа, и их нельзя смешивать:
        verified True    подпись настоящая и подписант тот
        verified False   подпись настоящая, но подписал не тот — не запускать
        verified None    проверить нечем: подписи нет или спросить не вышло
                         и подпись плохая, и сверять не с чем — это один
                         и тот же отказ, но сказать о нём надо по-разному
    """

    __slots__ = ("status", "verified", "safe_to_run", "signer", "detail",
                 "path", "name", "checked")

    def __init__(self, status: int, verified: bool, signer: str,
                 detail: str, path: str, name: str,
                 checked: bool | None = None) -> None:
        self.status = status
        #: Строго True или False, без третьего значения. «Проверить не
        #: чем» передаётся полем checked, а не значением verified:
        #: иначе «нет файла» и «подпись плохая» выглядели бы одинаково,
        #: а разница между ними — разница между «файла нет» и
        #: «файл подменили».
        self.verified = bool(verified)
        self.safe_to_run = self.verified and STATUS_ALLows.get(status, False)
        self.signer = signer
        self.detail = detail
        self.path = path
        self.name = name
        #: Выполнена ли проверка вовсе: систему спросили и она ответила.
        self.checked = (status != STATUS_UNREADABLE) if checked is None \
            else bool(checked)

    def __repr__(self) -> str:
        return (f"<SignatureResult статус={self.status} "
                f"checked={self.checked} verified={self.verified} "
                f"подписал={self.signer!r}>")


def check_signature(path: str | Path,
                    expected_signer: str | None = None) -> SignatureResult:
    """Проверяет подпись файла и сверяет подписанта с ожидаемым.

    Тонкость формулировок. Подпись, которая в порядке, но подписана не тем,
    кем ждали, — это не «плохая подпись». Плохая подпись значит файл
    изменён. Здесь файл цел, и говорить «плохая» нельзя: человек увидит
    и подумает, что файл подменили, а подменили только ожидание.

    Порядок проверок важен: сначала есть ли файл, потом есть ли что
    сверять, и только потом спрашиваем систему. Файл без подписи и файл,
    который нечем сверять, — разные вещи, и система на оба вопроса ответит
    одинаково.
    """
    target = Path(path)

    # 1. Файла нет. Проверка не выполнялась, но и успеха здесь нет.
    if not target.is_file():
        return SignatureResult(STATUS_UNREADABLE, False, "",
                               f"файла нет: {target}", str(target),
                               "файла нет", checked=False)

    # 2. Сверять не с чем. Тоже проверка не выполнялась: систему звать
    #    незачем, всё равно решения нет.
    if not _tokens(expected_signer):
        return SignatureResult(STATUS_UNREADABLE, False, "",
                               "подпись настоящая или нет — но сверять не с "
                               "чем: ожидаемый подписант не задан",
                               str(target), "сверять не с чем", checked=False)

    # 3. Спрашиваем систему.
    status, signer = _ask_system(target)
    name = STATUS_NAMES.get(status, "неизвестный статус")

    # 4. Система не ответила. Это «не знаю», а не «плохая подпись».
    if status == STATUS_UNREADABLE:
        return SignatureResult(status, False, "",
                               "проверка не удалась: систему не удалось "
                               "спросить. Запускать нельзя — но подпись "
                               "плохой не названа: её никто не смотрел",
                               str(target), name, checked=False)

    # 5. Статус, который запускать не разрешает.
    if not STATUS_ALLows.get(status, False):
        return SignatureResult(status, False, signer,
                               f"подпись плохая: {name}. Запускать нельзя",
                               str(target), name, checked=True)

    # 6. Подпись настоящая. Осталось сверить, кто подписал.
    if not signer_matches(signer, expected_signer):
        return SignatureResult(
            status, False, signer,
            f"подпись настоящая, но подписал {signer}, а ждали "
            f"{expected_signer}. Установка не идёт дальше",
            str(target), name, checked=True)

    return SignatureResult(status, True, signer,
                           f"подпись настоящая, подписал {signer}",
                           str(target), name, checked=True)


def describe(result: SignatureResult) -> str:
    """Пересказывает результат человеку.

    Отдельная функция, а не готовый `detail`: движок показывает это в
    карточке рядом с тем, кого ждали и кто подписал на самом деле. Одной
    строкой «отказ» человек ничего не поймёт, а одной строкой
    «подписал OpenJS Foundation, а ждали Node.js Foundation» поймёт всё.

    Порядок слов неслучаен: сначала что случилось, потом кто подписал,
    потом кого ждали.
    """
    if not result.checked:
        # Проверки не было. Обязательно сказать это прямо: иначе
        # «не проверено» читается как «проверено и плохо».
        return (f"Проверка не выполнялась: {result.detail}. "
                f"Ничего не сказано о подписи.")
    if result.verified:
        return f"Подпись настоящая. {result.detail}. Запускать можно."
    return (f"Запускать нельзя. {result.detail}.")


def verify_signature(path: str | Path,
                     expected_signer: str | None = None) -> dict:
    """Проверяет подпись файла и сверяет подписанта с ожидаемым.

    Возвращает словарь:
        status     число из набора STATUS_*, либо STATUS_UNREADABLE
        name       подпись как её показывают человеку
        signer     кто подписал
        expected   кого ждали
        verdict    ok | отказ | нечем
        detail     объяснение человеческим языком

    Три вердикта, и они не одно и то же:
        ok      подпись действительна и подписант сошёлся
        отказ   подпись настоящая, но подписал не тот — установка не идёт
        нечем   сверять нечем: подписи нет либо ожидание не задано
    """
    out = {"status": STATUS_UNREADABLE, "name": "", "signer": "",
           "expected": expected_signer or "", "verdict": "нечем",
           "detail": "", "file": str(path)}

    target = Path(path)
    if not target.is_file():
        out["detail"] = f"файла нет: {target}"
        return out

    status, signer = _ask_system(target)
    out["status"] = status
    out["signer"] = signer
    out["name"] = STATUS_NAMES.get(status, "неизвестный статус")

    if status == STATUS_UNREADABLE:
        out["detail"] = "систему не удалось спросить — проверить нечем"
        return out
    if status != STATUS_VALID:
        # Подпись недействительна. Это «нечем», а не «отказ»: файлом,
        # возможно, никто не подписывал, и виноват не подписант.
        out["detail"] = f"{out['name']}. Сверять подписанта бессмысленно."
        return out
    if not signer_matches(signer, expected_signer):
        if not _tokens(expected_signer):
            out["detail"] = ("подпись действительна, сверять не с чем: "
                             "ожидаемый подписант не задан")
        else:
            out["verdict"] = "отказ"
            out["detail"] = (f"подпись действительна, но подписал {signer}, "
                             f"а ждали {expected_signer}. Установка не идёт "
                             f"дальше.")
        return out

    out["verdict"] = "ok"
    out["detail"] = f"подпись действительна, подписал {signer}"
    return out