# -*- coding: utf-8 -*-
"""Подтверждает, что тринадцать правок плана действительно внесены.

Не пересказывает план, а ищет в нём каждую правку и показывает номер
строки. Если правка не найдена — это расхождение, а не «вроде сделал».

Ничего не меняет.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = (HERE.parent.parent / "документы"
        / "2026-10-05-план-указатели-знаний.md")
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "отчёт-13-правок.txt"

#: (номер, что искать, флаги)
CHECKS = [
    (1, "`_подсказки-безопасность.md` список направлений", False),
    (1, "`_подсказки-безопасности.md`", True),          # не должно остаться
    (2, "одиннадцать строк «записан»", False),
    (3, "у всех одиннадцати указателей есть `## Пути`", False),
    (4, "| `знания/Техника/_подсказки-техника.md` |", False),
    (5, "девять областей минус «Техника» и «Учёба»", False),
    (5, "одиннадцать строк «записан»", False),          # число в задаче 5
    (6, "## Задача 4а: Переименовать указатель Учёбы", False),
    (6, "_подсказки-программисту.md` → `знания/Учёба/_подсказки-учёба.md`", False),
    (6, "core.py` (строки 464, 775, 827)", False),
    (6, "`КАРТА-БАЗЫ.md` (строка 15)", False),
    (6, "заголовок первой строки самого указателя", False),
    (7, "Ноль совпадений старого имени **в коде, навыках, агентах, правилах и", False),
    (7, "| `tools/проверки/doc_numbers.py` | 1 совпадение", False),
    (7, "| `tools/проверки/count_refs.py` | 2 совпадения", False),
    (7, "| `tools/проверки/count_bases.py` | 1 совпадение", False),
    (7, "| `tools/проверки/count_targets.py` | 1 совпадение", False),
    (7, "| `tools/проверки/verify_13_edits.py` | 1 совпадение", False),
    (7, "`библиотека/записи/` | 6 совпадений в одной записи", False),
    (7, "пять файлов с шестью совпадениями", False),
    (7, "поимённо", False),
    (7, "а не маской `*.py`", False),   # маска запрещена, но упомянута
    (7, "| `tools/проверки/*.py`", True),          # и не должна быть в таблице
    (8, "создаётся тестовая база во временной папке", False),
    (8, "поиск по строке ловит только то, что написано буквально", False),
    (9, "Указатели создаются кодом, а не копированием файлов", False),
    (10, 'newline="\\n" обязателен', False),
    (11, 'unicodedata.normalize("NFC", p)', False),
    (12, "Формат не разбирается скриптом", False),
    (12, "Весь старый текст указателя целиком остаётся смысловой частью", False),
    (13, "**Сначала полная копия всей базы**", False),
    (13, "точечной заменой** строки 53", False),
    (13, "`.workbuddy-ai/backups/` **не трогаем**", False),
    (4, "Расхождение сначала измеряется, потом объясняется", False),
]


def main() -> int:
    lines = ["=== подтверждение тринадцати правок плана ===", ""]
    text = PLAN.read_text(encoding="utf-8")
    rows = text.splitlines()

    # Ищем по всему тексту с нормализацией, а не построчно. Первая версия
    # искала построчно и дала три ложных расхождения: две фразы разорваны
    # переносом строки, одна начинается с заглавной буквы. Проверка, которая
    # ругается на свой же формат, хуже отсутствия проверки.
    flat = " ".join(text.split()).lower()

    missing: list[str] = []
    seen: dict[int, list[str]] = {}

    for num, needle, must_absent in CHECKS:
        want = " ".join(needle.split()).lower()
        count = flat.count(want)
        if must_absent:
            ok = count == 0
            mark = ("отсутствует, как надо" if ok
                    else f"ОСТАЛОСЬ ЛИШНЕЕ ({count} раз)")
        else:
            ok = count > 0
            mark = f"найдено {count} раз" if ok else "НЕ НАЙДЕНО"
        if not ok:
            missing.append(f"правка {num}: «{needle}» — {mark}")
        seen.setdefault(num, []).append(f"{'✓' if ok else '✗'} {needle[:58]}")

    lines.append("по правкам:")
    for num in sorted(seen):
        lines.append(f"  правка {num}:")
        for row in seen[num]:
            lines.append(f"    {row}")

    lines.append("")
    lines.append(f"всего отметок: {len(CHECKS)}, "
                 f"расхождений: {len(missing)}")
    for m in missing:
        lines.append(f"  {m}")
    lines.append(f"ИТОГ: {'все тринадцать внесены' if not missing else 'НЕ ВСЕ ВНЕСЕНЫ'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())