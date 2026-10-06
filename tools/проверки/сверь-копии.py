#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверяет папку программы с конструктором перед коммитом.

Программа живёт в двух экземплярах: папка, из которой её запускают, и
репозиторий-конструктор. Пока копия в папке не синхронизирована с
конструктором, правка едет мимо git, и через месяц выясняется, что в
репозитории её нет. Так пропало четыре проверки.

Что сравнивать — только то, что определяет программу:

    tools/dbapp       код программы
    skills            навыки
    инструкции        инструкции для нейросети
    config            шаблоны и реестры
    mcp-registry.json реестр серверов
    skills-index.json индекс навыков
    README.md         описание

Что НЕ сравнивать и почему:

    tools/проверки     черновики, отчёты и откаты; они к программе не
                       относятся и в двух копиях различаются по построению
    __pycache__       кэш Python
    selftest-report.txt   отчёт прогона, каждый раз другой
    thirdparty, .venv     чужой код внутри проекта

Переводы строк нормализуются: CRLF против LF дают разницу в каждом
файле, и хук, который всегда красный, перестают читать. Красный всегда
означает не работает.

Путь к папке программы задаётся по первому найденному:

    1. переменная окружения OPENCODE_PROGRAM_ROOT
    2. файл .git/путь-к-папке-программы в репозитории
    3. иначе проверка НЕ выполняется, и об этом сказано прямо.

Молча пропустить нельзя: тогда расхождение будет считаться «проверено».

Запуск: python tools/проверки/сверь-копии.py
Код 0 — совпадает, 1 — расходится, 3 — сверка не настроена.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PROGRAM = REPO / "tools" / "dbapp" / "core.py"

#: Что определяет программу. Порядок — как в описании.
#: Раздел 16 плана разобрал корень, поэтому реестры и документы названы
#: папками: пока в списке были пути от корня, перенос тихо выключил бы их
#: из сверки, и она продолжала бы говорить «совпадают», не проверяя
#: ничего. Папки `служебное/` здесь нет намеренно: `.first-run-done`
#: создаёт работа программы, и на двух машинах он законно разный.
INCLUDE = ("tools/dbapp", "tools/hooks", "skills", "инструкции", "config",
           "документы", "отчёты", "данные", ".github")

#: Папки и файлы внутри INCLUDE, которые создаёт работа программы, а не
#: её исходники. Они в .gitignore, и сверять их между двумя папками
#: бессмысленно: они обязаны различаться. В списке — потому что сверка
#: берёт файлы с диска, а не только из git.
SKIP_PREFIXES = (
    "config/.secrets/", "config/cache/", "config/data/",
    "config/node_modules/",
    "config/device_id", "config/hwid", "config/preferences.json",
    "config/package-lock.json", "config/package.json",
    "config/.gitignore",
)
#: config/.*_migrated - флаги однократной миграции. Имена начинаются с
#: точки, поэтому проверяем отдельно, а не префиксом.
def is_skipped(rel: str) -> bool:
    if rel.startswith(SKIP_PREFIXES):
        return True
    parts = rel.split("/")
    return len(parts) == 2 and parts[0] == "config" and parts[1].startswith(
        ".") and parts[1].endswith("_migrated")

SKIP_NAMES = {"__pycache__", "selftest-report.txt"}
SKIP_DIRS = {"thirdparty", ".venv", ".git", "node_modules", ".pytest_cache"}

#: Расширения, которые нельзя читать текстом.
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".exe", ".dll",
          ".woff", ".woff2", ".ttf", ".pdf", ".pyc", ".db", ".sqlite"}


