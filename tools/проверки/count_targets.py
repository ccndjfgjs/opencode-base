# -*- coding: utf-8 -*-
"""Считает, сколько указателей даёт функция из плана.

Число «девять» в прозе плана уже один раз не сошло со счётчиком, поэтому
считает скрипт: он берёт настоящие KNOWLEDGE_* из core.py и выполняет
логику функции ровно как она написана в плане.

Ничего не меняет в программе.
"""

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent.parent
OUT = Path(sys.argv[1])
sys.path.insert(0, str(PROG / "tools" / "dbapp"))

import core  # noqa: E402

INDEX_LIMIT_ROOT = 4 * 1024
INDEX_LIMIT_AREA = 5 * 1024
INDEX_LIMIT_BRANCH = 32 * 1024


def knowledge_index_targets() -> list[tuple[str, str, int]]:
    """Ровно как в плане, задача 1, шаг 3."""
    out: list[tuple[str, str, int]] = [
        ("знания", "_подсказки-общая.md", INDEX_LIMIT_ROOT),
    ]
    branch_root = "знания/Техника"
    for area in core.KNOWLEDGE_AREAS:
        if area == "Техника":
            continue
        out.append((f"знания/{area}", f"_подсказки-{area.lower()}.md",
                    INDEX_LIMIT_AREA))
    out.append((branch_root, "_подсказки-техника.md", INDEX_LIMIT_AREA))
    for area, subs in core.KNOWLEDGE_SUBDIRS.items():
        for sub in subs:
            if core.KNOWLEDGE_SUBSUBDIRS.get(sub):
                out.append((f"знания/{area}/{sub}",
                            f"_подсказки-{sub.lower()}.md",
                            INDEX_LIMIT_BRANCH))
    return out


targets = knowledge_index_targets()
names = [f for _r, f, _l in targets]
folders = [r for r, _f, _l in targets]

lines: list[str] = []
lines.append("=== сколько указателей даёт код плана ===")
lines.append(f"  областей в KNOWLEDGE_AREAS: {len(core.KNOWLEDGE_AREAS)}")
lines.append(f"  всего указателей: {len(targets)}")
lines.append("")
lines.append("=== по уровням ===")
lines.append(f"  уровень 1 (корневой): {1}")
level2 = [t for t in targets if t[0].count("/") == 1 and t[1] != "_подсказки-общая.md"]
lines.append(f"  уровень 2 (области): {len(level2)}")
level3 = [t for t in targets if t[0].count("/") == 2]
lines.append(f"  уровень 3 (ветки): {len(level3)}")
lines.append(f"  сумма: {1 + len(level2) + len(level3)}")
lines.append("")
lines.append("=== весь список ===")
for rel, fname, lim in targets:
    exists = (PROG / rel / fname).is_file()
    lines.append(f"  {rel}/{fname}  лимит {lim}  "
                 f"{'файл уже есть' if exists else 'создать'}")
lines.append("")
lines.append("=== проверки ===")
lines.append(f"  всего {len(targets)}; ожидалось по решению 11: "
             f"{'сходится' if len(targets) == 11 else 'НЕ СХОДИТСЯ'}")
dupes = [n for n in set(names) if names.count(n) > 1]
lines.append(f"  одинаковых имён в разных папках: {len(dupes)} {dupes}")
lines.append("    (у папок разные родители, поэтому совпадение имени не коллизия)")
lines.append(f"  в плане в прозе написано: девять строк «записан», 9 областей — "
             f"это {len(targets)}, расхождение")

# --- сверка имён в документах: есть ли живая опечатка
lines.append("")
lines.append("=== имена указателей, упомянутые в документах ===")
import re  # noqa: E402

valid = {f for _r, f, _l in targets}
OLD = "_подсказки-программисту.md"
for name in ("2026-10-05-план-указатели-знаний.md",
             "2026-10-04-указатели-знаний-дизайн.md"):
    doc = PROG / "документы" / name
    if not doc.is_file():
        lines.append(f"  {name}: нет файла")
        continue
    text = doc.read_text(encoding="utf-8")
    tokens = sorted(set(re.findall(r"_подсказки-[^\s`|)\]]*\.md", text)))
    lines.append(f"  {name}:")
    for tok in tokens:
        if tok == OLD:
            verdict = "СТАРОЕ имя, будет переименовано"
        elif tok in valid:
            verdict = "верно, есть в списке"
        else:
            verdict = "НЕТ в списке — вот это опечатка"
        lines.append(f"    {tok:42} {verdict}")
    # отдельно: встречается ли производное имя, которого быть не должно
    for bad in ("_подсказки-знания.md", "_подсказки-общая.md "):
        if bad in text:
            lines.append(f"    встречается «{bad.strip()}»")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))