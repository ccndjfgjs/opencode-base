# -*- coding: utf-8 -*-
"""Проверка конфигурации Telegram-моста: без сети, входа и вывода значений.

Зачем отдельный модуль. У моста Telegram секрет — не один токен, а три
вещи: api_id, api_hash и сессия, причём сессию сервер принимает четырьмя
разными способами. Человеку, который правит файл руками, нужно сказать
словами, чего не хватает, — и не сказать при этом ничего лишнего.

Схема сверена с кодом самого сервера (telegram_mcp/runtime.py, коммит
e55d9c7): он читает TELEGRAM_API_ID, TELEGRAM_API_HASH,
TELEGRAM_SESSION_STRING, TELEGRAM_SESSION_STRINGS (пул),
TELEGRAM_SESSION_NAME (файл), а также варианты с суффиксом
TELEGRAM_SESSION_STRING_<МЕТКА> и TELEGRAM_SESSION_NAME_<МЕТКА>.
Имя файла — mcp-telegram.txt — задано реестром в MCP_BRIDGE_SECRETS.

Формат строки сессии — Telethon StringSession (telethon/sessions/string.py):
«1» + base64url(struct «>B{4|16}sH256s»: dc_id, ip, port, 256-байтовый ключ).
Длина 353 для IPv4 и 369 для IPv6.

Три уровня результата, и «готово» среди них нет:
    MISSING      — нет файла или нет обязательных полей;
    BAD_FORMAT   — поля есть, но формат неверный;
    FORMAT_OK    — формат разбирается, но действительность сессии не
                   проверялась: для этого нужен вход в аккаунт.

Значения api_id, api_hash и сессии не попадают ни в результат, ни в
исключения: наружу выходят только имена полей.
"""
from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

#: Имя файла секретов. Совпадает с MCP_BRIDGE_SECRETS в реестре.
FILE_NAME = "mcp-telegram.txt"

MISSING = "missing"
BAD_FORMAT = "bad_format"
PARTIAL = "partial"
FORMAT_OK = "format_ok"

_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_POOL_SPLIT = re.compile(r"[\s,;]+")
_STRING_PREFIX = "TELEGRAM_SESSION_STRING_"
_NAME_PREFIX = "TELEGRAM_SESSION_NAME_"


@dataclass
class CheckResult:
    """Итог проверки: уровень, что не так и что стоит знать."""

    level: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.level == FORMAT_OK

    def short(self) -> str:
        """Короткая строка для колонки состояния."""
        if self.level == MISSING:
            first = self.problems[0] if self.problems else "конфигурация"
            return f"нужно: {first}"
        if self.level == BAD_FORMAT:
            first = self.problems[0] if self.problems else "формат"
            return f"формат: {first}"
        if self.level == PARTIAL:
            # Файл сессии существует, но его содержимое не читалось:
            # «формат верный» тут было бы обещанием, которого нет.
            return "имя допустимо, сессия не проверена"
        return "можно включить (сессия не проверялась)"


