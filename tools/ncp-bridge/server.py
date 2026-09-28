# -*- coding: utf-8 -*-
"""Мост между библиотекой NCP и Qwen Desktop.

Обычный сервер MCP, который говорит по стандарту: сообщения JSON-RPC 2.0
через stdin/stdout, по одному в строке. Никаких сторонних пакетов — только
стандартная библиотека Python. Поэтому ничего не нужно устанавливать,
и ничего нельзя сломать в других программах.

Инструменты:
    ncp_status, ncp_search, ncp_save, ncp_read, ncp_update,
    ncp_checkpoint, ncp_reindex — работа с библиотекой NCP;
    memory_save, memory_read, memory_search, memory_log_work — профиль,
    проекты, факты и журнал работы (живут в memory_tools.py);
    library_* — псевдонимы под старыми именами, на которые записаны
    инструкции в базе. Новые тексты должны называть ncp_*.

Режимы запуска:
    server.py               — работа как сервер MCP (так запускает Qwen)
    server.py --install     — найти библиотеку, вписать путь в config.json,
                              прогнать проверку и напечатать инструкцию
    server.py --selftest    — три шага проверки на временной библиотеке
    server.py --print-config — напечатать готовый кусок настроек для Qwen

ВАЖНО: в режиме сервера в stdout нельзя печатать ничего, кроме сообщений
протокола. Все пояснения и ошибки идут в stderr.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import memory_tools  # noqa: E402
import ncp_core  # noqa: E402

CONFIG_FILE = HERE / "config.json"
PLACEHOLDER = "{{LIBRARY}}"

#: Версии протокола, которые понимает мост. Порядок — от новой к старой.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Локальная библиотека NCP: внешняя память пользователя на этом компьютере. "
    "Перед ответом про прошлую работу или сохранённую тему вызови ncp_search, "
    "а важное и стойкое сохраняй через ncp_save. Всё лежит на диске, "
    "в сеть ничего не уходит."
)


def log(text: str) -> None:
    """Пояснения — только в stderr: stdout занят протоколом."""
    try:
        sys.stderr.write(f"[ncp] {text}\n")
        sys.stderr.flush()
    except Exception:
        pass


# ------------------------------------------------------------------ настройки


def read_config() -> dict:
    """Читает config.json. При беде возвращает пустые настройки, не падая."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log(f"config.json не прочитан: {exc}")
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("server_name", "ncp")
    data.setdefault("server_version", "0.1.0")
    data.setdefault("search_limit", 10)
    data.setdefault("allow_save", True)
    return data


def library_path(config: dict) -> str:
    return str(config.get("library_path") or "").strip()


def open_library(config: dict) -> ncp_core.Library:
    """Библиотека из настроек. Если путь не вписан — понятная ошибка."""
    raw = library_path(config)
    if not raw or raw == PLACEHOLDER:
        raise ncp_core.NcpError(
            "В config.json не указан путь к библиотеке. Запустите install.bat "
            "или впишите путь в поле library_path."
        )
    return ncp_core.Library(Path(raw))


def library_candidates() -> list[dict]:
    """Все библиотеки NCP, которые видны рядом. Порядок — от лучшей к худшей.

    Пути нигде не вписаны жёстко, поэтому мост годится для любого
    компьютера и любого имени пользователя.

    Библиотек рядом может оказаться несколько (копии, пробы). Выбор
    объясним: сперва те базы, которыми управляет программа (есть папка
    .workbuddy-ai) и в которых есть profile.md; при равенстве — та, что
    менялась позже, то есть та, с которой сейчас работают.
    """
    roots: list[Path] = []

    def add_children(folder: Path) -> None:
        try:
            items = sorted(folder.iterdir())
        except OSError:
            return
        for item in items:
            if item.is_dir():
                roots.append(item)

    add_children(HERE.parent)  # соседние папки: мост лежит рядом с базой
    roots.append(HERE)  # мост лежит внутри самой базы
    roots.append(HERE.parent)
    home = Path.home()
    for base_dir in (home / "Desktop", home / "Рабочий стол", home):
        if base_dir.is_dir():
            add_children(base_dir)

    seen: set[str] = set()
    found: list[dict] = []
    for root in roots:
        library = root / "библиотека"
        if not (library / "NCP.md").is_file():
            continue
        try:
            key = str(library.resolve()).casefold()
        except OSError:
            key = str(library).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            stamp = root.stat().st_mtime
        except OSError:
            stamp = 0.0
        found.append(
            {
                "library": library,
                "base": root,
                "managed": (root / ".workbuddy-ai").is_dir(),
                "profile": (root / "profile.md").is_file(),
                "mtime": stamp,
            }
        )
    found.sort(
        key=lambda row: (-(int(row["managed"]) * 2 + int(row["profile"])), -row["mtime"])
    )
    return found


def find_library() -> Path | None:
    found = library_candidates()
    return found[0]["library"] if found else None


