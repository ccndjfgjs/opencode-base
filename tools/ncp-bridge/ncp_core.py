# -*- coding: utf-8 -*-
"""Ядро NCP — работа с библиотекой без MCP, без сети и без чужих пакетов.

Здесь только стандартная библиотека Python. Ядро ничего не знает про MCP,
поэтому его можно проверить отдельно, из обычного Python, без Qwen.

Границы взяты из протокола NCP, раздел 9 «Инварианты безопасности»:
  * все операции — только внутри папки библиотеки, выход наружу запрещён;
  * удаления нет вовсе: устаревшее помечается и переносится в архив;
  * поиск и чтение ничего не меняют;
  * создание и изменение попадают в журнал.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

#: Схема машинного индекса — та же, что у существующей библиотеки.
SCHEMA = "ncp-library-index-v1"

ENTRY_TYPES = (
    "fact",
    "note",
    "decision",
    "procedure",
    "source",
    "summary",
    "question",
)
ENTRY_STATUSES = ("active", "draft", "superseded", "archived")
CONFIDENCE_LEVELS = ("high", "medium", "low")

#: Папки, из которых состоит библиотека. Создаются, если их нет.
STRUCTURE = ("записи", "входящие", "архив", "журнал", "шаблоны")

#: Признаки того, что папка — действительно библиотека NCP.
LIBRARY_MARKS = ("NCP.md", "index.json", "записи", "КАТАЛОГ.md")

MAX_TITLE = 200
MAX_TOPIC = 60
MAX_CONTENT = 20000

#: Знаки, недопустимые в имени папки темы.
_TOPIC_BAD = set('<>:"/\\|?*')


class NcpError(Exception):
    """Понятная ошибка. Текст показывается человеку как есть."""


# ------------------------------------------------------------------ мелочи


def now_iso() -> str:
    """Время в том же виде, что уже записан в библиотеке: с Z на конце."""
    moment = datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def local_iso() -> str:
    """Время журнала — с местным сдвигом, как в существующих записях."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    """Идентификатор записи вида ncp-20260916-201500-a1b2."""
    moment = datetime.now(timezone.utc)
    return f"ncp-{moment.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def normalize(text: str) -> str:
    """Приводит текст к виду для сравнения: регистр, ё, лишние пробелы."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = text.replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def slug(text: str, limit: int = 40) -> str:
    """Короткое имя для файла: без пробелов и запрещённых знаков."""
    text = normalize(text)
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return text[:limit].strip("-.") or "запись"


