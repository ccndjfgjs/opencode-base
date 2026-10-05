#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересобрать указатели знаний в готовой базе.

Запуск:
    python tools/проверки/пересобрать-указатели.py <путь-к-базе>

Что делает:
1. Переносит текст старых карт в новые, если имя изменилось. В живой базе
   карта Учёбы лежала в `_подсказки-программисту.md`, а новая схема зовёт
   `_подсказки-учёба.md`. Без переноса новая карта создалась бы пустой, а
   правила отправляли бы модель именно в неё — то есть знание пропало бы
   из вида, хотя файл лежит на месте.
2. Прогоняет `refresh_knowledge_indexes` по всем целям: создаёт
   недостающие, пересобирает имеющиеся.
3. Печатает отчёт: что создано, что пересчитано, где появился архив.

Ничего не удаляет: старый файл переезжает в `99_Разобрать позже` внутри
базы, оттуда его можно поднять руками. Перед запуском сделай копию базы.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent
sys.path.insert(0, str(PROG / "tools" / "dbapp"))
import core  # noqa: E402

#: Старое имя → новое. Ключ — папка области, значение — пара имён.
LEGACY: dict[str, tuple[str, str]] = {
    "знания/Учёба": ("_подсказки-программисту.md", "_подсказки-учёба.md"),
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    base = Path(argv[1]).resolve()
    if not (base / "знания").is_dir():
        print(f"НЕ БАЗА: в {base} нет папки «знания»")
        return 1
    attic = base / "99_Разобрать позже"
    attic.mkdir(exist_ok=True)

    print(f"=== база: {base} ===")
    print()
    print("=== 1. переносы старых карт ===")
    moved = 0
    for rel, (old_name, new_name) in LEGACY.items():
        folder = base / rel
        old, new = folder / old_name, folder / new_name
        if not old.is_file():
            print(f"  нечего переносить: {rel}/{old_name} нет")
            continue
        text = old.read_text(encoding="utf-8")
        if new.is_file():
            new.write_text(new.read_text(encoding="utf-8") + "\n" + text,
                           encoding="utf-8", newline="\n")
            how = "дописан в новый"
        else:
            new.write_text(text, encoding="utf-8", newline="\n")
            how = "перенесён в новый"
        park = attic / f"{rel.replace('/', '_')}_{old_name}"
        shutil.copy2(old, park)
        moved += 1
        print(f"  {rel}/{old_name} — {how} ({rel}/{new_name})")
        print(f"    копия оставлена: {park.relative_to(base)}")
    if not moved:
        print("  переносов не потребовалось")
    print()

    print("=== 2. пересборка указателей ===")
    for line in core.refresh_knowledge_indexes(base):
        print(f"  {line}")
    print()

    print("=== 3. что получилось ===")
    want = core.knowledge_index_targets()
    for rel, fname, _lim in want:
        f = base / rel / fname
        if f.is_file():
            arch = f.parent / core.ARCHIVE_NAME
            extra = f", архив {arch.stat().st_size} байт" if arch.is_file() else ""
            print(f"  есть  {rel}/{fname}  {f.stat().st_size} байт{extra}")
        elif not (base / rel).is_dir():
            print(f"  нет папки области  {rel}")
        else:
            print(f"  НЕТ  {rel}/{fname}")
    print()
    print("Готово. Проверь глазами пару указателей и только потом удаляй "
          "«99_Разобрать позже».")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
