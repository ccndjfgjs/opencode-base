# -*- coding: utf-8 -*-
"""Инструменты памяти OpenCode_Base: профиль, проекты, факты, работа.

Отдельный файл, чтобы server.py не разрастался: там только протокол и
диспетчер, здесь — вся работа с файлами базы.

Почему инструменты здесь, а не в плагине OpenCode. Плагин с версии
opencode 1.18 грузится по новой схеме v2 и обязаны отдавать объект
{id, setup}. Старая форма — функция — отвергается, и всё, что плагин
регистрировал, терялось: 12 инструментов memory_* и library_* просто
переставали существовать, хотя инструкции продолжали их требовать.
Мост — обычный сервер MCP, новой версии opencode не касается, поэтому
инструменты памяти живут здесь.

Про library_*: это те же самые действия, что у ncp_*, только под старым
именем. Имена оставлены как псевдонимы, потому что на них записаны
инструкции в базе. Новые тексты должны называть ncp_*.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

#: Куда пишутся факты, профиль и проекты. Порядок для чтения «без аргументов».
PROFILE_FILES = ("profile", "projects", "facts")

#: Сколько строк показывает поиск по всей базе. Больше — шум.
SEARCH_HIT_LIMIT = 50

#: Сколько папок перебирает поиск вглубь. База должна быть невысокой.
SEARCH_MAX_DEPTH = 6

#: Папки, которые не читаем: бэкапы, кэши, служебное. Иначе поиск
#: вернёт тысячу одинаковых строк из прошлых копий базы.
SKIP_DIRS = {
    ".workbuddy-ai", ".git", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", ".idea", ".vscode",
}

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class MemoryError(Exception):
    """Понятная ошибка инструмента памяти. Сервер её не роняет."""


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def sanitize(name: str) -> str:
    """Имя папки нейросети: буквы, цифры, дефис. Остальное — прочерк."""
    cleaned = _ILLEGAL.sub("-", str(name or "").strip())
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-._")
    return cleaned[:60] or "Нейросеть"


def base_path(library_path: Path) -> Path:
    """Папка базы — родитель папки «библиотека».

    Мост знает только путь к библиотеке, а профиль, факты и проекты лежат
    уровнем выше. Отдельного поля в config.json для этого не заводим:
    при переносе библиотеки внутрь другой базы путь поедет сам.
    """
    return library_path.parent


# ------------------------------------------------------------------- проекты


def read_index(base: Path) -> dict:
    """projects/index.json — карта «имя проекта -> папка на диске»."""
    try:
        data = json.loads((base / "projects" / "index.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _norm(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").casefold()


def find_project(base: Path, project: str = "", folder: str = "") -> tuple[str, str]:
    """Ищет проект по имени или по папке. Возвращает (имя, причина ошибки).

    Мост не знает, в какой папке работает нейросеть, — это видит только
    она сама. Поэтому просим передать «проект» или «папку». Искать
    наугад нечего: индекс проектов может быть пустым или не совпасть.
    """
    index = read_index(base)
    if not index:
        return "", "В базе нет projects/index.json — проекты не заведены."

    if project and project in index:
        return project, ""

    if folder:
        want = _norm(folder)
        for name, info in index.items():
            if isinstance(info, dict) and _norm(info.get("path", "")) == want:
                return name, ""
        # Папка может быть вложена в папку проекта — ищем по началу пути.
        for name, info in index.items():
            if isinstance(info, dict):
                root = _norm(info.get("path", ""))
                if root and (want.startswith(root + "/") or root.startswith(want + "/")):
                    return name, ""

    known = ", ".join(sorted(index)) or "(пусто)"
    if project:
        return "", f"Проекта «{project}» нет в базе. Заведены: {known}."
    return "", f"Не понял, о каком проекте речь. Заведены: {known}."


# ------------------------------------------------------------------ журналы


def note_session(base: Path, tool_name: str, project: str = "") -> None:
    """Отметка активности в журналах. Ошибки молча проглатываются.

    Раньше это делал хук события opencode, но в новой схеме v2 такого
    хука нет. Поэтому пишем при каждом обращении к памяти: сессия, в
    которой память не трогали, в журнале и не нужна.
    """
    month = datetime.now().strftime("%Y-%m")
    try:
        sessions = base / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        with (sessions / f"{month}.md").open("a", encoding="utf-8") as handle:
            handle.write(f"- [{now()}] инструмент `{tool_name}`\n")
    except OSError:
        pass
    if not project:
        return
    try:
        folder = base / "projects" / project
        existing = [d.name for d in folder.iterdir() if d.is_dir()] if folder.is_dir() else []
        if not existing:
            return
        # Журналы ведут папки по именам нейросетей. Имя сессии мосту
        # неизвестно, поэтому берём единственную папку, а если их
        # несколько — не гадаем и не портим чужой журнал.
        if len(existing) != 1:
            return
        target = folder / existing[0] / "sessions.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"- [{now()}] инструмент `{tool_name}`\n")
    except OSError:
        pass


# --------------------------------------------------------------- инструменты


def memory_save(base: Path, file: str, text: str) -> str:
    """Дописать стойкий факт в profile.md, projects.md или facts.md."""
    name = str(file or "").strip()
    if name not in PROFILE_FILES:
        raise MemoryError(
            f"Файл «{name}» неизвестен. Доступны: {', '.join(PROFILE_FILES)}."
        )
    line = str(text or "").strip()
    if not line:
        raise MemoryError("Пустой факт сохранять нечем.")

    target = base / f"{name}.md"
    try:
        old = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        old = ""
    if line in old:
        return f"Такой факт уже есть в {name}.md — пропущен."
    if not old and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("a", encoding="utf-8") as handle:
            if old and not old.endswith("\n"):
                handle.write("\n")
            handle.write(f"- [{today()}] {line}\n")
    except OSError as exc:
        raise MemoryError(f"Не записалось в {name}.md: {exc}") from exc
    return f"Сохранено в {name}.md: {line}"


def memory_read(base: Path, file: str = "") -> str:
    """Прочитать профиль, проекты и факты. Без аргумента — все три."""
    name = str(file or "").strip()
    if name and name not in PROFILE_FILES:
        raise MemoryError(
            f"Файл «{name}» неизвестен. Доступны: {', '.join(PROFILE_FILES)}."
        )
    names = [name] if name else list(PROFILE_FILES)
    blocks = []
    for one in names:
        try:
            text = (base / f"{one}.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        blocks.append(f"===== {one}.md =====\n{text or '(файл пуст или отсутствует)'}")
    return "\n\n".join(blocks)


def memory_search(base: Path, query: str, limit: int = SEARCH_HIT_LIMIT) -> str:
    """Поиск по всей базе: папки проектов, журналы, профиль, факты."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return "Пустой запрос искать нечем."

    hits: list[str] = []
    base_resolved = base.resolve()

    def walk(folder: Path, depth: int) -> None:
        if depth > SEARCH_MAX_DEPTH or len(hits) >= limit:
            return
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            return
        for entry in entries:
            if len(hits) >= limit:
                return
            if entry.is_dir():
                if entry.name in SKIP_DIRS:
                    continue
                # За пределы базы не ходим: на диске рядом могут быть
                # чужие папки, а искать надо по своей базе.
                try:
                    if not entry.resolve().is_relative_to(base_resolved):
                        continue
                except OSError:
                    continue
                walk(entry, depth + 1)
            elif entry.suffix.lower() == ".md":
                try:
                    text = entry.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for number, line in enumerate(text.splitlines(), start=1):
                    if needle in line.casefold():
                        try:
                            rel = entry.relative_to(base)
                        except ValueError:
                            rel = entry
                        hits.append(f"{rel}:{number}: {line.strip()}")
                        if len(hits) >= limit:
                            return

    walk(base, 0)
    if not hits:
        return f"По запросу «{query}» в базе ничего не найдено."
    header = f"Найдено строк: {len(hits)} (показаны все, искать дальше не нужно)"
    return header + "\n" + "\n".join(hits)