def parse_kv(text: str) -> dict[str, str]:
    """KEY=VALUE, # — комментарий. Значения наружу не печатаются."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def string_session_problem(value: str) -> str:
    """Пусто — строка похожа на Telethon StringSession. Иначе — причина."""
    if not value.startswith("1"):
        return ("не похожа на Telethon StringSession: должна начинаться "
                "с «1»")
    if len(value) not in (353, 369):
        return (f"неверная длина строки сессии: {len(value)}, "
                "ожидалось 353 (IPv4) или 369 (IPv6)")
    try:
        raw = base64.urlsafe_b64decode(value[1:])
    except Exception:  # noqa: BLE001 — любая ошибка разбора
        return "строка сессии не разбирается как base64"
    fmt = ">B4sH256s" if len(value) == 353 else ">B16sH256s"
    try:
        dc_id, _ip, port, key = struct.unpack(fmt, raw)
    except struct.error:
        return "строка сессии не разбирается по структуре"
    if not 1 <= dc_id <= 5:
        return f"в сессии неверный dc_id: {dc_id}"
    if not 1 <= port <= 65535:
        return f"в сессии неверный порт: {port}"
    if not any(key):
        return "в сессии пустой ключ"
    return ""


def _session_file_exists(name: str, settings_dir: Path | None) -> bool:
    """Есть ли файл сессии для TELEGRAM_SESSION_NAME.

    Telethon (SQLiteSession.__init__, telethon/sessions/sqlite.py,
    v1.40.0) формирует имя файла как ``session_id`` с добавленным
    ``.session``, если имя ещё не оканчивается на ``.session``. Поэтому
    для «main.db» ищем «main.db.session», а не «main.session», как делал
    бы Path.with_suffix. Относительное имя сервер разрешает от каталога
    запуска, поэтому проверяем и рядом с настройками, и как есть.
    Содержимое не читается и сессия не создаётся.
    """
    if name == ":memory:":
        return True
    path = Path(name)
    candidates = [path] if path.is_absolute() else [path, Path.cwd() / path]
    if settings_dir is not None:
        candidates.append(Path(settings_dir) / path)
    for candidate in candidates:
        s = str(candidate)
        if not s.endswith(".session"):
            s += ".session"
        if Path(s).is_file():
            return True
    return False


def check(path: Path, settings_dir: Path | None = None) -> CheckResult:
    """Проверить файл конфигурации. Ничего не создаёт и не подключается."""
    path = Path(path)
    if not path.is_file():
        return CheckResult(MISSING, [f"нет файла {path.name}"])

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return CheckResult(MISSING, [f"файл {path.name} не читается"])

    values = parse_kv(text)
    problems: list[str] = []
    notes: list[str] = []

    api_id = values.get("TELEGRAM_API_ID", "")
    if not api_id:
        problems.append("не заполнено TELEGRAM_API_ID")
    elif not api_id.isdigit():
        problems.append("TELEGRAM_API_ID должен быть числом")

    api_hash = values.get("TELEGRAM_API_HASH", "")
    if not api_hash:
        problems.append("не заполнено TELEGRAM_API_HASH")
    elif not _HEX32.match(api_hash):
        problems.append("TELEGRAM_API_HASH должен быть 32 hex-символа")

    # Способы сессии — те же, что читает сервер (runtime.py, коммит
    # e55d9c7), и в том же порядке: суффиксные аккаунты → пул → строка →
    # файл. Суффиксные сервер строит все, поэтому проверяются все.
    labelled = 0
    labelled_file = 0
    for key in sorted(values):
        if key.startswith(_STRING_PREFIX) and values[key]:
            labelled += 1
            why = string_session_problem(values[key])
            if why:
                problems.append(f"{key}: {why}")
        elif key.startswith(_NAME_PREFIX) and values[key]:
            labelled += 1
            labelled_file += 1
            if not _session_file_exists(values[key], settings_dir):
                problems.append(f"{key}: нет файла сессии")

    pool = values.get("TELEGRAM_SESSION_STRINGS", "").strip()
    single = values.get("TELEGRAM_SESSION_STRING", "").strip()
    session_name = values.get("TELEGRAM_SESSION_NAME", "").strip()

    # Основная сессия аккаунта default: сервер берёт пул, иначе строку,
    # иначе файл. Поэтому имя файла проверяется только тогда, когда оно
    # действительно пойдёт в дело: иначе несуществующий файл рядом с
    # рабочей строкой давал бы ложную тревогу.
    default_kind = ""
    if pool:
        default_kind = "pool"
        tokens = [t for t in _POOL_SPLIT.split(pool) if t]
        if not tokens:
            problems.append("TELEGRAM_SESSION_STRINGS пуст")
        for index, token in enumerate(tokens, 1):
            why = string_session_problem(token)
            if why:
                problems.append(
                    f"TELEGRAM_SESSION_STRINGS, строка {index}: {why}")
        if len(tokens) > 1:
            notes.append(
                "проверка строже сервера: он берёт первую свободную строку "
                "пула, поэтому битая запись может не проявиться до второго "
                "запуска — здесь она считается ошибкой сразу")
    elif single:
        default_kind = "string"
        why = string_session_problem(single)
        if why:
            problems.append(f"TELEGRAM_SESSION_STRING: {why}")
    elif session_name:
        default_kind = "file"
        if session_name == ":memory:":
            notes.append(
                "сессия в памяти: файла нет по замыслу, но вход не "
                "выполнялся — при запуске Telegram попросит авторизацию")
        elif not _session_file_exists(session_name, settings_dir):
            problems.append("TELEGRAM_SESSION_NAME: нет файла сессии")

    if not default_kind and not labelled:
        problems.append(
            "нет сессии: нужен TELEGRAM_SESSION_STRING, "
            "TELEGRAM_SESSION_STRINGS, TELEGRAM_SESSION_NAME "
            "или вариант с суффиксом")

    if not values.get("TELEGRAM_EXPOSED_TOOLS", "").strip():
        notes.append(
            "TELEGRAM_EXPOSED_TOOLS не задан — мост без предохранителя; "
            "для чтения достаточно TELEGRAM_EXPOSED_TOOLS=read-only")
    if not values.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip():
        notes.append(
            "TELEGRAM_ALLOWED_CHAT_IDS не задан — доступны все чаты аккаунта")

    if problems:
        level = MISSING if all(
            "не заполнено" in p or "нет сессии" in p or "нет файла" in p
            for p in problems) else BAD_FORMAT
        return CheckResult(level, problems, notes)

    if default_kind == "file":
        # Содержимое файла не читалось: он может оказаться и не сессией.
        # Поэтому не «формат верный», а «имя допустимо» — и это видно
        # человеку в колонке состояния.
        notes.append(
            "файл сессии существует, но его содержимое не проверялось: "
            "подходит ли он — покажет только запуск")
        return CheckResult(PARTIAL, [], notes)

    if labelled_file > 0:
        # Суффиксная файловая сессия (TELEGRAM_SESSION_NAME_<МЕТКА>):
        # сервер тоже читает файл, но программа его содержимое не
        # проверяет. Существование файла не доказывает рабочую сессию —
        # поэтому, как и для обычного TELEGRAM_SESSION_NAME, возвращаем
        # PARTIAL, а не FORMAT_OK. Строковые суффиксные сессии
        # (TELEGRAM_SESSION_STRING_<МЕТКА>) проверяются по формату и
        # FORMAT_OK не портят.
        notes.append(
            "суффиксная файловая сессия (TELEGRAM_SESSION_NAME_<МЕТКА>) "
            "найдена, но её содержимое не проверялось: действительна ли "
            "она — покажет только запуск")
        return CheckResult(PARTIAL, [], notes)

    notes.append(
        "формат верный, но действительность сессии не проверялась: "
        "это требует входа в аккаунт, а его программа не делает")
    return CheckResult(FORMAT_OK, [], notes)