def find_program() -> Path | None:
    """Папка программы: сначала явное указание, потом настройка."""
    env = os.environ.get("OPENCODE_PROGRAM_ROOT", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        return p if (p / "tools" / "dbapp" / "core.py").is_file() else None
    cfg = REPO / ".git" / "путь-к-папке-программы"
    if cfg.is_file():
        # BOM терпим: настройку могут писать PowerShell и редакторы.
        raw = cfg.read_text(encoding="utf-8-sig").strip()
        if raw:
            p = Path(raw).expanduser().resolve()
            return p if (p / "tools" / "dbapp" / "core.py").is_file() else None
    return None


def norm(data: bytes) -> bytes:
    """CRLF → LF. Сравнивать побайтно нельзя: Windows переписывает
    переводы строк при checkout, и разница будет в каждом файле."""
    return data.replace(b"\r\n", b"\n")


def tracked(repo: Path) -> set[str]:
    """Файлы под контролем версий. Если git недоступен — пусто, сверка
    перейдёт на диск и честно скажет об этом в выводе."""
    try:
        # Два флага, и оба нужны. `core.quotepath=false` — иначе русские
        # пути приходят восьмеричными кавычками и не совпадают с диском
        # никогда: проверка сравнивает мусор с оригиналом и выглядит
        # рабочей. `-z` — разделитель NUL, а не перевод строки: имя файла
        # с переводом строки построчное чтение молча разрезает на два
        # несуществующих пути, и обе половины уезжают в «нет на диске».
        p = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.quotepath=false",
             "ls-files", "-z", "--"],
            capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return set()
    if p.returncode != 0:
        return set()
    out: set[str] = set()
    skipped: list[str] = []
    for raw in p.stdout.split(b"\x00"):
        if not raw:
            continue
        try:
            out.add(raw.decode("utf-8", "replace").replace("\\", "/"))
        except Exception:
            # Имя оказалось не в UTF-8: пропускаем и говорим, сколько
            # таких, иначе потеря файла выглядит как «всё на месте».
            skipped.append(raw.decode("utf-8", "replace"))
    if skipped:
        print(f"  сверка копий: не удалось разобрать {len(skipped)} путей "
              f"git, первый: {skipped[0][:60]!r}")
    return out


def files_of(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for rel in INCLUDE:
        base = root / rel
        if base.is_file():
            out[rel] = base
            continue
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(root)).replace("\\", "/")
            parts = set(f.relative_to(root).parts)
            if parts & SKIP_DIRS or f.name in SKIP_NAMES:
                continue
            if is_skipped(rel):
                continue
            if f.suffix.lower() in BINARY:
                continue
            out[rel] = f
    return out


def main() -> int:
    program = find_program()
    if program is None:
        print("сверка копий НЕ ВЫПОЛНЕНА")
        print("  Не нашена папка программы. Проверка пропущена, а не пройдена:")
        print("  расхождение сейчас возможно, и никто его не увидит.")
        print("  Укажи путь одним из двух способов:")
        print('    переменная OPENCODE_PROGRAM_ROOT="C:\\путь\\к\\папке"')
        print('    или файл .git/путь-к-папке-программы с путём внутри')
        return 3

    a, b = files_of(program), files_of(REPO)
    # Отслеживаемые git, которых нет на диске, тоже сверяем: иначе
    # удалённый файл не заметен, пока git не вспомнит.
    tracked_here = tracked(REPO)
    if not tracked_here:
        print("  ВНИМАНИЕ: список файлов git получить не удалось, "
              "сверка идёт только по диску")
    # Только те же области, что и INCLUDE. Файл вне их не сверяется:
    # он не попадёт в список папки программы и был бы виден вечно.
    scopes = tuple(INCLUDE)
    for rel in sorted(tracked_here):
        if rel not in b and (rel.startswith(scopes) or is_skipped(rel)):
            b[rel] = REPO / rel
    only_prog = sorted(set(a) - set(b))
    only_repo = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b)
                  if norm(a[k].read_bytes()) != norm(b[k].read_bytes()))

    print(f"сверка копий: папка программы {program}")
    print(f"  папка программы: {len(a)} файлов   конструктор: {len(b)}")
    if not (only_prog or only_repo or diff):
        print("  совпадают, расхождений нет")
        return 0

    for label, items, why in (
            ("только в папке программы", only_prog, "правка не попала в git"),
            ("только в конструкторе", only_repo,
             "в папке программы файла нет, программа может работать не так"),
            ("расходятся содержимым", diff,
             "в двух экземплярах разный код")):
        if not items:
            continue
        print(f"  {label}: {len(items)}  ({why})")
        for k in items[:12]:
            print(f"    {k}")
        if len(items) > 12:
            print(f"    …ещё {len(items) - 12}")

    print()
    print("  Один экземпляр без другого работает, но это разные программы.")
    print("  Копируй правку в конструктор и синхронизируй, потом повтори.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
