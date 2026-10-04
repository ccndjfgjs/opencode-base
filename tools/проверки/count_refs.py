# -*- coding: utf-8 -*-
"""Пересчёт ссылок на `_подсказки-программисту.md` по местам и по строкам.

В отчёте было расхождение: таблица давала 12 рабочих ссылок, а в выводе
стояло 11, и 27 вместо 36. Причина, вероятно, в том, что не все строки
перечислены: в восьми совпадениях `core.py` номера строк шли шестью.
Задача 4 стоит на счётчике «ноль совпадений», поэтому цифры должны быть
верными до того, как попадут в план.
"""

import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent.parent
OUT = Path(sys.argv[1])
NEEDLE = "программисту"
SKIP = ("node_modules", "\\.git\\", "\\__pycache__\\")

#: Контрольный образец. Поиск, который ничего не находит, и поиск, который
#: сломан, выглядят одинаково — оба дают ноль. Условие удаления старого
#: указателя построено на «ноль совпадений», поэтому сломанный поиск
#: выглядел бы как выполненное условие, и файл удалили бы при живых
#: ссылках. Поэтому рядом с числом совпадений всегда идёт проверка: файл,
#: который заведомо содержит искомое, обязан быть найден.
#:
#: Образец — сам план: переименование от 05.10 описано там словами про
#: старое имя, и пока это так, образец жив. Если исчезнет, это не поломка
#: поиска, а смена документа, и скрипт обязан сказать об этом голосом.
CONTROL_FILE = "документы/2026-10-05-план-указатели-знаний.md"
CONTROL_MIN = 1

#: Где ссылка должна быть починена, а где упоминание — часть истории и
#: переписывать её нельзя.
WORK = {
    "tools/dbapp/core.py": "код программы",
    "config/AGENTS.md": "шаблон правил, ставится в установленный AGENTS.md",
    "skills/test-driven-development/SKILL.md": "навык, в описании прямой путь",
    "tools/agents/proveryalschik.md": "агент, упоминание в списке",
    "ПРАВИЛА-ИИ.md": "правила для модели",
}
HISTORY = ("документы/", "библиотека/", "проекты/", "журнал-решений/",
           "сессии", "память/")


def classify(rel: str) -> str:
    if any(rel.startswith(h) or h in rel for h in HISTORY):
        return "история"
    if rel in WORK:
        return "работа"
    return "прочее"


lines: list[str] = []
total = work = history = other = 0
per_file: list[tuple[str, str, int, list[int]]] = []

for path in sorted(PROG.rglob("*")):
    if not path.is_file():
        continue
    if path.suffix not in (".py", ".js", ".md", ".json", ".jsonc", ".txt"):
        continue
    if any(s in str(path) for s in SKIP):
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    if NEEDLE not in text:
        continue
    rel = path.relative_to(PROG).as_posix()
    nums: list[int] = []
    count = 0
    for i, row in enumerate(text.splitlines(), 1):
        n = row.count(NEEDLE)
        if n:
            count += n
            nums.append(i)
    if count == 0:
        continue
    kind = classify(rel)
    total += count
    if kind == "работа":
        work += count
    elif kind == "история":
        history += count
    else:
        other += count
    per_file.append((kind, rel, count, nums))

lines.append("=== по файлам ===")
for kind, rel, count, nums in per_file:
    lines.append(f"  [{kind:8}] {count:3}  {rel}")
    if nums:
        lines.append(f"             строки: {', '.join(str(n) for n in nums)}")

lines.append("")
lines.append("=== итог ===")
lines.append(f"  всего совпадений: {total}")
lines.append(f"  рабочих (надо починить): {work}")
lines.append(f"  истории (не трогаем): {history}")
lines.append(f"  прочих: {other}")

# отдельно: рабочие места и точный счёт строк в каждом
lines.append("")
lines.append("=== рабочие места подробно ===")
work_files = [(rel, c, n) for k, rel, c, n in per_file if k == "работа"]
lines.append(f"  файлов: {len(work_files)}")
for rel, c, n in work_files:
    lines.append(f"    {rel}: совпадений {c}, строк {len(n)} → {n}")
    lines.append(f"       зачем: {WORK[rel]}")
sum_lines = sum(len(n) for _r, _c, n in work_files)
sum_hits = sum(c for _r, c, _n in work_files)
lines.append("")
lines.append(f"  рабочих совпадений: {sum_hits}, затронутых строк: {sum_lines}")

# дубликаты: совпадений больше, чем строк, если в строке слово встречается дважды
lines.append("")
lines.append("=== где в одной строке слово встречается дважды ===")
for path in sorted(PROG.rglob("*.md")):
    if any(s in str(path) for s in SKIP):
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    if NEEDLE not in text:
        continue
    rel = path.relative_to(PROG).as_posix()
    for i, row in enumerate(text.splitlines(), 1):
        if row.count(NEEDLE) > 1:
            lines.append(f"  {rel}:{i} — {row.count(NEEDLE)} раз")

control_hits = 0
control_seen = False
for _kind, _rel, _cnt, _nums in per_file:
    if _rel == CONTROL_FILE:
        control_seen = True
        control_hits = _cnt
        break

lines.append("")
lines.append("=== контрольный образец поиска ===")
lines.append(f"  образец: {CONTROL_FILE}")
if not control_seen:
    lines.append("  ПОИСК СЛОМАН: файл-образец не попал в перебор — "
                 "искомое в нём есть по построению")
    lines.append("  Числа выше нельзя читать как «ноль совпадений»: "
                 "перебор не дошёл до образца.")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("ПОИСК СЛОМАН: контрольный образец не найден")
    raise SystemExit(3)
if control_hits < CONTROL_MIN:
    lines.append(f"  ПОИСК СЛОМАН или документ изменился: в образце "
                 f"{control_hits} вхождений, ждали не меньше {CONTROL_MIN}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"ПОИСК СЛОМАН: в образце {control_hits} вхождений")
    raise SystemExit(3)
lines.append(f"  найдено вхождений: {control_hits} — образец найден, "
             "поиск работает")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"ok: всего {total}, рабочих {work}, истории {history}")
print(f"контрольный образец: {control_hits} вхождений, поиск рабочий")