def memory_log_work(
    base: Path,
    text: str,
    project: str = "",
    folder: str = "",
    ai: str = "",
) -> str:
    """Записать сделанную работу в журнал проекта и папку нейросети."""
    line = str(text or "").strip()
    if not line:
        raise MemoryError("Пустое описание работы записывать нечем.")

    name, problem = find_project(base, project=project, folder=folder)
    if problem:
        raise MemoryError(
            problem + " Передай проект или папку явно, например проект=\"opencode-base\"."
        )

    who = sanitize(ai) if ai else "Нейросеть"
    target_dir = base / "projects" / name / who
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MemoryError(f"Не создалась папка {target_dir}: {exc}") from exc

    work = target_dir / "work.md"
    try:
        if not work.exists():
            work.write_text(f"# Работа: {who} — проект «{name}»\n", encoding="utf-8")
        with work.open("a", encoding="utf-8") as handle:
            handle.write(f"- [{today()}] {line}\n")
    except OSError as exc:
        raise MemoryError(f"Не записалось в work.md: {exc}") from exc

    return f"Записано в projects/{name}/{who}/work.md"


#: Имена из инструкций базы, которые ведут на те же действия, что ncp_*.
#: Ключ — псевдоним, значение — настоящее имя инструмента моста.
LIBRARY_ALIASES = {
    "library_status": "ncp_status",
    "library_search": "ncp_search",
    "library_read": "ncp_read",
    "library_save": "ncp_save",
    "library_update": "ncp_update",
    "library_checkpoint": "ncp_checkpoint",
    "library_reindex": "ncp_reindex",
}