def yaml_scalar(value: str) -> str:
    """Значение для шапки записи. При риске спутать с разметкой — в кавычках."""
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    risky = (
        not text
        or text[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in text
        or text.endswith(":")
        or " #" in text
    )
    if risky:
        return '"' + text.replace('"', "'") + '"'
    return text


def split_tags(value) -> list[str]:
    """Теги: список строк или строка через запятую."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    else:
        raw = str(value).split(",")
    result: list[str] = []
    for item in raw:
        item = item.strip().strip('"').strip("'").strip()
        if item and item not in result:
            result.append(item)
    return result


#: Разделитель уровней в теме. Разрешён ровно один уровень вложенности:
#: «личное/животные» — категория «личное», тема «животные».
TOPIC_SEP = "/"

#: Категория личных записей. Такое не едет в новые базы: это часть
#: конкретного человека, а не эталон конструктора.
PRIVATE_ROOT = "личное"


def safe_topic(name: str) -> str:
    """Имя темы — одна папка или две через слеш: «личное/животные».

    Раньше путь был запрещён целиком, и структура, которая уже была в
    библиотеке (записи/личное/<тема>/), была недостижима из инструментов:
    нейросеть не могла положить запись в личную тему, хотя папки для этого
    были. Теперь разрешён один уровень вложенности — ровно столько нужно
    для личных папок.

    Запрещено по-прежнему: «..», двоеточие, ведущий слеш, больше двух
    уровней и слишком длинные имена. Запись не может выйти за пределы
    библиотеки — это проверяется отдельно, функцией inside().
    """
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    if not text:
        return "общее"

    text = text.replace("\\", TOPIC_SEP)
    if ".." in text or ":" in text:
        raise NcpError(f"Имя темы не должно содержать путей: {name!r}")
    if text.startswith(TOPIC_SEP):
        raise NcpError(f"Имя темы не может начинаться со слеша: {name!r}")

    parts = text.split(TOPIC_SEP)
    if len(parts) > 2:
        raise NcpError(
            f"Слишком глубокая тема: {name!r}. Допустимо не больше двух "
            "уровней — «категория» или «категория/тема»."
        )

    clean: list[str] = []
    for part in parts:
        piece = "".join(
            ch for ch in part if ch not in _TOPIC_BAD and ord(ch) >= 32
        )
        piece = piece.strip().strip(".")
        if piece:
            clean.append(piece[:MAX_TOPIC].strip())

    if not clean:
        raise NcpError(f"Имя темы пустое после очистки: {name!r}")
    return TOPIC_SEP.join(clean)


def topic_parts(topic: str) -> list[str]:
    """Тема как список папок: «личное/животные» → ['личное', 'животные']."""
    return [p for p in str(topic or "").split(TOPIC_SEP) if p]


def is_private(topic: str) -> bool:
    """Личная ли тема. Такое не едет в новые базы."""
    parts = topic_parts(topic)
    return bool(parts) and parts[0].lower() == PRIVATE_ROOT


def inside(root: Path, target: Path) -> bool:
    """Лежит ли путь внутри папки библиотеки."""
    try:
        target.resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n)?", re.DOTALL)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Разбирает шапку записи. Без шапки возвращает пустой словарь и весь текст."""
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, text[match.end():]


def read_entry(path: Path, root: Path) -> dict | None:
    """Читает одну запись. Битый файл пропускается, а не роняет работу."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta, body = split_front_matter(text)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    return {
        "id": meta.get("id") or path.stem,
        "title": meta.get("title") or path.stem,
        "type": meta.get("type") or "note",
        "topic": meta.get("topic") or path.parent.name,
        "status": meta.get("status") or "active",
        "created": meta.get("created") or "",
        "updated": meta.get("updated") or "",
        "tags": split_tags(meta.get("tags") or ""),
        "source": meta.get("source") or "",
        "confidence": meta.get("confidence") or "",
        "supersedes": meta.get("supersedes") or "",
        "path": rel,
        "body": body.strip(),
    }


def plain_body(body: str) -> str:
    """Тело без разметки — по нему ищем слова."""
    text = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    text = re.sub(r"[#*_>`\[\]()|-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_snippet(body: str, words: list[str], width: int = 180) -> str:
    """Кусочек текста вокруг первого совпадения — чтобы было видно, что нашли."""
    flat = plain_body(body)
    low = normalize(flat)
    spot = -1
    for word in words:
        spot = low.find(word)
        if spot >= 0:
            break
    if spot < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, spot - width // 3)
    end = min(len(flat), start + width)
    piece = flat[start:end].strip()
    return ("…" if start > 0 else "") + piece + ("…" if end < len(flat) else "")


# ------------------------------------------------------------------ библиотека


class Library:
    """Библиотека NCP на диске. Все пути считаются от её корня."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    # ---- где что лежит

    @property
    def records_dir(self) -> Path:
        return self.root / "записи"

    @property
    def archive_dir(self) -> Path:
        return self.root / "архив"

    @property
    def journal_dir(self) -> Path:
        return self.root / "журнал"

    @property
    def index_file(self) -> Path:
        return self.root / "index.json"

    @property
    def catalog_file(self) -> Path:
        return self.root / "КАТАЛОГ.md"

    @property
    def active_file(self) -> Path:
        return self.root / "АКТИВНАЯ-ПАМЯТЬ.md"

    @property
    def replaced_dir(self) -> Path:
        """Прежние версии активной памяти.

        Нужны для режима replace: он переписывает активную память, но
        прежнее содержимое не выбрасывает, а кладёт сюда. Замена не
        должна уметь стирать наработки безвозвратно.
        """
        return self.root / "замены"

    def looks_like_library(self) -> bool:
        return any((self.root / name).exists() for name in LIBRARY_MARKS)

    def ensure(self) -> None:
        """Готовит библиотеку к работе. В чужую папку писать отказывается."""
        if not self.root.exists():
            raise NcpError(f"Папки библиотеки нет: {self.root}")
        if not self.root.is_dir():
            raise NcpError(f"Путь библиотеки — не папка: {self.root}")
        if not self.looks_like_library():
            try:
                occupied = any(self.root.iterdir())
            except OSError as exc:
                raise NcpError(f"Не читается папка {self.root}: {exc}") from exc
            if occupied:
                raise NcpError(
                    f"Папка {self.root} не похожа на библиотеку NCP и не пуста. "
                    "Ничего не тронуто. Проверьте путь в config.json."
                )
        for name in STRUCTURE:
            folder = self.root / name
            if not inside(self.root, folder):
                raise NcpError(f"Папка вышла за пределы библиотеки: {folder}")
            folder.mkdir(parents=True, exist_ok=True)

    # ---- чтение

    def entries(self) -> list[dict]:
        """Все записи библиотеки. Индекс не используется: он производный."""
        rows: list[dict] = []
        root = self.records_dir
        if not root.is_dir():
            return rows
        for path in sorted(root.rglob("*.md")):
            # Точка — скрытый файл, подчёркивание — служебный: пояснение
            # папки, заготовка. Записьми библиотеки являются только
            # ncp-*.md, иначе счётчик и список тем врут.
            if not path.is_file():
                continue
            if path.name.startswith(".") or path.name.startswith("_"):
                continue
            row = read_entry(path, self.root)
            if row is not None:
                rows.append(row)
        return rows

    def active_memory(self) -> str:
        try:
            return self.active_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def index_count(self) -> int | None:
        try:
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, dict) and isinstance(data.get("count"), int):
            return data["count"]
        return None

    def last_journal_line(self) -> str:
        if not self.journal_dir.is_dir():
            return ""
        files = sorted(self.journal_dir.glob("*.md"))
        if not files:
            return ""
        try:
            lines = [
                line.strip()
                for line in files[-1].read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("- [")
            ]
        except (OSError, UnicodeDecodeError):
            return ""
        return lines[-1] if lines else ""

    def status(self) -> dict:
        """Состояние библиотеки. Ничего не меняет."""
        rows = self.entries()
        topics: dict[str, int] = {}
        for row in rows:
            topics[row["topic"]] = topics.get(row["topic"], 0) + 1
        active = self.active_memory()
        stored = self.index_count()
        notes: list[str] = []
        if stored is not None and stored != len(rows):
            notes.append(
                f"index.json говорит о {stored} записях, а на диске их "
                f"{len(rows)}. Индекс перестроится при следующем сохранении."
            )
        if not self.looks_like_library():
            notes.append("Папка пока не похожа на библиотеку NCP.")
        return {
            "library": str(self.root),
            "ready": self.looks_like_library(),
            "entries": len(rows),
            "topics": topics,
            "active_memory_lines": len(active.splitlines()),
            "active_memory_head": "\n".join(active.splitlines()[:12]).strip(),
            "index_count": stored,
            "last_journal": self.last_journal_line(),
            "notes": notes,
        }

    def search(self, query: str, limit: int = 10, topic: str = "") -> list[dict]:
        """Поиск по названию, тегам, теме и тексту. Ничего не меняет."""
        needle = normalize(query)
        if not needle:
            raise NcpError("Пустой запрос: нечего искать.")
        words = [word for word in needle.split() if len(word) > 1] or [needle]
        want_topic = normalize(topic)
        found: list[tuple[int, dict]] = []
        for row in self.entries():
            if want_topic and normalize(row["topic"]) != want_topic:
                continue
            title = normalize(row["title"])
            tags = normalize(" ".join(row["tags"]))
            body = normalize(plain_body(row["body"]))
            score = 0
            if needle in title:
                score += 100
            for word in words:
                if word in title:
                    score += 20
                if word in tags:
                    score += 12
                if word in normalize(row["topic"]):
                    score += 8
                if word in body:
                    score += 5
            if score == 0:
                continue
            found.append(
                (
                    score,
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "type": row["type"],
                        "topic": row["topic"],
                        "status": row["status"],
                        "updated": row["updated"],
                        "tags": row["tags"],
                        "path": row["path"],
                        "snippet": make_snippet(row["body"], words),
                        "score": score,
                    },
                )
            )
        found.sort(key=lambda pair: (-pair[0], pair[1]["title"]))
        limit = max(1, min(int(limit or 10), 50))
        return [row for _, row in found[:limit]]

    def find_duplicate(self, title: str, tags: list[str]) -> dict | None:
        """Возможный дубликат: совпало название или теги."""
        want = normalize(title)
        want_tokens = set(want.split())
        want_tags = {normalize(tag) for tag in tags}
        for row in self.entries():
            have = normalize(row["title"])
            if have == want:
                return {"id": row["id"], "title": row["title"],
                        "path": row["path"], "reason": "название совпадает полностью"}
            have_tokens = set(have.split())
            if want_tokens and have_tokens:
                common = want_tokens & have_tokens
                if len(common) >= 2 and len(common) / min(len(want_tokens), len(have_tokens)) >= 0.75:
                    return {"id": row["id"], "title": row["title"],
                            "path": row["path"], "reason": "названия почти совпадают"}
            if want_tags and want_tags == {normalize(tag) for tag in row["tags"]}:
                return {"id": row["id"], "title": row["title"],
                        "path": row["path"], "reason": "совпадают теги"}
        return None

    # ---- запись

    def save(
        self,
        title: str,
        content: str,
        topic: str = "общее",
        type: str = "note",
        tags=None,
        source: str = "пользователь",
        confidence: str = "medium",
        force: bool = False,
    ) -> dict:
        """Создаёт запись. При похожей записи возвращает отказ, а не дубликат."""
        title = str(title or "").strip()
        content = str(content or "").strip()
        if not title:
            raise NcpError("Не указано название записи.")
        if len(title) > MAX_TITLE:
            title = title[:MAX_TITLE].strip()
        if not content:
            raise NcpError("Пустая запись: нечего сохранять.")
        if len(content) > MAX_CONTENT:
            content = content[:MAX_CONTENT].rstrip() + "\n\n(текст сокращён)"
        type = str(type or "note").strip().lower()
        if type not in ENTRY_TYPES:
            raise NcpError(
                f"Неизвестный тип «{type}». Допустимо: {', '.join(ENTRY_TYPES)}."
            )
        confidence = str(confidence or "medium").strip().lower()
        if confidence not in CONFIDENCE_LEVELS:
            raise NcpError(
                f"Неизвестная уверенность «{confidence}». "
                f"Допустимо: {', '.join(CONFIDENCE_LEVELS)}."
            )
        topic = safe_topic(topic)
        tag_list = split_tags(tags)
        source = str(source or "").strip() or "пользователь"

        self.ensure()

        if not force:
            twin = self.find_duplicate(title, tag_list)
            if twin is not None:
                return {
                    "ok": False,
                    "duplicate": twin,
                    "entry": None,
                    "message": (
                        f"Похожая запись уже есть: «{twin['title']}» "
                        f"({twin['reason']}). Сохранять вторую не стали. "
                        "Если это всё-таки новое знание — повторите с force=true."
                    ),
                }

        entry_id = new_id()
        stamp = now_iso()
        folder = self.records_dir / topic
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{entry_id}-{slug(title)}.md"
        if not inside(self.root, path):
            raise NcpError("Путь записи вышел за пределы библиотеки.")
        path.write_text(
            self._render_entry(
                entry_id, title, type, topic, tag_list, source, confidence, stamp, content
            ),
            encoding="utf-8",
        )
        self.log(f"Создана запись «{title}» — тема «{topic}», тип {type}.")
        index = self.rebuild_index()
        return {
            "ok": True,
            "duplicate": None,
            "entry": {
                "id": entry_id,
                "title": title,
                "type": type,
                "topic": topic,
                "status": "active",
                "tags": tag_list,
                "source": source,
                "confidence": confidence,
                "created": stamp,
                "path": path.relative_to(self.root).as_posix(),
            },
            "index": {"count": index["count"], "topics": index["topics"]},
            "message": f"Запись сохранена: «{title}» (тема «{topic}»).",
        }

    def _find(self, id_or_path: str) -> Path:
        """Файл записи по id или относительному пути. Границы проверяются."""
        want = str(id_or_path or "").strip().replace("\\", "/")
        if not want:
            raise NcpError("Не указано что читать: нужен id или путь записи.")
        for row in self.entries():
            if row["id"] == want or row["path"] == want:
                path = self.root / row["path"]
                if not inside(self.root, path) or not path.is_file():
                    raise NcpError(f"Запись найдена, но файл недоступен: {row['path']}.")
                return path
        raise NcpError(f"Запись не найдена: {want}. Поищите через ncp_search.")

    def read_full(self, id_or_path: str) -> dict:
        """Вся запись целиком: шапка + полный текст. Ничего не меняет."""
        path = self._find(id_or_path)
        row = read_entry(path, self.root)
        if row is None:
            raise NcpError(f"Не смог прочитать файл: {path}.")
        return row

    def update(
        self,
        id: str,
        title: str = "",
        content: str = "",
        topic: str = "",
        type: str = "",
        tags=None,
        source: str = "",
        confidence: str = "",
        status: str = "",
    ) -> dict:
        """Меняет запись. Прежний текст не стирается бесследно: правка
        отмечается в разделе «История» и в журнале. Пустые поля не трогают."""
        path = self._find(id)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise NcpError(f"Не читается файл записи: {exc}") from exc
        meta, body = split_front_matter(text)

        new_title = str(title or "").strip() or meta.get("title") or path.stem
        new_content = str(content or "").strip()
        if not new_content:
            # Содержание лежит после "## Содержание" — достаём старое.
            if "## Содержание" in body:
                new_content = body.split("## Содержание", 1)[1].split("## Связи", 1)[0].strip()
            else:
                new_content = body.strip()
        new_topic = safe_topic(topic) if str(topic or "").strip() else (meta.get("topic") or path.parent.name)
        new_type = str(type or "").strip().lower() or meta.get("type") or "note"
        if new_type not in ENTRY_TYPES:
            raise NcpError(f"Неизвестный тип «{new_type}». Допустимо: {', '.join(ENTRY_TYPES)}.")
        new_conf = str(confidence or "").strip().lower() or meta.get("confidence") or "medium"
        if new_conf not in CONFIDENCE_LEVELS:
            raise NcpError(f"Неизвестная уверенность «{new_conf}». Допустимо: {', '.join(CONFIDENCE_LEVELS)}.")
        new_status = str(status or "").strip().lower() or meta.get("status") or "active"
        if new_status not in ENTRY_STATUSES:
            raise NcpError(f"Неизвестный статус «{new_status}». Допустимо: {', '.join(ENTRY_STATUSES)}.")
        new_tags = split_tags(tags) if tags is not None else split_tags(meta.get("tags") or "")
        new_source = str(source or "").strip() or meta.get("source") or "пользователь"

        # Раздел «Связи» бережём как был, историю дописываем.
        if "## История" in body:
            links_part, hist_old = body.split("## История", 1)
        else:
            links_part, hist_old = body, ""
        if "## Связи" in links_part:
            links = links_part.split("## Связи", 1)[1].strip()
        else:
            links = "- Пока нет."
        stamp = now_iso()
        entry_id = meta.get("id") or path.stem
        created = meta.get("created") or stamp
        new_text = (
            "---\n"
            f"id: {entry_id}\n"
            f"title: {yaml_scalar(new_title)}\n"
            f"type: {new_type}\n"
            f"topic: {yaml_scalar(new_topic)}\n"
            f"status: {new_status}\n"
            f"created: {created}\n"
            f"updated: {stamp}\n"
            f"tags: {yaml_scalar(', '.join(new_tags))}\n"
            f"source: {yaml_scalar(new_source)}\n"
            f"confidence: {new_conf}\n"
            f"supersedes: {yaml_scalar(meta.get('supersedes') or '')}\n"
            "---\n"
            "\n"
            f"# {new_title}\n"
            "\n"
            "## Содержание\n"
            "\n"
            f"{new_content}\n"
            "\n"
            "## Связи\n"
            "\n"
            f"{links}\n"
            "\n"
            "## История\n"
            "\n"
            f"{hist_old.strip()}\n"
            f"- [{stamp}] Изменено.\n"
        )
        new_path = self.records_dir / new_topic / path.name
        if not inside(self.root, new_path):
            raise NcpError("Новая тема выводит запись за пределы библиотеки.")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(new_text, encoding="utf-8")
        if new_path != path:
            try:
                path.unlink()
            except OSError:
                pass
        self.log(f"Изменена запись «{new_title}» (тема «{new_topic}»).")
        index = self.rebuild_index()
        return {
            "ok": True,
            "entry": {
                "id": entry_id,
                "title": new_title,
                "type": new_type,
                "topic": new_topic,
                "status": new_status,
                "tags": new_tags,
                "source": new_source,
                "confidence": new_conf,
                "updated": stamp,
                "path": new_path.relative_to(self.root).as_posix(),
            },
            "index": {"count": index["count"], "topics": index["topics"]},
            "message": f"Запись обновлена: «{new_title}».",
        }

    def _keep_replaced(self, stamp: str) -> Path | None:
        """Откладывает текущую активную память в замены/ перед replace.

        Возвращает путь сохранённой копии или None — если копировать
        нечего либо не получилось. Молчание здесь опаснее отказа, поэтому
        сам replace всё равно отрабатывает, а замена остаётся на диске.
        """
        try:
            old = self.active_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if not old.strip():
            return None
        safe = "".join(
            ch if ch.isalnum() or ch in "-_" else "-" for ch in str(stamp)[:19]
        )
        try:
            self.replaced_dir.mkdir(parents=True, exist_ok=True)
            target = self.replaced_dir / f"активная-память {safe}.md"
            counter = 1
            while target.exists():
                counter += 1
                target = (
                    self.replaced_dir / f"активная-память {safe} ({counter}).md"
                )
            target.write_text(old, encoding="utf-8")
            return target
        except OSError:
            return None

    def checkpoint(self, text: str, mode: str = "append") -> dict:
        """Состояние работы в активную память: дописать (append) или
        заменить целиком (replace). Попадает в журнал."""
        text = str(text or "").strip()
        if not text:
            raise NcpError("Пустая контрольная точка: нечего сохранять.")
        mode = str(mode or "append").strip().lower()
        if mode not in ("append", "replace"):
            raise NcpError("Режим — append (дописать) или replace (заменить).")
        stamp = local_iso()
        self.active_file.parent.mkdir(parents=True, exist_ok=True)
        if mode == "replace" or not self.active_file.is_file():
            if mode == "replace" and self.active_file.is_file():
                self._keep_replaced(stamp)
            self.active_file.write_text(
                f"# Активная память NCP\n\n- [{stamp}] {text}\n", encoding="utf-8"
            )
        else:
            with self.active_file.open("a", encoding="utf-8") as handle:
                handle.write(f"\n- [{stamp}] {text}\n")
        self.log("Записана контрольная точка в активную память.")
        lines = len(self.active_memory().splitlines())
        return {"ok": True, "mode": mode, "lines": lines,
                "message": f"Контрольная точка сохранена ({mode}), строк в памяти: {lines}."}

    @staticmethod
    def _render_entry(
        entry_id: str,
        title: str,
        type: str,
        topic: str,
        tags: list[str],
        source: str,
        confidence: str,
        stamp: str,
        content: str,
    ) -> str:
        """Тот же вид, что в шаблоны/ЗАПИСЬ.md."""
        return (
            "---\n"
            f"id: {entry_id}\n"
            f"title: {yaml_scalar(title)}\n"
            f"type: {type}\n"
            f"topic: {yaml_scalar(topic)}\n"
            "status: active\n"
            f"created: {stamp}\n"
            f"updated: {stamp}\n"
            f"tags: {yaml_scalar(', '.join(tags))}\n"
            f"source: {yaml_scalar(source)}\n"
            f"confidence: {confidence}\n"
            "supersedes:\n"
            "---\n"
            "\n"
            f"# {title}\n"
            "\n"
            "## Содержание\n"
            "\n"
            f"{content}\n"
            "\n"
            "## Связи\n"
            "\n"
            "- Пока нет.\n"
            "\n"
            "## История\n"
            "\n"
            f"- [{stamp}] Создано.\n"
        )

    def log(self, text: str) -> None:
        """Строка в месячный журнал. Журнал — добавляемый, не перезаписываемый."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.now().strftime("%Y-%m")
        path = self.journal_dir / f"{month}.md"
        if not path.is_file():
            path.write_text(
                f"# Журнал библиотеки NCP — {month}\n\n", encoding="utf-8"
            )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- [{local_iso()}] {text}\n")

    def rebuild_index(self) -> dict:
        """Пересобирает index.json и КАТАЛОГ.md из файлов на диске."""
        rows = self.entries()
        topics: dict[str, int] = {}
        for row in rows:
            topics[row["topic"]] = topics.get(row["topic"], 0) + 1
        index = {
            "schema": SCHEMA,
            "updated": now_iso(),
            "count": len(rows),
            "topics": topics,
            "entries": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "type": row["type"],
                    "topic": row["topic"],
                    "status": row["status"],
                    "created": row["created"],
                    "updated": row["updated"],
                    "tags": row["tags"],
                    "source": row["source"],
                    "confidence": row["confidence"],
                    "path": row["path"],
                }
                for row in rows
            ],
        }
        self.index_file.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self._write_catalog(rows, index["updated"])
        return index

    def _write_catalog(self, rows: list[dict], stamp: str) -> None:
        lines = [
            "# Каталог библиотеки NCP",
            "",
            f"**Последнее обновление:** {stamp}  ",
            f"**Записей:** {len(rows)}",
            "",
        ]
        if not rows:
            lines.append("Записей пока нет.")
        else:
            by_topic: dict[str, list[dict]] = {}
            for row in rows:
                by_topic.setdefault(row["topic"], []).append(row)
            for topic in sorted(by_topic):
                lines.append(f"## {topic}")
                lines.append("")
                for row in sorted(by_topic[topic], key=lambda item: item["title"]):
                    lines.append(
                        f"- **{row['title']}** — {row['type']}, {row['status']}, "
                        f"обновлено {row['updated'] or '—'}  "
                    )
                    lines.append(f"  `{row['path']}`")
                lines.append("")
        self.catalog_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