# ------------------------------------------------------------------ инструменты
#
# ЗДЕСЬ ДОБАВЛЯЮТСЯ НОВЫЕ ИНСТРУМЕНТЫ. Шаги всегда одни и те же:
#   1. в TOOLS — описание и схема аргументов (то, что видит нейросеть);
#   2. в run_tool() — ветка «if name == ...», которая зовёт ncp_core.Library;
#   3. в mode_selftest() — проверка нового инструмента на временной копии;
#   4. в ЧИТАТЬ-МЕНЯ.txt — строка в таблице инструментов.
# Имя инструмента обязано совпадать во всех четырёх местах: иначе он
# будет виден в списке, но не сработает.
#
# Готово (сентябрь 2026): ncp_read, ncp_update, ncp_checkpoint, ncp_reindex.
#
# Соответствие имён. В самом протоколе (библиотека/NCP.md, раздел 8) те же
# операции названы library_*. Здесь они названы ncp_* — так попросил
# пользователь. Это одно и то же, пары такие:
#   ncp_status  = library_status      ncp_read        = library_read
#   ncp_search  = library_search      ncp_update      = library_update
#   ncp_save    = library_save        ncp_checkpoint  = library_checkpoint
#                                     ncp_reindex     = library_reindex
#
# Пара «инструмент виден, но не работает» из этого списка убрана 28.09:
# псевдонимы library_* теперь не описание, а настоящий вызов.


def _alias_spec(old: str, new: str) -> dict:
    """Описание псевдонима: видно в списке, но честно называет настоящее имя."""
    return {
        "name": old,
        "description": (
            f"Псевдоним: то же самое, что {new}. Оставлен, потому что на это имя "
            f"записаны инструкции в базе. В новых записях называй {new}."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
    }


MEMORY_TOOL_SPECS = [
    {
        "name": "memory_save",
        "description": (
            "Сохранить стойкий факт о пользователе в базу OpenCode_Base. Для "
            "долговременных фактов: проекты, предпочтения, правила, решения, "
            "статус работ. Не использовать для временных деталей задачи."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "enum": list(memory_tools.PROFILE_FILES),
                    "description": (
                        "Куда сохранить: profile — о пользователе, "
                        "projects — про проекты, facts — правила и решения"
                    ),
                },
                "text": {"type": "string", "description": "Факт одной фразой на русском"},
            },
            "required": ["file", "text"],
        },
    },
    {
        "name": "memory_read",
        "description": (
            "Прочитать файлы базы памяти OpenCode_Base. Без аргумента читает "
            "все три основных файла."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "enum": list(memory_tools.PROFILE_FILES),
                    "description": "Какой файл прочитать; если не указан — все три",
                },
            },
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Поиск по всей базе памяти OpenCode_Base: профиль, проекты, факты, "
            "папки проектов и журналы нейросетей. Бэкапы и кэши не читаются."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Что искать, без учёта регистра"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_log_work",
        "description": (
            "Зафиксировать выполненную работу по проекту: что сделано, какие "
            "файлы изменены, итог. Вызывать после каждого завершённого этапа."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Что сделано: задачи, изменения, результаты — 1–3 предложения",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Имя проекта из projects/index.json, например opencode-base. "
                        "Обязательно: мост не знает, в какой папке ты работаешь. "
                        "Русское имя «проект» тоже принимается."
                    ),
                },
                "folder": {
                    "type": "string",
                    "description": (
                        "Вместо project можно передать папку, в которой идёт "
                        "работа — проект найдётся по ней. Русское «папка» "
                        "тоже принимается."
                    ),
                },
                "ai": {
                    "type": "string",
                    "description": (
                        "Имя нейросети для папки в проекте. Если не указать — "
                        "«Нейросеть»."
                    ),
                },
            },
            "required": ["text"],
        },
    },
]

ALIAS_TOOL_SPECS = [
    _alias_spec(old, new) for old, new in memory_tools.LIBRARY_ALIASES.items()
]


