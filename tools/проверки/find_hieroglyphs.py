#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ищет иероглифы в своём тексте программы.

Почему не по всей папке. Первая попытка прошлась по всему дереву и дала
2284 находки: node_modules, импортированные переводы, китайские доки в
знаниях. Там иероглифы законны, и проверка превратилась в шум, мимо
которого нельзя пройти. Свой текст — вот что важно: код программы,
документы плана и спецификации, скрипты проверок.

Что ищем. Иероглифы и кана: они появляются не от правки, а от вставки
текста из другого источника, где что-то не так с кодировкой. Замена
слова на китайское или зависшая строка из веб-страницы — такое надо
замечать.

Замена символа U+FFFD — это уже битый символ, его записали в файл.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent.parent

# Папки, где текст чужой: там иероглифы законны.
SKIP_DIRS = {".git", "__pycache__", "node_modules", "thirdparty",
             "99_Разобрать позже", "заметки"}

# Папки, где наш текст.
AREAS = ("документы", "tools/проверки", "tools/dbapp", "config",
         "skills", "agents", "библиотека")
SUFFIXES = (".py", ".md", ".sh", ".json", ".jsonc", ".txt")

SUSPECT = [
    (0x4E00, 0x9FFF, "иероглиф"),
    (0x3040, 0x30FF, "кана"),
    (0xAC00, 0xD7AF, "хангыль"),
    (0xFFFD, 0xFFFD, "битый символ"),
]

# Исключения записаны поимённо, с причиной. Молча пропускать папку нельзя:
# тогда непонятно, потеряна ли проверка или там действительно законно.
# Один на каждый случай — если исключений станет много, значит проверку
# надо переосмыслить, а не раздувать список.
ALLOWED = {
    ("skills/skill-creator/SKILL.md", 321):
        "пример запроса на китайском: показываем, что скилл понимает и его",
}


def main() -> int:
    found: list[str] = []
    scanned = 0
    for area in AREAS:
        base = PROG / area
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_dir() or p.suffix.lower() not in SUFFIXES:
                continue
            if any(d in SKIP_DIRS for d in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                found.append(f"{p.relative_to(PROG)}: не читается как UTF-8: {exc}")
                continue
            scanned += 1
            rel = p.relative_to(PROG).as_posix()
            for n, line in enumerate(text.split("\n"), 1):
                if (rel, n) in ALLOWED:
                    continue
                for ch in line:
                    o = ord(ch)
                    for lo, hi, what in SUSPECT:
                        if lo <= o <= hi:
                            found.append(f"{rel}:{n}: "
                                         f"{what} {ch!r} — {line.strip()[:60]}")
                            break

    print(f"проверено файлов: {scanned}")
    print(f"папки: {', '.join(AREAS)}")
    print(f"пропущены (чужой текст): {', '.join(sorted(SKIP_DIRS))}")
    print(f"исключений поимённо: {len(ALLOWED)}")
    for (rel, n), why in ALLOWED.items():
        print(f"  {rel}:{n} — {why}")
    print()
    if found:
        print(f"НАЙДЕНО: {len(found)}")
        for f in found[:40]:
            print("  " + f)
        return 1
    print("в своём тексте иероглифов нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())