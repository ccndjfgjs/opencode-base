# -*- coding: utf-8 -*-
"""Где лежат созданные базы и что в них с указателем Учёбы.

Перебор сделан скриптом, а не командами вручную: ручной перебор уже дважды
наврал — один раз посчитал 36 совпадений вместо 28, другой раз спутал файл
материала с файлом указателя.

Ничего не меняет: только читает и пишет отчёт.
"""

import json
import sys
from pathlib import Path

HOME = Path.home()
OUT = Path(sys.argv[1])

#: Признак базы — служебные файлы, которые создаёт конструктор.
MARKERS = ("профиль.md", "profile.md", "проекты", "sessions", "index.json")
OLD_NAME = "_подсказки-программисту.md"
NEW_NAME = "_подсказки-учёба.md"

lines: list[str] = ["=== где ищем базы ===", ""]

# --- 1. список баз, который ведёт сама программа
cfg = HOME / ".config" / "opencode"
for name in ("dbapp-bases.json", "bases.json", "cli.json", "service.json"):
    p = cfg / name
    if not p.is_file():
        continue
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        lines.append(f"  {name}: не разбирается как JSON")
        continue
    text = json.dumps(data, ensure_ascii=False)
    hits = text.count("DataBases") + text.count("OpenCode_Base")
    lines.append(f"  {name}: упоминаний баз {hits}")
    if isinstance(data, dict):
        for key in sorted(data)[:8]:
            value = data[key]
            if isinstance(value, (str, int, bool)) or value is None:
                lines.append(f"     {key} = {value!r}")
            elif isinstance(value, list):
                lines.append(f"     {key}: список из {len(value)}")
                for item in value[:6]:
                    lines.append(f"        {item!r}"[:110])
            else:
                lines.append(f"     {key}: объект с {len(value)} полями")

# --- 2. сами папки баз: где встречаются служебные файлы
lines.append("")
lines.append("=== найденные базы по служебным файлам ===")
SEARCH = [HOME / "Desktop" / "DataBases", HOME / "Downloads",
          HOME / "Documents", cfg, HOME / "Desktop"]
seen: set[str] = set()
bases: list[Path] = []
for root in SEARCH:
    if not root.is_dir():
        continue
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        continue
    for child in children:
        if child in seen:
            continue
        seen.add(child)
        found = [m for m in MARKERS if (child / m).exists()]
        if found:
            bases.append(child)
            lines.append(f"  {child}")
            lines.append(f"     признаки: {', '.join(found)}")

lines.append("")
lines.append(f"  всего найдено баз: {len(bases)}")

# --- 3. что в каждой базе с указателем Учёбы
lines.append("")
lines.append("=== состояние указателя Учёбы в каждой базе ===")
if not bases:
    lines.append("  баз не найдено — переименование не нужно")
for base in bases:
    ucheba = base / "знания" / "Учёба"
    old = ucheba / OLD_NAME
    new = ucheba / NEW_NAME
    lines.append(f"  {base}")
    lines.append(f"     папка знаний/Учёба: {ucheba.is_dir()}")
    lines.append(f"     {OLD_NAME}: {'есть' if old.is_file() else 'нет'}")
    lines.append(f"     {NEW_NAME}: {'есть' if new.is_file() else 'нет'}")
    if old.is_file():
        lines.append(f"     размер старого: {old.stat().st_size} байт, "
                     f"строк: {len(old.read_text(encoding='utf-8').splitlines())}")

# --- 4. установленный AGENTS.md: что он говорит про указатель
lines.append("")
lines.append("=== установленный AGENTS.md ===")
agents = cfg / "AGENTS.md"
if agents.is_file():
    lines.append(f"  {agents} — {agents.stat().st_size} байт")
    lines.append(f"     создан: {agents.stat().st_mtime}")
    text = agents.read_text(encoding="utf-8", errors="ignore")
    for i, row in enumerate(text.splitlines(), 1):
        if OLD_NAME.replace(".md", "") in row or NEW_NAME.replace(".md", "") in row:
            lines.append(f"     {i}: {row.strip()[:100]}")
else:
    lines.append("  установленного AGENTS.md нет")

# --- 5. живая база пользователя — отдельно и подробно
lines.append("")
lines.append("=== живая база пользователя ===")
live = HOME / "Desktop" / "DataBases" / "OpenCode_Base"
if live.is_dir():
    lines.append(f"  {live}")
    for rel in (f"знания/Учёба/{OLD_NAME}", f"знания/Учёба/{NEW_NAME}",
                "знания/_подсказки-общая.md"):
        p = live / rel
        lines.append(f"     {rel}: {'есть' if p.is_file() else 'нет'}")
    refs = 0
    for path in live.rglob("*.md"):
        try:
            if OLD_NAME.replace(".md", "") in path.read_text(
                    encoding="utf-8", errors="ignore"):
                refs += 1
        except OSError:
            continue
    lines.append(f"     файлов в живой базе со ссылкой на старое имя: {refs}")
else:
    lines.append("  живой базы по этому пути нет")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("ok")