TOOLS = [
    {
        "name": "ncp_status",
        "description": (
            "Состояние библиотеки NCP: путь, число записей и тем, активная "
            "память, последняя строка журнала. Ничего не меняет. Вызывай "
            "первым, чтобы понять, с чем работаешь."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ncp_search",
        "description": (
            "Поиск по библиотеке NCP: название, теги, тема и текст записей. "
            "Ничего не меняет. Возвращает идентификаторы, пути и отрывки текста."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Что искать: слова или фраза"},
                "limit": {
                    "type": "integer",
                    "description": "Сколько записей вернуть, по умолчанию 10",
                },
                "topic": {"type": "string", "description": "Ограничить одной темой"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ncp_save",
        "description": (
            "Создать запись в библиотеке NCP. Перед созданием проверяет "
            "дубликаты и при похожей записи отказывает. Создание попадает "
            "в журнал. Удаления в библиотеке нет: устаревшее архивируется."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Понятное название записи"},
                "content": {
                    "type": "string",
                    "description": "Само знание: одна самостоятельная мысль или материал",
                },
                "topic": {
                    "type": "string",
                    "description": "Тема — папка внутри «записи». По умолчанию «общее»",
                },
                "type": {
                    "type": "string",
                    "enum": list(ncp_core.ENTRY_TYPES),
                    "description": "Тип записи",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ключевые слова",
                },
                "source": {"type": "string", "description": "Откуда взялось знание"},
                "confidence": {
                    "type": "string",
                    "enum": list(ncp_core.CONFIDENCE_LEVELS),
                    "description": "Насколько знание надёжно",
                },
                "force": {
                    "type": "boolean",
                    "description": "Сохранить даже при похожей записи",
                },
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "ncp_read",
        "description": (
            "Прочитать запись целиком по id или пути: шапка и полный текст. "
            "Ничего не меняет."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id записи или путь (одно из двух)"},
                "path": {"type": "string", "description": "путь записи или id (одно из двух)"},
            },
        },
    },
    {
        "name": "ncp_update",
        "description": (
            "Изменить запись по id. Пустые поля не трогают. Правка отмечается "
            "в разделе «История» и в журнале. Удаления нет."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id записи"},
                "title": {"type": "string", "description": "Новое название"},
                "content": {"type": "string", "description": "Новое содержание"},
                "topic": {"type": "string", "description": "Новая тема (файл переедет)"},
                "type": {
                    "type": "string",
                    "enum": list(ncp_core.ENTRY_TYPES),
                    "description": "Новый тип",
                },
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Новые теги"},
                "source": {"type": "string", "description": "Новый источник"},
                "confidence": {
                    "type": "string",
                    "enum": list(ncp_core.CONFIDENCE_LEVELS),
                    "description": "Новая уверенность",
                },
                "status": {
                    "type": "string",
                    "enum": list(ncp_core.ENTRY_STATUSES),
                    "description": "Новый статус",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "ncp_checkpoint",
        "description": (
            "Записать состояние работы в активную память: дописать (append) "
            "или заменить целиком (replace). Попадает в журнал."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Что запомнить"},
                "mode": {"type": "string", "description": "append или replace"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "ncp_reindex",
        "description": (
            "Перестроить index.json и КАТАЛОГ.md из файлов на диске. "
            "Нужно после ручных правок. Ничего кроме индекса не меняет."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    *MEMORY_TOOL_SPECS,
    *ALIAS_TOOL_SPECS,
]


def render_status(data: dict) -> str:
    lines = [f"Библиотека NCP: {data['library']}"]
    if data["ready"]:
        lines.append(f"Записей: {data['entries']}   Тем: {len(data['topics'])}")
    else:
        lines.append("Папка пока не похожа на библиотеку NCP.")
    if data["topics"]:
        shown = ", ".join(
            f"{topic} ({count})"
            for topic, count in sorted(data["topics"].items(), key=lambda pair: -pair[1])
        )
        lines.append(f"Темы: {shown}")
    else:
        lines.append("Темы: пока ни одной")
    if data["active_memory_lines"]:
        lines.append(f"Активная память: есть, строк {data['active_memory_lines']}")
    else:
        lines.append("Активная память: файл пуст или отсутствует")
    if data["last_journal"]:
        lines.append(f"Последняя строка журнала: {data['last_journal']}")
    for note in data["notes"]:
        lines.append(f"Замечание: {note}")
    return "\n".join(lines)


def render_search(data: dict) -> str:
    if not data["results"]:
        return (
            f"По запросу «{data['query']}» в библиотеке ничего не найдено. "
            "Записей с такими словами нет."
        )
    lines = [f"Найдено записей: {data['count']} по запросу «{data['query']}»"]
    for number, row in enumerate(data["results"], start=1):
        lines.append("")
        lines.append(
            f"{number}. «{row['title']}» — тема «{row['topic']}», "
            f"тип {row['type']}, статус {row['status']}"
        )
        lines.append(f"   обновлено: {row['updated'] or '—'}")
        lines.append(f"   id: {row['id']}")
        lines.append(f"   путь: {row['path']}")
        if row["tags"]:
            lines.append(f"   теги: {', '.join(row['tags'])}")
        if row["snippet"]:
            lines.append(f"   отрывок: {row['snippet']}")
    return "\n".join(lines)


def render_save(data: dict) -> str:
    if not data.get("ok"):
        twin = data.get("duplicate") or {}
        return (
            "Не сохранял: похожая запись уже есть.\n"
            f"Существующая: «{twin.get('title', '—')}»\n"
            f"id: {twin.get('id', '—')}\n"
            f"путь: {twin.get('path', '—')}\n"
            f"причина: {twin.get('reason', '—')}\n"
            "Если это всё-таки новое знание — повтори с force=true."
        )
    entry = data["entry"]
    index = data.get("index") or {}
    lines = [
        f"Запись сохранена: «{entry['title']}»",
        f"тема: {entry['topic']}   тип: {entry['type']}   уверенность: {entry['confidence']}",
        f"id: {entry['id']}",
        f"путь: {entry['path']}",
    ]
    if entry["tags"]:
        lines.append(f"теги: {', '.join(entry['tags'])}")
    if index:
        lines.append(f"в индексе теперь записей: {index.get('count', '—')}")
    return "\n".join(lines)


def render_read(data: dict) -> str:
    lines = [
        f"Запись: «{data['title']}»",
        f"тема: {data['topic']}   тип: {data['type']}   статус: {data['status']}",
        f"создано: {data['created'] or '—'}   обновлено: {data['updated'] or '—'}",
        f"id: {data['id']}",
        f"путь: {data['path']}",
    ]
    if data["tags"]:
        lines.append(f"теги: {', '.join(data['tags'])}")
    lines.append("")
    lines.append(data["body"] or "(пустое содержание)")
    return "\n".join(lines)


def render_update(data: dict) -> str:
    entry = data["entry"]
    return (
        f"Запись обновлена: «{entry['title']}»\n"
        f"тема: {entry['topic']}   тип: {entry['type']}   статус: {entry['status']}\n"
        f"id: {entry['id']}\n"
        f"путь: {entry['path']}"
    )


def tool_result(text: str, data: dict, is_error: bool = False) -> dict:
    """Ответ инструмента: сначала понятный текст, затем точные данные."""
    body = text + "\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
    return {"content": [{"type": "text", "text": body}], "isError": bool(is_error)}


def run_tool(params: dict, config: dict) -> dict:
    """Выполняет инструмент. Ошибка инструмента — не ошибка протокола."""
    name = str(params.get("name") or "")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    # Псевдоним library_* разворачиваем в ncp_* до всего остального,
    # иначе пришлось бы дублировать семь одинаковых веток.
    if name in memory_tools.LIBRARY_ALIASES:
        name = memory_tools.LIBRARY_ALIASES[name]
    try:
        # Инструментам памяти библиотека NCP не нужна — им достаточно
        # папки базы, но путь всё равно проверяем: иначе при неверном
        # config.json ошибка вылезет позже и невнятно.
        raw_path = library_path(config)
        if not raw_path or raw_path == PLACEHOLDER:
            open_library(config)
        if name in ("memory_save", "memory_read", "memory_search", "memory_log_work"):
            base = memory_tools.base_path(Path(raw_path))
            if name == "memory_save":
                answer = memory_tools.memory_save(
                    base,
                    arguments.get("file") or "",
                    arguments.get("text") or "",
                )
            elif name == "memory_read":
                answer = memory_tools.memory_read(base, arguments.get("file") or "")
            elif name == "memory_search":
                answer = memory_tools.memory_search(base, arguments.get("query") or "")
            else:
                answer = memory_tools.memory_log_work(
                    base,
                    arguments.get("text") or arguments.get("описание") or "",
                    # Русские имена тоже принимаем: инструкции в базе
                    # написаны по-русски, и модель может назвать так.
                    project=str(arguments.get("project") or arguments.get("проект") or ""),
                    folder=str(arguments.get("folder") or arguments.get("папка") or ""),
                    ai=str(arguments.get("ai") or arguments.get("нейросеть") or ""),
                )
            # Журнал сессий. Раньше это делал хук события opencode,
            # а в новой схеме плагинов v2 такого хука нет.
            memory_tools.note_session(base, name)
            return tool_result(answer, {"ok": True, "tool": name})
        library = open_library(config)
        if name == "ncp_status":
            data = library.status()
            return tool_result(render_status(data), data)
        if name == "ncp_search":
            query = str(arguments.get("query") or "").strip()
            limit = arguments.get("limit") or config.get("search_limit", 10)
            topic = str(arguments.get("topic") or "").strip()
            rows = library.search(query, limit=limit, topic=topic)
            data = {"query": query, "count": len(rows), "results": rows}
            return tool_result(render_search(data), data)
        if name == "ncp_save":
            if not config.get("allow_save", True):
                return tool_result(
                    "Запись в библиотеку выключена в config.json (allow_save: false).",
                    {"ok": False, "reason": "запись запрещена настройкой"},
                    is_error=True,
                )
            data = library.save(
                title=arguments.get("title") or "",
                content=arguments.get("content") or "",
                topic=arguments.get("topic") or "общее",
                type=arguments.get("type") or "note",
                tags=arguments.get("tags"),
                source=arguments.get("source") or "пользователь",
                confidence=arguments.get("confidence") or "medium",
                force=bool(arguments.get("force")),
            )
            return tool_result(render_save(data), data, is_error=not data.get("ok"))
        if name == "ncp_read":
            want = str(arguments.get("id") or arguments.get("path") or "").strip()
            data = library.read_full(want)
            return tool_result(render_read(data), data)
        if name == "ncp_update":
            if not config.get("allow_save", True):
                return tool_result(
                    "Запись в библиотеку выключена в config.json (allow_save: false).",
                    {"ok": False, "reason": "запись запрещена настройкой"},
                    is_error=True,
                )
            data = library.update(
                id=str(arguments.get("id") or "").strip(),
                title=arguments.get("title") or "",
                content=arguments.get("content") or "",
                topic=arguments.get("topic") or "",
                type=arguments.get("type") or "",
                tags=arguments.get("tags"),
                source=arguments.get("source") or "",
                confidence=arguments.get("confidence") or "",
                status=arguments.get("status") or "",
            )
            return tool_result(render_update(data), data)
        if name == "ncp_checkpoint":
            if not config.get("allow_save", True):
                return tool_result(
                    "Запись в библиотеку выключена в config.json (allow_save: false).",
                    {"ok": False, "reason": "запись запрещена настройкой"},
                    is_error=True,
                )
            data = library.checkpoint(
                text=arguments.get("text") or "",
                mode=arguments.get("mode") or "append",
            )
            return tool_result(data["message"], data)
        if name == "ncp_reindex":
            index = library.rebuild_index()
            data = {"ok": True, "count": index["count"], "topics": index["topics"],
                    "updated": index["updated"]}
            return tool_result(f"Индекс перестроен: записей {index['count']}.", data)
        return tool_result(
            "Неизвестный инструмент: «{0}». Доступны: {1}.".format(
                name, ", ".join(tool["name"] for tool in TOOLS)),
            {"ok": False, "reason": "неизвестный инструмент"},
            is_error=True,
        )
    except memory_tools.MemoryError as exc:
        return tool_result(str(exc), {"ok": False, "reason": str(exc)}, is_error=True)
    except ncp_core.NcpError as exc:
        return tool_result(str(exc), {"ok": False, "reason": str(exc)}, is_error=True)
    except Exception as exc:  # noqa: BLE001 — сервер не должен падать из-за одной ошибки
        log("сбой инструмента:\n" + traceback.format_exc())
        return tool_result(
            f"Непредвиденная ошибка: {exc}", {"ok": False, "reason": repr(exc)}, is_error=True
        )


# ------------------------------------------------------------------ протокол


def pick_protocol(client_version: str) -> str:
    """Отвечаем той версией, которую клиент знает; иначе самой безопасной."""
    if client_version in PROTOCOL_VERSIONS:
        return client_version
    return PROTOCOL_VERSIONS[-1]


def reply(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def fail(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(message: dict, config: dict) -> dict | None:
    """Обрабатывает одно сообщение. Для уведомления возвращает None."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        log(f"уведомление: {method}")
        return None
    if method == "initialize":
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        return reply(
            msg_id,
            {
                "protocolVersion": pick_protocol(str(params.get("protocolVersion") or "")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": config["server_name"],
                    "version": config["server_version"],
                },
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return reply(msg_id, {})
    if method == "tools/list":
        return reply(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        return reply(msg_id, run_tool(params, config))
    if method == "resources/list":
        return reply(msg_id, {"resources": []})
    if method == "prompts/list":
        return reply(msg_id, {"prompts": []})
    return fail(msg_id, -32601, f"Метод не поддерживается: {method}")


def serve() -> int:
    """Основной цикл: строка на вход — строка на выход. Так работает stdio."""
    config = read_config()
    log(f"мост запущен, библиотека: {library_path(config) or 'не указана'}")
    source = sys.stdin.buffer
    sink = sys.stdout.buffer
    for raw in source:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log(f"строка не разобрана как JSON: {line[:200]}")
            continue
        if not isinstance(message, dict):
            log("сообщение не объект — пропущено")
            continue
        try:
            answer = handle(message, config)
        except Exception:  # noqa: BLE001
            log("сбой обработки:\n" + traceback.format_exc())
            if message.get("id") is not None:
                answer = fail(message["id"], -32603, "Внутренняя ошибка сервера")
            else:
                answer = None
        if answer is None:
            continue
        try:
            sink.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))
            sink.flush()
        except (BrokenPipeError, OSError):
            log("канал закрыт — выходим")
            return 0
    log("вход закрыт — выходим")
    return 0


# ------------------------------------------------------------------ режимы


def qwen_config_snippet(config: dict) -> str:
    """Готовый кусок настроек MCP для Qwen Desktop."""
    entry = {
        "ncp": {
            "command": sys.executable,
            "args": [str(HERE / "server.py")],
            "transportType": "stdio",
        }
    }
    return json.dumps(entry, ensure_ascii=False, indent=2)


def mode_install(asked: str) -> int:
    """Находит библиотеку, вписывает путь в config.json, печатает инструкцию."""
    config = read_config()
    library = Path(asked).expanduser() if asked else None
    if library is not None and not (library / "NCP.md").is_file():
        print(f"По пути {library} нет файла NCP.md — это не библиотека NCP.")
        return 2
    if library is None:
        found = library_candidates()
        if not found:
            print(
                "Не нашёл библиотеку NCP.\n"
                "Она должна лежать в папке «библиотека» рядом с базой,\n"
                "и внутри должен быть файл NCP.md.\n"
                "Укажите путь вручную:  server.py --install --library \"путь\""
            )
            return 2
        library = found[0]["library"]
        if len(found) > 1:
            print("Рядом нашлось несколько библиотек NCP:")
            for number, row in enumerate(found, start=1):
                mark = "выбрана" if number == 1 else "      "
                print(f"  [{mark}]  {row['library']}")
            print()
            print("Выбрана самая свежая база, которой управляет программа.")
            print("Если нужна другая, запустите установку с путём:")
            print('  install.bat --library "нужный путь"')
            print()

    config["library_path"] = str(library).replace("\\", "/")
    config["installed_at"] = ncp_core.now_iso()
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Путь к библиотеке записан в config.json:\n  {library}")
    print()
    code = mode_selftest(config)
    print()
    print("=" * 62)
    print(" Что вписать в Qwen Desktop")
    print("=" * 62)
    print("Настройки MCP в самом приложении Qwen отсутствуют: список")
    print("серверов ему передаёт веб-часть. Поэтому:")
    print()
    print("1. Откройте Qwen и поищите раздел про MCP (инструменты/расширения).")
    print("2. Если такой раздел есть — добавьте сервер с именем ncp")
    print("   и вставьте туда настройки ниже.")
    print("3. Если раздела нет — мост уже готов и работает; его можно")
    print("   подключить к любому другому клиенту MCP, поддерживающему stdio.")
    print()
    print(qwen_config_snippet(config))
    print()
    print(f"Проверить мост вручную:  \"{sys.executable}\" \"{HERE / 'server.py'}\" --selftest")
    return code


def _first_text(answer: dict) -> str:
    """Человеческий текст из ответа инструмента, без служебного JSON."""
    blocks = (answer.get("result") or {}).get("content") or []
    for block in blocks:
        text = str(block.get("text") or "")
        if "```json" in text:
            text = text.split("```json", 1)[0]
        if text.strip():
            return text
    return ""


def mode_selftest(config: dict) -> int:
    """Три шага проверки. Идут на временной библиотеке — настоящая не тронута."""
    results: list[tuple[bool, str]] = []

    def check(good: bool, text: str) -> None:
        results.append((bool(good), text))
        print(f"[{'ОК  ' if good else 'СБОЙ'}] {text}")

    print("=" * 62)
    print(" Проверка моста NCP → Qwen")
    print("=" * 62)
    print(f"Настоящая библиотека: {library_path(config) or 'не указана'}")
    print("Проверка идёт на временной копии — настоящую не трогаем.")
    print()

    temp = Path(tempfile.mkdtemp(prefix="ncp-check-"))
    try:
        temp_library = temp / "библиотека"
        temp_library.mkdir(parents=True)
        test_config = dict(config)
        test_config["library_path"] = str(temp_library)

        def call(msg_id: int, name: str, arguments: dict) -> dict:
            answer = handle(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                test_config,
            )
            return answer or {}

        def payload(answer: dict) -> dict:
            """Достаёт точные данные из ответа инструмента."""
            blocks = (answer.get("result") or {}).get("content") or []
            for block in blocks:
                text = str(block.get("text") or "")
                if "```json" in text:
                    chunk = text.split("```json", 1)[1].rsplit("```", 1)[0]
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        return {}
            return {}

        # ---- 0. рукопожатие и список инструментов
        hello = handle(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            test_config,
        ) or {}
        info = (hello.get("result") or {}).get("serverInfo") or {}
        check(info.get("name") == config["server_name"],
              f"рукопожатие прошло, имя сервера: {info.get('name', '—')}")
        check((hello.get("result") or {}).get("protocolVersion") == "2025-06-18",
              "версия протокола согласована")

        listing = handle(
            {"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, test_config
        ) or {}
        names = [tool["name"] for tool in (listing.get("result") or {}).get("tools", [])]
        # Сверяем не список целиком, а наличие каждого: иначе добавление
        # одного инструмента роняет проверку и её приходится чинить
        # вручную вместо того, чтобы просто принять новое имя.
        expected = [
            "ncp_status", "ncp_search", "ncp_save", "ncp_read",
            "ncp_update", "ncp_checkpoint", "ncp_reindex",
            "memory_save", "memory_read", "memory_search", "memory_log_work",
            *memory_tools.LIBRARY_ALIASES.keys(),
        ]
        absent = [name for name in expected if name not in names]
        check(not absent, f"все {len(expected)} инструментов на месте (нет: {absent})")
        check(len(names) == len(expected),
              f"лишних инструментов нет: {len(names)} против {len(expected)}")

        # ---- шаг 1. ncp_status: записей ноль
        ncp_core.Library(temp_library).ensure()
        check((temp_library / "записи").is_dir(),
              "библиотека развёрнута: папки созданы")
        answer = call(1, "ncp_status", {})
        data = payload(answer)
        check(data.get("entries") == 0,
              f"шаг 1: ncp_status на пустой библиотеке — записей {data.get('entries')}")
        check(data.get("ready") is True, "шаг 1: библиотека опознана как NCP")

        # ---- шаг 2. ncp_save: сохраняем тестовую запись
        answer = call(
            2,
            "ncp_save",
            {
                "title": "Проверка моста NCP",
                "content": "Тестовая запись, созданная самопроверкой моста. "
                           "Можно удалить или перенести в архив.",
                "topic": "проверка",
                "type": "note",
                "tags": ["проверка", "мост"],
                "source": "самопроверка",
                "confidence": "high",
            },
        )
        data = payload(answer)
        check(data.get("ok") is True, "шаг 2: ncp_save сохранил запись")
        saved_id = (data.get("entry") or {}).get("id") or ""
        check(bool(saved_id), f"шаг 2: у записи есть id: {saved_id}")
        saved_path = temp_library / str((data.get("entry") or {}).get("path") or "")
        check(saved_path.is_file(), "шаг 2: файл записи действительно появился")
        check((temp_library / "index.json").is_file(),
              "шаг 2: индекс перестроен")

        # ---- шаг 3. ncp_search: находим сохранённое
        answer = call(3, "ncp_search", {"query": "проверка моста"})
        data = payload(answer)
        titles = [row["title"] for row in data.get("results") or []]
        check(data.get("count", 0) >= 1,
              f"шаг 3: ncp_search нашёл записей {data.get('count')}")
        check("Проверка моста NCP" in titles,
              f"шаг 3: среди найденных есть наша запись")

        # ---- 4. защита от дубликата
        answer = call(
            4,
            "ncp_save",
            {"title": "Проверка моста NCP", "content": "Та же самая мысль."},
        )
        data = payload(answer)
        check(data.get("ok") is False, "повтор не создал дубликат")
        check((answer.get("result") or {}).get("isError") is True,
              "отказ по дубликату помечен как ошибка инструмента")
        check((data.get("duplicate") or {}).get("id") == saved_id,
              "в отказе указана существующая запись")

        # ---- 5. журнал
        journal = sorted((temp_library / "журнал").glob("*.md")) if (
            temp_library / "журнал"
        ).is_dir() else []
        text = journal[-1].read_text(encoding="utf-8") if journal else ""
        check("Создана запись" in text, "создание отмечено в журнале")

        # ---- 6. ncp_read: читаем целиком по id
        answer = call(8, "ncp_read", {"id": saved_id})
        data = payload(answer)
        check("Тестовая запись, созданная самопроверкой" in data.get("body", ""),
              "шаг 6: ncp_read вернул полный текст")
        check(data.get("id") == saved_id, "шаг 6: id совпал")

        # ---- 7. ncp_update: меняем название и содержание
        answer = call(9, "ncp_update", {"id": saved_id, "title": "Проверка моста NCP (обновлено)",
                                        "content": "Обновлённый текст самопроверки."})
        data = payload(answer)
        check(data.get("ok") is True, "шаг 7: ncp_update подтвердил правку")
        answer = call(10, "ncp_read", {"id": saved_id})
        data = payload(answer)
        check("Обновлённый текст самопроверки" in data.get("body", ""),
              "шаг 7: перечитали — новый текст на месте")
        check("Изменено." in data.get("body", ""),
              "шаг 7: правка отмечена в истории записи")

        # ---- 8. ncp_checkpoint: точка в активную память
        answer = call(11, "ncp_checkpoint", {"text": "Самопроверка прошла.", "mode": "append"})
        data = payload(answer)
        check(data.get("ok") is True and data.get("lines", 0) >= 1,
              "шаг 8: ncp_checkpoint записал точку")

        # ---- 8б. replace не стирает прежнее: найдено 28.09
        # Режим replace переписывает активную память целиком, и прежний
        # текст раньше просто исчезал — вместе с ним пропадали бы наработки
        # прошлых сессий. Теперь он уходит в библиотека/замены/, и
        # вернуть его можно руками с диска.
        _active = temp_library / "АКТИВНАЯ-ПАМЯТЬ.md"
        _repl = temp_library / "замены"
        answer = call(31, "ncp_checkpoint",
                      {"text": "Новая точка вместо старой.", "mode": "replace"})
        data = payload(answer)
        check(data.get("ok") is True and data.get("mode") == "replace",
              "шаг 8б: ncp_checkpoint заменил активную память")
        _after = _active.read_text(encoding="utf-8")
        check("Новая точка вместо старой." in _after,
              "шаг 8б: новая точка на месте")
        check("Самопроверка прошла." not in _after,
              "шаг 8б: память заменена, а не дописана — replace работает")
        _kept = sorted(_repl.glob("*.md")) if _repl.is_dir() else []
        check(len(_kept) >= 1,
              f"шаг 8б: прежняя версия сохранена в замены ({len(_kept)} шт.)")
        _restore = _kept[-1].read_text(encoding="utf-8") if _kept else ""
        check("Самопроверка прошла." in _restore,
              "шаг 8б: в сохранённой версии есть всё, что было до замены")

        # Повторная замена не затирает первую копию: обе лежат рядом.
        call(32, "ncp_checkpoint", {"text": "Третья точка.", "mode": "replace"})
        _kept2 = sorted(_repl.glob("*.md")) if _repl.is_dir() else []
        check(len(_kept2) > len(_kept),
              f"шаг 8б: каждая замена хранит свою прежнюю версию "
              f"({len(_kept)} → {len(_kept2)})")

        # ---- 8в. темы-папки: категория создаётся сама
        # Человек попросил: разносить данные по категориям и создавать
        # папку, если её нет. Проверяем на временной библиотеке, где
        # папки заведомо не было.
        _new_folder = temp_library / "записи" / "личное" / "проверка"
        check(not _new_folder.exists(),
              "темы личное/проверка до сохранения ещё нет")
        answer = call(33, "ncp_save", {
            "title": "Проверка вложенной темы",
            "content": "Запись в несуществующую вложенную тему.",
            "topic": "личное/проверка",
            "type": "note",
            "force": True,
        })
        data = payload(answer)
        check((answer.get("result") or {}).get("isError") is not True,
              "шаг 8в: запись во вложенную тему сохранилась")
        check(_new_folder.is_dir(),
              f"папка категории создана автоматически: {_new_folder}")
        _made = list(_new_folder.glob("*.md")) if _new_folder.is_dir() else []
        check(len(_made) == 1,
              f"файл записи лежит во вложенной папке: {[p.name for p in _made]}")

        # Глубже двух уровней — нельзя, это защита от выхода за папку.
        answer = call(34, "ncp_save", {
            "title": "Слишком глубокая тема", "content": "x",
            "topic": "a/b/c", "type": "note", "force": True,
        })
        check((answer.get("result") or {}).get("isError") is True,
              "шаг 8в: три уровня отклонены")
        _deep = (temp_library / "записи" / "a").exists()
        check(not _deep, "папка от отклонённой темы не создалась")
        answer = call(35, "ncp_save", {
            "title": "Попытка вылезти", "content": "x",
            "topic": "../выход", "type": "note", "force": True,
        })
        check((answer.get("result") or {}).get("isError") is True,
              "шаг 8в: выход за пределы отклонён")
        check(not (temp_library / "записи" / "выход").exists(),
              "ничего не записалось вне запис��й")

        # ---- 8г. служебные файлы не считаются записями
        # Ошибка была моя: пояснение _О-ПАПКЕ.md в записей/личное/ начало
        # считаться записью, и счётчик показывал лишнее. Имя с подчёркиванием
        # — служебное, это уже действующее правило проекта.
        _hint = temp_library / "записи" / "личное" / "_О-ПАПКЕ.md"
        _hint.parent.mkdir(parents=True, exist_ok=True)
        _hint.write_text("# О папке — личное\n\nПояснение папки.\n",
                         encoding="utf-8")
        _dot = temp_library / "записи" / "общее" / ".скрытый.md"
        _dot.parent.mkdir(parents=True, exist_ok=True)
        _dot.write_text("скрытый\n", encoding="utf-8")
        # Объекта библиотеки у самопроверки нет — она работает через
        # вызовы инструментов, поэтому счёт берём из index.json.
        _idx_file = temp_library / "index.json"
        _before = json.loads(_idx_file.read_text(encoding="utf-8")).get("count", 0)
        call(36, "ncp_reindex", {})
        _after = json.loads(_idx_file.read_text(encoding="utf-8")).get("count", 0)
        check(_after == _before,
              f"шаг 8г: служебные файлы не попали в счёт ({_before} → {_after})")
        _cat = (temp_library / "КАТАЛОГ.md").read_text(encoding="utf-8")
        check("О папке" not in _cat and "скрытый" not in _cat,
              "шаг 8г: в каталоге служебных файлов нет")
        _hint.unlink()
        _dot.unlink()

        # ---- 9. ncp_reindex: перестройка индекса
        (temp_library / "index.json").write_text("{}", encoding="utf-8")
        answer = call(12, "ncp_reindex", {})
        data = payload(answer)
        check(data.get("ok") is True and data.get("count", 0) >= 1,
              f"шаг 9: ncp_reindex восстановил индекс (записей {data.get('count')})")

        # ---- 10. ncp_read чужого id — вежливый отказ
        answer = call(13, "ncp_read", {"id": "ncp-нет-такого"})
        check((answer.get("result") or {}).get("isError") is True,
              "шаг 10: чтение несуществующего — ошибка инструмента, не падение")

        # ---- 6. защита от чужой папки
        stranger = temp / "чужая папка"
        stranger.mkdir(parents=True)
        (stranger / "важное.txt").write_text("не трогать", encoding="utf-8")
        stranger_config = dict(config)
        stranger_config["library_path"] = str(stranger)
        guarded = payload(
            handle(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "ncp_save",
                        "arguments": {"title": "Проба", "content": "Проба"},
                    },
                },
                stranger_config,
            ) or {}
        )
        check(guarded.get("ok") is False,
              "в чужую непустую папку запись не проходит")
        check(not (stranger / "записи").exists(),
              "в чужой папке ничего не создано")

        # ---- 11-14. инструменты работы с базой. Временная база — это
        # temp/библиотека, поэтому её родитель и есть «база» для них.
        temp_base = temp_library.parent
        answer = call(20, "memory_save", {"file": "facts", "text": "Факт самопроверки моста"})
        text = _first_text(answer)
        check("facts.md" in text, f"шаг 11: memory_save ответил: {text[:60]}")
        check("Факт самопроверки моста" in (temp_base / "facts.md").read_text(encoding="utf-8"),
              "шаг 11: факт записан в файл")

        answer = call(21, "memory_save", {"file": "facts", "text": "Факт самопроверки моста"})
        check("уже есть" in _first_text(answer), "шаг 11: повтор не создал дубль")

        answer = call(22, "memory_read", {"file": "facts"})
        check("Факт самопроверки моста" in _first_text(answer),
              "шаг 12: memory_read вернул записанный факт")

        answer = call(23, "memory_search", {"query": "Факт самопроверки"})
        check("facts.md:" in _first_text(answer),
              "шаг 13: memory_search нашёл факт с указанием файла и строки")

        # Проекта во временной базе нет, поэтому memory_log_work обязан
        # спросить, а не молча записать не туда.
        answer = call(24, "memory_log_work", {"text": "Работа самопроверки"})
        check("Не понял" in _first_text(answer) or "проект" in _first_text(answer).lower(),
              "шаг 14: без проекта memory_log_work спросил, а не испортил")

        (temp_base / "projects").mkdir(parents=True, exist_ok=True)
        (temp_base / "projects" / "index.json").write_text(
            json.dumps({"проба": {"path": str(temp_base), "created": "2026-09-28"}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        answer = call(25, "memory_log_work",
                      {"text": "Работа самопроверки", "project": "проба", "ai": "Самопроверка"})
        check("work.md" in _first_text(answer), "шаг 14: memory_log_work записал по имени проекта")
        work = temp_base / "projects" / "проба" / "Самопроверка" / "work.md"
        check(work.is_file() and "Работа самопроверки" in work.read_text(encoding="utf-8"),
              "шаг 14: журнал работы на диске")

        # Псевдонимы обязаны быть настоящими инструментами, а не строчками
        # в документации: именно на них записаны инструкции в базе.
        for alias in memory_tools.LIBRARY_ALIASES:
            answer = call(30, alias, {"query": "проверка"})
            bad = "Неизвестный инструмент" in _first_text(answer)
            check(not bad, f"псевдоним {alias} работает")
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    failed = [text for good, text in results if not good]
    print()
    print("=" * 62)
    if failed:
        print(f" ИТОГ: провалено {len(failed)} из {len(results)}")
        for text in failed:
            print(f"   - {text}")
        print("=" * 62)
        return 1
    print(f" ИТОГ: все {len(results)} проверок пройдены")
    print("=" * 62)
    return 0


def mode_print_config() -> int:
    print(qwen_config_snippet(read_config()))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Мост между библиотекой NCP и Qwen Desktop (MCP, stdio)."
    )
    parser.add_argument("--install", action="store_true",
                        help="найти библиотеку, записать config.json и проверить мост")
    parser.add_argument("--selftest", action="store_true",
                        help="проверить три инструмента на временной библиотеке")
    parser.add_argument("--print-config", action="store_true",
                        help="напечатать готовые настройки MCP для Qwen")
    parser.add_argument("--library", default="",
                        help="путь к папке библиотеки (для --install)")
    args = parser.parse_args(argv)

    if args.install:
        return mode_install(args.library)
    if args.selftest:
        return mode_selftest(read_config())
    if args.print_config:
        return mode_print_config()
    return serve()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
